"""
Tek kamera hızlı test script'i.
Kullanım: python scripts/test_camera.py rtsp://admin:sifre@192.168.1.101:554/Streaming/Channels/102

Penceresiz çalışır, sadece konsola log basar.
Geliştirme aşamasında bağlantı ve barkod tespitini doğrulamak için.
"""
import os
import sys
import time
from datetime import datetime

# OpenCV TCP transport - cv2 import edilmeden önce
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"

import cv2
from pyzbar import pyzbar


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python test_camera.py <rtsp_url>")
        print("Örnek:    python test_camera.py rtsp://admin:Sifre@192.168.1.101:554/Streaming/Channels/102")
        sys.exit(1)

    rtsp_url = sys.argv[1]
    print(f"Bağlanılıyor: {rtsp_url}")

    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print("❌ Stream açılamadı! URL'i, IP'yi, kullanıcı adı/şifreyi kontrol et.")
        sys.exit(1)

    print("✓ Bağlandı, frame okumaya başlıyor (Ctrl+C ile dur)")
    print()

    frame_count = 0
    detected_count = 0
    last_print = time.time()
    last_detected = {}  # {value: timestamp}

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("⚠ Frame okuma hatası")
                time.sleep(0.5)
                continue

            frame_count += 1

            # Her 5 frame'de bir tarama yap (CPU tasarrufu)
            if frame_count % 5 != 0:
                continue

            # Barkod ara
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            decoded = pyzbar.decode(gray)

            for d in decoded:
                value = d.data.decode("utf-8", errors="ignore")
                now = datetime.now()
                # Aynı barkod 5sn'de tekrar gelirse logla
                last = last_detected.get(value, 0)
                if (now.timestamp() - last) > 5:
                    detected_count += 1
                    last_detected[value] = now.timestamp()
                    print(f"[{now.strftime('%H:%M:%S')}] BARKOD: {value}  (tip: {d.type})")

            # Her 10 saniyede bir istatistik
            if time.time() - last_print > 10:
                fps = frame_count / (time.time() - last_print)
                print(f"  → İstatistik: {fps:.1f} fps, toplam {detected_count} tespit")
                frame_count = 0
                last_print = time.time()

    except KeyboardInterrupt:
        print("\nDurduruluyor...")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
