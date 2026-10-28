"""Pi-Software aus Git-Tags aktualisieren (Version wechseln und Dienst neu starten)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from typing import Any, Final, Optional

REPO_DIR: Final[str] = os.environ.get(
    "STOPPUHR_REPO_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
# Fruehere Staende kennen die systemd-Installation ohne Docker nicht
MIN_VERSION: Final[tuple[int, int, int]] = (0, 5, 1)
TAG_RE: Final[re.Pattern[str]] = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
FETCH_TTL_S: Final[int] = 120
_fetch: dict[str, Any] = {"ts": 0.0, "error": None}


def parse_tag(tag: str) -> Optional[tuple[int, int, int]]:
    m = TAG_RE.match(tag or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _git(*args: str, timeout: int = 20) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    res = subprocess.run(
        ["git", "-C", REPO_DIR, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or f"git {args[0]} fehlgeschlagen")
    return res.stdout.strip()


def available() -> bool:
    """True, wenn die Software als Git-Checkout laeuft (nicht im Docker-Image)."""
    try:
        _git("rev-parse", "--git-dir")
        return True
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False


def current() -> dict[str, Optional[str]]:
    info: dict[str, Optional[str]] = {"commit": None, "tag": None, "branch": None}
    try:
        info["commit"] = _git("rev-parse", "--short", "HEAD")
        info["branch"] = _git("branch", "--show-current") or None
        try:
            info["tag"] = _git("describe", "--tags", "--exact-match", "HEAD")
        except RuntimeError:
            info["tag"] = None
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    return info


def list_tags(refresh: bool = True) -> tuple[list[str], Optional[str]]:
    """Versions-Tags (neueste zuerst) und ggf. Fehlertext vom Abholen (dann nur lokale Tags)."""
    error = _fetch["error"]
    if refresh and time.time() - _fetch["ts"] >= FETCH_TTL_S:
        try:
            _git("fetch", "--tags", "--quiet", "origin", timeout=30)
            error = None
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            error = f"GitHub nicht erreichbar: {exc}"
        _fetch["ts"], _fetch["error"] = time.time(), error
    tags = [t for t in _git("tag", "-l", "v*").splitlines() if (v := parse_tag(t)) and v >= MIN_VERSION]
    tags.sort(key=lambda t: parse_tag(t) or (0, 0, 0), reverse=True)
    return tags, error


def switch_to(tag: str) -> str:
    """Wechselt auf den Tag und installiert Abhaengigkeiten; bei Fehlern zurueck. Gibt den neuen Commit zurueck."""
    if parse_tag(tag) is None:
        raise ValueError("Ungueltige Version")
    previous = _git("rev-parse", "HEAD")
    _git("checkout", "--detach", f"refs/tags/{tag}")
    requirements = os.path.join(REPO_DIR, "deploy", "requirements.txt")
    try:
        if os.path.isfile(requirements):
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "-r", requirements],
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
            if res.returncode != 0:
                raise RuntimeError("Abhaengigkeiten: " + (res.stderr or res.stdout).strip()[-200:])
    except (RuntimeError, subprocess.SubprocessError, OSError):
        _git("checkout", "--detach", previous)
        raise
    return _git("rev-parse", "--short", "HEAD")
