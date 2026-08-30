from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
import urllib.request

from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery


_SPARQL_RESULTS_JSON = "application/sparql-results+json"
_BINDING_TYPES = frozenset({"uri", "bnode", "literal", "typed-literal"})


@dataclass(frozen=True, slots=True)
class GraphQueryResult:
    query_id: str
    dataset_version: str
    coverage_status: str
    bindings: tuple[Mapping[str, str], ...]


class GraphQueryError(ValueError):
    pass


def _select_projection(sparql: str) -> tuple[str, ...]:
    try:
        operation = translateQuery(parseQuery(sparql)).algebra
    except Exception as error:
        raise GraphQueryError("invalid_select_query") from error
    if operation.name != "SelectQuery":
        raise GraphQueryError("non_select_query")
    return tuple(str(variable) for variable in operation["PV"])


def _validate_endpoint(query_endpoint: str) -> None:
    try:
        endpoint = urlsplit(query_endpoint)
        endpoint.port
    except (TypeError, ValueError) as error:
        raise GraphQueryError("invalid_endpoint") from error
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.fragment
        or any(character.isspace() for character in query_endpoint)
    ):
        raise GraphQueryError("invalid_endpoint")


def _binding_value(binding: object) -> str:
    if not isinstance(binding, dict):
        raise GraphQueryError("malformed_result")
    binding_type = binding.get("type")
    value = binding.get("value")
    if binding_type not in _BINDING_TYPES or not isinstance(value, str):
        raise GraphQueryError("malformed_result")
    keys = set(binding)
    if binding_type in {"uri", "bnode"}:
        if keys != {"type", "value"}:
            raise GraphQueryError("malformed_result")
    elif binding_type == "typed-literal":
        if keys != {"type", "value", "datatype"} or not isinstance(
            binding.get("datatype"), str
        ):
            raise GraphQueryError("malformed_result")
    elif (
        not {"type", "value"} <= keys <= {"type", "value", "datatype", "xml:lang"}
        or ("datatype" in keys and "xml:lang" in keys)
        or any(not isinstance(binding[key], str) for key in keys - {"type", "value"})
    ):
        raise GraphQueryError("malformed_result")
    return value


def _normalize_bindings(
    payload: object,
    expected_variables: tuple[str, ...],
) -> tuple[Mapping[str, str], ...]:
    if not isinstance(payload, dict) or set(payload) != {"head", "results"}:
        raise GraphQueryError("malformed_result")
    head = payload.get("head")
    results = payload.get("results")
    if (
        not isinstance(head, dict)
        or set(head) != {"vars"}
        or not isinstance(results, dict)
        or set(results) != {"bindings"}
    ):
        raise GraphQueryError("malformed_result")
    variables = head.get("vars")
    bindings = results.get("bindings")
    if (
        not isinstance(variables, list)
        or tuple(variables) != expected_variables
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
            if not isinstance(variable, str):
                raise GraphQueryError("malformed_result")
            result[variable] = _binding_value(binding)
        normalized.append(MappingProxyType(result))

    return tuple(sorted(normalized, key=lambda row: tuple(sorted(row.items()))))


class FusekiGraphClient:
    def __init__(self, query_endpoint: str, timeout_seconds: float = 5.0) -> None:
        _validate_endpoint(query_endpoint)
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
        expected_variables = _select_projection(sparql)
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
            bindings=_normalize_bindings(payload, expected_variables),
        )
