FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Render / Railway / Nginx gibi bir vekil sunucunun arkasında çalışır.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    TRUST_PROXY=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "app.py"]
