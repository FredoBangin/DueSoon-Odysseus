FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --gid 10001 duesoon \
    && useradd --uid 10001 --gid duesoon --create-home --shell /usr/sbin/nologin duesoon \
    && mkdir -p /app/data \
    && chown -R duesoon:duesoon /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=duesoon:duesoon src/duesoon ./src/duesoon
COPY --chown=duesoon:duesoon static ./static

USER duesoon

EXPOSE 7000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7000/health/ready', timeout=3).read()"]

CMD ["uvicorn", "src.duesoon.api.app:app", "--host", "0.0.0.0", "--port", "7000", "--workers", "1"]
