FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/bot.db \
    MPLCONFIGDIR=/tmp/jeti-nur-matplotlib

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
RUN mkdir -p /data

VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]
