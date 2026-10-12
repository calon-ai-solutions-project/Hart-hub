FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build-time only values so collectstatic can load settings; real ones come from Railway variables.
RUN SECRET_KEY=build DATABASE_URL=sqlite:////tmp/build.db ALLOWED_HOSTS=build \
    python manage.py collectstatic --noinput

RUN useradd --create-home app && chown -R app /app
USER app

# web service; the worker service overrides this (see railway.worker.json)
CMD ["gunicorn", "config.wsgi", "-c", "gunicorn.conf.py"]
