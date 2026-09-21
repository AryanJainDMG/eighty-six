"""Where the words come from.

Three providers behind one two-method interface, for three different
reasons:

- **gemini** is what the deployed app uses. Free tier, no card, good enough
  prose that the characters are worth talking to.
- **local** runs a small open model through transformers. It exists because
  the benchmark needs to run without spending anyone's quota, and because
  measuring a hosted model that silently changes underneath you is not
  measuring anything.
- **scripted** returns canned lines with no model at all. Every test in this
  repository runs against it, so the test suite is deterministic, offline
  and instant — and the app still boots and plays without an API key, which
  matters more than it sounds: the alternative is a demo that dies with the
  wifi.

Keeping the interface to `complete(system, history, user) -> str` is what
lets the benchmark and the live app run the identical pipeline. The moment
a provider needs a wider interface, the thing being measured stops being
the thing being served.
"""

from __future__ import annotations

import os
import re

import httpx

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class Provider:
    name = "base"

    def complete(self, system: str, history: list[dict], user: str) -> str:
        raise NotImplementedError


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-3.6-flash"):
        self.api_key = api_key
        self.model = model

    def complete(self, system: str, history: list[dict], user: str) -> str:
        contents = []
        for turn in history:
            contents.append(
                {
                    "role": "user" if turn["role"] == "user" else "model",
                    "parts": [{"text": turn["text"]}],
                }
            )
        contents.append({"role": "user", "parts": [{"text": user}]})

        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                # Low but not zero. A suspect who answers identically to the
                # same question twice feels like a lookup table; one at 1.0
                # wanders off and invents a sixth member of staff.
                "temperature": 0.4,
                "maxOutputTokens": 400,
                # Thinking is on by default on the Flash models, and
                # reasoning tokens are drawn from the same maxOutputTokens
                # budget as the reply. A suspect has nothing to reason
                # about — they are reading two facts off a dossier — so the
                # budget would be spent deliberating and the response would
                # come back with no text in it at all.
                #
                # Models that do not support the field ignore it, and the
                # token ceiling above is generous enough to survive one that
                # thinks anyway.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        response = httpx.post(
            GEMINI_URL.format(model=self.model),
            params={"key": self.api_key},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError):
            # Usually a safety block or a truncated response. Returning the
            # raw payload to the page would be a small information leak of a
            # different kind, so say nothing useful and log nothing sensitive.
            return "[no answer]"


class LocalProvider(Provider):
    """A small open model through transformers. Used by the benchmark."""

    name = "local"

    def __init__(self, model_id: str = "Qwen/Qwen2.5-1.5B-Instruct"):
        import torch  # heavy
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(int(os.environ.get("EIGHTYSIX_THREADS", "2")))

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float32)
        self.model_id = model_id

    def complete(self, system: str, history: list[dict], user: str) -> str:
        messages = [{"role": "system", "content": system}]
        for turn in history:
            messages.append(
                {
                    "role": "user" if turn["role"] == "user" else "assistant",
                    "content": turn["text"],
                }
            )
        messages.append({"role": "user", "content": user})

        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(prompt, return_tensors="pt")
        output = self.model.generate(
            **inputs,
            max_new_tokens=120,
            do_sample=False,  # deterministic, so the benchmark is reproducible
            pad_token_id=self.tokenizer.eos_token_id,
        )
        text = self.tokenizer.decode(
            output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )
        return text.strip()


class ScriptedProvider(Provider):
    """No model. Plays the part from the dossier it was given.

    Not a mock in the testing sense — it genuinely answers, by reading the
    dossier it was handed and echoing the relevant line. That makes it a
    useful control as well as a fallback: it is what a character sounds like
    when it is incapable of inventing anything at all.
    """

    name = "scripted"

    def complete(self, system: str, history: list[dict], user: str) -> str:
        segments = re.findall(
            r"^- (\d\d:\d\d)–(\d\d:\d\d): ([^,]+), ([^.]+)\.", system, re.M
        )
        if not segments:
            return "I've told you everything I know about tonight."

        # If this dossier belongs to the culprit it contains the story they
        # have agreed to tell. Use it. A fallback provider that answers
        # truthfully would hand the player the culprit on the first
        # question, which makes the fallback worse than no fallback.
        alibi = re.search(r"you say you were ([^.]+)\.", system)
        window = re.search(r"between (\d\d:\d\d) and (\d\d:\d\d)", system)

        asked_about_time = re.search(r"\b(\d\d)[:.]?(\d\d)\b", user)
        target = (
            f"{asked_about_time.group(1)}:{asked_about_time.group(2)}"
            if asked_about_time
            else None
        )

        if alibi and window and (target is None or window.group(1) <= target <= window.group(2)):
            return (
                f"Between {window.group(1)} and {window.group(2)} I was "
                f"{alibi.group(1)}. That's all there is to it."
            )

        chosen = segments[len(segments) // 2]
        if target:
            for seg in segments:
                if seg[0] <= target <= seg[1]:
                    chosen = seg
                    break

        start, end, place, company = chosen
        return f"Between {start} and {end} I was at {place}, {company}."


def get_provider() -> Provider:
    """Pick a provider from the environment.

    Falling back to scripted rather than raising is deliberate. A missing
    key should degrade the demo, not break the deployment — the first time
    this went live the key was not set and the whole site returned 500s,
    which is a bad way to find out.
    """
    requested = os.environ.get("EIGHTYSIX_PROVIDER", "").strip().lower()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if requested == "local":
        return LocalProvider(os.environ.get("EIGHTYSIX_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"))
    if requested == "scripted":
        return ScriptedProvider()
    if api_key:
        return GeminiProvider(
            api_key, os.environ.get("EIGHTYSIX_MODEL", "gemini-3.6-flash")
        )
    return ScriptedProvider()
