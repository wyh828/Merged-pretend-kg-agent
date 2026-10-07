"""Portable, versioned sharing artifacts; source datasets are never modified."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from techtrend.config import PROJECT_ROOT, Settings, resolve_project_path
from techtrend.storage import file_digest


def portable_path(value: str) -> str:
    """Normalize a relative archive path; reject traversal and drive paths."""
    windows = PureWindowsPath(value)
    path = PurePosixPath(value.replace("\\", "/"))
    if windows.drive or windows.root or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Unsafe relative path: {value}")
    return path.as_posix()


def reserve_export(root: Path, stem: str) -> Path:
    """Create an exclusive numbered directory; never reuse earlier output."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", stem):
        raise ValueError("Export stem must use English identifiers")
    root.mkdir(parents=True, exist_ok=True)
    indices = [int(match.group(1)) for item in root.iterdir()
               if (match := re.fullmatch(re.escape(stem) + r"_(\d+)", item.name))]
    index = max(indices, default=-1) + 1
    while True:
        destination = root / f"{stem}_{index:02d}"
        try:
            destination.mkdir(exist_ok=False)
            return destination
        except FileExistsError:
            index += 1


def transform_record(value, *, crossref: bool = False):
    """Return a portable public copy and a list of transformations.

    Unknown-license Crossref abstracts are removed only from sharing copies.
    Raw source checksums remain in the file manifest and sidecar metadata.
    """
    changes = []
    if isinstance(value, dict):
        crossref = crossref or value.get("source") == "crossref"
        result = {}
        for key, item in value.items():
            if crossref and key in {"abstract", "abstract_inverted_index"}:
                changes.append("crossref_abstract_removed")
                continue
            if key.lower() in {"api_key", "password", "access_token", "github_token", "llm_api_key"}:
                if item and item != "[REDACTED]":
                    raise ValueError("Unexpected credentials in a selected data file")
            if key in {"raw_snapshot", "monthly_activity_file", "sample_coverage_file", "summary_file"} and isinstance(item, str):
                normalized = portable_path(item)
                if normalized != item:
                    changes.append("relative_path_normalized")
                result[key] = normalized
            elif key == "data_dir" and isinstance(item, str):
                result[key] = "."
                changes.append("source_machine_path_removed")
            else:
                result[key], child_changes = transform_record(item, crossref=crossref)
                changes.extend(child_changes)
        return result, changes
    if isinstance(value, list):
        result = []
        for item in value:
            child, child_changes = transform_record(item, crossref=crossref)
            result.append(child)
            changes.extend(child_changes)
        return result, changes
    return value, changes


def copy_public_file(source: Path, destination: Path, *, crossref: bool = False) -> dict:
    """Copy one selected file, preserving its original hash and transformations."""
    if source.is_symlink() or not source.is_file():
        raise ValueError("Only regular source files can be shared")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    changes = []
    if source.suffix in {".json", ".jsonl"} and not source.name.endswith(".metadata.json"):
        with source.open(encoding="utf-8") as original, destination.open("x", encoding="utf-8", newline="\n") as public:
            if source.suffix == ".json":
                value, changes = transform_record(json.load(original), crossref=crossref)
                json.dump(value, public, ensure_ascii=False, indent=2)
            else:
                for line in original:
                    if line.strip():
                        value, row_changes = transform_record(json.loads(line), crossref=crossref)
                        changes.extend(row_changes)
                        public.write(json.dumps(value, ensure_ascii=False) + "\n")
    else:
        shutil.copyfile(source, destination)
    return {"source_sha256": file_digest(source), "sha256": file_digest(destination),
            "bytes": destination.stat().st_size, "transformations": sorted(set(changes))}


def write_json(path: Path, value: dict) -> None:
    """Write an exclusive UTF-8 record; fail instead of overwriting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def package_component(directory: Path, archive: Path, context: dict, *, level: int, max_bytes: int,
                      provenance: dict | None = None) -> dict:
    """Create a hash manifest and ZIP, then verify every packaged byte."""
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in sharing archives")
        if path.is_file():
            name = portable_path(path.relative_to(directory).as_posix())
            files[name] = {"sha256": file_digest(path), "bytes": path.stat().st_size}
            if provenance and name in provenance:
                files[name].update(provenance[name])
    write_json(directory / "manifest_00.json", {**context, "files": files})
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as bundle:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                bundle.write(path, portable_path(path.relative_to(directory).as_posix()))
    if archive.stat().st_size > max_bytes:
        raise ValueError("Archive exceeds configured GitHub asset size limit")
    checked = verify_archive(archive)
    return {"file": archive.name, "sha256": file_digest(archive), "bytes": archive.stat().st_size,
            "files_checked": checked["files_checked"], "status": "passed"}


def verify_archive(archive: Path) -> dict:
    """Check member paths, exact manifest coverage, ZIP CRC and SHA-256 without extracting."""
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        canonical = [portable_path(name) for name in names]
        if len(names) != len(set(name.casefold() for name in canonical)) or canonical != names:
            raise ValueError("Duplicate or noncanonical archive member")
        if bundle.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        manifest = json.loads(bundle.read("manifest_00.json"))
        expected = manifest["files"]
        if set(names) != set(expected) | {"manifest_00.json"}:
            raise ValueError("Archive file list does not match manifest")
        for name, metadata in expected.items():
            digest = hashlib.sha256()
            size = 0
            with bundle.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
            if digest.hexdigest() != metadata["sha256"] or size != metadata["bytes"]:
                raise ValueError(f"Checksum mismatch: {name}")
    return {"status": "passed", "files_checked": len(expected), "component": manifest["component"]}


def prepare_data_copy(settings: Settings, config: dict, destination: Path) -> dict:
    """Copy selected dataset files, repair public sidecars, and return provenance."""
    source_root = settings.data_dir.resolve()
    dataset = destination / "dataset" / source_root.name
    summary_path = sorted((source_root / "metadata").glob("preparation_summary_*.json"))[-1]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["dataset_version"] != source_root.name or not summary.get("graph_seed_ready"):
        raise ValueError("Dataset summary does not match a complete graph seed")
    selected = set()
    for directory in config["dataset_directories"]:
        folder = source_root / portable_path(directory)
        selected.update(path for path in folder.rglob("*") if path.is_file())
    for key in ("monthly_activity_file", "sample_coverage_file"):
        path = source_root / portable_path(summary[key])
        selected.add(path)
        if path.with_suffix(".csv").is_file():
            selected.add(path.with_suffix(".csv"))
    selected = {path for path in selected if not set(path.relative_to(source_root).parts) & set(config["excluded_directories"])
                and path.name not in config["excluded_files"] and path.suffix != ".sqlite"}
    provenance = {}
    for source in sorted(selected):
        if not source.resolve().is_relative_to(source_root):
            raise ValueError("Dataset file resolves outside the configured data directory")
        relative = source.relative_to(source_root)
        path = dataset / relative
        record = copy_public_file(source, path, crossref=config["drop_crossref_abstracts"] and "crossref" in relative.parts)
        provenance[path.relative_to(destination).as_posix()] = record
    # Shared raw copies can have a different checksum after the public transformation.
    for sidecar in dataset.rglob("*.metadata.json"):
        public_source = sidecar.with_suffix("").with_suffix(".jsonl")
        if not public_source.exists():
            raise ValueError(f"Snapshot sidecar has no source: {sidecar.name}")
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        original_sha = metadata["sha256"]
        public_sha = file_digest(public_source)
        metadata.update(sha256=public_sha, original_sha256=original_sha)
        transformations = provenance[public_source.relative_to(destination).as_posix()]["transformations"]
        if transformations:
            metadata["processing"] = metadata.get("processing", []) + transformations
        if "crossref_abstract_removed" in transformations:
            metadata["original_payload_preserved"] = False
        sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        provenance[sidecar.relative_to(destination).as_posix()].update(sha256=file_digest(sidecar), bytes=sidecar.stat().st_size)
    public_summary_path = dataset / "metadata" / summary_path.name
    public_summary = json.loads(public_summary_path.read_text(encoding="utf-8"))
    for key in ("monthly_activity_file", "sample_coverage_file"):
        path = dataset / public_summary[key]
        public_summary["derived_sha256"][path.name] = file_digest(path)
    public_summary_path.write_text(json.dumps(public_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    provenance[public_summary_path.relative_to(destination).as_posix()].update(sha256=file_digest(public_summary_path), bytes=public_summary_path.stat().st_size)
    for name in config["documentation"]:
        source = PROJECT_ROOT / portable_path(name)
        copy_public_file(source, destination / "documentation" / source.name)
    return provenance


def export_shares(settings: Settings, config_path: Path, dump: Path, graph_validation: Path) -> Path:
    """Prepare A/B/C, validate each archive, then write one release manifest.

    The dump is created externally while Neo4j is stopped. This function does
    not stop services, publish to GitHub, or overwrite source data.
    """
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    validation = json.loads(graph_validation.read_text(encoding="utf-8"))
    if not dump.is_file() or validation.get("status") != "passed" or validation.get("neo4j_version") != str(config["neo4j_version"]):
        raise ValueError("A matching, independently restored Neo4j dump is required")
    if validation.get("dump_sha256") != file_digest(dump):
        raise ValueError("Restored dump checksum does not match")
    if config["database"] == "system":
        raise ValueError("System databases cannot be shared")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    context = {"schema_version": "sharing_00", "created_at": datetime.now(timezone.utc).isoformat(),
               "repository": config["repository"], "code_commit": commit, "dataset_version": settings.data_dir.name,
               "historical_as_of_validated": False, "full_scale_forecasting_ready": False}
    export = reserve_export(resolve_project_path(config["export_root"]), config["export_stem"])
    suffix = export.name.rsplit("_", 1)[-1]
    options = {"level": config["compression_level"], "max_bytes": config["max_asset_bytes"]}
    data = export / "A"
    provenance = prepare_data_copy(settings, config, data)
    (data / "README.md").write_text(
        f"# A 数据文件\n\n代码版本：`{commit}`。先核对 manifest_00.json；数据目录为 `dataset/{settings.data_dir.name}`。\n"
        "\nJSONL 可逐行读取；原始响应分享副本去除 Crossref 许可不明摘要，原文校验和及转换保留在清单。\n"
        "\n本机此前检查记录是来源审计历史，并非本分享副本的新验证。共享清单验证文件完整性。\n"
        "\n在自己的独立项目目录解压，设置 DATA_DIR 为该数据目录，再按 documentation/sharing_00.md 操作。\n"
        "\n未完成正式历史可得性检查与全量预测；固定分层种子不是完整语料。\n", encoding="utf-8")
    graph = export / "B"
    graph.mkdir()
    shutil.copyfile(dump, graph / f"{config['database']}.dump")
    shutil.copyfile(graph_validation, graph / "restore_validation_00.json")
    write_json(graph / "database_00.json", {"database": config["database"], "neo4j_version": str(config["neo4j_version"]),
                                            "image": config["neo4j_image"], "contains_system_database": False})
    (graph / "README.md").write_text(
        f"# B 图谱备份\n\nNeo4j {config['neo4j_version']}；镜像 `{config['neo4j_image']}`。\n"
        "\n仅研究数据库，不含系统账户。接收者自行设置密码。先核对清单；\n"
        "按仓库 Attempt/docs/sharing_00.md，在全新空目录恢复；勿覆盖已有数据库。\n"
        "\n恢复验证见 restore_validation_00.json。\n", encoding="utf-8")
    board = export / "C"
    board.mkdir()
    for name in config["report_files"]:
        path = settings.output_dir / portable_path(name)
        if path.is_file():
            shutil.copyfile(path, board / name)
    from techtrend.stages.visualize import VisualizeStage
    board_settings = settings.model_copy(update={"data_dir": data / "dataset" / settings.data_dir.name, "output_dir": board, "viz_dashboard_file": str(board / "dashboard.html"),
        "viz_charts_dir": str(board / "charts"), "weekly_report_file": str(board / "weekly_report.md")})
    result = VisualizeStage(board_settings).run()
    if result.get("status") != "ok":
        raise ValueError("Dashboard generation failed")
    summary = json.loads(sorted((settings.data_dir / "metadata").glob("preparation_summary_*.json"))[-1].read_text(encoding="utf-8"))
    monthly = settings.data_dir / portable_path(summary["monthly_activity_file"])
    shutil.copyfile(monthly.with_suffix(".csv"), board / monthly.with_suffix(".csv").name)
    (board / "README.md").write_text("# C 看板与统计\n\n双击 dashboard.html；无需 Python 或 Docker。\n"
        "\n统计表为独立 API 回溯汇总；两个来源不可相加。预测结果尚未验证。\n", encoding="utf-8")
    assets = []
    for kind, folder, label in (("data", data, "A"), ("graph", graph, "B"), ("dashboard", board, "C")):
        assets.append(package_component(folder, export / f"{kind}_share_{suffix}.zip", {**context, "component": label},
                                        provenance=provenance if label == "A" else None, **options))
    write_json(export / "release_manifest_00.json", {**context, "release_tag": "research-share-" + suffix,
               "assets": assets, "validation": validation, "status": "prepared_not_uploaded"})
    return export
