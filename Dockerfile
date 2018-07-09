FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN DJANGO_SECRET_KEY=build-only \n    STATICFILES_BACKEND=whitenoise.storage.CompressedManifestStaticFilesStorage \n    python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 eventhub \
    && chown -R eventhub /app

USER eventhub
EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
