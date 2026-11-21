FROM python:3.12-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_THREAD_LIMIT=1 \
    OPENBLAS_NUM_THREADS=1
WORKDIR /srv/app
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --home-dir /tmp --no-create-home app \
    && install -d -o app -g app -m 0700 /var/lib/pdf-pro
ENV HOME=/tmp XDG_CACHE_HOME=/tmp/.cache PATH=/opt/venv/bin:$PATH

FROM runtime AS packages
RUN python -m venv /opt/venv
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --retries 8 --timeout 45 -r /tmp/requirements.txt

FROM packages AS ocr-packages
COPY backend/requirements-ocr.txt /tmp/requirements-ocr.txt
RUN pip install --no-cache-dir --retries 8 --timeout 45 -r /tmp/requirements.txt -r /tmp/requirements-ocr.txt

FROM packages AS api
COPY --chown=app:app backend/ /srv/app/
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-access-log"]

FROM runtime AS worker
RUN sed -i "s|http://deb.debian.org|https://deb.debian.org|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends \
       fonts-crosextra-carlito fonts-liberation fonts-noto-core ghostscript \
       libreoffice-writer-nogui tesseract-ocr tesseract-ocr-eng tesseract-ocr-urd \
       tesseract-ocr-ara tesseract-ocr-osd qpdf unpaper \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ocr-packages /opt/venv /opt/venv
COPY --chown=app:app backend/ /srv/app/
USER app
CMD ["celery", "-A", "app.workers.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=1"]
