from techtrend import config


def test_model_cache_defaults_stay_in_project(monkeypatch, tmp_path):
    keys = ("PYSTOW_HOME", "PYKEEN_HOME", "TORCH_HOME", "HF_HOME")
    for key in keys:
        monkeypatch.setenv(key, "")
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(data_dir=tmp_path))
    config.configure_model_storage()
    import os
    from pathlib import Path
    assert all(Path(os.environ[key]).is_relative_to(tmp_path / "cache") for key in keys)
