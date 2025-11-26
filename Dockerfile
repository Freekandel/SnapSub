FROM python:3.11-slim

# Systeemdeps (FFmpeg is vereist)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend ./backend
# .env is optioneel – je kunt deze ook via Render env vars zetten
# COPY .env ./.env

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]