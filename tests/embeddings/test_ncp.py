from __future__ import annotations

from collections.abc import Awaitable, Callable
import json

import pytest

from financial_agent.embeddings.ncp import (
    NCP_EMBEDDING_V2_ENDPOINT,
    EmbeddingHttpRequest,
    EmbeddingHttpResponse,
    NcpEmbeddingClient,
    PermanentEmbeddingError,
    RetryableEmbeddingError,
)


class ScriptedTransport:
    def __init__(
        self,
        *responses: EmbeddingHttpResponse | Exception,
    ) -> None:
        self._responses = iter(responses)
        self.requests: list[EmbeddingHttpRequest] = []

    async def post(
        self,
        request: EmbeddingHttpRequest,
    ) -> EmbeddingHttpResponse:
        self.requests.append(request)
        result = next(self._responses)
        if isinstance(result, Exception):
            raise result
        return result


def _success_response(
    *,
    dimension: int = 1024,
    input_tokens: object = 3,
    status_code: str = "20000",
) -> EmbeddingHttpResponse:
    return EmbeddingHttpResponse(
        status=200,
        headers={"X-NCP-CLOVASTUDIO-REQUEST-ID": "request-1"},
        body=json.dumps(
            {
                "status": {"code": status_code, "message": "OK"},
                "result": {
                    "embedding": [0.25] * dimension,
                    "inputTokens": input_tokens,
                },
            }
        ).encode(),
    )


def _recording_sleep() -> tuple[
    list[float],
    Callable[[float], Awaitable[None]],
]:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    return delays, sleep


@pytest.mark.asyncio
async def test_client_sends_exact_v2_request_and_returns_validated_result() -> None:
    transport = ScriptedTransport(_success_response(input_tokens=17))
    client = NcpEmbeddingClient("secret-value", transport=transport)

    result = await client.embed("공식 문서 본문")

    request = transport.requests[0]
    assert request.url == NCP_EMBEDDING_V2_ENDPOINT
    assert request.headers["Authorization"] == "Bearer secret-value"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["X-NCP-CLOVASTUDIO-REQUEST-ID"]
    assert json.loads(request.body) == {"text": "공식 문서 본문"}
    assert request.timeout_seconds == 30.0
    assert len(result.vector) == 1024
    assert result.input_tokens == 17
    assert result.request_id == "request-1"
    assert result.retry_count == 0


@pytest.mark.asyncio
async def test_client_retries_429_using_bounded_retry_after() -> None:
    transport = ScriptedTransport(
        EmbeddingHttpResponse(429, {"Retry-After": "1000"}, b"rate limited"),
        _success_response(),
    )
    delays, sleep = _recording_sleep()

    result = await NcpEmbeddingClient(
        "private-key",
        transport=transport,
        sleep=sleep,
    ).embed("공식 문서")

    assert result.retry_count == 1
    assert delays == [60.0]
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_client_retries_transport_failure_then_succeeds() -> None:
    transport = ScriptedTransport(
        RetryableEmbeddingError("transport_unavailable"),
        _success_response(),
    )
    delays, sleep = _recording_sleep()

    result = await NcpEmbeddingClient(
        "private-key",
        transport=transport,
        sleep=sleep,
    ).embed("공식 문서")

    assert result.retry_count == 1
    assert delays == [1.0]


@pytest.mark.asyncio
async def test_client_stops_after_four_retryable_failures() -> None:
    transport = ScriptedTransport(
        *(RetryableEmbeddingError("transport_unavailable") for _ in range(4))
    )
    delays, sleep = _recording_sleep()

    with pytest.raises(RetryableEmbeddingError, match="retry_exhausted"):
        await NcpEmbeddingClient(
            "private-key",
            transport=transport,
            sleep=sleep,
        ).embed("공식 문서")

    assert len(transport.requests) == 4
    assert delays == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_client_does_not_retry_permanent_http_failure_or_leak_body() -> None:
    secret = "private-key"
    transport = ScriptedTransport(
        EmbeddingHttpResponse(
            401,
            {},
            f"invalid Authorization: Bearer {secret}".encode(),
        )
    )

    with pytest.raises(PermanentEmbeddingError) as raised:
        await NcpEmbeddingClient(secret, transport=transport).embed("공식 문서")

    assert raised.value.code == "provider_http_permanent"
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    (
        (EmbeddingHttpResponse(200, {}, b"not-json"), "response_json_invalid"),
        (
            EmbeddingHttpResponse(200, {}, b'{"status":{"code":"20000"}}'),
            "response_shape_invalid",
        ),
        (_success_response(dimension=1), "response_dimension"),
        (_success_response(input_tokens=0), "input_tokens_invalid"),
        (_success_response(status_code="50000"), "provider_status_error"),
    ),
)
async def test_client_rejects_malformed_success_without_retry(
    response: EmbeddingHttpResponse,
    code: str,
) -> None:
    transport = ScriptedTransport(response)

    with pytest.raises(PermanentEmbeddingError) as raised:
        await NcpEmbeddingClient("secret", transport=transport).embed("text")

    assert raised.value.code == code
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_client_rejects_blank_input_before_transport() -> None:
    transport = ScriptedTransport(_success_response())

    with pytest.raises(PermanentEmbeddingError, match="input_text_blank"):
        await NcpEmbeddingClient("secret", transport=transport).embed(" \n ")

    assert transport.requests == []


def test_client_rejects_blank_api_key() -> None:
    with pytest.raises(PermanentEmbeddingError, match="api_key_blank"):
        NcpEmbeddingClient("  ")
