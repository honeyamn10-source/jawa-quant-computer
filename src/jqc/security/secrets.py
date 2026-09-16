"""Secret vault and redaction utilities.

Secrets (API keys, passwords, tokens) are never exposed to models or logs.
Storage strategy:

1. Prefer the OS keyring (``keyring`` package — Windows Credential Manager,
   macOS Keychain, Linux Secret Service). The vault master key lives there.
2. Fallback to an on-disk key file (``0600``) in the data directory.

The vault payload itself is encrypted with Fernet, so even the fallback key
file setup keeps secrets opaque at rest.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import suppress
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "jawa-quant-computer"
_KEYRING_USERNAME = "vault"

_SECRET_LIKE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret|token|password|passwd|authorization|bearer|"
    r"cookie|refresh_token|access_key|private[_-]?key|client[_-]?secret)\b"
    r"([\"'\s:=]+)([^\n]+)"
)

#: Exact secret strings to redact from any log/UI string.
LIVE_SECRETS: set[str] = set()


class VaultUnlockError(Exception):
    """The vault could not be opened with the available key material."""


class SecretStore:
    """Fernet-encrypted key-value vault."""

    def __init__(self, path: Path, key: bytes | None = None) -> None:
        self.path = path
        self._cipher = Fernet(key if key else self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        raw = _os_keyring_get()
        if raw:
            try:
                Fernet(raw)
                return raw
            except (ValueError, InvalidToken):
                log.warning("Keyring returned an unusable vault key; regenerating a local fallback")
        raw = self._local_key()
        return raw

    def _local_key(self) -> bytes:
        kf = self.path.with_suffix(".key")
        if kf.exists():
            return kf.read_bytes().strip()
        key = Fernet.generate_key()
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_bytes(key)
        with suppress(OSError):  # pragma: no cover - e.g. windows
            os.chmod(kf, 0o600)
        _os_keyring_set(key)
        return key

    def _lock(self):
        pass

    def set(self, name: str, value: str) -> None:
        payload = self._read()
        old = payload.get(name)
        if old:
            LIVE_SECRETS.discard(old)
        payload[name] = value
        if value:
            LIVE_SECRETS.add(value)
        posix = self.path.parent
        posix.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._cipher.encrypt(json.dumps(payload).encode()))

    def get(self, name: str, default: str | None = None) -> str | None:
        try:
            payload = self._read()
        except InvalidToken as exc:
            raise VaultUnlockError("Cannot decrypt the secret vault.") from exc
        val = payload.get(name)
        return val if val is not None else default

    def delete(self, name: str) -> None:
        payload = self._read()
        removed = payload.pop(name, None)
        if removed:
            LIVE_SECRETS.discard(removed)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._cipher.encrypt(json.dumps(payload).encode()))

    def list_names(self) -> list[str]:
        return sorted(self._read().keys())

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self._cipher.decrypt(self.path.read_bytes()).decode())


def _os_keyring_get() -> bytes | None:
    try:
        import keyring

        raw = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        return raw.encode() if raw else None
    except Exception as exc:  # pragma: no cover - environment dependent
        log.debug("keyring unavailable: %s", exc)
        return None


def _os_keyring_set(key: bytes) -> None:
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key.decode())
    except Exception as exc:  # pragma: no cover - environment dependent
        log.debug("keyring write unavailable: %s", exc)


# --------------------------------------------------------------------------
# Redaction helpers
# --------------------------------------------------------------------------


def redact_text(text: str) -> str:
    """Replace likely secret assignments and any known live secrets."""
    out = _SECRET_LIKE.sub(lambda m: f"{m.group(1)}{m.group(2)}***REDACTED***", text)
    for secret in LIVE_SECRETS:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "***REDACTED***")
    return out


def redact_dict(data: dict) -> dict:
    """Return a best-effort redacted copy of a dict (records too)."""
    if isinstance(data, list):
        return [redact_dict(item) if isinstance(item, dict) else item for item in data]
    out = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[k] = redact_dict(v)
        elif isinstance(v, list):
            out[k] = [redact_dict(i) if isinstance(i, dict) else i for i in v]
        elif isinstance(v, str) and k.lower() in {"api_key", "secret", "password", "token", "authorization",
                                                  "access_token", "refresh_token", "client_secret", "cookie"} or isinstance(v, str) and v in LIVE_SECRETS:
            out[k] = "***REDACTED***"
        else:
            out[k] = v
    return out


def redacted_str(data: object) -> str:
    """JSON-serialize ``data`` with secrets redacted."""
    return redact_text(json.dumps(data, default=str))


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))
