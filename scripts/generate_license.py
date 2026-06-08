"""
Vendor (satıcı) lisans aracı — yalnızca satıcıda çalışır, üründe dağıtılmaz.

Komutlar
--------
  keygen
      Yeni Ed25519 anahtar çifti üretir.
      * private key  -> config/private_key.pem  (GİZLİ, gitignore'lu, asla paylaşma)
      * public key   -> app/licensing/keys.py içine otomatik yazılır

  issue --customer "ACME" --cameras 8 --days 365 [--plan standard] [--feature admin_panel ...]
      Bir lisans anahtarı üretir ve ekrana basar. Müşteriye bu satır verilir
      (.env LICENSE_KEY veya config/license.key).

  verify "<license_key>"
      Bir anahtarı yerelde doğrular (debug).

Kullanım:
    python scripts/generate_license.py keygen
    python scripts/generate_license.py issue --customer "ACME Lojistik" --cameras 8 --days 365
    python scripts/generate_license.py verify "eyJ...==.AbC..."
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_KEY_PATH = ROOT / "config" / "private_key.pem"
KEYS_PY_PATH = ROOT / "app" / "licensing" / "keys.py"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --------------------------------------------------------------------------- #
def cmd_keygen(_args) -> int:
    if PRIVATE_KEY_PATH.exists():
        ans = input(f"{PRIVATE_KEY_PATH} zaten var. Üzerine yazılsın mı? (e/h): ")
        if ans.strip().lower() != "e":
            print("İptal edildi.")
            return 1

    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_KEY_PATH.write_bytes(priv_pem)

    pub_hex = pub_raw.hex()
    text = KEYS_PY_PATH.read_text(encoding="utf-8")
    text = re.sub(
        r'VENDOR_PUBLIC_KEY_HEX = "[0-9a-fA-F]*"',
        f'VENDOR_PUBLIC_KEY_HEX = "{pub_hex}"',
        text,
    )
    KEYS_PY_PATH.write_text(text, encoding="utf-8")

    print("✓ Anahtar çifti üretildi.")
    print(f"  private key -> {PRIVATE_KEY_PATH}  (GİZLİ tut, yedekle, paylaşma)")
    print(f"  public key  -> {KEYS_PY_PATH} güncellendi ({pub_hex})")
    return 0


def _load_private_key() -> Ed25519PrivateKey:
    if not PRIVATE_KEY_PATH.exists():
        print(f"❌ {PRIVATE_KEY_PATH} yok. Önce: python scripts/generate_license.py keygen")
        sys.exit(1)
    key = serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        print("❌ private_key.pem bir Ed25519 anahtarı değil.")
        sys.exit(1)
    return key


def cmd_issue(args) -> int:
    priv = _load_private_key()

    payload = {
        "customer": args.customer,
        "plan": args.plan,
        "max_cameras": args.cameras,
        "issued_at": date.today().isoformat(),
        "expires_at": (
            (date.today() + timedelta(days=args.days)).isoformat() if args.days > 0 else None
        ),
        "features": args.feature or [],
    }
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    payload_b64 = _b64url(payload_json.encode("utf-8"))
    signature = priv.sign(payload_b64.encode("ascii"))
    license_key = f"{payload_b64}.{_b64url(signature)}"

    print("\n=== LİSANS ANAHTARI (müşteriye verilecek) ===")
    print(license_key)
    print("\n=== İçerik ===")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("\nMüşteri kurulumu: .env -> LICENSE_KEY=<anahtar>  (veya config/license.key dosyası)")
    return 0


def cmd_verify(args) -> int:
    # keys.py'deki public key ile doğrula (üründeki davranışın aynısı)
    sys.path.insert(0, str(ROOT))
    from app.licensing.keys import VENDOR_PUBLIC_KEY_HEX

    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(VENDOR_PUBLIC_KEY_HEX))
    try:
        payload_b64, sig_b64 = args.key.split(".", 1)
        pub.verify(_b64url_decode(sig_b64), payload_b64.encode("ascii"))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as e:  # noqa: BLE001 — CLI debug aracı
        print(f"❌ GEÇERSİZ: {e}")
        return 1
    print("✓ GEÇERLİ imza")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Vendor lisans aracı")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("keygen", help="Yeni anahtar çifti üret")

    p_issue = sub.add_parser("issue", help="Lisans anahtarı üret")
    p_issue.add_argument("--customer", required=True)
    p_issue.add_argument("--cameras", type=int, default=8)
    p_issue.add_argument("--days", type=int, default=365, help="0 = süresiz")
    p_issue.add_argument("--plan", default="standard")
    p_issue.add_argument("--feature", action="append", help="Tekrarlanabilir")

    p_verify = sub.add_parser("verify", help="Anahtar doğrula")
    p_verify.add_argument("key")

    args = parser.parse_args()
    return {"keygen": cmd_keygen, "issue": cmd_issue, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
