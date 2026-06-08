FROM python:3.11-slim

# pyzbar -> libzbar0 ; OpenCV -> libgl1, libglib2.0-0 ; RTSP -> ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Istanbul \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY VERSION ./VERSION

# config, data ve logs runtime'da volume olarak bağlanır
EXPOSE 8080

# Admin Panel /health endpoint'ine bakarak konteyner sağlığı (curl yok → python)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]

CMD ["python", "-m", "app.main"]
