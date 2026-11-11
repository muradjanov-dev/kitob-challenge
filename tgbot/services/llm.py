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


def providers() -> list:
    """[(name, api_key, base_url, model)] in the order to try."""
    out = []
    if os.environ.get("OPENAI_API_KEY"):
        out.append(("openai", os.environ["OPENAI_API_KEY"], None, OPENAI_MODEL))
    if os.environ.get("GEMINI_API_KEY"):
        out.append(("gemini", os.environ["GEMINI_API_KEY"], GEMINI_BASE_URL, GEMINI_MODEL))
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


def complete(messages, max_tokens=2000, json_mode=False, timeout=120) -> tuple:
    """(text, provider_name). Raises the last error when every provider fails."""
    from openai import OpenAI
    last = RuntimeError("no LLM key configured (OPENAI_API_KEY / GEMINI_API_KEY)")
    for name, key, base, model in providers():
        try:
            client = OpenAI(api_key=key, base_url=base) if base else OpenAI(api_key=key)
            r = client.chat.completions.create(messages=messages, timeout=timeout,
                                               **_kwargs(name, model, max_tokens, json_mode))
            text = (r.choices[0].message.content or "").strip()
            if text:
                return text, name
            last = RuntimeError(f"{name}: empty answer ({r.choices[0].finish_reason})")
        except Exception as e:
            last = e
            print(f"llm.complete {name} failed: {str(e)[:300]}")
    raise last


async def acomplete(messages, max_tokens=2000, json_mode=False, timeout=180) -> tuple:
    from openai import AsyncOpenAI
    last = RuntimeError("no LLM key configured (OPENAI_API_KEY / GEMINI_API_KEY)")
    for name, key, base, model in providers():
        try:
            client = AsyncOpenAI(api_key=key, base_url=base) if base else AsyncOpenAI(api_key=key)
            r = await client.chat.completions.create(messages=messages, timeout=timeout,
                                                     **_kwargs(name, model, max_tokens, json_mode))
            text = (r.choices[0].message.content or "").strip()
            if text:
                return text, name
            last = RuntimeError(f"{name}: empty answer ({r.choices[0].finish_reason})")
        except Exception as e:
            last = e
            print(f"llm.acomplete {name} failed: {str(e)[:300]}")
    raise last


def health() -> dict:
    """Which keys are set and whether each provider answers a one-word ping."""
    from openai import OpenAI
    out = {}
    for name, key, base, model in providers():
        try:
            client = OpenAI(api_key=key, base_url=base) if base else OpenAI(api_key=key)
            r = client.chat.completions.create(messages=[{"role": "user", "content": "Say OK"}], timeout=30,
                                               **_kwargs(name, model, 200, False))
            out[name] = {"ok": True, "model": model, "answer": (r.choices[0].message.content or "")[:20]}
        except Exception as e:
            out[name] = {"ok": False, "model": model, "error": str(e)[:300]}
    out["keys"] = {"openai": bool(os.environ.get("OPENAI_API_KEY")), "gemini": bool(os.environ.get("GEMINI_API_KEY"))}
    return out
