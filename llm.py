"""Provider-agnostic LLM call: Groq, OpenAI, Anthropic, and Google Gemini."""

PROVIDERS = ("groq", "openai", "anthropic", "gemini")


def available(cfg):
    return {p: bool(cfg[f"{p}_key"]) for p in PROVIDERS}


def default_model(cfg, provider):
    return cfg[f"{provider}_model"]


def run(provider, model, system, user, cfg, temperature=0.1, max_tokens=4000):
    key = cfg.get(f"{provider}_key")
    if not key:
        raise ValueError(f"{provider.upper()}_API_KEY is missing in .env")
    if not model:
        raise ValueError(f"No model set for {provider} (set {provider.upper()}_MODEL in .env)")
    model = model.strip()
    if model.lower().startswith(provider + ":"):  # tolerate "groq:openai/gpt-oss-20b"
        model = model[len(provider) + 1:]
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if provider == "groq":
        from groq import Groq
        r = Groq(api_key=key).chat.completions.create(model=model, messages=msgs, temperature=temperature, max_tokens=max_tokens, timeout=45)
        return r.choices[0].message.content
    if provider == "openai":
        from openai import OpenAI
        cl = OpenAI(api_key=key, timeout=45)
        try:
            r = cl.chat.completions.create(model=model, messages=msgs, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:  # newer models reject max_tokens/temperature
            if "max_completion_tokens" in str(e) or "temperature" in str(e):
                r = cl.chat.completions.create(model=model, messages=msgs, max_completion_tokens=max_tokens)
            else:
                raise
        return r.choices[0].message.content
    if provider == "anthropic":
        import anthropic
        r = anthropic.Anthropic(api_key=key).messages.create(
            model=model, max_tokens=max_tokens, temperature=temperature, system=system, timeout=45,
            messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in r.content if getattr(b, "text", None))
    if provider == "gemini":
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        r = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        if not getattr(r, "text", None):
            raise RuntimeError("Gemini returned an empty response. Check model access and API quota.")
        return r.text
    raise ValueError(f"Unknown provider {provider}")


def validate(provider, model, system, payload, cfg):
    """Second-opinion call on ONE deterministic signal. Returns a validated dict; raises on unusable output."""
    import json
    import re
    txt = run(provider, model, system, json.dumps(payload, default=str, separators=(",", ":")), cfg, temperature=0.0, max_tokens=500)
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        raise ValueError("LLM returned no JSON object")
    r = json.loads(m.group(0))
    if r.get("verdict") not in ("CONFIRM", "DOWNGRADE", "REJECT"):
        raise ValueError(f"bad verdict {r.get('verdict')!r}")
    adj = r.get("confidence_adjustment", 0)
    r["confidence_adjustment"] = int(min(0, max(-30, adj))) if isinstance(adj, (int, float)) else 0
    r["risks"] = [str(x)[:140] for x in (r.get("risks") or [])][:3]
    r["rationale"] = str(r.get("rationale", ""))[:400]
    return r
