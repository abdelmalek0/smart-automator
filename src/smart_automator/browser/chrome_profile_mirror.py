from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path

from ..config import DEFAULT_CHROME_PROFILE_DIR
from .chrome_profiles import is_system_chrome_user_data_dir

log = logging.getLogger(__name__)

_EXCLUDE_NAMES = frozenset(
    {
        "Cache",
        "Code Cache",
        "GPUCache",
        "Service Worker",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "ShaderCache",
        "GrShaderCache",
        "blob_storage",
        "BrowserMetrics",
        "Crashpad",
        "optimization_guide_hint_cache_store",
    }
)

_SYSTEM_CHROME_ROOT_ERROR = (
    "System Chrome user-data directories require selecting a named profile. "
    "Pick a profile in Settings → Browser, or use a non-system custom path."
)


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in _EXCLUDE_NAMES or name.startswith("Singleton"):
            ignored.add(name)
    return ignored


def _sanitize_mirror_key(user_data_dir: str, profile_directory: str) -> str:
    raw = f"{user_data_dir}|{profile_directory}"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)
    return sanitized.strip("_") or "profile"


def mirror_destination(user_data_dir: str, profile_directory: str) -> Path:
    mirror_key = _sanitize_mirror_key(user_data_dir, profile_directory)
    return DEFAULT_CHROME_PROFILE_DIR / "mirrors" / mirror_key


def chrome_profile_mirror_path(user_data_dir: str, profile_directory: str) -> str:
    profile_directory = (profile_directory or "").strip()
    if not profile_directory or not is_system_chrome_user_data_dir(user_data_dir):
        return ""
    return str(mirror_destination(user_data_dir, profile_directory))


def _write_local_state(mirror_root: Path) -> None:
    local_state = {
        "profile": {
            "info_cache": {"Default": {"name": "Default"}},
            "last_used": "Default",
        }
    }
    with open(mirror_root / "Local State", "w", encoding="utf-8") as handle:
        json.dump(local_state, handle)


def sync_chrome_profile(user_data_dir: str, profile_directory: str) -> Path:
    profile_directory = (profile_directory or "").strip()
    if not profile_directory:
        raise ValueError(_SYSTEM_CHROME_ROOT_ERROR)

    source_root = Path(user_data_dir).expanduser()
    source_profile = source_root / profile_directory
    if not source_profile.is_dir():
        raise ValueError(f"Chrome profile not found: {source_profile}")

    mirror_root = mirror_destination(str(source_root), profile_directory)
    dest_profile = mirror_root / "Default"
    mirror_root.mkdir(parents=True, exist_ok=True)
    if dest_profile.exists():
        shutil.rmtree(dest_profile)

    started = time.monotonic()
    shutil.copytree(source_profile, dest_profile, ignore=_copy_ignore)
    _write_local_state(mirror_root)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "Mirrored Chrome profile %s/%s to %s in %dms",
        source_root,
        profile_directory,
        mirror_root,
        elapsed_ms,
    )
    return mirror_root


def resolve_persistent_launch_dir(user_data_dir: str, profile_directory: str) -> tuple[str, str]:
    profile_directory = (profile_directory or "").strip()
    if is_system_chrome_user_data_dir(user_data_dir):
        if not profile_directory:
            raise ValueError(_SYSTEM_CHROME_ROOT_ERROR)
        mirror_path = sync_chrome_profile(user_data_dir, profile_directory)
        return str(mirror_path), ""

    if profile_directory:
        return user_data_dir, profile_directory
    return user_data_dir, ""


def format_mirrored_chrome_profile(
    *,
    profile_directory: str,
    mirror_path: str,
    profile_name: str = "",
) -> str:
    label = (profile_name or profile_directory or "profile").strip()
    return f"{label} (mirrored to {mirror_path})"
