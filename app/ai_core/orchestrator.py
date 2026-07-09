"""AI Router — the single dispatch point every AI Engine sub-system goes
through, implementing the flow from the master prompt:

    User Request -> Context Builder -> Prompt Generator -> AI Router ->
    Provider Selection Engine -> API Call -> Response Validator ->
    Post Processing -> Return Result

This module is the "AI Router" + "Response Validator" + "Cache Manager" +
"Fallback Manager" boxes from the architecture diagram; Context Builder and
Prompt Manager are separate modules that feed into it. Provider selection
and the actual API calls are delegated to the existing, BYOK-aware
`AIProviderManager` from the Resume module (Part 3) rather than
reimplemented here, so there is exactly one place that owns provider
credentials and fallback order.
"""

import logging
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.cache import AICacheManager, build_cache_key
from app.ai_core.exceptions import AllProvidersExhaustedError
from app.ai_core.models import AICallLog
from app.ai_core.prompts import PromptManager
from app.resume.ai_providers import AIProviderManager, ProviderCallError

logger = logging.getLogger("app.ai_core.orchestrator")


class AIRouter:
    """Every AI Engine call site (job intelligence, matching, cover letter,
    cold email, email analysis, resume analysis) should go through
    `AIRouter.dispatch_json` rather than touching AIProviderManager or
    PromptManager directly, so caching, logging, and fallback stay uniform.
    """

    def __init__(self, session: AsyncSession, user_id: uuid.UUID | None = None):
        self.session = session
        self.user_id = user_id
        self.prompts = PromptManager(session)
        self.providers = AIProviderManager(session, user_id=user_id)
        self.cache = AICacheManager()

    async def dispatch_json(
        self,
        *,
        stage: str,
        prompt_key: str,
        prompt_variables: dict,
        use_cache: bool = True,
        cache_ttl_seconds: int | None = None,
    ) -> dict:
        """Renders the prompt, checks cache, calls the provider chain with
        fallback, validates/post-processes the JSON response, logs the call,
        and returns the parsed result annotated with `_provider_used` and
        `_cache_hit`.
        """
        system_prompt, user_prompt, resolved = await self.prompts.render(prompt_key, **prompt_variables)

        cache_key = build_cache_key(
            user_id=self.user_id,
            stage=stage,
            provider=None,
            prompt_payload={"system": system_prompt, "user": user_prompt, "version": resolved.version},
        )

        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                await self._log_call(stage=stage, provider_used=cached.get("_provider_used"), cache_hit=True, success=True)
                return {**cached, "_cache_hit": True}

        start = time.perf_counter()
        try:
            data, provider = await self.providers.complete_json(system_prompt, user_prompt)
        except ProviderCallError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            await self._log_call(stage=stage, provider_used=None, cache_hit=False, success=False, latency_ms=latency_ms, error=str(exc))
            raise AllProvidersExhaustedError(stage, providers_tried=[]) from exc

        latency_ms = (time.perf_counter() - start) * 1000
        validated = self._validate_response(data, stage=stage)
        validated["_provider_used"] = provider.value
        validated["_cache_hit"] = False

        if use_cache:
            await self.cache.set(cache_key, validated, stage=stage, ttl_seconds=cache_ttl_seconds)

        await self._log_call(stage=stage, provider_used=provider.value, cache_hit=False, success=True, latency_ms=latency_ms)
        return validated

    # ------------------------------------------------------------------

    def _validate_response(self, data: dict, *, stage: str) -> dict:
        """Minimal structural validation: must be a dict. Stage-specific
        engines perform their own deeper field validation on top of this,
        since required shapes differ per prompt category.
        """
        if not isinstance(data, dict):
            logger.warning("ai_response_not_dict", extra={"stage": stage, "type": type(data).__name__})
            return {"_raw": data}
        return data

    async def _log_call(
        self,
        *,
        stage: str,
        provider_used: str | None,
        cache_hit: bool,
        success: bool,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        try:
            self.session.add(
                AICallLog(
                    user_id=self.user_id,
                    stage=stage,
                    provider_used=provider_used,
                    cache_hit=cache_hit,
                    success=success,
                    latency_ms=latency_ms,
                    error_message=error,
                )
            )
            await self.session.flush()
        except Exception:  # noqa: BLE001
            logger.exception("ai_call_log_failed", extra={"stage": stage})
