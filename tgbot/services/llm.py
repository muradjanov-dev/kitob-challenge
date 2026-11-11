"""One way to ask a language model, with a fallback (2026-11-11).

The AI quiz and the personal thank-you letters both need a model. OpenAI is
tried first when OPENAI_API_KEY is set; when it fails (no key, no credit,
rate limit) Google Gemini answers through its OpenAI-compatible endpoint
with GEMINI_API_KEY -- Google AI Studio gives that key a free daily quota,
so the features keep working without a paid balance. LLM_PROVIDER=gemini
puts Gemini first.
"""
import os

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# The free tier allows only 20 Flash requests a day (seen 2026-11-11:
# "generate_content_free_tier_requests, limit: 20"); Flash-Lite has its own,
# larger quota, so it answers when Flash is spent.
GEMINI_LITE_MODEL = os.environ.get("GEMINI_LITE_MODEL", "gemini-2.5-flash-lite")


_BAD_KEY_FLAG = "llm_bad_key:{}"


def _bad_key(name) -> bool:
    try:
        from django.core.cache import cache
        return bool(cache.get(_BAD_KEY_FLAG.format(name)))
    except Exception:
        return False


def _note_failure(name, err) -> None:
    """A rejected key (401) is skipped for an hour instead of costing a
    round trip on every request (2026-11-11: the OpenAI key was revoked)."""
    if "401" in str(err) or "Incorrect API key" in str(err):
        try:
            from django.core.cache import cache
            cache.set(_BAD_KEY_FLAG.format(name), 1, 60 * 60)
        except Exception:
            pass


def providers(lite_first=False, lite_only=False) -> list:
    """[(name, api_key, base_url, model)] in the order to try. Gemini comes
    twice: Flash, then Flash-Lite (or the other way round with lite_first,
    for bulk jobs that should leave the small Flash quota to the AI quiz)."""
    out = []
    if os.environ.get("OPENAI_API_KEY") and not _bad_key("openai"):
        out.append(("openai", os.environ["OPENAI_API_KEY"], None, OPENAI_MODEL))
    if os.environ.get("GEMINI_API_KEY"):
        models = [GEMINI_MODEL, GEMINI_LITE_MODEL]
        if lite_first:
            models.reverse()
        if lite_only:
            models = [GEMINI_LITE_MODEL]
        for m in dict.fromkeys(models):
            out.append(("gemini", os.environ["GEMINI_API_KEY"], GEMINI_BASE_URL, m))
    if os.environ.get("LLM_PROVIDER") == "gemini":
        out.sort(key=lambda p: p[0] != "gemini")
    return out


def _kwargs(name, model, max_tokens, json_mode):
    kw = {"model": model}
    if name == "openai":
        # gpt-5-mini is a reasoning model: no temperature, max_completion_tokens.
        kw["max_completion_tokens"] = max_tokens
        kw["extra_body"] = {"reasoning_effort": "low"}
    else:
        kw["max_tokens"] = max_tokens
        kw["extra_body"] = {"reasoning_effort": "low"}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    return kw


def complete(messages, max_tokens=2000, json_mode=False, timeout=120, lite_first=False, lite_only=False) -> tuple:
    """(text, provider_name). Raises the last error when every provider fails.
    lite_only: Gemini Flash-Lite only -- for bulk jobs, so they can never eat
    the small free Flash quota the AI quiz lives on."""
    from openai import OpenAI
    last = RuntimeError("no LLM key configured (OPENAI_API_KEY / GEMINI_API_KEY)")
    for name, key, base, model in providers(lite_first, lite_only):
        try:
            # No silent SDK retries: a spent quota should move on to the next model.
            client = (OpenAI(api_key=key, base_url=base, max_retries=0) if base
                      else OpenAI(api_key=key, max_retries=0))
            r = client.chat.completions.create(messages=messages, timeout=timeout,
                                               **_kwargs(name, model, max_tokens, json_mode))
            text = (r.choices[0].message.content or "").strip()
            if text:
                return text, name
            last = RuntimeError(f"{name}: empty answer ({r.choices[0].finish_reason})")
        except Exception as e:
            last = e
            _note_failure(name, e)
            print(f"llm.complete {name} failed: {str(e)[:300]}")
    raise last


async def acomplete(messages, max_tokens=2000, json_mode=False, timeout=180) -> tuple:
    from openai import AsyncOpenAI
    last = RuntimeError("no LLM key configured (OPENAI_API_KEY / GEMINI_API_KEY)")
    for name, key, base, model in providers():
        try:
            client = (AsyncOpenAI(api_key=key, base_url=base, max_retries=0) if base
                      else AsyncOpenAI(api_key=key, max_retries=0))
            r = await client.chat.completions.create(messages=messages, timeout=timeout,
                                                     **_kwargs(name, model, max_tokens, json_mode))
            text = (r.choices[0].message.content or "").strip()
            if text:
                return text, name
            last = RuntimeError(f"{name}: empty answer ({r.choices[0].finish_reason})")
        except Exception as e:
            last = e
            _note_failure(name, e)
            print(f"llm.acomplete {name} failed: {str(e)[:300]}")
    raise last


def health() -> dict:
    """Which keys are set and whether each provider answers a one-word ping."""
    from openai import OpenAI
    out = {}
    every = [p for p in (("openai", os.environ.get("OPENAI_API_KEY"), None, OPENAI_MODEL),
                         ("gemini", os.environ.get("GEMINI_API_KEY"), GEMINI_BASE_URL, GEMINI_MODEL),
                         ("gemini-lite", os.environ.get("GEMINI_API_KEY"), GEMINI_BASE_URL, GEMINI_LITE_MODEL))
             if p[1]]
    for name, key, base, model in every:
        try:
            client = OpenAI(api_key=key, base_url=base) if base else OpenAI(api_key=key)
            r = client.chat.completions.create(messages=[{"role": "user", "content": "Say OK"}], timeout=30,
                                               **_kwargs(name, model, 200, False))
            out[name] = {"ok": True, "model": model, "answer": (r.choices[0].message.content or "")[:20]}
        except Exception as e:
            out[name] = {"ok": False, "model": model, "error": str(e)[:300]}
    out["keys"] = {"openai": bool(os.environ.get("OPENAI_API_KEY")), "gemini": bool(os.environ.get("GEMINI_API_KEY"))}
    return out
