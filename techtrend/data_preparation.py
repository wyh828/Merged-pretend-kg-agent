"""Free, resumable retrospective data preparation using existing source clients.

API aggregates estimate corpus activity. Stratified records are graph seeds,
never estimates of corpus activity or point-in-time historical evidence.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import yaml

from techtrend.config import Settings
from techtrend.io import append_jsonl, read_jsonl, write_jsonl
from techtrend.signal.config import month_range
from techtrend.sources.openalex import OpenAlexClient
from techtrend.sources.crossref import CrossrefClient
from techtrend.stages.collect import _append_dedup
from techtrend.storage import file_digest, reserve_snapshot_path, write_api_snapshot


class PreparationStopped(RuntimeError):
    """A request budget or provider access condition stops further requests."""


def months_between(start: str, end: str) -> list[str]:
    """Inclusive calendar months; preparation requires complete month boundaries."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.day != 1 or end != month_range(end[:7])[1] or first > last:
        raise ValueError("Preparation dates must bound complete calendar months")
    months = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def parse_field_counts(payload: dict) -> tuple[list[dict], int]:
    """Primary-field bins must reconcile with total, including unknowns.

    Missing/truncated/error payloads raise, so callers record unavailable data,
    rather than manufacturing zero counts for failed requests.
    """
    groups = payload.get("group_by")
    total = (payload.get("meta") or {}).get("count")
    if not isinstance(groups, list) or type(total) is not int or total < 0:
        raise ValueError("OpenAlex grouped count response is invalid")
    rows, seen = [], set()
    for group in groups:
        key = group.get("key")
        count = group.get("count")
        if not key or key in seen or type(count) is not int or count < 0:
            raise ValueError("Invalid or repeated primary-field group")
        seen.add(key)
        rows.append({"field_id": key, "field_name": group.get("key_display_name") or key,
                     "activity_count": count})
    if sum(row["activity_count"] for row in rows) != total:
        raise ValueError("Primary-field groups do not cover the reported total")
    return rows, total


def validate_works(records: list[dict], start: str, end: str, require_day: bool) -> tuple[list[dict], list[dict]]:
    """Accept valid IDs/dates within query bounds; retain rejected data with reasons."""
    accepted, rejected = [], []
    for row in records:
        reason = None
        value = row.get("publication_date")
        if not row.get("id"):
            reason = "missing_id"
        elif not value or (require_day and len(value) != 10):
            reason = "missing_or_imprecise_publication_date"
        else:
            try:
                parsed = date.fromisoformat(value)
                if not (date.fromisoformat(start) <= parsed <= date.fromisoformat(end)):
                    reason = "publication_date_outside_query"
            except (ValueError, TypeError):
                reason = "invalid_publication_date"
        (rejected if reason else accepted).append({**row, "rejection_reason": reason} if reason else row)
    return accepted, rejected


class DataPreparation:
    """One explicit preparation protocol with append-only per-query audit history."""

    def __init__(self, settings: Settings, config_path: Path | None = None):
        self.settings = settings
        path = Path(config_path or settings.data_preparation_config)
        self.config = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.config_path = path
        self.months = months_between(settings.collection_start_date, settings.collection_end_date)
        self.root = settings.data_dir
        self.known_ids = {r["id"] for r in read_jsonl(self.root / "interim/works.jsonl") if r.get("id")}
        self.ledger = self.root / "metadata/preparation_queries_02.jsonl"
        self.completed = {r["task_id"]: r for r in read_jsonl(self.ledger) if r.get("status") == "ok"}
        self.requests = 0
        self.failures = []
        self.stopped = False
        http = self.config["http"]
        self.openalex = OpenAlexClient(api_key=settings.openalex_api_key, mailto=settings.openalex_mailto,
                                       timeout=http["timeout_seconds"], min_interval=http["min_interval_seconds"],
                                       base_url=self.config["openalex"]["base_url"])
        self.crossref = CrossrefClient(mailto=settings.crossref_mailto, timeout=http["timeout_seconds"],
                                      min_interval=http["min_interval_seconds"],
                                      base_url=self.config["crossref"]["base_url"])

    def close(self):
        self.openalex.close()
        self.crossref.close()

    def query(self, source: str, kind: str, params: dict) -> tuple[dict, Path, str]:
        """Read verified saved responses or persist one new original response.

        Transport retries are handled by existing clients. Failed queries do
        not enter the success cache. Budget exhaustion retains all prior pages.
        """
        spec = {"source": source, "kind": kind, "url": self.config[source]["base_url"], "params": params}
        task_id = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        previous = self.completed.get(task_id)
        if previous:
            path = self.root / previous["raw_snapshot"]
            if file_digest(path) != previous["sha256"]:
                raise ValueError(f"Snapshot checksum mismatch: {path.name}")
            envelope = read_jsonl(path)[0]
            return envelope["payload"], path, envelope["collected_at"]
        if self.requests >= self.config["http"]["max_requests_per_run"]:
            raise PreparationStopped("configured_request_budget_reached")
        self.requests += 1
        event = {**spec, "task_id": task_id, "observed_at": datetime.now(timezone.utc).isoformat()}
        try:
            client = self.openalex if source == "openalex" else self.crossref
            payload = client._get_page(params)
            if source == "openalex":
                if kind in {"registry", "monthly_counts"}:
                    parse_field_counts(payload)
                elif not isinstance(payload.get("results"), list):
                    raise ValueError("OpenAlex sample response lacks results")
            else:
                message = payload.get("message") or {}
                if type(message.get("total-results")) is not int or not isinstance(message.get("items"), list):
                    raise ValueError("Crossref response lacks count/items")
            path = write_api_snapshot(self.root / "raw" / source / datetime.now(timezone.utc).date().isoformat(),
                                      f"{kind}_{task_id[:12]}", source=source,
                                      source_url=spec["url"] + "/works", query=params, payload=payload,
                                      dataset_version=self.root.name, access=self.config[source]["access"])
            event.update(status="ok", raw_snapshot=str(path.relative_to(self.root)), sha256=file_digest(path))
            append_jsonl(self.ledger, [event])
            self.completed[task_id] = event
            return payload, path, event["observed_at"]
        except Exception as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            # Never serialize HTTP URLs/headers: they may contain credentials.
            event.update(status="failed", http_status=status, error_type=type(exc).__name__)
            append_jsonl(self.ledger, [event])
            self.failures.append({"task_id": task_id, "source": source, "kind": kind,
                                  "http_status": status, "error_type": type(exc).__name__})
            if status in self.config["http"]["stop_on_status"]:
                raise PreparationStopped(f"provider_access_status_{status}") from None
            raise

    def save_records(self, source: str, records: list[dict], raw_path: Path,
                     collected_at: str, start: str, end: str, sample_kind: str) -> dict:
        """Produce versioned normalized/quarantine snapshots and the deduped index."""
        client = self.openalex if source == "openalex" else self.crossref
        normalized = [{**client.normalize(row), "raw_snapshot": str(raw_path.relative_to(self.root)),
                       "collected_at": collected_at, "dataset_version": self.root.name,
                       "sample_kind": sample_kind, "historical_available_at": None,
                       "cited_by_count_as_of": collected_at if source == "openalex" else None}
                      for row in records]
        accepted, rejected = validate_works(normalized, start, end,
                                           self.config["quality"]["require_day_precision_for_graph"])
        if normalized:
            # One derived file per original response; reruns read the same file.
            target = self.root / "interim/snapshots" / raw_path.name
            if not target.exists():
                write_jsonl(target, accepted)
                quarantine = self.root / "interim/quarantine" / raw_path.name
                write_jsonl(quarantine, rejected)
            sidecar = target.with_suffix(".metadata.json")
            if not sidecar.exists():
                sidecar.write_text(json.dumps({"schema_version": "derived_works_02", "source": source,
                                               "dataset_version": self.root.name, "collected_at": collected_at,
                                               "input_file": str(raw_path.relative_to(self.root)),
                                               "input_sha256": file_digest(raw_path), "sha256": file_digest(target),
                                               "accepted": len(accepted), "rejected": len(rejected),
                                               "processing": ["source_normalization", "publication_date_validation"],
                                               "historical_available_at": None}, indent=2), encoding="utf-8")
            _append_dedup(self.root / "interim/works.jsonl", accepted, self.known_ids)
        return {"received": len(records), "accepted": len(accepted), "rejected": len(rejected)}

    def run(self) -> dict:
        """Collect broad monthly counts, then field-year graph seeds; emit coverage."""
        s, cfg = self.settings, self.config
        fields, counts, strata = [], [], []
        registry_query = {"filter": f"from_publication_date:{s.collection_start_date},to_publication_date:{s.collection_end_date}",
                          "group_by": cfg["openalex"]["group_by"], "per_page": 100,
                          "corpus": cfg["openalex"]["corpus"]}
        try:
            payload, path, observed = self.query("openalex", "registry", registry_query)
            registry, _ = parse_field_counts(payload)
            fields = [r for r in registry if str(r["field_id"]).startswith("https://openalex.org/fields/")
                      and str(r["field_id"]).rsplit("/", 1)[-1].isdigit()]
            registry_file = reserve_snapshot_path(self.root / "metadata", "field_registry", suffix=".json")
            registry_file.write_text(json.dumps({"source": "openalex", "collected_at": observed,
                                                  "raw_snapshot": str(path.relative_to(self.root)),
                                                  "fields": fields, "unknown": [r for r in registry if r not in fields]},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
            for month in self.months:
                start, end = month_range(month)
                try:
                    payload, raw, collected = self.query("openalex", "monthly_counts", {
                        "filter": f"from_publication_date:{start},to_publication_date:{end}",
                        "group_by": cfg["openalex"]["group_by"], "per_page": 100, "corpus": cfg["openalex"]["corpus"]})
                    rows, total = parse_field_counts(payload)
                    by_id = {r["field_id"]: r for r in rows}
                    # Missing known fields are zero only after counts reconcile.
                    for field in fields:
                        rows_for_field = by_id.get(field["field_id"], {**field, "activity_count": 0})
                        counts.append({**rows_for_field, "source": "openalex", "month": month,
                                       "collection_status": "ok", "corpus_total": total,
                                       "collected_at": collected, "raw_snapshot": str(raw.relative_to(self.root))})
                    for row in rows:
                        if row["field_id"] not in {f["field_id"] for f in fields}:
                            counts.append({**row, "source": "openalex", "month": month, "collection_status": "ok",
                                           "corpus_total": total, "collected_at": collected,
                                           "raw_snapshot": str(raw.relative_to(self.root))})
                except PreparationStopped:
                    raise
                except Exception:
                    for field in fields:
                        counts.append({**field, "activity_count": None, "source": "openalex", "month": month,
                                       "collection_status": "failed", "corpus_total": None})
                try:
                    payload, raw, collected = self.query("crossref", "monthly_counts_and_seeds", {
                        "filter": f"from-pub-date:{start},until-pub-date:{end}",
                        "rows": cfg["crossref"]["samples_per_month"], "sort": "published", "order": "asc"})
                    message = payload["message"]
                    counts.append({"source": "crossref", "field_id": "all", "field_name": "All DOI records",
                                   "month": month, "activity_count": message["total-results"], "collection_status": "ok",
                                   "corpus_total": message["total-results"], "collected_at": collected,
                                   "raw_snapshot": str(raw.relative_to(self.root))})
                    quality = self.save_records("crossref", message["items"], raw, collected, start, end,
                                                "publication_order_metadata_seeds")
                    strata.append({"source": "crossref", "month": month, "status": "ok", **quality})
                except PreparationStopped:
                    raise
                except Exception:
                    counts.append({"source": "crossref", "field_id": "all", "field_name": "All DOI records",
                                   "month": month, "activity_count": None, "collection_status": "failed", "corpus_total": None})
                print(f"month {month}: coverage saved", flush=True)
            for field in fields:
                for year in range(int(self.months[0][:4]), int(self.months[-1][:4]) + 1):
                    start = max(f"{year}-01-01", s.collection_start_date)
                    end = min(f"{year}-12-31", s.collection_end_date)
                    sample_size = cfg["openalex"]["samples_per_field_year"]
                    try:
                        payload, raw, collected = self.query("openalex", "field_year_sample", {
                            "filter": f"primary_topic.field.id:{field['field_id']},from_publication_date:{start},to_publication_date:{end}",
                            "sample": sample_size, "seed": cfg["openalex"]["seed"], "per_page": sample_size,
                            "corpus": cfg["openalex"]["corpus"]})
                        quality = self.save_records("openalex", payload["results"], raw, collected, start, end,
                                                    "seeded_random_field_year")
                        strata.append({"source": "openalex", "field_id": field["field_id"], "year": year,
                                       "status": "ok", **quality, "reported_total": payload["meta"].get("count"),
                                       "raw_snapshot": str(raw.relative_to(self.root))})
                    except PreparationStopped:
                        raise
                    except Exception:
                        strata.append({"source": "openalex", "field_id": field["field_id"], "year": year, "status": "failed"})
                print(f"field {field['field_name']}: year strata saved", flush=True)
        except PreparationStopped as exc:
            self.stopped = True
            print(f"stopped: {exc}", flush=True)
        finally:
            self.close()
        return self.summarize(fields, counts, strata)

    def summarize(self, fields: list[dict], counts: list[dict], strata: list[dict]) -> dict:
        """Version every derived coverage report and explicitly gate evaluation."""
        report_path = reserve_snapshot_path(self.root / "metadata", "preparation_summary", suffix=".json")
        version = report_path.stem.rsplit("_", 1)[-1]
        count_path = self.root / "processed" / f"monthly_activity_{version}.jsonl"
        strata_path = self.root / "processed" / f"sample_coverage_{version}.jsonl"
        write_jsonl(count_path, counts)
        write_jsonl(strata_path, strata)
        works = read_jsonl(self.root / "interim/works.jsonl")
        oa_counts = [r for r in counts if r["source"] == "openalex"]
        successful_months = {r["month"] for r in oa_counts if r["collection_status"] == "ok"}
        crossref_months = {r["month"] for r in counts if r["source"] == "crossref" and r["collection_status"] == "ok"}
        years = int(self.months[-1][:4]) - int(self.months[0][:4]) + 1
        sampled = [r for r in strata if r["source"] == "openalex" and r["status"] == "ok"]
        required = self.config["quality"]["minimum_works_per_field_year"]
        sparse = [r for r in sampled if r["accepted"] < required]
        coverage_complete = (len(successful_months) == len(self.months)
                             and len(crossref_months) == len(self.months)
                             and len(sampled) == len(fields) * years and bool(fields))
        summary = {"schema_version": "data_preparation_02", "dataset_version": self.root.name,
                   "created_at": datetime.now(timezone.utc).isoformat(), "start_date": self.settings.collection_start_date,
                   "end_date": self.settings.collection_end_date, "fields": len(fields), "expected_months": len(self.months),
                   "openalex_months_ok": len(successful_months), "crossref_months_ok": len(crossref_months),
                   "expected_field_year_strata": len(fields) * years, "sampled_field_year_strata": len(sampled),
                   "sparse_field_year_strata": len(sparse), "works": len(works),
                   "classified_works": sum(bool(w.get("concepts")) for w in works),
                   "works_with_references": sum(bool(w.get("referenced_works")) for w in works),
                   "quarantined_records": sum(r.get("rejected", 0) for r in strata),
                   "requests_this_run": self.requests, "stopped": self.stopped, "failures": self.failures,
                   "monthly_activity_file": str(count_path.relative_to(self.root)),
                   "sample_coverage_file": str(strata_path.relative_to(self.root)),
                   "historical_as_of_evaluation_ready": False,
                   "graph_seed_ready": coverage_complete and not self.stopped,
                   "coverage_complete": coverage_complete,
                   "research_sample_size_ready": coverage_complete and not sparse,
                   "full_scale_forecasting_ready": False,
                   "limitations": ["current_metadata_is_retrospective", "random_records_are_graph_seeds_not_corpus_counts",
                                   "crossref_publication_order_seeds_are_not_representative", "patent_citations_missing",
                                   "historical_classification_and_reference_availability_unknown", "source_counts_must_not_be_added"],
                   "effective_config": self.config,
                   "environment": {"collection_start_date": self.settings.collection_start_date,
                                   "collection_end_date": self.settings.collection_end_date, "data_dir": str(self.root)},
                   "derived_sha256": {count_path.name: file_digest(count_path), strata_path.name: file_digest(strata_path)}}
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        csv_path = count_path.with_suffix(".csv")
        with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
            keys = ["source", "field_id", "field_name", "month", "activity_count", "collection_status", "corpus_total", "collected_at", "raw_snapshot"]
            writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(counts)
        return summary
