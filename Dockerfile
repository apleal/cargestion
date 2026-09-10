FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

# En cada arranque: migraciones + datos iniciales (idempotente) + superusuario
# desde DJANGO_SUPERUSER_* (si están definidos), y luego gunicorn.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_datos && python manage.py crear_admin && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
