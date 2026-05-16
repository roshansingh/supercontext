from __future__ import annotations

import os
from typing import Any


DEFAULT_LIGHT_MODEL = "gpt-4.1-mini"


class LightLlmClient:
    """Optional helper for later enrichment; the default KG builder does not call it."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("SUPERCONTEXT_LLM_MODEL") or DEFAULT_LIGHT_MODEL

    def respond(self, prompt: str) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for LLM calls")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the openai package to use LLM enrichment") from exc

        client = OpenAI(api_key=api_key)
        response: Any = client.responses.create(model=self.model, input=prompt)
        return str(response.output_text)
