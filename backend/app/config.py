from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pydantic import field_validator
from urllib.parse import urlsplit


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    database_url: str = ""
    secure_cookies: bool = False
    public_origin: str = ""
    pdf_max_bytes: int = 50 * 1024 * 1024
    ai_encryption_key: str = ""
    ai_rate_limit_count: int = Field(default=10, ge=1, le=1000)
    ai_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86400)

    @field_validator('public_origin')
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        if not value:
            return ''
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or '*' in value or value != value.strip()):
            raise ValueError('PUBLIC_ORIGIN must be an exact HTTPS origin without a path')
        try:
            port = parsed.port
        except ValueError:
            raise ValueError('PUBLIC_ORIGIN has an invalid port') from None
        if port is not None and not 1 <= port <= 65535:
            raise ValueError('PUBLIC_ORIGIN has an invalid port')
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
