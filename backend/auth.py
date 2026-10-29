"""Anmeldung fuer die Weboberflaeche: Benutzer und Kennwort liegen (als Hash) im Redis.

Der Zugang wird beim ersten Oeffnen festgelegt. Liegt Redis auf beiden Pis (Replikation),
gilt er auch nach einer Ausfallübernahme.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Final, Optional

from werkzeug.security import check_password_hash, generate_password_hash

AUTH_KEY: Final[str] = "AUTH"
SECRET_KEY: Final[str] = "AUTH_SECRET"
MIN_PASSWORD_LEN: Final[int] = 6
MAX_USER_LEN: Final[int] = 32


def load(r: Any) -> Optional[dict[str, str]]:
    raw = r.get(AUTH_KEY)
    return json.loads(raw) if raw else None


def validate(user: str, password: str) -> Optional[str]:
    """Fehlertext oder None, wenn Benutzer und Kennwort zulaessig sind."""
    if not user or len(user) > MAX_USER_LEN or user != user.strip():
        return f"Benutzername: 1 bis {MAX_USER_LEN} Zeichen, ohne Leerzeichen am Rand"
    if len(password) < MIN_PASSWORD_LEN:
        return f"Kennwort: mindestens {MIN_PASSWORD_LEN} Zeichen"
    return None


def _entry(user: str, password: str) -> str:
    return json.dumps({"user": user, "hash": generate_password_hash(password)})


def create_first(r: Any, user: str, password: str) -> bool:
    """Legt den Zugang an, aber nur wenn noch keiner existiert (False sonst)."""
    return bool(r.set(AUTH_KEY, _entry(user, password), nx=True))


def replace(r: Any, user: str, password: str) -> None:
    r.set(AUTH_KEY, _entry(user, password))


def verify(r: Any, user: str, password: str) -> bool:
    cred = load(r)
    # Auch bei falschem Benutzer rechnen, damit die Antwortzeit nichts verraet
    hash_ = cred["hash"] if cred else generate_password_hash("x")
    ok = check_password_hash(hash_, password)
    return bool(cred) and ok and secrets.compare_digest(cred["user"], user)


def fingerprint(cred: dict[str, str]) -> str:
    """Kurzer Wert, der sich mit dem Kennwort aendert (macht alte Sitzungen ungueltig)."""
    return hashlib.sha256(cred["hash"].encode("utf-8")).hexdigest()[:16]


def secret(r: Any) -> str:
    """Geheimer Schluessel fuer die Sitzungs-Cookies; liegt im Redis, damit beide Pis ihn teilen."""
    value = r.get(SECRET_KEY)
    if not value:
        r.set(SECRET_KEY, secrets.token_hex(32), nx=True)
        value = r.get(SECRET_KEY)
    return value
