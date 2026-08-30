from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
import urllib.request

from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery


_SPARQL_RESULTS_JSON = "application/sparql-results+json"


@dataclass(frozen=True, slots=True)
class GraphQueryResult:
    query_id: str
    dataset_version: str
    coverage_status: str
    bindings: tuple[Mapping[str, str], ...]


class GraphQueryError(ValueError):
    pass


def _validate_select(sparql: str) -> None:
    try:
        operation = translateQuery(parseQuery(sparql)).algebra
    except Exception as error:
        raise GraphQueryError("invalid_select_query") from error
    if operation.name != "SelectQuery":
        raise GraphQueryError("non_select_query")


def _normalize_bindings(payload: object) -> tuple[Mapping[str, str], ...]:
    if not isinstance(payload, dict):
        raise GraphQueryError("malformed_result")
    head = payload.get("head")
    results = payload.get("results")
    if not isinstance(head, dict) or not isinstance(results, dict):
        raise GraphQueryError("malformed_result")
    variables = head.get("vars")
    bindings = results.get("bindings")
    if (
        not isinstance(variables, list)
        or not all(isinstance(variable, str) for variable in variables)
        or len(variables) != len(set(variables))
        or not isinstance(bindings, list)
    ):
        raise GraphQueryError("malformed_result")

    normalized: list[Mapping[str, str]] = []
    variable_names = set(variables)
    for row in bindings:
        if not isinstance(row, dict) or not set(row) <= variable_names:
            raise GraphQueryError("malformed_result")
        result: dict[str, str] = {}
        for variable, binding in row.items():
            if (
                not isinstance(variable, str)
                or not isinstance(binding, dict)
                or not isinstance(binding.get("type"), str)
                or not isinstance(binding.get("value"), str)
            ):
                raise GraphQueryError("malformed_result")
            result[variable] = binding["value"]
        normalized.append(MappingProxyType(result))

    return tuple(sorted(normalized, key=lambda row: tuple(sorted(row.items()))))


class FusekiGraphClient:
    def __init__(self, query_endpoint: str, timeout_seconds: float = 5.0) -> None:
        self._query_endpoint = query_endpoint
        self._timeout_seconds = timeout_seconds

    def select(
        self,
        *,
        query_id: str,
        sparql: str,
        dataset_version: str,
        coverage_status: str,
    ) -> GraphQueryResult:
        _validate_select(sparql)
        request = urllib.request.Request(
            self._query_endpoint,
            data=urlencode({"query": sparql}).encode("utf-8"),
            headers={
                "Accept": _SPARQL_RESULTS_JSON,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError) as error:
            raise GraphQueryError("request_failed") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GraphQueryError("malformed_result") from error

        return GraphQueryResult(
            query_id=query_id,
            dataset_version=dataset_version,
            coverage_status=coverage_status,
            bindings=_normalize_bindings(payload),
        )
