from __future__ import annotations

import logging
import time

from .api_client import AlDenteAPI, APIConfigurationError, APIError
from .cache import TTLCache
from .config import Settings, get_settings
from .evidence import EvidencePack
from .handlers import Context
from .handlers.artifacts_handler import handle_artifact
from .handlers.calls import (
    handle_defect_count,
    handle_latest_complaint,
    handle_price_conflict,
    handle_return_qualification,
)
from .handlers.crm import (
    handle_account_brief,
    handle_customer_lookup,
    handle_negotiation_by_channel,
    handle_open_opportunities,
    handle_opportunity_lookup,
    handle_order_status,
)
from .handlers.erp import (
    handle_bom_chain,
    handle_inventory,
    handle_lot_status,
    handle_margin_trap,
    handle_supplier_materials,
)
from .handlers.generic import handle_generic
from .handlers.kb_handlers import handle_generic_kb, handle_price, handle_product_spec
from .kb import KnowledgeBase
from .llm import LLMClient, grounding_text
from .normalizers import (
    answer_keeps_polarity,
    answer_preserves_tokens,
    answer_within_tokens,
    extract_hard_tokens,
    normalize_text,
)
from .router import FastRoute, classify_fast, needs_llm_classification
from .schemas import AskResponse

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.api_cache: TTLCache[dict] = TTLCache(
            self.settings.cache_ttl_seconds, self.settings.cache_max_entries
        )
        self.answer_cache: TTLCache[AskResponse] = TTLCache(
            self.settings.cache_ttl_seconds, self.settings.cache_max_entries
        )
        self.customer_cache: TTLCache[list[dict]] = TTLCache(
            self.settings.cache_ttl_seconds, 8
        )
        self.graph_cache: TTLCache[dict] = TTLCache(
            self.settings.cache_ttl_seconds, 4
        )
        self.api = AlDenteAPI(self.settings, self.api_cache)
        self.kb = KnowledgeBase()
        self.llm = LLMClient(self.settings)

    def _context(self) -> Context:
        return Context(
            settings=self.settings,
            api=self.api,
            kb=self.kb,
            customer_cache=self.customer_cache,
            deadline=time.monotonic() + self.settings.ask_timeout_seconds,
        )

    def _apply_llm_route(self, question: str, route: FastRoute) -> FastRoute:
        if not needs_llm_classification(question, route) or not self.settings.has_llm:
            return route
        classification = self.llm.classify(question)
        if not classification:
            return route
        hint = classification.get("verticale_hint")
        if hint in {"crm", "erp", "calls", "kb"}:
            route.verticale = hint
        route.classification = classification
        if hint == "kb":
            route.handler = "kb_generic"
            route.confidence = 0.7
        return route

    def _maybe_compose(
        self,
        question: str,
        route: FastRoute,
        evidence: EvidencePack,
        deterministic: str,
        ctx: Context,
    ) -> str:
        """Let the LLM rewrite a confident, fully-grounded answer into natural prose.

        Falls back to the deterministic answer whenever composition is unsafe or
        unavailable: artifacts, low confidence, no LLM configured, the latency
        budget is tight, the model fails/times out, or it drops a hard fact.
        """
        if route.handler == "artifact" or evidence.artifact_url:
            return deterministic
        if "artifact_type" in evidence.facts:
            return deterministic
        if not (evidence.answerable and evidence.confidence >= 0.72):
            return deterministic
        if not self.settings.has_llm:
            return deterministic
        if ctx.remaining() < self.settings.compose_min_remaining_seconds:
            return deterministic
        required = extract_hard_tokens(deterministic)
        allowed = extract_hard_tokens(grounding_text(deterministic, evidence.facts))
        composed = self.llm.compose(question, deterministic, evidence.facts)
        if (
            composed
            and answer_preserves_tokens(composed, required)
            and answer_within_tokens(composed, allowed)
            and answer_keeps_polarity(composed, deterministic)
        ):
            return composed
        return deterministic

    def answer(self, question: str) -> AskResponse:
        normalized = normalize_text(question)
        cache_key = f"ask:{normalized}"
        cached = self.answer_cache.get(cache_key)
        if cached is not None:
            return cached

        route = self._apply_llm_route(question, classify_fast(question))
        ctx = self._context()
        handlers = {
            "artifact": lambda: handle_artifact(question, route, ctx),
            "crm_open_opportunities": lambda: handle_open_opportunities(question, ctx),
            "crm_negotiation_by_channel": lambda: handle_negotiation_by_channel(question, ctx),
            "crm_customer_lookup": lambda: handle_customer_lookup(question, ctx),
            "crm_opportunity_lookup": lambda: handle_opportunity_lookup(question, ctx),
            "crm_order_status": lambda: handle_order_status(question, ctx),
            "erp_shipment_status": lambda: handle_order_status(question, ctx),
            "crm_account_brief": lambda: handle_account_brief(question, ctx),
            "erp_inventory": lambda: handle_inventory(question, ctx),
            "erp_bom_chain": lambda: handle_bom_chain(question, ctx),
            "erp_lot_status": lambda: handle_lot_status(question, ctx),
            "erp_margin_trap": lambda: handle_margin_trap(question, ctx),
            "erp_supplier_materials": lambda: handle_supplier_materials(question, ctx),
            "calls_latest_complaint": lambda: handle_latest_complaint(question, ctx),
            "calls_return_qualification": lambda: handle_return_qualification(question, ctx),
            "calls_defect_count": lambda: handle_defect_count(question, ctx),
            "calls_price_conflict": lambda: handle_price_conflict(question, ctx),
            "kb_product_spec": lambda: handle_product_spec(question, ctx),
            "kb_price": lambda: handle_price(question, ctx),
            "kb_generic": lambda: handle_generic_kb(question, ctx),
            "generic": lambda: handle_generic(question, route, ctx),
        }
        try:
            evidence = handlers.get(route.handler, handlers["generic"])()
        except APIConfigurationError:
            evidence = None
            response = AskResponse(
                answer=(
                    "I could not check the requested company data because MOCK_API_TOKEN "
                    "is not configured. Knowledge-base-only questions remain available."
                ),
                sources=[],
                verticale=route.verticale,
                artifact_url=None,
            )
            return response
        except APIError as exc:
            logger.warning("Data-source error on %s: %s", exc.path, exc)
            response = AskResponse(
                answer=(
                    f"I could not answer reliably because the data source {exc.path} "
                    "returned an error while I checked the provided company data."
                ),
                sources=[exc.path.strip("/")],
                verticale=route.verticale,
                artifact_url=None,
            )
            return response

        if evidence.answerable and evidence.confidence < 0.72:
            answer = (
                "I found partial evidence, but not enough to answer reliably. "
                + (evidence.answer or "Required fields were missing from the checked sources.")
            )
        else:
            deterministic = evidence.answer or (
                "Not available from the checked Al Dente sources."
            )
            answer = self._maybe_compose(question, route, evidence, deterministic, ctx)
        response = AskResponse(
            answer=answer,
            sources=list(dict.fromkeys(evidence.sources)),
            verticale=evidence.verticale,
            artifact_url=evidence.artifact_url,
        )
        self.answer_cache.set(cache_key, response)
        return response
