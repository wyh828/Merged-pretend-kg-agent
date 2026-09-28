"""Optional cloud backup for processed data via Huawei Cloud OBS.

This module is a thin, additive wrapper around the Huawei Cloud OBS Python
SDK (``esdk-obs-python``). It does NOT change how :mod:`config.PipelineConfig`
resolves local paths -- local files under ``Data/`` remain the source of
truth. Cloud sync is opt-in and controlled by
``Attempt/configs/cloud_storage.yaml`` (``huawei_obs.enabled``).

Credentials (``HUAWEICLOUD_AK`` / ``HUAWEICLOUD_SK``) are read from ``.env``
and are never read from or written to any config file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from techtrend.signal.config import SIGNAL_CONFIG_DIR, PipelineConfig

DEFAULT_CLOUD_CONFIG_PATH = SIGNAL_CONFIG_DIR / "cloud_storage.yaml"


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def load_cloud_storage_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load the ``huawei_obs`` section of ``cloud_storage.yaml``.

    Returns an empty-but-valid dict (``enabled: False``) if the file is
    missing, so callers can treat cloud sync as opt-in without extra checks.
    """
    path = config_path or DEFAULT_CLOUD_CONFIG_PATH
    if not path.exists():
        return {"enabled": False, "sync_targets": []}
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("huawei_obs", {"enabled": False, "sync_targets": []})


def _get_client(obs_cfg: dict[str, Any]):
    """Build an authenticated ``ObsClient``. Raises if credentials are missing.

    Imported lazily so importing this module does not require the OBS SDK
    to be installed unless cloud sync is actually used.
    """
    from obs import ObsClient  # local import: optional dependency

    _load_env()
    ak_env = obs_cfg.get("access_key_env", "HUAWEICLOUD_AK")
    sk_env = obs_cfg.get("secret_key_env", "HUAWEICLOUD_SK")
    access_key = os.environ.get(ak_env, "").strip()
    secret_key = os.environ.get(sk_env, "").strip()
    if not access_key or not secret_key:
        raise RuntimeError(
            f"Missing Huawei Cloud credentials: set {ak_env} and {sk_env} in .env"
        )
    endpoint = obs_cfg["endpoint"]
    return ObsClient(access_key_id=access_key, secret_access_key=secret_key, server=endpoint)


def upload_file(local_path: Path, remote_key: str, obs_cfg: dict[str, Any] | None = None) -> None:
    """Upload one local file to OBS under ``remote_key``.

    Raises ``RuntimeError`` if the upload does not return a 2xx status.
    """
    cfg = obs_cfg or load_cloud_storage_config()
    client = _get_client(cfg)
    try:
        resp = client.putFile(cfg["bucket"], remote_key, str(local_path))
    finally:
        client.close()
    if resp.status >= 300:
        raise RuntimeError(f"OBS upload failed for {remote_key}: {resp.errorMessage}")


def download_file(remote_key: str, local_path: Path, obs_cfg: dict[str, Any] | None = None) -> None:
    """Download one OBS object to ``local_path``.

    Raises ``RuntimeError`` if the download does not return a 2xx status.
    """
    cfg = obs_cfg or load_cloud_storage_config()
    client = _get_client(cfg)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = client.getObject(cfg["bucket"], remote_key, downloadPath=str(local_path))
    finally:
        client.close()
    if resp.status >= 300:
        raise RuntimeError(f"OBS download failed for {remote_key}: {resp.errorMessage}")


def list_remote_objects(prefix: str, obs_cfg: dict[str, Any] | None = None) -> list[str]:
    """List object keys under ``prefix`` in the configured bucket."""
    cfg = obs_cfg or load_cloud_storage_config()
    client = _get_client(cfg)
    try:
        resp = client.listObjects(cfg["bucket"], prefix=prefix)
    finally:
        client.close()
    if resp.status >= 300:
        raise RuntimeError(f"OBS listObjects failed for prefix {prefix!r}: {resp.errorMessage}")
    return [content.key for content in resp.body.contents]


def sync_processed_data(pipeline_cfg: PipelineConfig, obs_cfg: dict[str, Any] | None = None) -> list[str]:
    """Upload every file under each enabled ``sync_targets`` local layer to OBS.

    Local layer names in ``cloud_storage.yaml`` (e.g. ``Processed``,
    ``Interim``) are resolved relative to ``pipeline_cfg.data_root``. Remote
    keys are ``{remote_prefix}/{dataset_name}/{relative_path}``.

    Returns the list of remote keys that were uploaded. No-op (returns an
    empty list) if cloud sync is disabled.
    """
    cfg = obs_cfg or load_cloud_storage_config()
    if not cfg.get("enabled", False):
        return []

    uploaded: list[str] = []
    for target in cfg.get("sync_targets", []):
        if not target.get("enabled", True):
            continue
        local_layer_root = pipeline_cfg.data_root / target["local"] / pipeline_cfg.dataset_name
        if not local_layer_root.exists():
            continue
        for file_path in local_layer_root.rglob("*"):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(local_layer_root)
            remote_key = f"{target['remote_prefix']}/{pipeline_cfg.dataset_name}/{relative.as_posix()}"
            upload_file(file_path, remote_key, cfg)
            uploaded.append(remote_key)
    return uploaded
