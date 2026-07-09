"""AI Provider Manager for the Resume Intelligence System.

Abstracts calls across Groq, OpenAI, Gemini, Claude, and Ollama (local
fallback). Each user may supply their own API key per provider (BYOK,
encrypted at rest); if absent, the platform-level key from Settings is used.
If neither is configured for a provider, that provider is skipped and the
manager falls through to the next one in AI_PROVIDER_PRIORITY.

All AI call sites in this module (parsing refinement, classification,
scoring, rewriting, matching) should go through `AIProviderManager.complete`
rather than calling a provider SDK directly, so retries/fallback/BYOK
resolution stay centralized.

MongoDB migration note: only `_resolve_key`'s BYOK lookup touched the
database (a SQLAlchemy `select` against UserAIProviderKey). That's now a
Motor query via UserAIProviderKeyRepository. Everything else in this file —
provider dispatch, retry/fallback logic, HTTP calls — is unchanged, per the
instruction to preserve this module's behavior exactly.
"""

import json
import logging

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.core.security import decrypt_secret
from app.resume.exceptions import AIProviderUnavailableError
from app.resume.models import AIProviderEnum
from app.resume.repositories import UserAIProviderKeyRepository

logger = logging.getLogger("app.resume.ai_providers")


class ProviderCallError(Exception):
    """Raised when a single provider call fails; caught by the manager to
    trigger fallback to the next provider in priority order.
    """


class AIProviderManager:
    """Resolves credentials and dispatches chat-completion-style calls
    across multiple AI providers with automatic fallback.
    """

    def __init__(self, db: AsyncIOMotorDatabase, user_id: str | None = None):
        self.db = db
        self.user_id = str(user_id) if user_id is not None else None
        self.key_repo = UserAIProviderKeyRepository(db)
        self._key_cache: dict[AIProviderEnum, str | None] = {}

    async def _resolve_key(self, provider: AIProviderEnum) -> str | None:
        """BYOK first (per-user, decrypted), then platform-level fallback."""
        if provider in self._key_cache:
            return self._key_cache[provider]

        key: str | None = None
        if self.user_id is not None:
            row = await self.key_repo.get_by_provider(self.user_id, provider)
            if row and row.is_active and not row.is_deleted:
                try:
                    key = decrypt_secret(row.encrypted_api_key)
                except Exception:  # noqa: BLE001
                    logger.exception("byok_decrypt_failed", extra={"provider": provider.value})

        if not key:
            key = {
                AIProviderEnum.GROQ: settings.GROQ_API_KEY,
                AIProviderEnum.OPENAI: settings.OPENAI_API_KEY,
                AIProviderEnum.GEMINI: settings.GEMINI_API_KEY,
                AIProviderEnum.CLAUDE: settings.ANTHROPIC_API_KEY,
                AIProviderEnum.OLLAMA: "local",  # ollama needs no key, just base URL
            }.get(provider)

        self._key_cache[provider] = key
        return key

    async def _available_providers(self) -> list[AIProviderEnum]:
        ordered = [AIProviderEnum(p) for p in settings.AI_PROVIDER_PRIORITY if p in AIProviderEnum._value2member_map_]
        available = []
        for provider in ordered:
            if await self._resolve_key(provider):
                available.append(provider)
        return available

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(ProviderCallError),
        reraise=True,
    )
    async def _call_provider(
        self, provider: AIProviderEnum, system_prompt: str, user_prompt: str, json_mode: bool
    ) -> str:
        key = await self._resolve_key(provider)
        timeout = httpx.Timeout(settings.AI_REQUEST_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if provider == AIProviderEnum.GROQ:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "response_format": {"type": "json_object"} if json_mode else None,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"]

                elif provider == AIProviderEnum.OPENAI:
                    resp = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={
                            "model": "gpt-4o-mini",
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "response_format": {"type": "json_object"} if json_mode else None,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"]

                elif provider == AIProviderEnum.GEMINI:
                    resp = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}",
                        json={
                            "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

                elif provider == AIProviderEnum.CLAUDE:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": "claude-sonnet-4-6",
                            "max_tokens": 2000,
                            "system": system_prompt,
                            "messages": [{"role": "user", "content": user_prompt}],
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["content"][0]["text"]

                elif provider == AIProviderEnum.OLLAMA:
                    resp = await client.post(
                        f"{settings.OLLAMA_BASE_URL}/api/generate",
                        json={
                            "model": "llama3",
                            "prompt": f"{system_prompt}\n\n{user_prompt}",
                            "stream": False,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["response"]

                raise ProviderCallError(f"Unsupported provider: {provider}")

        except httpx.HTTPStatusError as exc:
            raise ProviderCallError(f"{provider.value} returned {exc.response.status_code}") from exc
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise ProviderCallError(f"{provider.value} call failed: {exc}") from exc

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> tuple[str, AIProviderEnum]:
        """Tries each available provider in priority order until one
        succeeds. Returns (response_text, provider_used).
        Raises AIProviderUnavailableError if all providers fail or none
        are configured.
        """
        providers = await self._available_providers()
        if not providers:
            raise AIProviderUnavailableError(providers_tried=[])

        tried: list[str] = []
        for provider in providers:
            tried.append(provider.value)
            try:
                result = await self._call_provider(provider, system_prompt, user_prompt, json_mode)
                return result, provider
            except ProviderCallError as exc:
                logger.warning("ai_provider_failed", extra={"provider": provider.value, "error": str(exc)})
                continue

        raise AIProviderUnavailableError(providers_tried=tried)

    async def complete_json(self, system_prompt: str, user_prompt: str) -> tuple[dict, AIProviderEnum]:
        """Convenience wrapper that parses the response as JSON, stripping
        markdown code fences if the model wrapped the JSON in them.
        """
        raw, provider = await self.complete(system_prompt, user_prompt, json_mode=True)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned.strip()), provider
        except json.JSONDecodeError as exc:
            logger.error("ai_json_parse_failed", extra={"provider": provider.value, "raw": raw[:500]})
            raise ProviderCallError(f"Failed to parse JSON from {provider.value}: {exc}") from exc
