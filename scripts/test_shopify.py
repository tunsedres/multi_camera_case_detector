"""
Shopify bağlantı testi.
Kullanım: python scripts/test_shopify.py "#1001"

Verilen sipariş no'yu arar, bulursa test yorumu ekler.
"""
import sys
import os
from datetime import datetime
from pathlib import Path

# app modülüne erişebilmek için parent dir'i path'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.integrations.shopify_client import ShopifyClient, OrderNotFound


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python test_shopify.py <sipariş_no>")
        print("Örnek:    python test_shopify.py '#1001'")
        sys.exit(1)

    order_no = sys.argv[1]

    shop_url = os.getenv("SHOPIFY_SHOP_URL")
    token = os.getenv("SHOPIFY_ACCESS_TOKEN")

    if not shop_url or not token:
        print("❌ .env dosyasında SHOPIFY_SHOP_URL ve SHOPIFY_ACCESS_TOKEN gerekli!")
        sys.exit(1)

    print(f"Shopify: {shop_url}")
    print(f"Sipariş aranıyor: {order_no}")

    client = ShopifyClient(shop_url=shop_url, access_token=token)

    try:
        order = client.find_order_by_name(order_no)
        if not order:
            print(f"❌ Sipariş bulunamadı: {order_no}")
            print("   Shopify admin'de bu sipariş var mı?")
            sys.exit(1)

        print(f"✓ Sipariş bulundu: id={order['id']}, name={order['name']}")
        print(f"  Mevcut not: {order.get('note') or '(boş)'}")
        print()

        confirm = input("Test yorumu eklensin mi? (e/h): ").strip().lower()
        if confirm != "e":
            print("İptal edildi.")
            return

        client.log_packing_event(
            order_no=order_no,
            camera_id=99,
            camera_name="TEST",
            timestamp=datetime.now(),
            note_template="🧪 [{timestamp}] TEST: {camera_name} (Kamera #{camera_id})",
            write_note=True,
            write_metafield=True,
        )

        print("✓ Test yorumu eklendi. Shopify admin > Orders > {order_no} > Timeline'a bak.")

    except OrderNotFound as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Hata: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
