import os
from pathlib import Path
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_SQLITE_PATH = f"sqlite:///{BASE_DIR / 'nanolab_glp.db'}"


class Settings(BaseSettings):
    APP_NAME: str = "Nanolab Edirne GLP Operasyonel Planlama ve Çakışma Yönetimi"
    ENV: str = "development"
    APP_ENV: str = "development"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = DEFAULT_SQLITE_PATH
    TRUSTED_PROXY_CIDRS: str = ""
    SECRET_KEY: str = "glp_nanolab_secret_key_2026_edirne"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720  # 12 saat (1 vardiya)
    ALLOWED_ORIGINS: str = "*"

    # OpenAI & LLM Configuration (değerler backend/.env dosyasından okunur)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TIMEOUT_SECONDS: float = 60.0

    # FAZ 6: Belge yükleme (Document Ingestion)
    UPLOAD_DIR: str = str(BASE_DIR / "uploads")
    MAX_UPLOAD_MB: int = 25
    # LLM'e gönderilecek azami metin uzunluğu (karakter); uzun belgeler kırpılır
    MAX_PARSE_CHARS: int = 60000

    @property
    def is_production(self) -> bool:
        env_val = (os.environ.get("ENV") or os.environ.get("APP_ENV") or self.ENV or self.APP_ENV or "").strip().lower()
        return env_val in ("production", "prod")

    @property
    def allowed_origins_list(self) -> List[str]:
        raw = (self.ALLOWED_ORIGINS or "*").strip()
        if raw == "*":
            return ["*"]
        items = [o.strip() for o in raw.split(",") if o.strip()]
        return items or ["*"]

    @field_validator("OPENAI_API_KEY")
    @classmethod
    def _clean_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Boş / tırnaklı / boşluklu değerleri temizler; boşsa None döner."""
        if v is None:
            return None
        v = v.strip().strip('"').strip("'").strip()
        return v or None

    # .env her zaman backend/ altından okunur (çalışma dizininden bağımsız)
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    @field_validator("DATABASE_URL")
    @classmethod
    def _anchor_relative_sqlite(cls, v: str) -> str:
        """Göreli SQLite yollarını backend/ klasörüne sabitler; tek bir veritabanı dosyası garanti edilir."""
        prefix = "sqlite:///"
        if v.startswith(prefix):
            path = v[len(prefix):]
            if path and path != ":memory:" and not os.path.isabs(path):
                return prefix + str((BASE_DIR / path).resolve())
        return v


settings = Settings()
