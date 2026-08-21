FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIFE_HUB_MODE=cloud \
    LIFE_HUB_DATA_DIR=/data

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

EXPOSE 8766
CMD ["python", "-m", "backend.cloud_serve"]
