"""
Shopify bağlantı + yazma testi (GraphQL).

Kullanım:
    python scripts/test_shopify.py                 # sadece bağlantı testi
    python scripts/test_shopify.py "#1001"         # sipariş bul + test yorumu ekle

.env içinde SHOPIFY_SHOP_URL ve SHOPIFY_ACCESS_TOKEN dolu olmalı.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from app.integrations.shopify_client import OrderNotFound, ShopifyClient  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main() -> int:
    load_dotenv()
    s = get_settings()
    if not s.shopify_shop_url or not s.shopify_access_token:
        print("❌ .env'de SHOPIFY_SHOP_URL ve SHOPIFY_ACCESS_TOKEN gerekli!")
        return 1

    client = ShopifyClient(
        shop_url=s.shopify_shop_url,
        access_token=s.shopify_access_token,
        api_version=s.shopify_api_version,
    )

    print(f"Shopify: {s.shopify_shop_url}  (API {s.shopify_api_version})")
    try:
        shop = client.test_connection()
        print(f"✓ Bağlantı OK — mağaza: {shop.get('name')} ({shop.get('myshopifyDomain')})")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Bağlantı/token hatası: {e}")
        return 1

    if len(sys.argv) < 2:
        print("\nSipariş testi için: python scripts/test_shopify.py '#1001'")
        return 0

    order_no = sys.argv[1]
    print(f"\nSipariş aranıyor: {order_no}")
    try:
        order = client.find_order_by_name(order_no)
        if not order:
            print(f"❌ Sipariş bulunamadı: {order_no} (Shopify admin'de var mı?)")
            return 1

        print(f"✓ Bulundu: {order['name']} (id={order['id']})")
        print(f"  Mevcut not: {order.get('note') or '(boş)'}")

        if input("\nTest yorumu eklensin mi? (e/h): ").strip().lower() != "e":
            print("İptal edildi.")
            return 0

        client.log_packing_event(
            order_no=order_no,
            camera_id=99,
            camera_name="TEST",
            timestamp=datetime.now(),
            note_template="🧪 [{timestamp}] TEST: {camera_name} (Kamera #{camera_id})",
        )
        print("✓ Eklendi. Shopify admin > Orders > Timeline'a bak.")
        return 0
    except OrderNotFound as e:
        print(f"❌ {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"❌ Hata: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
