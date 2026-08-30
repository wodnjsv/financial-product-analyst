from __future__ import annotations

from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

import pytest

from financial_agent.graph.client import FusekiGraphClient, GraphQueryError


SELECT_QUERY = "# accepted comment\nPREFIX ex: <urn:example:>\nSELECT ?item WHERE { ?item ?p ?o }"


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _results_json(bindings: list[dict[str, object]]) -> bytes:
    import json

    return json.dumps(
        {"head": {"vars": ["item", "optional"]}, "results": {"bindings": bindings}}
    ).encode()


def test_select_posts_a_parsed_select_and_normalizes_sorted_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a non-POST request, wrong wire format, or unstable result ordering."""
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, *, timeout: float) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            _results_json(
                [
                    {"item": {"type": "literal", "value": "z"}},
                    {
                        "item": {"type": "literal", "value": "a"},
                        "optional": {"type": "literal", "value": "bound"},
                    },
                ]
            )
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = FusekiGraphClient("http://graph.test/query", timeout_seconds=2.5).select(
        query_id="query-1",
        sparql=SELECT_QUERY,
        dataset_version="2026-08-24/v1",
        coverage_status="covered",
    )

    request = captured["request"]
    assert request.full_url == "http://graph.test/query"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert request.get_header("Accept") == "application/sparql-results+json"
    assert parse_qs(request.data.decode()) == {"query": [SELECT_QUERY]}
    assert captured["timeout"] == 2.5
    assert result.query_id == "query-1"
    assert result.dataset_version == "2026-08-24/v1"
    assert result.coverage_status == "covered"
    assert result.bindings == (
        {"item": "a", "optional": "bound"},
        {"item": "z"},
    )


def test_select_preserves_caller_metadata_for_an_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches turning zero graph rows into an unsupported absence claim."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, *, timeout: _Response(_results_json([])),
    )

    result = FusekiGraphClient("http://graph.test/query").select(
        query_id="empty-query",
        sparql="SELECT * WHERE { ?s ?p ?o }",
        dataset_version="dataset-version",
        coverage_status="coverage-unknown",
    )

    assert result.query_id == "empty-query"
    assert result.dataset_version == "dataset-version"
    assert result.coverage_status == "coverage-unknown"
    assert result.bindings == ()


@pytest.mark.parametrize(
    "sparql",
    (
        "ASK { ?s ?p ?o }",
        "INSERT DATA { <urn:s> <urn:p> <urn:o> }",
        "SELECT * WHERE { ?s ?p ?o }; SELECT * WHERE { ?s ?p ?o }",
        "SELECT WHERE { ?s ?p ?o }",
    ),
)
def test_select_rejects_non_select_or_malformed_sparql_before_http(
    monkeypatch: pytest.MonkeyPatch,
    sparql: str,
) -> None:
    """Catches update, multi-operation, or malformed input reaching Fuseki."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: pytest.fail("invalid SPARQL reached HTTP"),
    )

    with pytest.raises(GraphQueryError, match="select"):
        FusekiGraphClient("http://graph.test/query").select(
            query_id="invalid-query",
            sparql=sparql,
            dataset_version="dataset-version",
            coverage_status="covered",
        )


def test_select_wraps_http_and_transport_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches leaking urllib exceptions through the read-only boundary."""
    failures = (
        HTTPError("http://graph.test/query", 500, "server error", Message(), BytesIO()),
        URLError("connection refused"),
    )
    for failure in failures:
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *args, failure=failure, **kwargs: (_ for _ in ()).throw(failure),
        )
        with pytest.raises(GraphQueryError, match="request_failed"):
            FusekiGraphClient("http://graph.test/query").select(
                query_id="failure-query",
                sparql="SELECT * WHERE { ?s ?p ?o }",
                dataset_version="dataset-version",
                coverage_status="covered",
            )


@pytest.mark.parametrize(
    "body",
    (
        b"not json",
        b'{"head": {"vars": ["item"]}}',
        b'{"head": {"vars": ["item"]}, "results": {"bindings": [{"item": {"value": 3}}]}}',
    ),
)
def test_select_rejects_malformed_sparql_results_json(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    """Catches incomplete or malformed SPARQL Results JSON being treated as data."""
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, *, timeout: _Response(body)
    )

    with pytest.raises(GraphQueryError, match="malformed_result"):
        FusekiGraphClient("http://graph.test/query").select(
            query_id="malformed-result",
            sparql="SELECT * WHERE { ?s ?p ?o }",
            dataset_version="dataset-version",
            coverage_status="covered",
        )
