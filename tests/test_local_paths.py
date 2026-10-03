from pathlib import Path

from techtrend.config import PROJECT_ROOT, Settings
from techtrend.signal.config import load_pipeline_config


def test_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert settings.data_dir == (PROJECT_ROOT / "data").resolve()
    assert settings.output_dir == PROJECT_ROOT / "output"
    assert Path(settings.patent_citations_file) == settings.data_dir / "interim/patent_citations.jsonl"
    assert Path(settings.viz_dashboard_file) == settings.output_dir / "dashboard.html"
    assert Path(settings.signal_topics_path).is_file()
    signal = load_pipeline_config()
    assert signal.data_root == Settings().data_dir / "signal"
    assert signal.start_date == Settings().collection_start_date[:7]
    assert signal.end_date == "2026-01"
    assert signal.resources_root == PROJECT_ROOT / "resources"


def test_storage_overrides_move_related_files(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "inputs", output_dir=tmp_path / "reports")
    assert Path(settings.uspto_raw_dir) == tmp_path / "inputs/raw"
    assert Path(settings.run_manifest_file) == tmp_path / "reports/run_manifest.jsonl"
    assert Path(settings.weekly_report_file) == tmp_path / "reports/weekly_report.md"
    assert Path(settings.viz_charts_dir) == tmp_path / "reports/charts"


def test_explicit_absolute_paths_and_bare_report_names(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path, viz_dashboard_file="board.html",
                        patent_citations_file=str(tmp_path / "citations.jsonl"))
    assert Path(settings.viz_dashboard_file) == tmp_path / "board.html"
    assert Path(settings.patent_citations_file) == tmp_path / "citations.jsonl"


def test_env_file_is_loaded_from_checkout(tmp_path, monkeypatch):
    from techtrend.config import Settings

    monkeypatch.chdir(tmp_path)
    env_path = Path(Settings.model_config["env_file"])
    assert env_path == PROJECT_ROOT / ".env"
