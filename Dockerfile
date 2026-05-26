FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CLIPSYNC_DATA_DIR=/data \
    CLIPSYNC_PORT=8080

WORKDIR /app

# gosu lets the entrypoint drop from root → clipsync after fixing /data perms.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd -u 1000 -m clipsync \
    && chown -R clipsync /app

EXPOSE 8080
VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${CLIPSYNC_PORT} --worker-class gthread --workers 1 --threads 8 --timeout 0 'app:create_app()'"]
