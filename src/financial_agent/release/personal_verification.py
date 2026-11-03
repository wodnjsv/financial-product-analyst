"""Request-scoped hard verification records for the personal SQL bridge."""

from datetime import date, datetime
from decimal import Decimal
import json
import re
from typing import Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.canonical import canonical_json_bytes, canonical_sha256
from .local_semantic_results import render_semantic_rows


_LOCAL_STAGES = ('plan', 'query', 'execution', 'evidence_loading', 'evidence', 'result_contract', 'final')
_TASK_STAGES = ('query', 'execution', 'evidence_loading', 'evidence', 'result_contract')
_TRANSIENT_STAGES = ('execution', 'evidence_loading')
_UNUSED_STAGES = {
    'calculation_record': 'NO_CALCULATION_RECORD_IN_LOCAL_SQL_PATH',
    'production_claim_gate': 'LOCAL_VERIFIED_ROWS_NOT_PRODUCTION_RELEASE',
    'graph_projection': 'GRAPH_NOT_USED',
    'vector_projection': 'VECTOR_NOT_USED',
    'dataset_activation': 'PINNED_PERSONAL_BUILDING_PROFILE',
    'semantic_judge': 'ADDITIONAL_LLM_JUDGE_NOT_ENABLED',
}


class PersonalVerificationCheck(ContractModel):
    stage: Identifier
    task_id: Identifier | None = None
    attempt: int = Field(default=1, ge=1, le=2)
    status: Literal['pass', 'fail', 'not_run', 'not_applicable']
    rule_ids: tuple[Identifier, ...] = ()
    reason_code: Identifier | None = None
    artifact_hash: Sha256Hex | None = None

    @model_validator(mode='after')
    def validate_check(self):
        if self.status == 'pass':
            if (self.artifact_hash is None or not self.rule_ids
                    or len(self.rule_ids) != len(set(self.rule_ids)) or self.reason_code is not None):
                raise ValueError('VERIFICATION_PASS_INVALID')
        elif (self.artifact_hash is not None or self.rule_ids
              or self.reason_code is None
              or re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}', self.reason_code) is None):
            raise ValueError('VERIFICATION_NON_PASS_INVALID')
        if (self.stage not in (*_LOCAL_STAGES, *_UNUSED_STAGES)
                or self.stage in _LOCAL_STAGES and self.status == 'not_applicable'
                or self.stage in _UNUSED_STAGES and (
                    self.status != 'not_applicable'
                    or self.reason_code != _UNUSED_STAGES[self.stage]
                    or self.task_id is not None or self.attempt != 1)
                or self.stage in ('plan', 'final') and self.task_id is not None):
            raise ValueError('VERIFICATION_STAGE_INVALID')
        return self


class PersonalVerificationReport(ContractModel):
    harness_version: Literal['personal-verification.v1'] = 'personal-verification.v1'
    dataset_version: Identifier
    manifest_hash: Sha256Hex
    request_key: Sha256Hex
    cutoff_date: date
    task_ids: tuple[Identifier, ...] = ()
    outcome: Literal['verified', 'limited', 'failed']
    checks: tuple[PersonalVerificationCheck, ...]
    output_hash: Sha256Hex | None = None
    report_hash: Sha256Hex

    @model_validator(mode='after')
    def validate_report(self):
        if self.report_hash != canonical_sha256(self, exclude_fields=('report_hash',)):
            raise ValueError('VERIFICATION_REPORT_HASH_MISMATCH')
        keys = [(item.stage, item.task_id, item.attempt) for item in self.checks]
        if len(keys) != len(set(keys)):
            raise ValueError('DUPLICATE_VERIFICATION_CHECK')
        terminal = {}
        for item in self.checks:
            key = (item.stage, item.task_id)
            previous = terminal.get(key)
            if previous is not None:
                if item.attempt <= previous.attempt:
                    raise ValueError('VERIFICATION_ATTEMPT_ORDER_INVALID')
                if (previous.status == 'fail' and item.status == 'pass'
                        and item.stage not in _TRANSIENT_STAGES):
                    raise ValueError('VERIFICATION_HARD_FAILURE_OVERRIDDEN')
            terminal[key] = item
        if (len(self.task_ids) != len(set(self.task_ids))
                or any(item.task_id is not None and item.task_id not in self.task_ids for item in self.checks)):
            raise ValueError('VERIFICATION_TASK_SCOPE_MISMATCH')
        if (set(item.stage for item in self.checks) != set((*_LOCAL_STAGES, *_UNUSED_STAGES))
                or any((stage, task_id) not in terminal
                       for task_id in self.task_ids for stage in _TASK_STAGES)):
            raise ValueError('VERIFICATION_CHECK_COVERAGE_INVALID')
        complete_tasks = all(
            all((item := terminal.get((stage, task_id))) is not None and item.status == 'pass'
                and item.attempt == terminal[('query', task_id)].attempt for stage in _TASK_STAGES)
            or all((item := terminal.get((stage, task_id))) is not None
                   and item.status == 'not_run' and item.reason_code == 'PRIOR_RESULT_EMPTY'
                   for stage in _TASK_STAGES)
            for task_id in self.task_ids
        )
        if self.outcome == 'verified' and (
            any(item.status == 'fail' and item.stage not in _TRANSIENT_STAGES for item in self.checks)
            or any(item.status == 'fail' for item in terminal.values())
            or any(not any(item.stage == stage and item.status == 'pass'
                           for item in self.checks) for stage in _LOCAL_STAGES)
            or self.output_hash is None
            or not self.task_ids or not complete_tasks
        ):
            raise ValueError('VERIFICATION_STAGES_INCOMPLETE')
        if self.outcome == 'failed' and self.output_hash is not None:
            raise ValueError('FAILED_VERIFICATION_CANNOT_RELEASE_OUTPUT')
        if self.outcome == 'limited' and (
            any(item.status == 'fail' for item in self.checks)
            or (item := terminal.get(('final', None))) is None or item.status != 'pass'
            or self.output_hash is None
        ):
            raise ValueError('VERIFICATION_STAGES_INCOMPLETE')
        if self.outcome in ('verified', 'limited') and (
            terminal[('final', None)].artifact_hash != canonical_sha256({'output_hash': self.output_hash})
        ):
            raise ValueError('VERIFICATION_FINAL_HASH_MISMATCH')
        return self


class VerificationHarness:
    def __init__(self, dataset_version, manifest_hash, request_key, cutoff_date, *, task_ids=()):
        self._pins = dict(dataset_version=dataset_version, manifest_hash=manifest_hash,
                          request_key=request_key, cutoff_date=cutoff_date, task_ids=tuple(task_ids))
        self._checks: list[PersonalVerificationCheck] = []

    def passed(self, stage, artifact, *, task_id=None, rule_ids=()):
        self._record(stage, 'pass', task_id, rule_ids, None, canonical_sha256(artifact))

    def failed(self, stage, code, *, task_id=None):
        if not isinstance(code, str) or re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}', code) is None:
            raise ValueError('UNSAFE_VERIFICATION_REASON')
        self._record(stage, 'fail', task_id, (), code, None)

    def not_run(self, stage, code, *, task_id=None):
        self._record(stage, 'not_run', task_id, (), code, None)

    def _record(self, stage, status, task_id, rule_ids, reason_code, artifact_hash):
        queries = sum(item.stage == 'query' and item.task_id == task_id for item in self._checks)
        attempt = queries + 1 if stage == 'query' else max(1, queries)
        self._checks.append(PersonalVerificationCheck(
            stage=stage, task_id=task_id, attempt=attempt, status=status, rule_ids=tuple(rule_ids),
            reason_code=reason_code, artifact_hash=artifact_hash,
        ))

    def finish(self, outcome, *, text=None):
        checks = list(self._checks)
        present = {item.stage for item in checks}
        for stage in _LOCAL_STAGES:
            if stage in _TASK_STAGES and self._pins['task_ids']:
                for task_id in self._pins['task_ids']:
                    if not any(item.stage == stage and item.task_id == task_id for item in checks):
                        checks.append(PersonalVerificationCheck(
                            stage=stage, task_id=task_id, status='not_run', reason_code='NO_STAGE_RESULT',
                        ))
            elif stage not in present:
                checks.append(PersonalVerificationCheck(
                    stage=stage, status='not_run', reason_code='NO_STAGE_RESULT',
                ))
        checks.extend(PersonalVerificationCheck(
            stage=stage, status='not_applicable', reason_code=code,
        ) for stage, code in _UNUSED_STAGES.items())
        draft = PersonalVerificationReport.model_construct(
            **self._pins, outcome=outcome, checks=tuple(checks),
            output_hash=canonical_sha256({'text': text}) if text is not None else None,
            report_hash='0' * 64,
        )
        draft = draft.model_copy(update={
            'report_hash': canonical_sha256(draft, exclude_fields=('report_hash',)),
        })
        return PersonalVerificationReport.model_validate_json(draft.model_dump_json())


def _evidence_json_value(value):
    if type(value) in (date, datetime):
        return value.isoformat()
    if type(value) is Decimal and value.is_finite():
        return str(value)
    raise TypeError('UNSUPPORTED_EVIDENCE_METADATA')


def evidence_artifact(verified_rows):
    facts = json.loads(json.dumps(
        [dict(fact) for item in verified_rows for fact in item.facts],
        default=_evidence_json_value, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ))
    return {
        'rows': [item.row.model_dump(mode='json') for item in verified_rows],
        'facts': sorted(facts, key=canonical_json_bytes),
    }


class VerifiedAnswerSection(ContractModel):
    section_id: Identifier
    text: str
    text_hash: Sha256Hex


def seal_answer_section(section_id: str, text: str) -> VerifiedAnswerSection:
    return VerifiedAnswerSection(section_id=section_id, text=text,
                                 text_hash=canonical_sha256({'text': text}))


def seal_semantic_section(section_id: str, rows, **render_options) -> VerifiedAnswerSection:
    """Canonical rendering consumes verified structures, never generated prose."""
    return seal_answer_section(section_id, render_semantic_rows(rows, **render_options))


def validate_final_text(sections, text: str) -> str:
    if any(section.text_hash != canonical_sha256({'text': section.text}) for section in sections):
        raise ValueError('FINAL_SOURCE_SECTION_CHANGED')
    if text != '\n'.join(section.text for section in sections):
        raise ValueError('FINAL_RESPONSE_MISMATCH')
    return canonical_sha256({'text': text})
