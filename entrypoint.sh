#!/bin/sh
set -e

echo "=== Running migrations ==="
python manage.py migrate --noinput

echo "=== Collecting static files ==="
python manage.py collectstatic --noinput 2>&1 || echo "collectstatic warning (non-fatal)"

echo "=== Starting gunicorn on port ${PORT:-8000} ==="
exec gunicorn src.wsgi \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --threads 4 \
  --timeout 120 \
  --log-level info \
  --access-logfile - \
  --error-logfile -
