"""The proposed new Uzbek Latin alphabet, applied where text leaves for users.

    o' -> ŏ    g' -> ğ    sh -> ş    ch -> ç    (and capitals Ŏ Ğ Ş Ç)

Owner's decision (2026-10-25): the whole system writes in the new alphabet.
Source strings stay in the current spelling; conversion happens at the three
exits instead, so code identifiers, URLs, callback data and commands are never
touched and one switch turns it all off:

- every Telegram Bot API call (aiogram's bot.request and direct
  requests.post to api.telegram.org) -- install() / wrap_bot()
- every Mini App / site page -- AlphabetPageMiddleware injects PAGE_SCRIPT,
  which converts the rendered text nodes, including JS-rendered ones
- typed input comes back in the old spelling (to_old) so reply-keyboard
  button handlers keep matching, and chain_text.answer_key folds ŏ/ğ/ş/ç so
  typed game answers match in either alphabet

Kill switch: cache key "new_alphabet_off" (internal/ops/alphabet/).
"""
import json
import re
import time

APOS = "'‘’ʻʼ`"
_A = "[" + re.escape(APOS) + "]"

# English and brand words that keep their spelling.
KEEP_WORDS = {
    "challenge", "challenges", "challange", "shop", "chat", "chats", "check",
    "checks", "show", "share", "sheet", "flash", "watch", "search", "bach",
    "touch", "match", "machine", "cash", "chrome", "chess", "coach", "teacher",
    "chapter", "fresh", "english", "push", "telegram", "whatsapp",
}

# Pieces of text that are not prose: HTML tags/entities, links, @handles,
# /commands, {placeholders}, `code`.
_PROTECT = re.compile(
    r"<[^<>]*>|&#?\w+;|https?://\S+|www\.\S+|t\.me/\S+|(?<![\w/])[@/#][\w.\-/]+"
    r"|\{[^{}]*\}|`[^`]*`",
)
_WORD = re.compile(r"[A-Za-z" + re.escape(APOS) + r"]+")

_FLAG_KEY = "new_alphabet_off"
_flag = {"at": 0.0, "on": True}


def enabled() -> bool:
    now = time.monotonic()
    if now - _flag["at"] > 30:
        try:
            from django.core.cache import cache
            _flag["on"] = not cache.get(_FLAG_KEY)
        except Exception:
            pass
        _flag["at"] = now
    return _flag["on"]


def set_enabled(on: bool) -> None:
    from django.core.cache import cache
    if on:
        cache.delete(_FLAG_KEY)
    else:
        cache.set(_FLAG_KEY, 1, None)
    _flag["at"] = 0.0


def _case(src: str, new_lower: str) -> str:
    return new_lower.upper() if src[:1].isupper() else new_lower


def _word(w: str) -> str:
    core = w.strip(APOS).lower()
    # "Challenge'ga": the suffix after the apostrophe does not make it Uzbek.
    if not core or core in KEEP_WORDS or re.split(_A, core)[0] in KEEP_WORDS:
        return w
    w = re.sub(r"([Oo])" + _A + r"(?=[A-Za-z])", lambda m: _case(m.group(1), "ŏ"), w)
    w = re.sub(r"([Gg])" + _A, lambda m: _case(m.group(1), "ğ"), w)
    w = re.sub(r"[Ss][Hh]", lambda m: _case(m.group(0), "ş"), w)
    w = re.sub(r"[Cc][Hh]", lambda m: _case(m.group(0), "ç"), w)
    return w


def _prose(text: str) -> str:
    return _WORD.sub(lambda m: _word(m.group(0)), text)


def to_new(text):
    """Current Uzbek Latin -> new alphabet, leaving markup and links alone."""
    if not text or not isinstance(text, str):
        return text
    out, pos = [], 0
    for m in _PROTECT.finditer(text):
        out.append(_prose(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_prose(text[pos:]))
    return "".join(out)


_BACK = {"ŏ": "o'", "ğ": "g'", "ş": "sh", "ç": "ch"}
_HAS_NEW = re.compile("[ŏğşçŎĞŞÇ]")


def to_old(text):
    """New alphabet -> current spelling, for input coming back from users."""
    if not text or not isinstance(text, str) or not _HAS_NEW.search(text):
        return text
    out = []
    for i, ch in enumerate(text):
        low = ch.lower()
        if low not in _BACK:
            out.append(ch)
            continue
        rep = _BACK[low]
        if ch != low:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prv = text[i - 1] if i else ""
            all_caps = nxt.isupper() or (not nxt.isalpha() and prv.isupper())
            rep = rep.upper() if all_caps else rep[0].upper() + rep[1:]
        out.append(rep)
    return "".join(out)


# ── Telegram payloads ──────────────────────────────────────────────────────

_TEXT_FIELDS = ("text", "caption", "question", "explanation")


def _markup(value):
    raw = value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except ValueError:
            return raw
    elif isinstance(value, dict):
        data = value
    else:
        return raw
    for key in ("inline_keyboard", "keyboard"):
        for row in data.get(key) or []:
            for i, btn in enumerate(row):
                if isinstance(btn, dict) and isinstance(btn.get("text"), str):
                    btn["text"] = to_new(btn["text"])
                elif isinstance(btn, str):
                    row[i] = to_new(btn)
    if isinstance(data.get("input_field_placeholder"), str):
        data["input_field_placeholder"] = to_new(data["input_field_placeholder"])
    return json.dumps(data, ensure_ascii=False) if isinstance(value, str) else data


def _list_field(value, key=None):
    as_str = isinstance(value, str)
    try:
        items = json.loads(value) if as_str else value
    except ValueError:
        return value
    if not isinstance(items, list):
        return value
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(to_new(it))
        elif isinstance(it, dict):
            it = dict(it)
            for k in ("text", "description", "caption"):
                if isinstance(it.get(k), str):
                    it[k] = to_new(it[k])
            out.append(it)
        else:
            out.append(it)
    return json.dumps(out, ensure_ascii=False) if as_str else out


def transform_payload(data):
    """Convert the user-visible fields of one Bot API call, in place."""
    if not isinstance(data, dict):
        return data
    for k in _TEXT_FIELDS:
        if isinstance(data.get(k), str):
            data[k] = to_new(data[k])
    if data.get("reply_markup") is not None:
        data["reply_markup"] = _markup(data["reply_markup"])
    for k in ("options", "commands", "media"):
        if data.get(k) is not None:
            data[k] = _list_field(data[k])
    return data


def install() -> None:
    """Route every requests call to the Bot API through transform_payload."""
    import requests.sessions as rs
    if getattr(rs.Session.request, "_kc_alphabet", False):
        return
    orig = rs.Session.request

    def request(self, method, url, *args, **kwargs):
        if isinstance(url, str) and "api.telegram.org/bot" in url and enabled():
            try:
                for k in ("data", "json"):
                    if isinstance(kwargs.get(k), dict):
                        kwargs[k] = transform_payload(dict(kwargs[k]))
            except Exception as e:
                print(f"alphabet: payload left as is: {e}")
        return orig(self, method, url, *args, **kwargs)

    request._kc_alphabet = True
    rs.Session.request = request


def wrap_bot(bot) -> None:
    """Same for aiogram: every method ends in bot.request(method, data)."""
    if bot is None or getattr(bot, "_kc_alphabet", False):
        return
    orig = bot.request

    async def request(method, data=None, *args, **kwargs):
        if data and enabled():
            try:
                data = transform_payload(dict(data))
            except Exception as e:
                print(f"alphabet: payload left as is: {e}")
        return await orig(method, data, *args, **kwargs)

    bot.request = request
    bot._kc_alphabet = True


# ── Web pages ──────────────────────────────────────────────────────────────

# Mirrors to_new() in the browser: text nodes only (never script/style/inputs),
# re-run on every DOM change so the polled, JS-rendered game screens convert
# too. Kept in step with KEEP_WORDS above.
PAGE_SCRIPT = """<script>(function(){
var KEEP=%(keep)s,A="'\\u2018\\u2019\\u02bb\\u02bc`";
var SKIP={SCRIPT:1,STYLE:1,TEXTAREA:1,INPUT:1,CODE:1,PRE:1,NOSCRIPT:1};
function cs(s,n){return s.charAt(0)===s.charAt(0).toUpperCase()?n.toUpperCase():n;}
function word(w){var c=w.replace(/^['\\u2018\\u2019\\u02bb\\u02bc`]+|['\\u2018\\u2019\\u02bb\\u02bc`]+$/g,'').toLowerCase();
 if(!c||KEEP.indexOf(c)>=0||KEEP.indexOf(c.split(/['\\u2018\\u2019\\u02bb\\u02bc`]/)[0])>=0)return w;
 return w.replace(/([Oo])['\\u2018\\u2019\\u02bb\\u02bc`](?=[A-Za-z])/g,function(m,o){return cs(o,'\\u014f');})
  .replace(/([Gg])['\\u2018\\u2019\\u02bb\\u02bc`]/g,function(m,g){return cs(g,'\\u011f');})
  .replace(/[Ss][Hh]/g,function(m){return cs(m,'\\u015f');})
  .replace(/[Cc][Hh]/g,function(m){return cs(m,'\\u00e7');});}
var PROT=/(https?:\\/\\/\\S+|www\\.\\S+|t\\.me\\/\\S+|(?:^|\\s)[@\\/#][\\w.\\-\\/]+)/;
function conv(t){if(!/[sScCoOgG]/.test(t))return t;return t.split(PROT).map(function(p,i){return i%%2?p:p.replace(/[A-Za-z'\\u2018\\u2019\\u02bb\\u02bc`]+/g,word);}).join('');}
function walk(root){if(!root)return;if(root.nodeType===3){var v=root.nodeValue,n=conv(v);if(n!==v)root.nodeValue=n;return;}
 if(root.nodeType!==1||SKIP[root.tagName]||root.isContentEditable||root.hasAttribute('data-raw'))return;
 ['placeholder','title','aria-label'].forEach(function(a){var v=root.getAttribute(a);if(v){var n=conv(v);if(n!==v)root.setAttribute(a,n);}});
 for(var c=root.firstChild;c;c=c.nextSibling)walk(c);}
function start(){walk(document.body);document.title=conv(document.title);
 new MutationObserver(function(ms){ms.forEach(function(m){if(m.type==='characterData')walk(m.target);else m.addedNodes.forEach(walk);});})
 .observe(document.body,{childList:true,subtree:true,characterData:true});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();</script>""" % {"keep": json.dumps(sorted(KEEP_WORDS))}


class AlphabetPageMiddleware:
    """Adds PAGE_SCRIPT to every HTML page outside the Django admin."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if (response.status_code == 200 and not request.path.startswith("/admin")
                    and "text/html" in response.get("Content-Type", "")
                    and not getattr(response, "streaming", False) and enabled()):
                body = response.content.decode(response.charset or "utf-8")
                idx = body.rfind("</body>")
                if idx != -1:
                    body = body[:idx] + PAGE_SCRIPT + body[idx:]
                    response.content = body.encode(response.charset or "utf-8")
                    if response.has_header("Content-Length"):
                        response["Content-Length"] = str(len(response.content))
        except Exception as e:
            print(f"AlphabetPageMiddleware: {e}")
        return response
