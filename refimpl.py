#!/usr/bin/env python3
"""Reference impl for: voicemail-onecontainer

Applies the merged-container design directly to the four target files and
deletes Dockerfile.whisper. The gate applies this, runs verify.sh, confirms
VERIFY_OK, then reverts every tracked file it touched (git checkout) so the
model starts from the untouched two-container baseline. It doubles as the
review reference once the model's own diff comes back.
"""
import pathlib
import sys

wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

# System deps for both processes: ffmpeg (audio decode for faster-whisper)
# and supervisor (runs the app + the whisper worker as one container). One
# apt transaction, cache cleaned in the same layer.
RUN apt-get update \\
    && apt-get install -y --no-install-recommends ffmpeg supervisor \\
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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \\
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/')" || exit 1

CMD ["supervisord", "-c", "/app/supervisord.conf"]
"""

SUPERVISORD = """[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
pidfile=/tmp/supervisord.pid
loglevel=info
user=root

[unix_http_server]
file=/tmp/supervisor.sock
chmod=0700

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

[program:app]
command=uvicorn server:app --host 0.0.0.0 --port 8000
directory=/app
priority=100
autostart=true
autorestart=true
startsecs=5
startretries=5
stopsignal=TERM
stopwaitsecs=10
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
redirect_stderr=true

[program:whisper]
command=python worker.py
directory=/app
priority=200
autostart=true
autorestart=true
startsecs=30
startretries=10
stopsignal=TERM
stopwaitsecs=10
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
redirect_stderr=true
"""

COMPOSE = """services:
  voicemail-inbox:
    build: .
    image: voicemail-inbox
    container_name: voicemail-inbox
    restart: unless-stopped
    networks:
      br0:
        ipv4_address: 10.0.12.44
    mac_address: "02:42:0A:00:0C:2C"
    environment:
      - DATA_DIR=/data
      - AUTH_TOKEN=${AUTH_TOKEN}
    volumes:
      - /mnt/user/data/Documents/Voicemail:/data
      - /mnt/user/data/Documents/Voicemail/whisper-models:/models
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')"]
      interval: 30s
      timeout: 5s
      start_period: 10s
      retries: 3
    labels:
      net.unraid.docker.icon: "https://raw.githubusercontent.com/frindle/voicemail-inbox/main/icon.png"

networks:
  br0:
    external: true
    name: br0
"""

REQUIREMENTS = """fastapi==0.115.6
uvicorn[standard]==0.34.0
python-multipart==0.0.20
httpx==0.28.1
faster-whisper==1.1.1
requests==2.32.3
"""

(wt / "Dockerfile").write_text(DOCKERFILE)
(wt / "supervisord.conf").write_text(SUPERVISORD)
(wt / "docker-compose.yml").write_text(COMPOSE)
(wt / "requirements.txt").write_text(REQUIREMENTS)

whisper_df = wt / "Dockerfile.whisper"
if whisper_df.exists():
    whisper_df.unlink()

print("refimpl applied")
