"""Environment-based configuration for the TikTok slideshow MCP server.

Settings are read from environment variables (a local `.env` file is loaded automatically
if present). See `.env.example` for the full list and how to obtain each value.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_token_path() -> Path:
    return Path.home() / ".tiktok_slideshow_mcp" / "tokens.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- TikTok app credentials (TikTok for Developers portal) ---
    tiktok_client_key: str = Field(default="", validation_alias="TIKTOK_CLIENT_KEY")
    tiktok_client_secret: str = Field(default="", validation_alias="TIKTOK_CLIENT_SECRET")
    tiktok_redirect_uri: str = Field(default="", validation_alias="TIKTOK_REDIRECT_URI")
    # Space-separated OAuth scopes. video.upload = required for MEDIA_UPLOAD (inbox draft).
    tiktok_scopes: str = Field(
        default="user.info.basic,video.upload",
        validation_alias="TIKTOK_SCOPES",
    )

    # --- Cloudflare R2 (S3-compatible) image hosting ---
    r2_account_id: str = Field(default="", validation_alias="R2_ACCOUNT_ID")
    r2_access_key_id: str = Field(default="", validation_alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(default="", validation_alias="R2_SECRET_ACCESS_KEY")
    r2_bucket: str = Field(default="tiktok-slideshows", validation_alias="R2_BUCKET")
    # Public base URL = the TikTok-verified custom domain mapped to the R2 bucket.
    # e.g. https://tt-media.yourbrand.com  (no trailing slash required)
    r2_public_base_url: str = Field(default="", validation_alias="R2_PUBLIC_BASE_URL")

    # --- Local token persistence ---
    token_store_path: Path = Field(
        default_factory=_default_token_path,
        validation_alias="TOKEN_STORE_PATH",
    )

    @property
    def r2_endpoint_url(self) -> str:
        """S3 API endpoint for the R2 account."""
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @property
    def scope_list(self) -> list[str]:
        return [s.strip() for s in self.tiktok_scopes.replace(" ", ",").split(",") if s.strip()]

    def require_tiktok(self) -> None:
        missing = [
            name
            for name, val in {
                "TIKTOK_CLIENT_KEY": self.tiktok_client_key,
                "TIKTOK_CLIENT_SECRET": self.tiktok_client_secret,
                "TIKTOK_REDIRECT_URI": self.tiktok_redirect_uri,
            }.items()
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Missing TikTok config: " + ", ".join(missing) + ". Set them in your .env file."
            )

    def require_r2(self) -> None:
        missing = [
            name
            for name, val in {
                "R2_ACCOUNT_ID": self.r2_account_id,
                "R2_ACCESS_KEY_ID": self.r2_access_key_id,
                "R2_SECRET_ACCESS_KEY": self.r2_secret_access_key,
                "R2_BUCKET": self.r2_bucket,
                "R2_PUBLIC_BASE_URL": self.r2_public_base_url,
            }.items()
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Missing Cloudflare R2 config: " + ", ".join(missing) + ". Set them in your .env file."
            )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
