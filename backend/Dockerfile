FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# the browser the Codeweavers quote connector drives, in a place the app user can read
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium

COPY . .

# Build-time only values so collectstatic can load settings; real ones come from Railway variables.
RUN SECRET_KEY=build DATABASE_URL=sqlite:////tmp/build.db ALLOWED_HOSTS=build \
    python manage.py collectstatic --noinput

RUN useradd --create-home app && chown -R app /app
USER app

# web service; the worker service overrides this (see railway.worker.json)
CMD ["gunicorn", "config.wsgi", "-c", "gunicorn.conf.py"]
