"""
Vendor (satıcı) Ed25519 public key.

Lisans anahtarları satıcının PRIVATE key'i ile imzalanır; uygulama buradaki
PUBLIC key ile doğrular. Private key ASLA bu repoda/üründe bulunmaz — yalnızca
satıcıda kalır (scripts/generate_license.py keygen ile üretilir).

Ürünleştirirken kendi anahtar çiftini üret ve bu değeri DEĞİŞTİR:
    python scripts/generate_license.py keygen
komutu yeni public key'i otomatik buraya yazar ve private key'i
config/private_key.pem'e (gitignore'lu) kaydeder.
"""

# 32 byte Ed25519 public key (hex). Aşağıdaki örnek bir geliştirme anahtarıdır.
VENDOR_PUBLIC_KEY_HEX = "5c1d4688bd84df4e1eaa383828ff0fba26097c26d6964297313ac00a92c354eb"
