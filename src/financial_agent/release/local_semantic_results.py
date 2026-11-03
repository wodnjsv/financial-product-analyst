"""Validate personal SQL facts against their immutable observation lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
import re
from typing import Mapping, Sequence
from types import MappingProxyType
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.execution import Exclusion, ResultRow
from financial_agent.contracts.values import ScalarValue, decode_contract_value
from financial_agent.ingestion.mapping.domestic_bond import SPEC as DOMESTIC_BOND_SPEC
from financial_agent.ingestion.mapping.domestic_etp import SPEC as DOMESTIC_ETP_SPEC
from financial_agent.ingestion.mapping.overseas_etp import SPEC as OVERSEAS_ETP_SPEC
from financial_agent.ingestion.mapping.public_fund import SPEC as PUBLIC_FUND_SPEC
from financial_agent.planning.physical_bindings import EXPECTED_MAPPER_BINDINGS, PhysicalBindingDefinition
from financial_agent.intent.query_contracts import RelationConditionV2


class LocalSemanticResultError(ValueError):
    code = 'LOCAL_RESULT_EVIDENCE_INVALID'


@dataclass(frozen=True, slots=True)
class VerifiedSemanticRow:
    row: ResultRow
    facts: tuple[Mapping[str, object], ...]
    missing_fields: tuple[tuple[str, str], ...] = ()


_SCALAR = TypeAdapter(ScalarValue)
_SEOUL = ZoneInfo('Asia/Seoul')
_ORGANIZER_SPECS = {spec.source_code: spec for spec in (
    DOMESTIC_BOND_SPEC, DOMESTIC_ETP_SPEC, OVERSEAS_ETP_SPEC, PUBLIC_FUND_SPEC,
)}
_LABELS = {
    'fee_rate': '총보수', 'aum': '순자산', 'maturity_date': '만기일',
    'trailing_1y_historical_cumulative_return': '과거 1년 누적수익률',
    'region': '지역', 'asset_class': '자산 유형', 'currency': '통화',
    'credit_grade': '신용등급', 'remaining_days': '잔존일수',
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
    row_ids, product_ids = set(), set()
    for row in rows:
        if len(row.entity_ids) != 1:
            raise LocalSemanticResultError()
        product_id = row.entity_ids[0]
        field_ids = [field.field_id for field in row.fields]
        if row.row_id in row_ids or product_id in product_ids or len(field_ids) != len(set(field_ids)):
            raise LocalSemanticResultError()
        row_ids.add(row.row_id)
        product_ids.add(product_id)
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
    _validate_source_metadata(item)
    if item.get('subject_product_family') != binding.product_family_id.value:
        raise LocalSemanticResultError()
    if item['metric_id'].startswith('organizer.'):
        _validate_organizer_ownership(item, binding)
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
    storage_column = {
        'date': 'date_value', 'decimal': 'numeric_value', 'integer': 'numeric_value',
        'string': 'text_value', 'boolean': 'boolean_value',
    }.get(binding.semantic_value_kind.value)
    if storage_column is None:
        raise LocalSemanticResultError()
    storage_value = item.get(storage_column)
    try:
        normalized = decode_contract_value(_SCALAR.validate_json(json.dumps(item['normalized_value'])))
    except (ValueError, TypeError):
        raise LocalSemanticResultError() from None
    expected_type = {'date': date, 'decimal': Decimal, 'integer': int,
                     'string': str, 'boolean': bool}[binding.semantic_value_kind.value]
    if not missing and any(type(actual) is not expected_type
                           for actual in (value, storage_value, normalized)):
        raise LocalSemanticResultError()
    stored_values = tuple(item.get(column) for column in (
        'numeric_value', 'text_value', 'boolean_value', 'date_value', 'timestamp_value',
    ))
    if sum(actual is not None for actual in stored_values) != (0 if missing else 1):
        raise LocalSemanticResultError()
    if item['value_status'] == 'zero' and (
        binding.semantic_value_kind.value not in ('decimal', 'integer') or value != 0
    ):
        raise LocalSemanticResultError()
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
        actual = _source_date(item[key])
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
    _validate_source_metadata(item)
    _validate_relation_ownership(item, condition.relation_id)
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
        actual = _source_date(item[key])
        if actual is not None and actual > cutoff:
            raise LocalSemanticResultError()


def _validate_source_metadata(item):
    if any(not isinstance(item.get(field), str) or not item[field].strip()
           for field in ('publisher', 'publisher_type', 'source_type', 'authority_tier')):
        raise LocalSemanticResultError()
    checksum = item.get('content_checksum')
    if not isinstance(checksum, str) or re.fullmatch(r'[0-9a-f]{64}', checksum) is None:
        raise LocalSemanticResultError()


def _validate_organizer_ownership(item, binding):
    owner = EXPECTED_MAPPER_BINDINGS.get(binding.id)
    if owner is None:
        raise LocalSemanticResultError()
    _, column, metric_id = owner
    spec = _ORGANIZER_SPECS.get(metric_id.split('.')[1].upper())
    if (
        (item['publisher_type'], item['source_type'], item['authority_tier'])
        != ('organizer', 'dataset', 'organizer')
        or spec is None or item['metric_id'] != metric_id
        or item['locator_uri_or_object_key'] != spec.data_file_name
        or item['source_locator_root'] != spec.data_file_name
        or item['locator_column'] != column
    ):
        raise LocalSemanticResultError()


def _validate_relation_ownership(item, relation_id):
    family = item.get('subject_product_family')
    if not isinstance(family, str):
        raise LocalSemanticResultError()
    if relation_id == 'managedBy':
        expected = (
            ('organizer', 'dataset', 'organizer')
            if family in {value.value for value in ProductFamily} else None
        )
    else:
        expected = {
            'domestic_etf': ('exchange', 'dataset', 'official'),
            'overseas_etf': ('regulator', 'dataset', 'official'),
        }.get(family)
    if expected is None or (item['publisher_type'], item['source_type'], item['authority_tier']) != expected:
        raise LocalSemanticResultError()


def _source_date(value):
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise LocalSemanticResultError()
        return value.astimezone(_SEOUL).date()
    if value is not None and type(value) is not date:
        raise LocalSemanticResultError()
    return value


def render_semantic_rows(
    rows: Sequence[VerifiedSemanticRow], *, total_count: int, display_limit: int,
    ranked: bool,
    bounded_screen: bool = False,
) -> str:
    valid_count = (
        type(total_count) is int and total_count >= 0 and not ranked
        and len(rows) == min(total_count, display_limit)
    ) if bounded_screen else total_count == len(rows)
    if not 1 <= display_limit <= 50 or not valid_count:
        raise LocalSemanticResultError()
    displayed = rows[:display_limit]
    count_label = '순위 결과' if ranked else '전체 일치'
    lines = [f'{count_label} {total_count}건 · 표시 {len(displayed)}건']
    undated = sum(any(field.field_id not in ('product_name', 'maturity_date')
                      and field.applicable_date is None for field in verified.row.fields)
                  for verified in rows) if ranked else 0
    if undated:
        lines.append(f'기준일 미제공 {undated}건: 저장된 원천값의 순위이며 현재 기준 비교는 확인할 수 없습니다.')
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
