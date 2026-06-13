from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from openai import OpenAI

from .config import Settings, get_settings

CLASSIFIER_PROMPT = """You classify questions for an Al Dente internal company brain.
Return JSON only. Do not answer the user.
Sources available: crm, erp, calls, kb.
Extract IDs, customer names, SKUs, lots, calls, document IDs, requested artifact type,
and likely intent. If uncertain, use null or empty arrays. Never invent entities."""


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: OpenAI | None = None
        if self.settings.has_llm:
            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=1,
            )

    @staticmethod
    def _response_text(response: Any) -> str:
        message = response.choices[0].message
        content = message.content or ""
        if not content:
            content = getattr(message, "reasoning_content", "") or ""
        content = content.strip()
        if not content:
            raise ValueError("LLM returned no content or reasoning_content.")
        return content

    def classify(self, question: str) -> dict[str, Any]:
        if not self._client or not self.settings.model:
            return {}
        try:
            response = self._client.chat.completions.create(
                model=self.settings.model,
                temperature=0,
                max_tokens=500,
                messages=[
                    {"role": "system", "content": CLASSIFIER_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n"
                            'Schema: {"intent":"lookup|aggregate|multi_source|artifact|trap_or_unknown",'
                            '"verticale_hint":"crm|erp|calls|kb|null","entities":{'
                            '"customer_names":[],"customer_ids":[],"skus":[],"lot_ids":[],'
                            '"order_ids":[],"call_ids":[],"doc_ids":[]},"artifact_type":'
                            '"html|pdf|xlsx|docx|pptx|null","needs":[]}'
                        ),
                    },
                ],
            )
            content = self._response_text(response)
            match = re.search(r"\{.*\}", content, re.S)
            return json.loads(match.group(0)) if match else {}
        except Exception:
            return {}

    def _complete(self, system: str, prompt: str, max_tokens: int = 700) -> str:
        if not self._client or not self.settings.model:
            return ""
        try:
            response = self._client.chat.completions.create(
                model=self.settings.model,
                temperature=0,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            return self._response_text(response)
        except Exception:
            return ""

    def final_answer(self, question: str, evidence: Any) -> str:
        payload = asdict(evidence) if hasattr(evidence, "__dataclass_fields__") else evidence
        return self._complete(
            (
                "Write a concise English answer using only the evidence JSON. "
                "Do not add facts, estimates, or outside knowledge. Preserve every ID "
                "and number exactly. If evidence is insufficient, explain what is missing."
            ),
            f"Question: {question}\nEvidence: {json.dumps(payload, default=str)}",
        )

    def generate_artifact_html(self, question: str, evidence: Any) -> str:
        payload = asdict(evidence) if hasattr(evidence, "__dataclass_fields__") else evidence
        return self._complete(
            (
                "Create polished client-ready HTML using only the evidence JSON. "
                "Use dark espresso, semolina gold, tomato accents, and a clean executive "
                "layout. Do not invent facts. Return HTML only."
            ),
            f"Request: {question}\nEvidence: {json.dumps(payload, default=str)}",
            max_tokens=1400,
        )
