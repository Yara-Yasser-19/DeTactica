FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DETACTICA_ENV=production \
    PORT=8000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 10001 detactica \
    && useradd --uid 10001 --gid detactica --create-home detactica \
    && mkdir -p /app/instance \
    && chown detactica:detactica /app/instance

COPY app.py models.py translations.py gunicorn.conf.py ./
COPY templates/ ./templates/
COPY static/ ./static/

USER detactica

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz', timeout=3).read()"

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
