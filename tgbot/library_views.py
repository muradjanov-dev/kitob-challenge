"""Library API — comments on GlobalBook entries.

Auth: Telegram WebApp initData, same pattern as shop_views.py.
Users who haven't registered in the bot yet get a 403.
Each user can leave one comment per book (upsert on re-submit).
"""
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tgbot.models import BookComment, BooksToRead, GlobalBook, TelegramProfile


# ── initData auth ──────────────────────────────────────────────────────────

def _verify_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    except ValueError:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", settings.API_TOKEN.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return None
    user_json = pairs.get("user")
    if not user_json:
        return None
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user


def _read_init_data(request: HttpRequest) -> str:
    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.POST.get("initData")
        or request.GET.get("initData")
        or ""
    )


def _resolve_profile(init_data: str) -> tuple:
    tg_user = _verify_init_data(init_data)
    if not tg_user:
        return None, "invalid_init_data"
    profile = TelegramProfile.objects.filter(telegram_id=str(tg_user["id"])).first()
    if not profile:
        return None, "not_registered"
    return profile, None


# ── GET /kutubxona/api/comments/?book_id=N ────────────────────────────────

@require_GET
def api_comments(request: HttpRequest):
    book_id = request.GET.get("book_id")
    if not book_id or not book_id.isdigit():
        return JsonResponse({"error": "book_id required"}, status=400)

    comments = (
        BookComment.objects
        .filter(book_id=int(book_id))
        .select_related("user")
        .order_by("-created_at")[:50]
    )
    return JsonResponse({
        "comments": [
            {
                "id": c.id,
                "user": c.user.full_name or "Kitobxon",
                "text": c.text,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for c in comments
        ]
    })


# ── POST /kutubxona/api/comment/ ──────────────────────────────────────────

@csrf_exempt
@require_POST
def api_add_comment(request: HttpRequest):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = body.get("book_id")
    text = (body.get("text") or "").strip()

    if not book_id:
        return JsonResponse({"error": "book_id required"}, status=400)
    if not text:
        return JsonResponse({"error": "text required"}, status=400)
    if len(text) > 1000:
        return JsonResponse({"error": "too_long"}, status=400)

    book = GlobalBook.objects.filter(id=book_id).first()
    if not book:
        return JsonResponse({"error": "not_found"}, status=404)

    comment, created = BookComment.objects.update_or_create(
        book=book,
        user=profile,
        defaults={"text": text},
    )
    return JsonResponse({
        "ok": True,
        "created": created,
        "comment": {
            "id": comment.id,
            "user": profile.full_name or "Kitobxon",
            "text": comment.text,
            "created_at": comment.created_at.strftime("%Y-%m-%d %H:%M"),
        },
    })


# ── DELETE /kutubxona/api/comment/ ────────────────────────────────────────

@csrf_exempt
def api_delete_comment(request: HttpRequest):
    if request.method != "DELETE":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = body.get("book_id")
    if not book_id:
        return JsonResponse({"error": "book_id required"}, status=400)

    deleted, _ = BookComment.objects.filter(book_id=book_id, user=profile).delete()
    return JsonResponse({"ok": True, "deleted": deleted > 0})


# ── GET /kutubxona/api/my-books/ ──────────────────────────────────────────────

@require_GET
def api_my_books(request: HttpRequest):
    init_data = _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_ids = list(
        BooksToRead.objects
        .filter(user=profile, total_pages__gt=0)
        .values_list("global_book_id", flat=True)
    )
    return JsonResponse({"book_ids": book_ids})


# ── GET /kutubxona/api/progress/?book_id=N ────────────────────────────────

@require_GET
def api_get_progress(request: HttpRequest):
    init_data = _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = request.GET.get("book_id")
    if not book_id or not book_id.isdigit():
        return JsonResponse({"error": "book_id required"}, status=400)

    record = BooksToRead.objects.filter(user=profile, global_book_id=int(book_id)).first()
    return JsonResponse({
        "current_page": record.current_page if record else 0,
        "total_pages": record.total_pages if record else 0,
    })


# ── POST /kutubxona/api/progress/ ─────────────────────────────────────────

@csrf_exempt
@require_POST
def api_save_progress(request: HttpRequest):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    init_data = body.get("initData") or _read_init_data(request)
    profile, err = _resolve_profile(init_data)
    if err:
        return JsonResponse({"error": err}, status=403)

    book_id = body.get("book_id")
    if not book_id:
        return JsonResponse({"error": "book_id required"}, status=400)
    try:
        current_page = int(body.get("current_page"))
        total_pages = int(body.get("total_pages"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_pages"}, status=400)
    if current_page < 0 or total_pages < 0:
        return JsonResponse({"error": "invalid_pages"}, status=400)

    book = GlobalBook.objects.filter(id=book_id).first()
    if not book:
        return JsonResponse({"error": "not_found"}, status=404)

    # No unique_together on (user, global_book) historically, so a couple of
    # accounts may already carry more than one row for the same book -- take
    # the first instead of update_or_create() to avoid MultipleObjectsReturned.
    record = BooksToRead.objects.filter(user=profile, global_book=book).first()
    if record:
        record.title = book.title
        record.is_audio = False
        record.current_page = current_page
        record.total_pages = total_pages
        record.save(update_fields=["title", "is_audio", "current_page", "total_pages", "updated_at"])
    else:
        record = BooksToRead.objects.create(
            user=profile, global_book=book, title=book.title,
            is_audio=False, current_page=current_page, total_pages=total_pages,
        )

    return JsonResponse({"ok": True, "current_page": record.current_page, "total_pages": record.total_pages})


# ── GET /kutubxona/api/comments/recent/ ───────────────────────────────────────

@require_GET
def api_recent_comments(request: HttpRequest):
    limit = min(int(request.GET.get("limit", 20)), 50)
    comments = (
        BookComment.objects
        .select_related("user", "book")
        .order_by("-created_at")[:limit]
    )
    return JsonResponse({
        "comments": [
            {
                "id": c.id,
                "book": c.book.title,
                "book_id": c.book_id,
                "user": c.user.full_name or "Kitobxon",
                "text": c.text,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for c in comments
        ]
    })
