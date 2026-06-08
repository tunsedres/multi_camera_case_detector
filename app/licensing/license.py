"""
Offline lisans doğrulama (Ed25519).

Lisans anahtarı formatı:   <base64url(payload_json)>.<base64url(signature)>

payload örneği:
    {
      "customer": "ACME Lojistik",
      "plan": "standard",
      "max_cameras": 8,
      "issued_at": "2026-06-08",
      "expires_at": "2027-06-08",   # null/eksik = süresiz
      "features": ["admin_panel", "nvr_isapi"]
    }

İmza, base64url(payload) ASCII baytları üzerinden alınır. Doğrulama tamamen
offline'dır (phone-home yok) — internetsiz depolar için uygundur. Sahtecilik
asimetrik imza ile engellenir: yalnızca satıcının private key'i geçerli anahtar
üretebilir.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.licensing.keys import VENDOR_PUBLIC_KEY_HEX


class LicenseError(Exception):
    """Lisans çözümlenemedi, imza geçersiz veya zorunluyken eksik."""


class LicenseStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"  # imza/format hatalı
    MISSING = "missing"  # anahtar yok
    OVER_LIMIT = "over_limit"  # kamera limiti aşıldı


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@dataclass(frozen=True)
class License:
    customer: str
    plan: str = "standard"
    max_cameras: int | None = None
    issued_at: date | None = None
    expires_at: date | None = None
    features: tuple[str, ...] = field(default_factory=tuple)
    raw_payload: dict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict) -> License:
        def _parse_date(v):
            return date.fromisoformat(v) if v else None

        return cls(
            customer=payload.get("customer", "unknown"),
            plan=payload.get("plan", "standard"),
            max_cameras=payload.get("max_cameras"),
            issued_at=_parse_date(payload.get("issued_at")),
            expires_at=_parse_date(payload.get("expires_at")),
            features=tuple(payload.get("features", [])),
            raw_payload=payload,
        )

    def is_expired(self, today: date | None = None) -> bool:
        if self.expires_at is None:
            return False
        today = today or datetime.now().date()
        return today > self.expires_at

    def days_remaining(self, today: date | None = None) -> int | None:
        if self.expires_at is None:
            return None
        today = today or datetime.now().date()
        return (self.expires_at - today).days

    def has_feature(self, name: str) -> bool:
        return name in self.features


class LicenseManager:
    """Lisans anahtarını doğrular ve durumunu raporlar."""

    def __init__(self, public_key_hex: str = VENDOR_PUBLIC_KEY_HEX):
        self._public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))

    def verify(self, license_key: str) -> License:
        """
        Anahtarı doğrular ve License döner. İmza/format hatasında LicenseError atar.
        Süre dolmuşsa hata ATMAZ (License döner) — süre kontrolü çağıran tarafça
        evaluate() ile yapılır; böylece "süresi dolmuş ama geçerli imzalı" durumu
        ayırt edilebilir.
        """
        if not license_key or "." not in license_key:
            raise LicenseError("Lisans anahtarı boş veya hatalı formatta")

        payload_b64, sig_b64 = license_key.strip().split(".", 1)

        try:
            signature = _b64url_decode(sig_b64)
        except (ValueError, TypeError) as e:
            raise LicenseError(f"İmza base64 çözülemedi: {e}") from e

        try:
            self._public_key.verify(signature, payload_b64.encode("ascii"))
        except InvalidSignature as e:
            raise LicenseError("İmza geçersiz — anahtar bu ürüne ait değil") from e

        try:
            payload = json.loads(_b64url_decode(payload_b64))
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            raise LicenseError(f"Lisans payload bozuk: {e}") from e

        return License.from_payload(payload)

    def evaluate(
        self,
        license_key: str,
        active_cameras: int = 0,
        today: date | None = None,
    ) -> tuple[LicenseStatus, License | None]:
        """
        Anahtarı doğrula + durum belirle. Exception atmaz; (status, license) döner.
        Çağıran taraf enforce ayarına göre karar verir.
        """
        if not license_key:
            return LicenseStatus.MISSING, None
        try:
            lic = self.verify(license_key)
        except LicenseError:
            return LicenseStatus.INVALID, None

        if lic.is_expired(today):
            return LicenseStatus.EXPIRED, lic
        if lic.max_cameras is not None and active_cameras > lic.max_cameras:
            return LicenseStatus.OVER_LIMIT, lic
        return LicenseStatus.VALID, lic
