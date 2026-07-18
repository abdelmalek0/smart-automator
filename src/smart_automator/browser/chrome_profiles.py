from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_CHROME_ROOTS: list[tuple[str, str]] = [
    ("Chrome", "~/.config/google-chrome"),
    ("Chrome Beta", "~/.config/google-chrome-beta"),
    ("Chromium", "~/.config/chromium"),
    ("Chromium (snap)", "~/snap/chromium/common/chromium"),
]


def known_system_chrome_roots() -> list[Path]:
    return [Path(path_template).expanduser() for _, path_template in _CHROME_ROOTS]


def is_system_chrome_user_data_dir(path: str) -> bool:
    if not (path or "").strip():
        return False
    resolved = Path(path).expanduser().resolve()
    for root in known_system_chrome_roots():
        try:
            if resolved == root.resolve():
                return True
        except OSError:
            if resolved == root:
                return True
    return False


@dataclass(frozen=True)
class ChromeProfile:
    id: str
    browser: str
    name: str
    user_data_dir: str
    profile_directory: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _profile_id(user_data_dir: str, profile_directory: str) -> str:
    return f"{user_data_dir}|{profile_directory}"


def _display_name(raw_name: str, profile_directory: str) -> str:
    stripped = (raw_name or "").strip()
    if stripped:
        return stripped
    if profile_directory == "Default":
        return "Default"
    return profile_directory


def _profiles_from_local_state(root: Path, browser: str) -> list[ChromeProfile]:
    local_state_path = root / "Local State"
    if not local_state_path.is_file():
        return []

    try:
        with open(local_state_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("Failed to read Chrome Local State at %s: %s", local_state_path, exc)
        return []

    info_cache = data.get("profile", {}).get("info_cache", {})
    if not isinstance(info_cache, dict):
        return []

    profiles: list[ChromeProfile] = []
    user_data_dir = str(root)
    for profile_directory, info in info_cache.items():
        if not isinstance(info, dict):
            continue
        name = _display_name(str(info.get("name", "")), str(profile_directory))
        profiles.append(
            ChromeProfile(
                id=_profile_id(user_data_dir, str(profile_directory)),
                browser=browser,
                name=name,
                user_data_dir=user_data_dir,
                profile_directory=str(profile_directory),
            )
        )
    return profiles


def _profiles_from_preferences_dirs(root: Path, browser: str) -> list[ChromeProfile]:
    profiles: list[ChromeProfile] = []
    user_data_dir = str(root)
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "Preferences").is_file():
            continue
        profile_directory = child.name
        profiles.append(
            ChromeProfile(
                id=_profile_id(user_data_dir, profile_directory),
                browser=browser,
                name=_display_name("", profile_directory),
                user_data_dir=user_data_dir,
                profile_directory=profile_directory,
            )
        )
    return profiles


def discover_chrome_profiles() -> list[ChromeProfile]:
    discovered: list[ChromeProfile] = []
    seen_ids: set[str] = set()

    for browser, root_template in _CHROME_ROOTS:
        root = Path(root_template).expanduser()
        if not root.is_dir():
            continue

        profiles = _profiles_from_local_state(root, browser)
        if not profiles:
            profiles = _profiles_from_preferences_dirs(root, browser)

        for profile in profiles:
            if profile.id in seen_ids:
                continue
            seen_ids.add(profile.id)
            discovered.append(profile)

    discovered.sort(key=lambda item: (item.browser.lower(), item.name.lower(), item.profile_directory))
    return discovered


def format_effective_chrome_profile(
  user_data_dir: str,
  *,
  profile_directory: str = "",
) -> str:
    if profile_directory:
        return f"{user_data_dir} (profile: {profile_directory})"
    return user_data_dir
