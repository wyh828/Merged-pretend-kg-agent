"""Configuration loader and path manager for Predictive Agents pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from techtrend.config import resolve_project_path


SIGNAL_CONFIG_DIR = Path(__file__).resolve().parent / "configs"
DEFAULT_CONFIG_PATH = SIGNAL_CONFIG_DIR / "default.yaml"


@dataclass
class TopicConfig:
    topic_id: str
    topic_label: str
    openalex_query: str
    gdelt_query: str
    crossref_query: str = ""
    github_query: str = ""
    arxiv_query: str = ""
    uspto_query: str = ""


@dataclass
class PipelineConfig:
    project_name: str
    timezone: str
    random_seed: int
    data_root: Path
    resources_root: Path
    dataset_name: str
    start_date: str
    end_date: str
    window_size_months: int
    train_ratio: float
    validation_ratio: float
    test_ratio: float
    topics: list[TopicConfig] = field(default_factory=list)

    @property
    def raw_api_path(self) -> Path:
        return self.data_root / "Raw" / "APIs" / self.dataset_name

    @property
    def interim_path(self) -> Path:
        return self.data_root / "Interim" / self.dataset_name

    @property
    def processed_path(self) -> Path:
        return self.data_root / "Processed" / self.dataset_name

    @property
    def reports_path(self) -> Path:
        return self.data_root / "Reports" / self.dataset_name


def load_yaml_config(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topics(topics_path: Path) -> list[TopicConfig]:
    raw = load_yaml_config(topics_path)
    topics = []
    for item in raw.get("topics", []):
        topics.append(TopicConfig(
            topic_id=item["topic_id"],
            topic_label=item["topic_label"],
            openalex_query=item["openalex_query"],
            gdelt_query=item["gdelt_query"],
            crossref_query=item.get("crossref_query", item["openalex_query"]),
            github_query=item.get("github_query", ""),
            arxiv_query=item.get("arxiv_query", item["openalex_query"]),
            uspto_query=item.get("uspto_query", item["openalex_query"]),
        ))
    return topics


def load_pipeline_config(
    config_path: Path | None = None,
    topics_path: Path | None = None,
) -> PipelineConfig:
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    if topics_path is None:
        topics_path = SIGNAL_CONFIG_DIR / "topics.yaml"

    raw = load_yaml_config(config_path)
    split = raw.get("default_data_split", {})

    cfg = PipelineConfig(
        project_name=raw.get("project_name", "predictive-agents"),
        timezone=raw.get("timezone", "Asia/Shanghai"),
        random_seed=raw.get("random_seed", 42),
        data_root=resolve_project_path(raw.get("data_root", "data/signal")),
        resources_root=resolve_project_path(raw.get("resources_root", "resources")),
        dataset_name=raw.get("dataset_name", "technology_cultivation_00"),
        start_date=raw.get("start_date", "2023-01"),
        end_date=raw.get("end_date", "2025-07"),
        window_size_months=int(raw.get("window_size_months", 1)),
        train_ratio=split.get("train_ratio", 0.7),
        validation_ratio=split.get("validation_ratio", 0.15),
        test_ratio=split.get("test_ratio", 0.15),
    )

    if topics_path.exists():
        cfg.topics = load_topics(topics_path)

    return cfg


def month_range(window_start: str) -> tuple[str, str]:
    """Convert a YYYY-MM window start to (first_day, last_day) in YYYY-MM-DD.

    Used by per-month count collectors (CrossRef, OpenAlex) that need explicit
    day-level date filters for their API calls.
    """
    year, month = window_start.split("-")
    y, m = int(year), int(month)
    if m == 12:
        next_y, next_m = y + 1, 1
    else:
        next_y, next_m = y, m + 1
    last_day = (datetime(next_y, next_m, 1) - datetime(y, m, 1)).days
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}"


def generate_monthly_windows(
    start: str,
    end: str,
) -> list[tuple[str, str]]:
    """Generate (window_start, window_end) pairs in YYYY-MM format.

    Each window covers one month. The end month is exclusive.
    """
    start_dt = datetime.strptime(start, "%Y-%m")
    end_dt = datetime.strptime(end, "%Y-%m")
    windows: list[tuple[str, str]] = []
    current = start_dt
    while current < end_dt:
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1)
        else:
            next_month = current.replace(month=current.month + 1)
        windows.append((current.strftime("%Y-%m"), next_month.strftime("%Y-%m")))
        current = next_month
    return windows


def ensure_dirs(cfg: PipelineConfig) -> None:
    for path in [
        cfg.raw_api_path / "openalex",
        cfg.raw_api_path / "crossref",
        cfg.raw_api_path / "arxiv",
        cfg.raw_api_path / "uspto",
        cfg.raw_api_path / "gdelt",
        cfg.raw_api_path / "github",
        cfg.interim_path,
        cfg.processed_path,
        cfg.reports_path,
    ]:
        path.mkdir(parents=True, exist_ok=True)
