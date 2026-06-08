"""
Ortam (env) tabanlı ayarlar — sırlar ve deployment parametreleri.

İki katmanlı konfigürasyon yaklaşımı:
  * settings.py (bu dosya) → .env'den okunur: sırlar, kimlik bilgileri, web/log/lisans.
  * config.py              → config.yaml'dan okunur: kameralar, tespit, depolama (yapısal).

Sırların YAML'a sızmaması, deployment-spesifik değerlerin koddan ayrılması için.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`.env` ve ortam değişkenlerinden yüklenen runtime ayarları."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Shopify ----
    shopify_shop_url: str = ""
    shopify_access_token: str = ""
    shopify_api_version: str = "2025-01"

    # ---- Kamera kimlik bilgileri (RTSP {user}/{pass} doldurma) ----
    camera_username: str = "admin"
    camera_password: str = ""

    # ---- Lisans ----
    license_key: str = ""
    license_enforce: bool = False

    # ---- Admin Web Panel ----
    web_enabled: bool = True
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8080, ge=1, le=65535)
    admin_username: str = "admin"
    admin_password: str = ""

    # ---- Loglama ----
    log_level: str = "INFO"
    tz: str = "Europe/Istanbul"

    @property
    def auth_enabled(self) -> bool:
        """Panel kimlik doğrulaması yalnızca parola tanımlıysa devreye girer."""
        return bool(self.admin_password)

    def resolve_license_key(self, license_file: str = "config/license.key") -> str:
        """
        Lisans anahtarını çöz: önce LICENSE_KEY env, yoksa config/license.key dosyası.
        Dağıtımda anahtarı dosyaya koymak (env'den daha kalıcı) yaygın bir yöntem.
        """
        if self.license_key.strip():
            return self.license_key.strip()
        path = Path(license_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton Settings (uygulama boyunca tek örnek)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
