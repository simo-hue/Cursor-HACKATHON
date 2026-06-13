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

COMPOSE_PROMPT = (
    "You rewrite a verified internal answer for Al Dente S.r.l. into clear, natural prose. "
    "Use ONLY the verified answer and the evidence provided; never add, infer, or estimate "
    "any fact. Preserve every ID, code, date, currency figure and number exactly as given. "
    "Never change the verdict: keep yes/no, below/above and late/on-time exactly as stated, "
    "and never add or remove a negation. "
    "Reply in the same language as the question, in 1-4 concise sentences of plain text - "
    "no markdown, no headings, no bullet lists. Output only the answer text."
)

FACTS_LIST_CAP = 8
FACTS_JSON_CAP = 4000
QUESTION_CAP = 2000


def _curate_facts(facts: Any) -> dict[str, Any]:
    """Trim the evidence facts into a compact payload for the prompt.

    Drops the redundant deterministic 'answer' (passed separately as the anchor)
    and caps large record lists so prompts stay short and cheap.
    """
    if not isinstance(facts, dict):
        return {}
    curated: dict[str, Any] = {}
    for key, value in facts.items():
        if key == "answer":
            continue
        if isinstance(value, list):
            trimmed = list(value[:FACTS_LIST_CAP])
            if len(value) > FACTS_LIST_CAP:
                trimmed.append(f"... (+{len(value) - FACTS_LIST_CAP} more)")
            curated[key] = trimmed
        else:
            curated[key] = value
    return curated


def _curated_json(facts: Any) -> str:
    return json.dumps(_curate_facts(facts), default=str)[:FACTS_JSON_CAP]


def grounding_text(anchor: str, facts: Any) -> str:
    """Exact factual material the model is allowed to draw on.

    Used both to build the prompt and (by the orchestrator) to compute the set of
    hard tokens a composed answer may legitimately contain.
    """
    return f"{anchor}\n{_curated_json(facts)}"


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
                            f"Question: {question[:QUESTION_CAP]}\n"
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

    def compose(self, question: str, anchor: str, facts: Any) -> str:
        """Rewrite a verified deterministic answer into natural prose.

        Returns an empty string on any failure, empty response, or timeout so the
        caller can fall back to the deterministic answer. All policy (when to call,
        token validation) lives in the orchestrator.
        """
        if not self._client or not self.settings.model:
            return ""
        prompt = (
            f"Question: {question[:QUESTION_CAP]}\n"
            f"Verified answer: {anchor}\n"
            f"Evidence: {_curated_json(facts)}"
        )
        try:
            response = self._client.with_options(
                timeout=self.settings.compose_timeout_seconds,
                max_retries=0,
            ).chat.completions.create(
                model=self.settings.model,
                temperature=0,
                max_tokens=400,
                messages=[
                    {"role": "system", "content": COMPOSE_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return self._response_text(response)
        except Exception:
            return ""

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
