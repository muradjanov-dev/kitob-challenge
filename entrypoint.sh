#!/bin/sh
set -e

SERVICE_TYPE="${SERVICE_TYPE:-web}"

# Migrations + collectstatic + deploy notification: only on web.
# (Worker / beat must not race the migration; deploy-notify spam is dedup'd here.)
if [ "$SERVICE_TYPE" = "web" ]; then
  echo "=== Running migrations ==="
  python manage.py migrate --noinput

  echo "=== Collecting static files ==="
  python manage.py collectstatic --noinput 2>&1 || echo "collectstatic warning (non-fatal)"

  echo "=== Setting bot commands ==="
  if [ -n "$API_TOKEN" ]; then
    # Only /start is exposed as a shortkey. /admin and /restart still work
    # as commands but are intentionally hidden from the menu.
    curl -s -X POST "https://api.telegram.org/bot${API_TOKEN}/setMyCommands" \
      -H "Content-Type: application/json" \
      -d '{"commands":[{"command":"start","description":"Asosiy menyuga qaytish"}]}' \
      || echo "setMyCommands failed (non-fatal)"
    echo ""
  fi

  echo "=== Notifying admins of deploy ==="
  python - <<'PY' || echo "deploy-notify skipped/failed (non-fatal)"
import os, urllib.request, urllib.parse, datetime
token = os.environ.get("API_TOKEN")
admins = os.environ.get("ADMINS", "")
if not (token and admins):
    raise SystemExit(0)
service = os.environ.get("RAILWAY_SERVICE_NAME", "web")
env = os.environ.get("RAILWAY_ENVIRONMENT_NAME", "production")
commit = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:7] or "n/a"
branch = os.environ.get("RAILWAY_GIT_BRANCH", "")
msg_lines = [
    "\U0001F680 <b>Deploy</b>",
    f"Service: <code>{service}</code>",
    f"Env: <code>{env}</code>",
    f"Commit: <code>{commit}</code>" + (f" ({branch})" if branch else ""),
    f"Time: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
]
text = "\n".join(msg_lines)
for raw in admins.split(","):
    chat_id = raw.strip()
    if not chat_id:
        continue
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, timeout=5,
        ).read()
    except Exception as e:
        print(f"notify failed for {chat_id}: {e}")
PY

  # Optional: one-shot test broadcast of a random inspiration to all users.
  # Set BROADCAST_INSPIRATION_ON_BOOT=1 on the web service for the deploy,
  # then unset after the broadcast fires.
  if [ "$BROADCAST_INSPIRATION_ON_BOOT" = "1" ]; then
    echo "=== Firing one-shot inspiration broadcast ==="
    python manage.py shell -c "from tgbot.tasks import send_random_inspiration; send_random_inspiration()" \
      || echo "broadcast failed (non-fatal)"
  fi
fi

case "$SERVICE_TYPE" in
  worker)
    echo "=== Starting Celery worker ==="
    exec celery -A src worker --loglevel=info --pool=threads --concurrency=20
    ;;
  beat)
    echo "=== Starting Celery beat ==="
    exec celery -A src beat --loglevel=info
    ;;
  *)
    echo "=== Starting gunicorn on port ${PORT:-8000} ==="
    exec gunicorn src.wsgi \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers 2 \
      --threads 4 \
      --timeout 120 \
      --log-level info \
      --access-logfile - \
      --error-logfile -
    ;;
esac
