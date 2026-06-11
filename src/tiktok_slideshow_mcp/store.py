"""Persistent OAuth token storage.

Tokens are stored as JSON at `settings.token_store_path` (default
`~/.tiktok_slideshow_mcp/tokens.json`). Accounts are keyed by TikTok `open_id`; the most
recently authorized account is treated as the default when none is specified.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings, get_settings


@dataclass
class TokenRecord:
    open_id: str
    access_token: str
    refresh_token: str
    # Epoch seconds at which each token expires.
    access_expires_at: float
    refresh_expires_at: float
    scope: str = ""
    nickname: str = ""

    def access_expired(self, skew: int = 60) -> bool:
        return time.time() >= (self.access_expires_at - skew)

    def refresh_expired(self) -> bool:
        return time.time() >= self.refresh_expires_at

    @classmethod
    def from_token_response(cls, data: dict) -> "TokenRecord":
        """Build a record from a TikTok /v2/oauth/token/ response body."""
        now = time.time()
        return cls(
            open_id=data["open_id"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            access_expires_at=now + float(data.get("expires_in", 0)),
            refresh_expires_at=now + float(data.get("refresh_expires_in", 0)),
            scope=data.get("scope", ""),
        )


class TokenStore:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.path = Path(self.settings.token_store_path)

    # --- persistence ---
    def _read(self) -> dict:
        if not self.path.is_file():
            return {"default": None, "accounts": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"default": None, "accounts": {}}

    def _write(self, blob: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
        # Best-effort lock down the file (no-op on platforms without chmod support).
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # --- API ---
    def save(self, record: TokenRecord, make_default: bool = True) -> None:
        blob = self._read()
        blob["accounts"][record.open_id] = asdict(record)
        if make_default or blob.get("default") is None:
            blob["default"] = record.open_id
        self._write(blob)

    def get(self, open_id: str | None = None) -> TokenRecord | None:
        blob = self._read()
        accounts = blob.get("accounts", {})
        key = open_id or blob.get("default")
        if not key or key not in accounts:
            return None
        return TokenRecord(**accounts[key])

    def list(self) -> list[TokenRecord]:
        blob = self._read()
        return [TokenRecord(**a) for a in blob.get("accounts", {}).values()]

    def default_open_id(self) -> str | None:
        return self._read().get("default")
