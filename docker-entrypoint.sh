#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput -v 0
# One worker process on purpose: indexing runs on an in-process background thread
# (see "Limitations"). Threads handle concurrent requests; the timeout leaves room
# for a slow local model to answer.
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 --workers 1 --threads 8 --timeout 300 \
  --access-logfile -
