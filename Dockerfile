FROM python:3.12-slim

WORKDIR /app

# Install dependencies before copying app code so the requirements layer is
# not invalidated by an app edit (Docker layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV DATA_DIR=/data
VOLUME ["/data"]

COPY server.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/')" || exit 1

# Non-root runtime user with write access to the data volume.
RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /data
USER appuser

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
