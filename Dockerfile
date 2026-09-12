FROM python:3.12-slim

WORKDIR /app

# One apt transaction for system deps (ffmpeg for faster-whisper, supervisor
# to run both processes), cache cleaned in the same layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies before copying app code so the requirements layer is
# not invalidated by an app edit (Docker layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV DATA_DIR=/data
ENV WHISPER_MODEL_DIR=/models
VOLUME ["/data", "/models"]

COPY server.py worker.py supervisord.conf .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/')" || exit 1

CMD ["supervisord", "-c", "/app/supervisord.conf"]
