"""Library admin — manage GlobalBook rows directly from the bot.

Add-book wizard:
  title → author (/skip) → language → cover (/skip) → description (/skip)
        → pdf (/skip) → audio (/skip) → premium toggle → confirm
  /bekor at any step aborts.

List view (paginated, 10 per page) with per-book edit/delete actions.
Each field can be edited individually after the book is created.
"""
import difflib
import io
import re

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils import timezone

from tgbot.bot.loader import dp, bot
from tgbot.bot.utils import aget_user
from tgbot.bot.states.main import LibraryBookCreateState, LibraryBookEditState
from tgbot.models import GlobalBook, BOOK_LANGUAGE_CHOICES

_BOOKS_PER_PAGE = 10
_CANCEL_STATES = [
    LibraryBookCreateState.title,
    LibraryBookCreateState.author,
    LibraryBookCreateState.language,
    LibraryBookCreateState.cover,
    LibraryBookCreateState.description,
    LibraryBookCreateState.pdf_file,
    LibraryBookCreateState.audio_file,
    LibraryBookCreateState.premium,
    LibraryBookEditState.field,
]
_FILE_FIELDS = {"cover", "pdf_file", "audio_file"}

_LANG_LABELS = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Ruscha",
    "en": "🇬🇧 Inglizcha",
    "tr": "🇹🇷 Turkcha",
    "ar": "🇸🇦 Arabcha",
    "other": "🌐 Boshqa",
}


def _is_admin(user) -> bool:
    return bool(user and getattr(user, "is_admin", False))


def _esc(s: str) -> str:
    _MAP = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}
    return re.sub(r"[&<>\"']", lambda m: _MAP[m.group(0)], s or "")


def _lib_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("➕ Kitob qo'shish", callback_data="libadm:add"))
    kb.add(InlineKeyboardButton("📋 Kitoblar ro'yxati", callback_data="libadm:list:1"))
    kb.add(InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="menu:admin"))
    return kb


def _lang_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    for code, label in _LANG_LABELS.items():
        kb.insert(InlineKeyboardButton(label, callback_data=f"libadm:lang:{code}"))
    return kb


def _premium_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("💎 Faqat Premium", callback_data="libadm:premium:1"),
        InlineKeyboardButton("🆓 Barchaga bepul", callback_data="libadm:premium:0"),
    )
    return kb


# ──────────────────────────────────────────────────────────────────────────
# Entry point — called from admin_panel.py admin_inline_router
# ──────────────────────────────────────────────────────────────────────────
async def library_admin_menu(message: types.Message, user):
    total = await sync_to_async(
        GlobalBook.objects.exclude(pdf_file="").exclude(pdf_file__isnull=True).count
    )()
    await message.answer(
        f"📚 <b>Kutubxona boshqaruvi</b>\n\n"
        f"Hozirda <b>{total}</b> ta kitob mavjud.\n\n"
        "Bot orqali kitob qo'shish, tahrirlash va o'chirish mumkin.",
        parse_mode="HTML",
        reply_markup=_lib_menu_kb(),
    )


# ──────────────────────────────────────────────────────────────────────────
# /bekor — cancel any wizard step
# ──────────────────────────────────────────────────────────────────────────
@dp.message_handler(commands=["bekor"], state=_CANCEL_STATES)
async def libadm_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Bekor qilindi.", reply_markup=_lib_menu_kb())


# ──────────────────────────────────────────────────────────────────────────
# ADD wizard
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data == "libadm:add", state="*")
async def libadm_add_start(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    await call.answer()
    await LibraryBookCreateState.title.set()
    await call.message.answer(
        "1️⃣ <b>Kitob nomini yuboring</b>\n\n"
        "Masalan: <code>O'tkan kunlar</code>\n\n"
        "Bekor qilish: /bekor",
        parse_mode="HTML",
    )


@sync_to_async
def _find_similar_titles(title: str, limit: int = 5, threshold: float = 0.55) -> list[str]:
    """Fuzzy (non-strict, case-insensitive) nearest-title lookup so admins get
    warned about likely duplicates like the ~150 that had piled up in the
    catalog under slightly different spellings before a big cleanup pass."""
    norm_new = title.strip().lower()
    ranked = []
    for existing in GlobalBook.objects.values_list("title", flat=True):
        ratio = difflib.SequenceMatcher(None, norm_new, existing.strip().lower()).ratio()
        if ratio >= threshold:
            ranked.append((ratio, existing))
    ranked.sort(key=lambda x: -x[0])
    return [t for _, t in ranked[:limit]]


@dp.message_handler(state=LibraryBookCreateState.title, content_types=types.ContentTypes.TEXT)
async def libadm_get_title(message: types.Message, state: FSMContext):
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Nom juda qisqa. Qaytadan yuboring (yoki /bekor).")
        return
    if len(title) > 255:
        await message.answer("Nom 255 belgidan oshmasligi kerak. Qaytadan.")
        return
    exists = await sync_to_async(GlobalBook.objects.filter(title__iexact=title).exists)()
    if exists:
        await message.answer(
            f"⚠️ <b>{_esc(title)}</b> nomli kitob allaqachon mavjud.\n\nBoshqa nom kiriting yoki /bekor.",
            parse_mode="HTML",
        )
        return

    similar = await _find_similar_titles(title)
    if similar:
        lines = "\n".join(f"• {_esc(t)}" for t in similar)
        await message.answer(
            f"🔎 <b>E'tibor bering</b> — kutubxonada shunga o'xshash nomlar bor:\n\n{lines}\n\n"
            "Agar bu chindan boshqa kitob bo'lsa, xotirjam davom eting — bu shunchaki eslatma.",
            parse_mode="HTML",
        )

    await state.update_data(title=title)
    await LibraryBookCreateState.author.set()
    await message.answer(
        "2️⃣ <b>Muallif ismini yuboring</b>\n\nO'tkazib yuborish: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=LibraryBookCreateState.author)
async def libadm_skip_author(message: types.Message, state: FSMContext):
    await state.update_data(author="")
    await _ask_language(message)


@dp.message_handler(state=LibraryBookCreateState.author, content_types=types.ContentTypes.TEXT)
async def libadm_get_author(message: types.Message, state: FSMContext):
    author = (message.text or "").strip()
    if len(author) > 255:
        await message.answer("Muallif ismi 255 belgidan oshmasligi kerak. Qaytadan.")
        return
    await state.update_data(author=author)
    await _ask_language(message)


async def _ask_language(message: types.Message):
    await LibraryBookCreateState.language.set()
    await message.answer(
        "3️⃣ <b>Kitob tilini tanlang</b>",
        parse_mode="HTML",
        reply_markup=_lang_kb(),
    )


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:lang:"), state=LibraryBookCreateState.language)
async def libadm_get_language(call: types.CallbackQuery, state: FSMContext):
    lang = call.data.split(":")[-1]
    if lang not in dict(BOOK_LANGUAGE_CHOICES):
        await call.answer("Noto'g'ri til", show_alert=True)
        return
    await call.answer(_LANG_LABELS.get(lang, lang))
    await state.update_data(language=lang)
    await _ask_cover(call.message)


async def _ask_cover(message: types.Message):
    await LibraryBookCreateState.cover.set()
    await message.answer(
        "4️⃣ <b>Muqova rasmini yuboring</b>\n\nO'tkazib yuborish: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=LibraryBookCreateState.cover)
async def libadm_skip_cover(message: types.Message, state: FSMContext):
    await state.update_data(cover_file_id=None)
    await _ask_description(message)


@dp.message_handler(state=LibraryBookCreateState.cover, content_types=types.ContentTypes.PHOTO)
async def libadm_get_cover(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    await state.update_data(cover_file_id=photo.file_id)
    await _ask_description(message)


@dp.message_handler(state=LibraryBookCreateState.cover)
async def libadm_cover_invalid(message: types.Message):
    await message.answer("Iltimos rasm yuboring yoki /skip.")


async def _ask_description(message: types.Message):
    await LibraryBookCreateState.description.set()
    await message.answer(
        "5️⃣ <b>Kitob tavsifi</b>\n\nQisqacha tavsif (ixtiyoriy). O'tkazib yuborish: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=LibraryBookCreateState.description)
async def libadm_skip_description(message: types.Message, state: FSMContext):
    await state.update_data(description="")
    await _ask_pdf(message)


@dp.message_handler(state=LibraryBookCreateState.description, content_types=types.ContentTypes.TEXT)
async def libadm_get_description(message: types.Message, state: FSMContext):
    desc = (message.text or "").strip()
    if len(desc) > 2000:
        await message.answer(f"Tavsif 2000 belgidan oshmasligi kerak ({len(desc)} belgi). Qaytadan.")
        return
    await state.update_data(description=desc)
    await _ask_pdf(message)


async def _ask_pdf(message: types.Message):
    await LibraryBookCreateState.pdf_file.set()
    await message.answer(
        "6️⃣ <b>PDF faylini yuboring</b>\n\n"
        "Kitobning PDF versiyasini fayl sifatida yuboring.\n"
        "O'tkazib yuborish: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=LibraryBookCreateState.pdf_file)
async def libadm_skip_pdf(message: types.Message, state: FSMContext):
    await state.update_data(pdf_file_id=None, pdf_filename=None)
    await _ask_audio(message)


@dp.message_handler(state=LibraryBookCreateState.pdf_file, content_types=types.ContentTypes.DOCUMENT)
async def libadm_get_pdf(message: types.Message, state: FSMContext):
    doc = message.document
    mime = (doc.mime_type or "").lower()
    if mime != "application/pdf" and not (doc.file_name or "").lower().endswith(".pdf"):
        await message.answer("Iltimos PDF fayl yuboring (yoki /skip).")
        return
    await state.update_data(pdf_file_id=doc.file_id, pdf_filename=doc.file_name or "book.pdf")
    await _ask_audio(message)


@dp.message_handler(state=LibraryBookCreateState.pdf_file)
async def libadm_pdf_invalid(message: types.Message):
    await message.answer("Iltimos PDF fayl yuboring yoki /skip.")


async def _ask_audio(message: types.Message):
    await LibraryBookCreateState.audio_file.set()
    await message.answer(
        "7️⃣ <b>Audio faylini yuboring</b>\n\n"
        "MP3, M4A, OGG yoki boshqa audio formatdagi fayl.\n"
        "O'tkazib yuborish: /skip",
        parse_mode="HTML",
    )


@dp.message_handler(commands=["skip"], state=LibraryBookCreateState.audio_file)
async def libadm_skip_audio(message: types.Message, state: FSMContext):
    await state.update_data(audio_file_id=None, audio_filename=None)
    await _ask_premium(message)


@dp.message_handler(state=LibraryBookCreateState.audio_file, content_types=types.ContentTypes.AUDIO)
async def libadm_get_audio_native(message: types.Message, state: FSMContext):
    audio = message.audio
    await state.update_data(
        audio_file_id=audio.file_id,
        audio_filename=audio.file_name or "audio.mp3",
    )
    await _ask_premium(message)


@dp.message_handler(state=LibraryBookCreateState.audio_file, content_types=types.ContentTypes.DOCUMENT)
async def libadm_get_audio_doc(message: types.Message, state: FSMContext):
    doc = message.document
    fname = (doc.file_name or "").lower()
    if not any(fname.endswith(ext) for ext in (".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac", ".opus")):
        await message.answer("Iltimos audio fayl yuboring (MP3, M4A, OGG…) yoki /skip.")
        return
    await state.update_data(audio_file_id=doc.file_id, audio_filename=doc.file_name or "audio")
    await _ask_premium(message)


@dp.message_handler(state=LibraryBookCreateState.audio_file)
async def libadm_audio_invalid(message: types.Message):
    await message.answer("Iltimos audio fayl yuboring yoki /skip.")


async def _ask_premium(message: types.Message):
    await LibraryBookCreateState.premium.set()
    await message.answer(
        "8️⃣ <b>PDF/Audio kim uchun?</b>\n\n"
        "Bu kitobning fayllari (PDF/Audio) faqat Premium foydalanuvchilarga ko'rinadimi\n"
        "yoki hamma uchun bepulmi?",
        parse_mode="HTML",
        reply_markup=_premium_kb(),
    )


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:premium:"), state=LibraryBookCreateState.premium)
async def libadm_get_premium(call: types.CallbackQuery, state: FSMContext):
    is_premium = call.data.endswith(":1")
    await call.answer("💎 Premium" if is_premium else "🆓 Bepul")
    await state.update_data(is_premium_only=is_premium)
    await _show_add_preview(call.message, state)


async def _show_add_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data.get("title", "")
    author = data.get("author") or "—"
    desc = data.get("description") or "—"
    lang_code = data.get("language", "uz")
    lang_label = _LANG_LABELS.get(lang_code, lang_code)
    is_premium = data.get("is_premium_only", False)
    has_cover = "Ha ✅" if data.get("cover_file_id") else "Yo'q"
    has_pdf = "Ha ✅" if data.get("pdf_file_id") else "Yo'q"
    has_audio = "Ha ✅" if data.get("audio_file_id") else "Yo'q"
    premium_label = "💎 Faqat Premium" if is_premium else "🆓 Barchaga bepul"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("✅ Saqlash", callback_data="libadm:save"),
        InlineKeyboardButton("❌ Bekor", callback_data="libadm:cancel_add"),
    )
    await message.answer(
        "📋 <b>Kitobni tasdiqlang</b>\n\n"
        f"<b>Nomi:</b> {_esc(title)}\n"
        f"<b>Muallif:</b> {_esc(author)}\n"
        f"<b>Til:</b> {lang_label}\n"
        f"<b>Muqova:</b> {has_cover}\n"
        f"<b>PDF:</b> {has_pdf}\n"
        f"<b>Audio:</b> {has_audio}\n"
        f"<b>Kirish:</b> {premium_label}\n\n"
        f"<b>Tavsif:</b> {_esc(desc)}",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query_handler(lambda c: c.data == "libadm:cancel_add", state=LibraryBookCreateState.states)
async def libadm_cancel_add(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.finish()
    await call.message.answer("❌ Bekor qilindi.", reply_markup=_lib_menu_kb())


@sync_to_async
def _create_book_sync(title, author, description, language, is_premium_only):
    return GlobalBook.objects.create(
        title=title,
        author=author or "",
        description=description or "",
        language=language or "uz",
        is_premium_only=is_premium_only,
    )


@sync_to_async
def _attach_file_sync(book: GlobalBook, field_name: str, filename: str, blob: bytes):
    field = getattr(book, field_name)
    if field:
        field.delete(save=False)
    getattr(book, field_name).save(filename, ContentFile(blob), save=True)


@dp.callback_query_handler(lambda c: c.data == "libadm:save", state=LibraryBookCreateState.states)
async def libadm_save(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    title = data.get("title") or ""
    author = data.get("author") or ""
    description = data.get("description") or ""
    language = data.get("language") or "uz"
    is_premium_only = bool(data.get("is_premium_only", False))
    cover_file_id = data.get("cover_file_id")
    pdf_file_id = data.get("pdf_file_id")
    pdf_filename = data.get("pdf_filename") or "book.pdf"
    audio_file_id = data.get("audio_file_id")
    audio_filename = data.get("audio_filename") or "audio"

    if not title:
        await call.answer("Nom bo'sh — qaytadan boshlang.", show_alert=True)
        await state.finish()
        return

    await call.answer("Saqlanmoqda…")
    book = await _create_book_sync(title, author, description, language, is_premium_only)
    ts = int(timezone.now().timestamp())

    if cover_file_id:
        try:
            buf: io.BytesIO = await bot.download_file_by_id(cover_file_id)
            buf.seek(0)
            await _attach_file_sync(book, "cover", f"book_{book.id}_{ts}.jpg", buf.read())
        except Exception as e:
            print(f"library_admin: cover attach failed for book {book.id}: {e}")
            await call.message.answer("⚠️ Muqova yuklashda xatolik.")

    if pdf_file_id:
        try:
            buf: io.BytesIO = await bot.download_file_by_id(pdf_file_id)
            buf.seek(0)
            await _attach_file_sync(book, "pdf_file", f"book_{book.id}_{ts}_{pdf_filename}", buf.read())
        except Exception as e:
            print(f"library_admin: PDF attach failed for book {book.id}: {e}")
            await call.message.answer("⚠️ PDF yuklashda xatolik.")

    if audio_file_id:
        try:
            buf: io.BytesIO = await bot.download_file_by_id(audio_file_id)
            buf.seek(0)
            await _attach_file_sync(book, "audio_file", f"book_{book.id}_{ts}_{audio_filename}", buf.read())
        except Exception as e:
            print(f"library_admin: audio attach failed for book {book.id}: {e}")
            await call.message.answer("⚠️ Audio yuklashda xatolik.")

    await state.finish()
    book = await _get_book_sync(book.id)
    yoq = "Yo'q"
    premium_tag = "💎 Faqat Premium" if book.is_premium_only else "🆓 Bepul"
    await call.message.answer(
        f"✅ <b>Kitob qo'shildi!</b>\n\n"
        f"📖 <b>{_esc(book.title)}</b>\n"
        f"✍️ {_esc(book.author) if book.author else '—'}\n"
        f"🌐 {_LANG_LABELS.get(book.language, book.language)}\n"
        f"📄 PDF: {'Ha ✅' if book.pdf_file else yoq}\n"
        f"🎧 Audio: {'Ha ✅' if book.audio_file else yoq}\n"
        f"🔐 Kirish: {premium_tag}",
        parse_mode="HTML",
        reply_markup=_lib_menu_kb(),
    )


# ──────────────────────────────────────────────────────────────────────────
# LIST (paginated)
# ──────────────────────────────────────────────────────────────────────────
@sync_to_async
def _list_books_sync(page: int):
    # Hide the ~1400 placeholder rows that only have a title (bulk-imported,
    # no pdf_file) -- they clutter the list and aren't meant to be managed
    # here. They still exist in the DB; this is a display filter only.
    qs = GlobalBook.objects.exclude(pdf_file="").exclude(pdf_file__isnull=True).order_by("title")
    total = qs.count()
    offset = (page - 1) * _BOOKS_PER_PAGE
    rows = list(qs.values("id", "title", "author")[offset: offset + _BOOKS_PER_PAGE])
    total_pages = max(1, (total + _BOOKS_PER_PAGE - 1) // _BOOKS_PER_PAGE)
    return rows, total, total_pages


def _list_kb(rows, page, total_pages) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for r in rows:
        author_tag = f" — {r['author']}" if r.get("author") else ""
        label = f"📖 {r['title'][:35]}{author_tag}"[:60]
        kb.add(InlineKeyboardButton(label, callback_data=f"libadm:view:{r['id']}"))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"libadm:list:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="libadm:noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"libadm:list:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(
        InlineKeyboardButton("➕ Qo'shish", callback_data="libadm:add"),
        InlineKeyboardButton("🔙 Orqaga", callback_data="admin:library"),
    )
    return kb


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:list:"), state="*")
async def libadm_list(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    await call.answer()
    page = int(call.data.split(":")[-1])
    rows, total, total_pages = await _list_books_sync(page)
    if not rows:
        await call.message.answer(
            "📋 Kutubxona bo'sh.\n\nBirinchi kitobni qo'shing:",
            reply_markup=_lib_menu_kb(),
        )
        return
    await call.message.answer(
        f"📚 <b>Kutubxona</b> — jami <b>{total}</b> ta kitob · sahifa {page}/{total_pages}",
        parse_mode="HTML",
        reply_markup=_list_kb(rows, page, total_pages),
    )


@dp.callback_query_handler(lambda c: c.data == "libadm:noop", state="*")
async def libadm_noop(call: types.CallbackQuery):
    await call.answer()


# ──────────────────────────────────────────────────────────────────────────
# VIEW / detail card
# ──────────────────────────────────────────────────────────────────────────
@sync_to_async
def _get_book_sync(bid: int):
    return GlobalBook.objects.filter(id=bid).first()


def _book_card_kb(book: GlobalBook) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("✏️ Nom", callback_data=f"libadm:edit:title:{book.id}"),
        InlineKeyboardButton("✏️ Muallif", callback_data=f"libadm:edit:author:{book.id}"),
    )
    kb.row(
        InlineKeyboardButton("🌐 Til", callback_data=f"libadm:edit:language:{book.id}"),
        InlineKeyboardButton("🔐 Kirish", callback_data=f"libadm:edit:premium:{book.id}"),
    )
    kb.row(
        InlineKeyboardButton("🖼 Muqova", callback_data=f"libadm:edit:cover:{book.id}"),
        InlineKeyboardButton("📝 Tavsif", callback_data=f"libadm:edit:description:{book.id}"),
    )
    kb.row(
        InlineKeyboardButton("📄 PDF", callback_data=f"libadm:edit:pdf_file:{book.id}"),
        InlineKeyboardButton("🎧 Audio", callback_data=f"libadm:edit:audio_file:{book.id}"),
    )
    kb.row(InlineKeyboardButton("🗑 O'chirish", callback_data=f"libadm:delete:{book.id}"))
    kb.row(InlineKeyboardButton("📋 Ro'yxatga qaytish", callback_data="libadm:list:1"))
    return kb


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:view:"), state="*")
async def libadm_view(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    bid = int(call.data.split(":")[-1])
    book = await _get_book_sync(bid)
    if not book:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.answer()
    yoq = "Yo'q"
    no_desc = "<i>Tavsif yo'q</i>"
    premium_tag = "💎 Faqat Premium" if book.is_premium_only else "🆓 Bepul"
    text = (
        f"📖 <b>{_esc(book.title)}</b>\n"
        f"✍️ {_esc(book.author) if book.author else '—'}\n"
        f"🌐 {_LANG_LABELS.get(book.language, book.language)}\n"
        f"🔐 Kirish: {premium_tag}\n"
        f"🖼 Muqova: {'Ha ✅' if book.cover else yoq}\n"
        f"📄 PDF: {'Ha ✅' if book.pdf_file else yoq}\n"
        f"🎧 Audio: {'Ha ✅' if book.audio_file else yoq}\n\n"
        f"{_esc(book.description) if book.description else no_desc}"
    )
    await call.message.answer(text, parse_mode="HTML", reply_markup=_book_card_kb(book))


# ──────────────────────────────────────────────────────────────────────────
# EDIT individual fields
# ──────────────────────────────────────────────────────────────────────────
_EDIT_PROMPTS = {
    "title":       "✏️ <b>Yangi kitob nomini yuboring</b>\n\nBekor qilish: /bekor",
    "author":      "✏️ <b>Yangi muallif ismini yuboring</b>\n\nO'chirish uchun: /clear\nBekor qilish: /bekor",
    "cover":       "🖼 <b>Yangi muqova rasmini yuboring</b>\n\nO'chirish uchun: /clear\nBekor qilish: /bekor",
    "description": "📝 <b>Yangi tavsifni yuboring</b>\n\nO'chirish uchun: /clear\nBekor qilish: /bekor",
    "pdf_file":    "📄 <b>Yangi PDF faylini yuboring</b>\n\nO'chirish uchun: /clear\nBekor qilish: /bekor",
    "audio_file":  "🎧 <b>Yangi audio faylini yuboring</b>\n\nMP3, M4A, OGG…\nO'chirish uchun: /clear\nBekor qilish: /bekor",
}


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:edit:"), state="*")
async def libadm_edit_start(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    parts = call.data.split(":")
    # format: libadm:edit:<field>:<id>
    field = parts[2]
    bid = int(parts[3])
    book = await _get_book_sync(bid)
    if not book:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.answer()

    # language and premium have inline keyboards — handle here directly
    if field == "language":
        await LibraryBookEditState.field.set()
        await state.update_data(edit_book_id=bid, edit_field="language")
        await call.message.answer(
            "🌐 <b>Yangi tilni tanlang</b>",
            parse_mode="HTML",
            reply_markup=_lang_kb(),
        )
        return

    if field == "premium":
        await LibraryBookEditState.field.set()
        await state.update_data(edit_book_id=bid, edit_field="premium")
        await call.message.answer(
            "🔐 <b>Kirish turini tanlang</b>",
            parse_mode="HTML",
            reply_markup=_premium_kb(),
        )
        return

    await LibraryBookEditState.field.set()
    await state.update_data(edit_book_id=bid, edit_field=field)
    await call.message.answer(_EDIT_PROMPTS.get(field, "Yangi qiymat yuboring:"), parse_mode="HTML")


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:lang:"), state=LibraryBookEditState.field)
async def libadm_edit_language(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("edit_field") != "language":
        await call.answer()
        return
    lang = call.data.split(":")[-1]
    bid = data.get("edit_book_id")
    book = await _update_book_text_field(bid, "language", lang)
    await call.answer(_LANG_LABELS.get(lang, lang))
    await state.finish()
    if book:
        await call.message.answer(
            f"✅ <b>{_esc(book.title)}</b> tili yangilandi: {_LANG_LABELS.get(lang, lang)}",
            parse_mode="HTML",
            reply_markup=_lib_menu_kb(),
        )
    else:
        await call.message.answer("Kitob topilmadi.", reply_markup=_lib_menu_kb())


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:premium:"), state=LibraryBookEditState.field)
async def libadm_edit_premium(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("edit_field") != "premium":
        await call.answer()
        return
    is_premium = call.data.endswith(":1")
    bid = data.get("edit_book_id")
    book = await _update_book_bool_field(bid, "is_premium_only", is_premium)
    await call.answer("💎 Premium" if is_premium else "🆓 Bepul")
    await state.finish()
    label = "💎 Faqat Premium" if is_premium else "🆓 Barchaga bepul"
    if book:
        await call.message.answer(
            f"✅ <b>{_esc(book.title)}</b> kirish turi: {label}",
            parse_mode="HTML",
            reply_markup=_lib_menu_kb(),
        )
    else:
        await call.message.answer("Kitob topilmadi.", reply_markup=_lib_menu_kb())


@sync_to_async
def _update_book_text_field(bid: int, field: str, value: str):
    book = GlobalBook.objects.filter(id=bid).first()
    if not book:
        return None
    setattr(book, field, value)
    book.save()
    return book


@sync_to_async
def _update_book_bool_field(bid: int, field: str, value: bool):
    book = GlobalBook.objects.filter(id=bid).first()
    if not book:
        return None
    setattr(book, field, value)
    book.save()
    return book


@sync_to_async
def _clear_file_field(bid: int, field: str):
    book = GlobalBook.objects.filter(id=bid).first()
    if not book:
        return None
    f = getattr(book, field)
    if f:
        f.delete(save=True)
    return book


@dp.message_handler(commands=["clear"], state=LibraryBookEditState.field)
async def libadm_edit_clear(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bid = data.get("edit_book_id")
    field = data.get("edit_field")
    if field == "title":
        await message.answer("Kitob nomini o'chirib bo'lmaydi.")
        return
    if field in _FILE_FIELDS:
        book = await _clear_file_field(bid, field)
        await state.finish()
        label = {"cover": "Muqova", "pdf_file": "PDF", "audio_file": "Audio"}.get(field, field)
        await message.answer(f"✅ {label} o'chirildi.", reply_markup=_lib_menu_kb())
    else:
        book = await _update_book_text_field(bid, field, "")
        await state.finish()
        if book:
            await message.answer(f"✅ {field.capitalize()} o'chirildi.", reply_markup=_lib_menu_kb())
        else:
            await message.answer("Kitob topilmadi.", reply_markup=_lib_menu_kb())


@dp.message_handler(state=LibraryBookEditState.field, content_types=types.ContentTypes.PHOTO)
async def libadm_edit_cover_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    if field != "cover":
        await message.answer("Matn yuboring (yoki /bekor).")
        return
    bid = data.get("edit_book_id")
    book = await _get_book_sync(bid)
    if not book:
        await state.finish()
        await message.answer("Kitob topilmadi.")
        return
    photo = message.photo[-1]
    try:
        buf: io.BytesIO = await bot.download_file_by_id(photo.file_id)
        buf.seek(0)
        ts = int(timezone.now().timestamp())
        await _attach_file_sync(book, "cover", f"book_{bid}_{ts}.jpg", buf.read())
    except Exception as e:
        print(f"library_admin: edit cover failed for book {bid}: {e}")
        await state.finish()
        await message.answer("⚠️ Muqova yuklashda xatolik.")
        return
    await state.finish()
    book = await _get_book_sync(bid)
    await message.answer(
        f"✅ <b>{_esc(book.title)}</b> muqovasi yangilandi!",
        parse_mode="HTML",
        reply_markup=_lib_menu_kb(),
    )


@dp.message_handler(state=LibraryBookEditState.field, content_types=types.ContentTypes.DOCUMENT)
async def libadm_edit_file_doc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    bid = data.get("edit_book_id")

    if field == "pdf_file":
        doc = message.document
        mime = (doc.mime_type or "").lower()
        if mime != "application/pdf" and not (doc.file_name or "").lower().endswith(".pdf"):
            await message.answer("Iltimos PDF fayl yuboring yoki /clear yoki /bekor.")
            return
        book = await _get_book_sync(bid)
        if not book:
            await state.finish()
            await message.answer("Kitob topilmadi.")
            return
        try:
            buf: io.BytesIO = await bot.download_file_by_id(doc.file_id)
            buf.seek(0)
            ts = int(timezone.now().timestamp())
            fname = doc.file_name or "book.pdf"
            await _attach_file_sync(book, "pdf_file", f"book_{bid}_{ts}_{fname}", buf.read())
        except Exception as e:
            print(f"library_admin: edit PDF failed for book {bid}: {e}")
            await state.finish()
            await message.answer("⚠️ PDF yuklashda xatolik.")
            return
        await state.finish()
        book = await _get_book_sync(bid)
        await message.answer(
            f"✅ <b>{_esc(book.title)}</b> PDF yangilandi!",
            parse_mode="HTML",
            reply_markup=_lib_menu_kb(),
        )
        return

    if field == "audio_file":
        doc = message.document
        fname = (doc.file_name or "").lower()
        if not any(fname.endswith(ext) for ext in (".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac", ".opus")):
            await message.answer("Iltimos audio fayl yuboring (MP3, M4A…) yoki /clear yoki /bekor.")
            return
        book = await _get_book_sync(bid)
        if not book:
            await state.finish()
            await message.answer("Kitob topilmadi.")
            return
        try:
            buf: io.BytesIO = await bot.download_file_by_id(doc.file_id)
            buf.seek(0)
            ts = int(timezone.now().timestamp())
            await _attach_file_sync(book, "audio_file", f"book_{bid}_{ts}_{doc.file_name or 'audio'}", buf.read())
        except Exception as e:
            print(f"library_admin: edit audio failed for book {bid}: {e}")
            await state.finish()
            await message.answer("⚠️ Audio yuklashda xatolik.")
            return
        await state.finish()
        book = await _get_book_sync(bid)
        await message.answer(
            f"✅ <b>{_esc(book.title)}</b> audio yangilandi!",
            parse_mode="HTML",
            reply_markup=_lib_menu_kb(),
        )
        return

    await message.answer("Matn yuboring (yoki /bekor).")


@dp.message_handler(state=LibraryBookEditState.field, content_types=types.ContentTypes.AUDIO)
async def libadm_edit_audio_native(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    bid = data.get("edit_book_id")
    if field != "audio_file":
        await message.answer("Matn yuboring (yoki /bekor).")
        return
    book = await _get_book_sync(bid)
    if not book:
        await state.finish()
        await message.answer("Kitob topilmadi.")
        return
    audio = message.audio
    try:
        buf: io.BytesIO = await bot.download_file_by_id(audio.file_id)
        buf.seek(0)
        ts = int(timezone.now().timestamp())
        fname = audio.file_name or "audio.mp3"
        await _attach_file_sync(book, "audio_file", f"book_{bid}_{ts}_{fname}", buf.read())
    except Exception as e:
        print(f"library_admin: edit audio native failed for book {bid}: {e}")
        await state.finish()
        await message.answer("⚠️ Audio yuklashda xatolik.")
        return
    await state.finish()
    book = await _get_book_sync(bid)
    await message.answer(
        f"✅ <b>{_esc(book.title)}</b> audio yangilandi!",
        parse_mode="HTML",
        reply_markup=_lib_menu_kb(),
    )


@dp.message_handler(state=LibraryBookEditState.field, content_types=types.ContentTypes.TEXT)
async def libadm_edit_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bid = data.get("edit_book_id")
    field = data.get("edit_field")
    value = (message.text or "").strip()

    if field in _FILE_FIELDS or field in ("language", "premium"):
        await message.answer("Iltimos tugmadan tanlang yoki /bekor.")
        return

    if field == "title":
        if len(value) < 2 or len(value) > 255:
            await message.answer("Nom 2–255 belgi bo'lishi kerak.")
            return
        exists = await sync_to_async(
            GlobalBook.objects.filter(title__iexact=value).exclude(id=bid).exists
        )()
        if exists:
            await message.answer(f"⚠️ <b>{_esc(value)}</b> nomli kitob allaqachon mavjud.", parse_mode="HTML")
            return
    elif field == "description" and len(value) > 2000:
        await message.answer("Tavsif 2000 belgidan oshmasligi kerak.")
        return

    book = await _update_book_text_field(bid, field, value)
    await state.finish()
    if book:
        await message.answer(
            f"✅ <b>{_esc(book.title)}</b> yangilandi!",
            parse_mode="HTML",
            reply_markup=_lib_menu_kb(),
        )
    else:
        await message.answer("Kitob topilmadi.", reply_markup=_lib_menu_kb())


@dp.message_handler(state=LibraryBookEditState.field)
async def libadm_edit_invalid(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field", "")
    if field in _FILE_FIELDS:
        await message.answer("Iltimos fayl yuboring yoki /clear yoki /bekor.")
    else:
        await message.answer("Matn yuboring yoki /bekor.")


# ──────────────────────────────────────────────────────────────────────────
# DELETE
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("libadm:delete:") and "delete_yes" not in c.data, state="*")
async def libadm_delete_confirm(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    bid = int(call.data.split(":")[-1])
    book = await _get_book_sync(bid)
    if not book:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.answer()
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"libadm:delete_yes:{bid}"),
        InlineKeyboardButton("❌ Bekor", callback_data=f"libadm:view:{bid}"),
    )
    await call.message.answer(
        f"🗑 <b>{_esc(book.title)}</b> ni o'chirilsinmi?\n\n"
        "Foydalanuvchilardagi o'qish ma'lumotlari ham o'chadi.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@sync_to_async
def _delete_book_sync(bid: int) -> bool:
    book = GlobalBook.objects.filter(id=bid).first()
    if not book:
        return False
    for field_name in ("cover", "pdf_file", "audio_file"):
        f = getattr(book, field_name)
        if f:
            f.delete(save=False)
    book.delete()
    return True


@dp.callback_query_handler(lambda c: c.data.startswith("libadm:delete_yes:"), state="*")
async def libadm_delete_yes(call: types.CallbackQuery, state: FSMContext):
    user = await aget_user(call.from_user.id)
    if not _is_admin(user):
        await call.answer("Faqat adminlar uchun", show_alert=True)
        return
    bid = int(call.data.split(":")[-1])
    ok = await _delete_book_sync(bid)
    await call.answer("🗑 O'chirildi" if ok else "Topilmadi", show_alert=True)
    rows, total, total_pages = await _list_books_sync(1)
    await call.message.answer(
        f"📚 <b>Kutubxona</b> — jami <b>{total}</b> ta kitob" if rows else "📚 Kutubxona bo'sh.",
        parse_mode="HTML",
        reply_markup=_list_kb(rows, 1, total_pages) if rows else _lib_menu_kb(),
    )
