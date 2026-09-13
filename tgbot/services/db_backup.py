"""Kunlik baza zaxirasi -> Telegram.

Format: gzip qilingan oddiy SQL (`pg_dump --no-owner --no-privileges`). Bu eng
oson tiklanadigan format: har qanday Postgres serverga, har qanday
foydalanuvchi bilan, bitta buyruq bilan tiklanadi va ichini oddiy matn
sifatida ochib ko'rish mumkin:

    gunzip -c kitob_YYYY-MM-DD.sql.gz | psql "postgresql://user:pass@host:5432/db"

Telegram bot fayl yuklash chegarasi 50 MB. Undan katta zaxira 45 MB lik
bo'laklarga bo'linadi (.part01, .part02, ...), tiklash:

    cat kitob_YYYY-MM-DD.sql.gz.part* | gunzip | psql "postgresql://..."

Ulanish: BACKUP_DATABASE_URL -> POSTGRES_DATABASE_URL -> DATABASE_URL.
PgBouncer (transaction pooling) orqali pg_dump ishonchsiz, shuning uchun
production'da BACKUP_DATABASE_URL ni to'g'ridan-to'g'ri Postgres'ga qarating.
"""
import glob
import os
import shutil
import subprocess
import tempfile

import requests
from django.conf import settings
from django.utils import timezone

PART_BYTES = 45 * 1024 * 1024
DUMP_TIMEOUT_SECONDS = 30 * 60


def _database_url() -> str:
    for key in ("BACKUP_DATABASE_URL", "POSTGRES_DATABASE_URL", "DATABASE_URL"):
        url = os.environ.get(key, "").strip()
        if url:
            return url
    db = settings.DATABASES["default"]
    return (f"postgresql://{db.get('USER', '')}:{db.get('PASSWORD', '')}@"
            f"{db.get('HOST', '')}:{db.get('PORT') or 5432}/{db.get('NAME', '')}")


def _targets() -> list:
    """Chat ids the backup goes to: every admin's DM (the ADMINS env list),
    or BACKUP_CHAT_ID when set. DMs, not a group -- the dump holds users'
    phone numbers and payments."""
    ids = os.environ.get("BACKUP_CHAT_ID", "") or os.environ.get("ADMINS", "")
    return [a.strip() for a in ids.split(",") if a.strip()]


def _api(method: str, data: dict, files=None, timeout=60):
    return requests.post(
        f"https://api.telegram.org/bot{settings.API_TOKEN}/{method}",
        data=data, files=files, timeout=timeout,
    )


def _notify(text: str) -> None:
    for chat in _targets():
        try:
            _api("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=15)
        except Exception as e:
            print(f"db_backup notify {chat} failed: {e}")


def _human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def run_backup() -> dict:
    """Dump the database, gzip it, send it to Telegram. Reports failures to
    the same chat so a silently broken backup is noticed the next morning."""
    if not shutil.which("pg_dump"):
        _notify("❌ <b>Kunlik backup ishlamadi:</b> serverda <code>pg_dump</code> yo'q.")
        return {"ok": False, "error": "pg_dump_missing"}

    stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M")
    workdir = tempfile.mkdtemp(prefix="kc_backup_")
    path = os.path.join(workdir, f"kitob_{stamp}.sql.gz")
    try:
        # pg_dump | gzip without a shell: the URL (with its password) never
        # appears in a command line string that could end up in a log.
        err_path = os.path.join(workdir, "pg_dump.err")
        with open(path, "wb") as out, open(err_path, "wb") as err_file:
            dump = subprocess.Popen(
                ["pg_dump", "--no-owner", "--no-privileges", "--dbname", _database_url()],
                stdout=subprocess.PIPE, stderr=err_file,
            )
            gz = subprocess.Popen(["gzip", "-6"], stdin=dump.stdout, stdout=out)
            dump.stdout.close()
            gz.wait(timeout=DUMP_TIMEOUT_SECONDS)
            dump.wait(timeout=60)
        if dump.returncode != 0 or gz.returncode != 0:
            with open(err_path, "rb") as f:
                err = f.read().decode("utf-8", "replace")[-700:]
            _notify(f"❌ <b>Kunlik backup ishlamadi</b> (pg_dump {dump.returncode}):\n"
                    f"<pre>{_escape(err)}</pre>")
            return {"ok": False, "error": err}

        size = os.path.getsize(path)
        parts = [path]
        if size > PART_BYTES:
            parts = _split(path)

        from tgbot.models import TelegramProfile
        users = TelegramProfile.objects.count()
        name = os.path.basename(path)
        restore = (f"gunzip -c {name} | psql \"$DATABASE_URL\"" if len(parts) == 1
                   else f"cat {name}.part* | gunzip | psql \"$DATABASE_URL\"")
        targets = _targets()
        if not targets:
            print("db_backup: no ADMINS / BACKUP_CHAT_ID to send to")
            return {"ok": False, "error": "no_targets"}
        delivered, failures = set(), []
        for i, part in enumerate(parts, 1):
            caption = ""
            if i == 1:
                caption = (
                    f"🗄 <b>Kunlik backup</b> — {timezone.localtime():%d.%m.%Y %H:%M}\n"
                    f"👥 Foydalanuvchilar: {users:,}\n"
                    f"📦 Hajmi: {_human(size)}"
                    + (f" ({len(parts)} bo'lak)" if len(parts) > 1 else "") + "\n\n"
                    f"♻️ Tiklash (bo'sh bazaga):\n<code>{_escape(restore)}</code>"
                )
            file_id = None
            for chat in targets:
                data = {"chat_id": chat, "caption": caption, "parse_mode": "HTML"}
                try:
                    if file_id:
                        # Uploaded once; every other admin gets the same file by id.
                        resp = _api("sendDocument", {**data, "document": file_id}, timeout=60)
                    else:
                        with open(part, "rb") as f:
                            resp = _api("sendDocument", data,
                                        files={"document": (os.path.basename(part), f)}, timeout=600)
                        if resp.status_code == 200:
                            file_id = resp.json()["result"]["document"]["file_id"]
                except Exception as e:
                    failures.append(f"{chat}: {e}")
                    continue
                if resp.status_code == 200:
                    delivered.add(chat)
                else:
                    failures.append(f"{chat}: {resp.text[:200]}")

        if failures:
            _notify("⚠️ <b>Backup ba'zi adminlarga yetmadi:</b>\n<code>"
                    + _escape("\n".join(failures)[:800]) + "</code>")
        print(f"db_backup: sent {name} {_human(size)} in {len(parts)} part(s) "
              f"to {len(delivered)}/{len(targets)} admins")
        return {"ok": bool(delivered), "file": name, "bytes": size, "parts": len(parts),
                "delivered": len(delivered), "failures": failures}
    except Exception as e:
        _notify(f"❌ <b>Kunlik backup ishlamadi:</b> <code>{_escape(str(e)[:500])}</code>")
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _split(path: str) -> list:
    n = 0
    with open(path, "rb") as src:
        while True:
            chunk = src.read(PART_BYTES)
            if not chunk:
                break
            n += 1
            with open(f"{path}.part{n:02d}", "wb") as dst:
                dst.write(chunk)
    os.remove(path)
    return sorted(glob.glob(f"{path}.part*"))


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
