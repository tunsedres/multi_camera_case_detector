"""
Shopify access token'ının GERÇEKTE hangi scope'lara sahip olduğunu gösterir.

Fulfillment çalışmıyorsa ilk bakılacak yer burası: `write_orders` TEK BAŞINA
fulfillment'ı KAPSAMAZ; ayrı fulfillment-order scope'ları gerekir. Bu script
canlı token'ın scope listesini Shopify'dan çeker (kodun varsaydığını değil,
mağazanın gerçekten verdiğini) ve eksik fulfillment scope'larını işaretler.

Kullanım:
    python scripts/check_shopify_scopes.py

.env içinde SHOPIFY_SHOP_URL + (SHOPIFY_ACCESS_TOKEN ya da
SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET) dolu olmalı.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from app.integrations.shopify_client import ShopifyClient  # noqa: E402
from app.settings import get_settings  # noqa: E402

# Otomatik fulfillment (notifyCustomer dâhil) için gereken scope'lar.
_REQUIRED_FOR_FULFILLMENT = [
    "read_merchant_managed_fulfillment_orders",
    "write_merchant_managed_fulfillment_orders",
]
_REQUIRED_FOR_NOTE_METAFIELD = ["read_orders", "write_orders"]

_QUERY_SCOPES = """
query { currentAppInstallation { accessScopes { handle } } }
"""


def main() -> int:
    load_dotenv()
    s = get_settings()
    if not s.shopify_shop_url:
        print("❌ .env'de SHOPIFY_SHOP_URL gerekli!")
        return 1
    if not (s.shopify_access_token or s.shopify_use_client_credentials):
        print("❌ SHOPIFY_ACCESS_TOKEN ya da SHOPIFY_CLIENT_ID+SECRET tanımla!")
        return 1

    client = ShopifyClient.from_settings(s)
    auth_mode = "client_credentials" if s.shopify_use_client_credentials else "statik token"
    print(f"Shopify: {s.shopify_shop_url}  (API {s.shopify_api_version}, auth: {auth_mode})\n")

    try:
        data = client._graphql(_QUERY_SCOPES, {})
    except Exception as e:  # noqa: BLE001
        print(f"❌ Scope sorgusu başarısız: {e}")
        print("   (Token/bağlantı sorunuysa önce: python scripts/test_shopify.py)")
        return 1

    scopes = {
        n["handle"] for n in ((data.get("currentAppInstallation") or {}).get("accessScopes") or [])
    }
    if not scopes:
        print("❌ Hiç scope dönmedi — token geçersiz olabilir.")
        return 1

    print("Token'daki scope'lar:")
    for sc in sorted(scopes):
        print(f"  • {sc}")

    def _check(label: str, required: list[str]) -> bool:
        missing = [r for r in required if r not in scopes]
        if missing:
            print(f"\n❌ {label} — EKSİK scope: {', '.join(missing)}")
            return False
        print(f"\n✓ {label} — tüm scope'lar mevcut")
        return True

    ok_meta = _check("Not / metafield yazımı", _REQUIRED_FOR_NOTE_METAFIELD)
    ok_fulfill = _check("Otomatik fulfillment", _REQUIRED_FOR_FULFILLMENT)

    if not ok_fulfill:
        print(
            "\n⚠️  Fulfillment çalışmamasının nedeni büyük olasılıkla bu. "
            "Shopify admin → Apps → (app) → Configuration → Admin API access scopes'a\n"
            "    read_merchant_managed_fulfillment_orders\n"
            "    write_merchant_managed_fulfillment_orders\n"
            "ekle, KAYDET, sonra app'i yeniden yetkilendir (Install/Update) → "
            "yeni token'da scope'lar görünür → uygulamayı yeniden başlat.\n"
            "(3rd-party fulfillment servisi kullanıyorsan *_third_party_fulfillment_orders çiftini de ekle.)"
        )
    return 0 if (ok_meta and ok_fulfill) else 2


if __name__ == "__main__":
    raise SystemExit(main())
