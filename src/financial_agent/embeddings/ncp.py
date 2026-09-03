"""NCP CLOVA Studio Embedding v2 client with sanitized failures."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
import json
import math
from time import monotonic as system_monotonic
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from financial_agent.embeddings.contracts import (
    EmbeddingContractError,
    EmbeddingResult,
    validate_result,
)


NCP_EMBEDDING_V2_ENDPOINT = (
    "https://clovastudio.stream.ntruss.com/v1/api-tools/embedding/v2/"
)
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class EmbeddingProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PermanentEmbeddingError(EmbeddingProviderError):
    """A request or configuration cannot succeed unchanged."""


class RetryableEmbeddingError(EmbeddingProviderError):
    """The provider operation may succeed when attempted again."""


@dataclass(frozen=True, slots=True)
class EmbeddingHttpRequest:
    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class EmbeddingHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class EmbeddingHttpTransport(Protocol):
    async def post(
        self,
        request: EmbeddingHttpRequest,
    ) -> EmbeddingHttpResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


class UrllibEmbeddingTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    async def post(
        self,
        request: EmbeddingHttpRequest,
    ) -> EmbeddingHttpResponse:
        return await asyncio.to_thread(self._post_sync, request)

    def _post_sync(
        self,
        request: EmbeddingHttpRequest,
    ) -> EmbeddingHttpResponse:
        http_request = Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method="POST",
        )
        try:
            response = self._opener.open(
                http_request,
                timeout=request.timeout_seconds,
            )
        except HTTPError as error:
            body = error.read(_MAX_RESPONSE_BYTES + 1)
            return EmbeddingHttpResponse(
                status=error.code,
                headers=dict(error.headers.items()),
                body=body[:_MAX_RESPONSE_BYTES],
            )
        except (URLError, TimeoutError, OSError):
            raise RetryableEmbeddingError("transport_unavailable") from None

        with closing(response):
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise PermanentEmbeddingError("response_too_large")
            return EmbeddingHttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=body,
            )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return value
    return None


def _retry_after_seconds(
    response: EmbeddingHttpResponse | None,
    attempt: int,
) -> float:
    if response is not None:
        raw_value = _header(response.headers, "Retry-After")
        if raw_value is not None:
            try:
                return min(max(float(raw_value), 0.0), 60.0)
            except ValueError:
                pass
    return float(min(2 ** (attempt - 1), 8))


class NcpEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: EmbeddingHttpTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = system_monotonic,
        minimum_interval_seconds: float = 0.0,
        max_attempts: int = 4,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise PermanentEmbeddingError("api_key_blank")
        if (
            isinstance(minimum_interval_seconds, bool)
            or not isinstance(minimum_interval_seconds, (int, float))
            or not math.isfinite(minimum_interval_seconds)
            or minimum_interval_seconds < 0
        ):
            raise PermanentEmbeddingError("minimum_interval_invalid")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise PermanentEmbeddingError("max_attempts_invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise PermanentEmbeddingError("timeout_invalid")
        self._api_key = api_key.strip()
        self._transport = transport or UrllibEmbeddingTransport()
        self._sleep = sleep
        self._monotonic = monotonic
        self._minimum_interval_seconds = float(minimum_interval_seconds)
        self._last_request_started_at: float | None = None
        self._max_attempts = max_attempts
        self._timeout_seconds = float(timeout_seconds)

    async def embed(self, text: str) -> EmbeddingResult:
        if not isinstance(text, str) or not text.strip():
            raise PermanentEmbeddingError("input_text_blank")
        body = json.dumps(
            {"text": text},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        retries = 0
        for attempt in range(1, self._max_attempts + 1):
            await self._pace_request()
            request = EmbeddingHttpRequest(
                url=NCP_EMBEDDING_V2_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid4()),
                    "Content-Type": "application/json",
                },
                body=body,
                timeout_seconds=self._timeout_seconds,
            )
            try:
                response = await self._transport.post(request)
            except RetryableEmbeddingError:
                if attempt == self._max_attempts:
                    raise RetryableEmbeddingError("retry_exhausted") from None
                await self._sleep(_retry_after_seconds(None, attempt))
                retries += 1
                continue

            if response.status == 429 or 500 <= response.status <= 599:
                if attempt == self._max_attempts:
                    raise RetryableEmbeddingError("retry_exhausted")
                await self._sleep(_retry_after_seconds(response, attempt))
                retries += 1
                continue
            if response.status < 200 or response.status >= 300:
                raise PermanentEmbeddingError("provider_http_permanent")
            return self._parse_response(response, retries)
        raise RetryableEmbeddingError("retry_exhausted")

    async def _pace_request(self) -> None:
        now = self._monotonic()
        if self._last_request_started_at is not None:
            remaining = (
                self._minimum_interval_seconds
                - (now - self._last_request_started_at)
            )
            if remaining > 0:
                await self._sleep(remaining)
                now = self._monotonic()
        self._last_request_started_at = now

    @staticmethod
    def _parse_response(
        response: EmbeddingHttpResponse,
        retries: int,
    ) -> EmbeddingResult:
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PermanentEmbeddingError("response_json_invalid") from None
        if not isinstance(payload, dict):
            raise PermanentEmbeddingError("response_shape_invalid")
        status = payload.get("status")
        result = payload.get("result")
        if not isinstance(status, dict) or not isinstance(result, dict):
            raise PermanentEmbeddingError("response_shape_invalid")
        if status.get("code") != "20000":
            raise PermanentEmbeddingError("provider_status_error")
        vector = result.get("embedding")
        input_tokens = result.get("inputTokens")
        if not isinstance(vector, list):
            raise PermanentEmbeddingError("response_shape_invalid")
        if len(vector) != 1024:
            raise PermanentEmbeddingError("response_dimension")
        embedding_result = EmbeddingResult(
            vector=tuple(vector),
            input_tokens=input_tokens,
            request_id=_header(
                response.headers,
                "X-NCP-CLOVASTUDIO-REQUEST-ID",
            ),
            retry_count=retries,
        )
        try:
            return validate_result(embedding_result)
        except EmbeddingContractError as error:
            raise PermanentEmbeddingError(error.args[0]) from None
