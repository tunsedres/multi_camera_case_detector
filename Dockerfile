FROM python:3.11-slim

# pyzbar libzbar0 gerektirir; OpenCV için de bazı sistem kütüphaneleri
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Istanbul \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# data ve logs runtime'da volume olarak bağlanır
CMD ["python", "-m", "app.main"]
