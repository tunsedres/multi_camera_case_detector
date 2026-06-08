"""
Konfigürasyon yükleyici.
YAML'dan ayarları okur, .env'den sırları doldurur.
"""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def load_config(config_path: str = "config/config.yaml") -> dict:
    """config.yaml'i yükler ve RTSP URL'lerindeki placeholder'ları doldurur."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config bulunamadı: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # RTSP URL'lerindeki {user} ve {pass} placeholder'larını doldur
    user = os.getenv("CAMERA_USERNAME", "admin")
    password = os.getenv("CAMERA_PASSWORD", "")

    for cam in config.get("cameras", []):
        cam["rtsp"] = cam["rtsp"].replace("{user}", user).replace("{pass}", password)

    return config


def get_shopify_config() -> dict:
    """Shopify API için gerekli env değişkenlerini döner."""
    return {
        "shop_url": os.getenv("SHOPIFY_SHOP_URL", "").strip(),
        "access_token": os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip(),
        "api_version": os.getenv("SHOPIFY_API_VERSION", "2024-01"),
    }
