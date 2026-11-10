# The EduNexa image: one image runs the web app (the default command), the Celery worker and the
# scheduler (compose files give them their own command). See docs/DEPLOYMENT.md.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod
WORKDIR /app
COPY requirements/ ./requirements/
RUN pip install -r requirements/prod.txt
COPY . .
# Static files are collected into the image, so a container starts without writing them. The
# build settings need no secrets (config/settings/build.py).
RUN DJANGO_SETTINGS_MODULE=config.settings.build python manage.py collectstatic --noinput \
    && useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=6s --start-period=30s --retries=3 \
    CMD ["python", "deploy/healthcheck.py"]
# Workers: WEB_CONCURRENCY (Gunicorn reads it; default 1). Requests are logged by the proxy.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--timeout", "60"]
