# Sanal Makine (VM) Gereksinimleri — IT için

Kurulacak uygulama tek bir Docker konteyneri olarak çalışır. Aşağıdaki
özelliklerde bir VM yeterlidir. (3–8 kamera için, büyüme payı eklenmiştir.)

## Önerilen VM özellikleri

| Kaynak | Değer |
|--------|-------|
| **CPU** | 8–12 vCPU |
| **RAM** | 16 GB |
| **Disk** | 120 GB SSD |
| **OS** | Linux (Ubuntu 22.04 LTS) |
| **Yazılım** | Docker Engine + Docker Compose |
| **Mimari** | x86-64 (amd64) |

## Ağ erişimi

- **Kameralara (yerel ağ):** VM, kameraların bulunduğu LAN'a erişebilmeli — RTSP, **TCP 554** (giden).
- **İnternet (giden):** Shopify'a yazım için **HTTPS / TCP 443** (`*.myshopify.com`). Sadece giden; gelen internet gerekmez.
- **Yönetim paneli (gelen):** VM üzerinde **TCP 8080** açık olmalı; iç ağdan/VPN'den erişilecek. (Kullanıcılar kendi bilgisayarlarından tarayıcıyla `http://<VM-IP>:8080` adresine girer — VM'e uzaktan masaüstü bağlantısı gerekmez.)
- VM'e kurulum/bakım için **SSH** erişimi.

## Not — GPU (opsiyonel)

VM'de **NVIDIA GPU (≥6 GB VRAM)** sağlanabiliyorsa performans için tercih ederiz;
özellikle kamera sayısı arttığında. GPU sağlanırsa **NVIDIA driver + NVIDIA
Container Toolkit** kurulu olmalı. GPU yoksa yukarıdaki CPU'lu yapı yeterlidir;
GPU verilecekse lütfen bize bildirin (kurulumu ona göre hazırlarız).
