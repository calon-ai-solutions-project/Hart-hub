"""The one metered AI client. Every AI call in the project goes through `complete_json`."""

import json
import logging
import re

import requests
from django.conf import settings

from .models import AiUsage

logger = logging.getLogger(__name__)


class AiUnavailable(Exception):
    """AI is not configured, or the call failed. Callers fall back to rule-based behaviour."""


def ai_enabled():
    return bool(settings.OPENROUTER_API_KEY and settings.OPENROUTER_MODEL)


def embeddings_enabled():
    return bool(settings.OPENROUTER_API_KEY and settings.OPENROUTER_EMBEDDING_MODEL)


def embed(feature, texts):
    """One vector per text, in order. Logged like every other AI call."""
    if not embeddings_enabled():
        raise AiUnavailable("Embeddings are not configured (OPENROUTER_API_KEY and OPENROUTER_EMBEDDING_MODEL).")
    usage = AiUsage(feature=feature, model=settings.OPENROUTER_EMBEDDING_MODEL, prompt_version="embedding")
    try:
        response = requests.post(
            settings.OPENROUTER_EMBEDDINGS_URL,
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            json={"model": settings.OPENROUTER_EMBEDDING_MODEL, "input": list(texts)},
            timeout=settings.AI_TIMEOUT_SECONDS * 2,
        )
        response.raise_for_status()
        body = response.json()
        counts = body.get("usage") or {}
        usage.input_tokens = counts.get("prompt_tokens") or 0
        usage.cost_usd = counts.get("cost")
        vectors = [row["embedding"] for row in sorted(body["data"], key=lambda row: row["index"])]
        if len(vectors) != len(texts) or any(len(v) != settings.EMBEDDING_DIMENSIONS for v in vectors):
            raise ValueError("The embedding service returned the wrong number or size of vectors.")
        return vectors
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
        usage.ok, usage.error = False, f"{type(e).__name__}: {e}"[:255]
        logger.warning("Embedding call for %s failed: %s", feature, usage.error)
        raise AiUnavailable(usage.error) from e
    finally:
        usage.save()


def _parse_json(text):
    """The model is asked for JSON only, but tolerate a code fence around it."""
    fenced = re.search(r"`{3}(?:json)?\s*(.*?)`{3}", text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


def complete_json(feature, prompt_version, system, user):
    """Send one prompt and return the model's JSON answer. Logs model, prompt version and cost."""
    if not ai_enabled():
        raise AiUnavailable("AI is not configured (OPENROUTER_API_KEY and OPENROUTER_MODEL).")
    usage = AiUsage(feature=feature, model=settings.OPENROUTER_MODEL, prompt_version=prompt_version)
    try:
        request = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": settings.AI_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "usage": {"include": True},
        }
        if settings.AI_REASONING_EFFORT:
            request["reasoning"] = {"effort": settings.AI_REASONING_EFFORT}
        response = requests.post(
            settings.OPENROUTER_URL,
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            json=request,
            timeout=settings.AI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        counts = body.get("usage") or {}
        usage.input_tokens = counts.get("prompt_tokens") or 0
        usage.output_tokens = counts.get("completion_tokens") or 0
        usage.cost_usd = counts.get("cost")
        return _parse_json(body["choices"][0]["message"]["content"])
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
        usage.ok, usage.error = False, f"{type(e).__name__}: {e}"[:255]
        logger.warning("AI call for %s failed: %s", feature, usage.error)
        raise AiUnavailable(usage.error) from e
    finally:
        usage.save()
