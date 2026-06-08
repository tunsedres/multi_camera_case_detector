FROM python:3.11-slim

# pyzbar -> libzbar0 ; OpenCV -> libgl1, libglib2.0-0 ; RTSP -> ffmpeg
# OCR -> tesseract-ocr (etiketteki #numarayı okumak için)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    tesseract-ocr \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Istanbul \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# PaddleOCR (varsayılan OCR motoru — Tesseract'tan çok daha doğru). En sona
# kurulur ve opencv-headless tekrar pinlenir (paddle, opencv-python 4.6 çekip
# headless'ı ezmesin → çakışmayı önle).
RUN pip install --no-cache-dir paddlepaddle==2.6.2 paddleocr==2.7.3 \
    && pip install --no-cache-dir --force-reinstall --no-deps \
        opencv-python-headless==4.10.0.84

COPY app/ ./app/
COPY models/ ./models/
COPY VERSION ./VERSION

# config, data ve logs runtime'da volume olarak bağlanır
EXPOSE 8080

# Admin Panel /health endpoint'ine bakarak konteyner sağlığı (curl yok → python)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]

CMD ["python", "-m", "app.main"]
