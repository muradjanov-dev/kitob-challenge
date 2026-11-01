"""App shell: the four site sections (Bosh sahifa, Kutubxona, Do'kon, Kabinet)
kept loaded side by side in one document, so a swipe or a tab tap slides to
the next one without reloading it (owner, 2026-11-01).

Each section stays its own page inside an iframe (`?embed=1`): its CSS,
scripts and ids cannot clash with the others. Inside the shell a section
uses the shell's Telegram SDK (templates/app/_embed.html), so initData,
popups and links all go through the one window Telegram talks to.

Off until switched on (internal/ops/app-shell/): the section URLs then
answer with the shell. `?shell=1` / `?shell=0` force it either way for
testing; crawlers and link previews always get the plain page.
"""
from django.shortcuts import render

SECTIONS = ["/", "/kutubxona/", "/shop/", "/kabinet/"]
TITLES = ["Kitob Challenge", "Kutubxona — Kitob Challenge", "Do'kon — Kitob Challenge", "Kabinet — Kitob Challenge"]
_FLAG = "app_shell_on"
_BOT_UA = ("bot", "crawl", "spider", "slurp", "preview", "facebookexternalhit", "whatsapp")


def enabled() -> bool:
    from django.core.cache import cache
    return bool(cache.get(_FLAG))


def set_enabled(on: bool) -> None:
    from django.core.cache import cache
    cache.set(_FLAG, bool(on), None)


def wanted(request) -> bool:
    if request.GET.get("embed") or request.headers.get("Sec-Fetch-Dest") == "iframe":
        return False
    forced = request.GET.get("shell")
    if forced in ("0", "1"):
        return forced == "1"
    ua = (request.META.get("HTTP_USER_AGENT") or "").lower()
    if any(b in ua for b in _BOT_UA):
        return False
    return enabled()


def render_shell(request, section: str):
    """The shell, opening on `section` with the request's own query."""
    idx = SECTIONS.index(section)
    query = request.GET.copy()
    keep_shell = query.pop("shell", None)
    resp = render(request, "app/shell.html", {
        "sections": SECTIONS,
        "initial_idx": idx,
        "initial_query": query.urlencode(),
        "title": TITLES[idx],
        "shell_param": "shell=1" if keep_shell == ["1"] else "",
    })
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp
