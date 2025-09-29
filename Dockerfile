FROM python:3.11-slim

# Install ping/arp tools for scanning
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       iputils-ping iproute2 net-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config

ENV FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    SCAN_INTERVAL=15 \
    CONFIG_PATH=/app/config/devices.yaml

EXPOSE 8000

CMD ["python", "-m", "app.server"]
