FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8008

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir -r requirements.lock

RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --no-create-home app

COPY --chown=app:app app ./app
RUN python -c "from app.main import app; assert app.title == 'API Reseñas'"

USER app
EXPOSE 8008

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD python -c "import os; from urllib.request import urlopen; urlopen('http://127.0.0.1:' + os.getenv('PORT', '8008') + '/health', timeout=2)" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8008}\""]
