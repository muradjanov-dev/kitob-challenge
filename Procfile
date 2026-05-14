web: python manage.py migrate && python manage.py collectstatic --noinput && python manage.py send_deploy_notif && python manage.py announce_first_challenge && gunicorn src.wsgi
