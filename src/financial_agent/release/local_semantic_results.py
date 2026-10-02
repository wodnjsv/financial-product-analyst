"""Validate personal SQL facts against their immutable observation lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Mapping, Sequence
from types import MappingProxyType

from pydantic import TypeAdapter

from financial_agent.contracts.execution import Exclusion, ResultRow
from financial_agent.contracts.values import ScalarValue, decode_contract_value
from financial_agent.planning.physical_bindings import PhysicalBindingDefinition
from financial_agent.intent.query_contracts import RelationConditionV2


class LocalSemanticResultError(ValueError):
    code = 'LOCAL_RESULT_EVIDENCE_INVALID'


@dataclass(frozen=True, slots=True)
class VerifiedSemanticRow:
    row: ResultRow
    facts: tuple[Mapping[str, object], ...]
    missing_fields: tuple[tuple[str, str], ...] = ()


_SCALAR = TypeAdapter(ScalarValue)
_LABELS = {
    'fee_rate': '총보수', 'aum': '순자산', 'maturity_date': '만기일',
    'trailing_1y_historical_cumulative_return': '과거 1년 누적수익률',
}


def validate_semantic_rows(
    rows: Sequence[ResultRow], facts: Sequence[Mapping[str, object]],
    evidence_refs: Sequence[str], bindings: Sequence[PhysicalBindingDefinition],
    dataset_version: str, cutoff_date: date,
    *, relation_conditions: Sequence[RelationConditionV2] = (), as_of_date: date | None = None,
    exclusions: Sequence[Exclusion] = (),
) -> tuple[VerifiedSemanticRow, ...]:
    """Missing or altered facts never become text, even with plausible values."""
    refs = set(evidence_refs)
    by_concept = {binding.semantic_concept_id: binding for binding in bindings}
    by_product = {}
    for item in facts:
        by_product.setdefault(item['subject_id'], []).append(item)
    verified = []
    for row in rows:
        if len(row.entity_ids) != 1:
            raise LocalSemanticResultError()
        product_id = row.entity_ids[0]
        names = [decode_contract_value(f.value) for f in row.fields if f.field_id == 'product_name']
        if len(names) != 1:
            raise LocalSemanticResultError()
        product_facts = by_product.get(product_id, [])
        if not product_facts or any(item['canonical_name'] != names[0] for item in product_facts):
            raise LocalSemanticResultError()
        supports = []
        for condition in relation_conditions:
            candidates = [item for item in product_facts
                          if item['evidence_kind'] == 'relation'
                          and item['relation_predicate_id'] == condition.relation_id
                          and item['relation_object_id'] == condition.object_entity_id]
            if not candidates:
                raise LocalSemanticResultError()
            for item in candidates:
                _validate_relation_fact(item, refs, condition, product_id, dataset_version, cutoff_date, as_of_date)
                supports.append(item)
        for field in row.fields:
            if field.field_id == 'product_name':
                continue
            binding = by_concept.get(field.field_id)
            if binding is None:
                raise LocalSemanticResultError()
            candidates = [item for item in product_facts
                          if item['metric_id'] in binding.approved_metric_ids]
            if not candidates:
                raise LocalSemanticResultError()
            for item in candidates:
                _validate_fact(item, refs, binding, field, product_id, dataset_version, cutoff_date)
                supports.append(item)
        missing_fields = []
        visible_fields = {field.field_id for field in row.fields}
        for concept_id, binding in by_concept.items():
            if concept_id in visible_fields:
                continue
            if not any(item.subject_id == product_id and item.rule_id == 'exclude_missing.v1'
                       and item.reason_code == 'SOURCE_VALUE_MISSING' for item in exclusions):
                raise LocalSemanticResultError()
            candidates = [item for item in product_facts
                          if item['metric_id'] in binding.approved_metric_ids]
            if not candidates:
                raise LocalSemanticResultError()
            for item in candidates:
                _validate_fact(item, refs, binding, None, product_id, dataset_version, cutoff_date)
                supports.append(item)
            missing_fields.append((concept_id, 'SOURCE_VALUE_MISSING'))
        if len(row.fields) == 1 and not supports:
            raise LocalSemanticResultError()
        verified.append(VerifiedSemanticRow(
            row, tuple(MappingProxyType(dict(item)) for item in supports), tuple(missing_fields),
        ))
    return tuple(verified)


def _validate_fact(item, refs, binding, field, product_id, dataset_version, cutoff):
    definition = f"{item['metric_id']}:{item['metric_definition_version']}"
    required = {
        f"evidence:{item['evidence_id']}", f"source:{item['source_id']}",
        f"observation:{item['observation_id']}", f"metric-definition:{definition}",
    }
    missing = field is None
    value = None if missing else decode_contract_value(field.value)
    field_unit = item['observation_unit'] if missing else field.unit_id
    field_currency = item['observation_currency'] if missing else field.currency
    field_date = item['observation_date'] if missing else field.applicable_date
    storage_value = item['date_value'] if binding.semantic_value_kind.value == 'date' else item['numeric_value']
    try:
        normalized = decode_contract_value(_SCALAR.validate_json(json.dumps(item['normalized_value'])))
    except (ValueError, TypeError):
        raise LocalSemanticResultError() from None
    # Maturity is itself a future date; it must not masquerade as a source date.
    maturity = binding.semantic_concept_id == 'maturity_date'
    evidence_date = None if maturity and value is not None and value > cutoff else field_date
    if (
        item['dataset_version'] != dataset_version
        or item['evidence_kind'] != 'observation'
        or item['entity_id'] != product_id
        or item['subject_id'] != product_id
        or item['predicate_id'] != item['metric_id']
        or definition not in binding.approved_metric_definition_refs
        or not required <= refs
        or item['value_status'] not in (('missing',) if missing else ('present', 'zero'))
        or not missing and value is None
        or storage_value != value or normalized != value
        or item['unit'] != field_unit or item['observation_unit'] != field_unit
        or field_unit != binding.storage_unit_id
        or item['currency'] != field_currency or item['observation_currency'] != field_currency
        or item['observation_date'] != field_date
        or item['applicable_date'] != evidence_date
        or item['cutoff_status'] != 'eligible'
        or item['eligible_for_claim'] is not True
        or not isinstance(item['source_title'], str) or not item['source_title'].strip()
        or item['source_locator_root'] != item['locator_uri_or_object_key']
        or not item['locator_uri_or_object_key'] or not item['locator_sheet']
        or not item['locator_row'] or not item['locator_column']
    ):
        raise LocalSemanticResultError()

    for key in ('vintage_date', 'published_at', 'available_at'):
        actual = item[key]
        if isinstance(actual, datetime):
            actual = actual.date()
        if actual is not None and actual > cutoff:
            raise LocalSemanticResultError()
    if (not maturity or missing) and field_date is not None and field_date > cutoff:
        raise LocalSemanticResultError()
    for key in ('period_start', 'period_end'):
        if item[key] is not None and item[key] > cutoff:
            raise LocalSemanticResultError()
    if binding.semantic_concept_id == 'trailing_1y_historical_cumulative_return' and (
        item['period_end'] != field_date
        or item['period_start'] is not None and item['period_start'] > item['period_end']
    ):
        raise LocalSemanticResultError()


def _validate_relation_fact(item, refs, condition, product_id, dataset_version, cutoff, as_of):
    required = {f"relation:{item['relation_id']}", f"evidence:{item['evidence_id']}", f"source:{item['source_id']}"}
    try:
        target = decode_contract_value(_SCALAR.validate_json(json.dumps(item['value_or_object_id'])))
    except (ValueError, TypeError):
        raise LocalSemanticResultError() from None
    reference_date = as_of or cutoff
    if (
        item['dataset_version'] != dataset_version or item['subject_id'] != product_id
        or item['relation_subject_id'] != product_id
        or item['predicate_id'] != condition.relation_id
        or target != condition.object_entity_id or not required <= refs
        or item['cutoff_status'] != 'eligible' or item['eligible_for_claim'] is not True
        or not item['source_title'] or item['source_locator_root'] != item['locator_uri_or_object_key']
        or not item['relation_object_name']
        or item['relation_valid_from'] is not None and item['relation_valid_from'] > reference_date
        or item['relation_valid_to'] is not None and item['relation_valid_to'] < reference_date
        or condition.relation_id == 'holdsSecurity' and as_of is None
    ):
        raise LocalSemanticResultError()
    for key in ('vintage_date', 'published_at', 'available_at', 'applicable_date'):
        actual = item[key]
        if isinstance(actual, datetime):
            actual = actual.date()
        if actual is not None and actual > cutoff:
            raise LocalSemanticResultError()


def render_semantic_rows(
    rows: Sequence[VerifiedSemanticRow], *, total_count: int, display_limit: int,
    ranked: bool,
) -> str:
    if not 1 <= display_limit <= 50 or total_count != len(rows):
        raise LocalSemanticResultError()
    displayed = rows[:display_limit]
    count_label = '상위 결과' if ranked else '전체 일치'
    lines = [f'{count_label} {total_count}건 · 표시 {len(displayed)}건']
    for index, verified in enumerate(displayed, 1):
        row = verified.row
        name = next(decode_contract_value(f.value) for f in row.fields if f.field_id == 'product_name')
        lines.append(f'{index}. {_line(name)} [상품 ID: {row.entity_ids[0]}]')
        for field in row.fields:
            if field.field_id == 'product_name':
                continue
            value = decode_contract_value(field.value)
            value_text = format(value, 'f') if isinstance(value, Decimal) else str(value)
            if isinstance(value, Decimal) and '.' in value_text:
                value_text = value_text.rstrip('0').rstrip('.')
            suffix = '%' if field.unit_id == 'percentage_point' else (f' {field.unit_id}' if field.unit_id else '')
            if field.currency:
                suffix += f' {field.currency}'
            basis = '' if field.field_id == 'maturity_date' else f" · 실제 기준일: {field.applicable_date or '미제공'}"
            lines.append(f"   {_LABELS.get(field.field_id, field.field_id)}: {value_text}{suffix}{basis}")
        for field_id, reason in verified.missing_fields:
            lines.append(f"   {_LABELS.get(field_id, field_id)}: 미제공 ({reason})")
        for fact in verified.facts:
            if fact['evidence_kind'] == 'relation':
                label = '운용사' if fact['relation_predicate_id'] == 'managedBy' else '보유 종목'
                actual_date = fact['applicable_date'] or fact['relation_valid_from'] or fact['vintage_date']
                lines.append(f"   {label}: {_line(fact['relation_object_name'])} · 실제 기준일: {actual_date or '미제공'}")
                lines.append(f"   관계 출처: {_line(fact['source_title'])} · {_line(fact['locator_uri_or_object_key'])} · 근거: {fact['evidence_id']}")
                continue
            locator = f"시트={fact['locator_sheet']} · 행={fact['locator_row']} · 열={fact['locator_column']}"
            definition = f"{fact['metric_id']}:{fact['metric_definition_version']}"
            period = f" · 기간 종료: {fact['period_end']}" if fact['period_end'] else ''
            lines.append(f"   출처: {_line(fact['source_title'])} · {_line(fact['locator_uri_or_object_key'])} · {_line(locator)}")
            lines.append(f"   원천 지표: {definition} · 스냅샷: {fact['vintage_date'] or '미제공'}{period} · 근거: {fact['evidence_id']}")
    return '\n'.join(lines)


def _line(value: object) -> str:
    return str(value).replace('\r', '\\r').replace('\n', '\\n')
