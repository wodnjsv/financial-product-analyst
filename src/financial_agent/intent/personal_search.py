"""Bounded personal semantic SQL execution and verified text results."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts.enums import Capability, ExecutionOutcome
from financial_agent.orchestration.executors import ExecutorRegistry, SqlCapabilityExecutor
from financial_agent.orchestration.graph import ExecutionGraphCompiler
from financial_agent.orchestration.semantic_graph import SemanticExecutionGraphCompiler
from financial_agent.orchestration.service import Orchestrator
from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry, load_semantic_sql_policy_registry,
)
from financial_agent.planning.primitive_contracts import LogicalExecutionRoute
from financial_agent.planning.registry import load_planning_registry
from financial_agent.release.local_semantic_results import validate_semantic_rows, render_semantic_rows
from financial_agent.sql.compiler import SemanticSqlCompiler, SemanticSqlRuntimeBinder
from financial_agent.sql.executor import ReadOnlySqlRunner, SqlExecutionError

from .personal import PersonalIntentResult, PersonalIntentService
from .personal_clarification import personal_clarifications
from .view import ActiveDatasetPin


class PersonalSearchError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PersonalSearchResult:
    intent: PersonalIntentResult
    text: str
    execution_performed: bool


class _PersonalSqlExecutor(SqlCapabilityExecutor):
    """Retain the bounded row-limit reason across the orchestration boundary."""

    row_limit_exceeded = False

    async def execute(self, request):
        try:
            return await super().execute(request)
        except SqlExecutionError as error:
            if error.args == ('SQL_RESULT_ROW_LIMIT_EXCEEDED',):
                self.row_limit_exceeded = True
            raise


class SemanticResultRepository:
    """Read source lineage in one dataset-pinned batch, never change the ledger."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load(self, dataset_version: str, evidence_refs: tuple[str, ...]) -> tuple[dict, ...]:
        ids = sorted({ref.removeprefix('evidence:') for ref in evidence_refs if ref.startswith('evidence:')})
        if not ids:
            return ()
        async with self._engine.connect() as connection:
            async with connection.begin():
                await connection.execute(sa.text('SET TRANSACTION READ ONLY'))
                await connection.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
                rows = (await connection.execute(sa.text('''
                    SELECT e.dataset_version, e.evidence_id, e.source_id, e.evidence_kind,
                           e.subject_id, e.predicate_id, e.normalized_value, e.value_or_object_id, e.unit,
                           e.currency, e.applicable_date, e.vintage_date, e.published_at,
                           e.available_at, e.cutoff_status, e.locator_uri_or_object_key,
                           e.locator_sheet, e.locator_row, e.locator_column,
                           s.eligible_for_claim, s.source_title, s.source_locator_root,
                           n.canonical_name, o.observation_id, o.entity_id, o.metric_id,
                           o.metric_definition_version, o.value_status, o.numeric_value,
                           o.date_value, o.unit AS observation_unit,
                           o.currency AS observation_currency, o.applicable_date AS observation_date,
                           o.period_start, o.period_end, r.relation_id,
                           r.subject_id AS relation_subject_id, r.predicate_id AS relation_predicate_id,
                           r.object_id AS relation_object_id, r.valid_from AS relation_valid_from,
                           r.valid_to AS relation_valid_to, obj.canonical_name AS relation_object_name
                    FROM evidence.evidence_record e
                    JOIN evidence.source_record s
                      ON s.dataset_version=e.dataset_version AND s.source_id=e.source_id
                    JOIN catalog.entity n
                      ON n.dataset_version=e.dataset_version AND n.entity_id=e.subject_id
                    LEFT JOIN evidence.evidence_observation_origin eo
                      ON eo.dataset_version=e.dataset_version AND eo.evidence_id=e.evidence_id
                    LEFT JOIN observation.observation_record o
                      ON o.dataset_version=eo.dataset_version AND o.observation_id=eo.observation_id
                    LEFT JOIN evidence.evidence_relation_origin er
                      ON er.dataset_version=e.dataset_version AND er.evidence_id=e.evidence_id
                    LEFT JOIN relation.relation_record r
                      ON r.dataset_version=er.dataset_version AND r.relation_id=er.relation_id
                    LEFT JOIN catalog.entity obj
                      ON obj.dataset_version=r.dataset_version AND obj.entity_id=r.object_id
                    WHERE e.dataset_version=:dataset_version
                      AND e.evidence_id=ANY(CAST(:evidence_ids AS text[]))
                    ORDER BY e.evidence_id
                '''), {'dataset_version': dataset_version, 'evidence_ids': ids})).mappings().all()
        if {row['evidence_id'] for row in rows} != set(ids):
            raise PersonalSearchError('LOCAL_RESULT_LINEAGE_MISSING')
        return tuple(dict(row) for row in rows)


class PersonalSemanticSearch:
    def __init__(
        self, intent_service: PersonalIntentService, *, project_root: Path,
        runner_factory: Callable, repository: SemanticResultRepository,
        utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._intent, self._repository, self._runner_factory = intent_service, repository, runner_factory
        self._bindings = load_physical_binding_registry(project_root)
        self._policies = load_semantic_sql_policy_registry(project_root)
        self._planning = load_planning_registry(project_root)
        self._utcnow = utcnow

    async def search(
        self, question: str, question_id: str = 'local-search', display_limit: int = 5,
    ) -> PersonalSearchResult:
        if type(display_limit) is not int or not 1 <= display_limit <= 50:
            raise PersonalSearchError('DISPLAY_LIMIT_INVALID')
        intent = await self._intent.resolve(question, question_id)
        lines = _intent_trace(intent)
        compilation = intent.compilation
        plan = compilation.logical_query_plan if compilation else None
        if plan is None:
            return PersonalSearchResult(intent, '\n'.join(lines + _limitations(intent)), False)
        if any(task.action_id.value not in ('lookup', 'screen', 'rank', 'compare')
               or any(step.execution_route is not LogicalExecutionRoute.SEMANTIC_SQL
                      for step in task.execution_steps) for task in plan.tasks):
            return PersonalSearchResult(intent, '\n'.join(lines + [
                '[제한] LOCAL_RESULT_SHAPE_NOT_SUPPORTED: 이 로컬 출력 경로에 연결되지 않은 작업입니다.',
            ]), False)
        remaining = (intent.context.deadline_at - self._utcnow()).total_seconds()
        if remaining <= 0:
            raise PersonalSearchError('PERSONAL_SEARCH_DEADLINE_EXCEEDED')
        pin = ActiveDatasetPin(dataset_version=plan.dataset_version, manifest_hash=plan.dataset_pin)
        compiler = SemanticSqlCompiler(self._bindings, self._policies, self._planning, pin)
        requests = {}

        def compile_request(logical_plan, task):
            outcome = compiler.compile_task(logical_plan, task.task_id)
            if outcome.request is None:
                raise PersonalSearchError(outcome.rejection.code)
            requests[task.task_id] = outcome.request
            return outcome.request

        executor = _PersonalSqlExecutor(
            self._runner_factory(compiler), runtime_binder=SemanticSqlRuntimeBinder(compiler),
        )
        orchestrator = Orchestrator(
            graph_compiler=ExecutionGraphCompiler(self._planning),
            semantic_graph_compiler=SemanticExecutionGraphCompiler(
                self._planning, compiled_request_provider=compile_request,
            ),
            executors=ExecutorRegistry(((Capability.RDB_LOOKUP, executor),)),
            hard_deadline_ms=max(1, min(55_000, int(remaining * 1000))), max_concurrency=2,
        )
        try:
            async with asyncio.timeout(remaining):
                execution = await orchestrator.execute_semantic(compilation)
                if execution.execution_outcome is not ExecutionOutcome.COMPLETED:
                    if executor.row_limit_exceeded:
                        raise PersonalSearchError('SQL_RESULT_ROW_LIMIT_EXCEEDED')
                    if any(item.code == 'TASK_TIMEOUT' for item in execution.failures):
                        raise PersonalSearchError('PERSONAL_SQL_TIMEOUT')
                    raise PersonalSearchError('PERSONAL_SQL_EXECUTION_FAILED')
                lines.append('[2. 데이터 조회] 승인된 계획 → 컴파일러 SQL → fa_runtime 읽기 전용 실행')
                for task in plan.tasks:
                    if f'semantic-execution:{task.task_id}' in execution.skipped_task_ids:
                        lines.append(f'{task.frame_id}: 선행 조회 결과 0건으로 후속 조회를 생략했습니다.')
                        continue
                    tool = next(result for result in execution.tool_results
                                if result.task_id == f'semantic-execution:{task.task_id}')
                    facts = await self._repository.load(plan.dataset_version, tool.evidence_refs)
                    verified = validate_semantic_rows(
                        tool.result_rows, facts, tool.evidence_refs,
                        requests[task.task_id].render_manifest.binding_definitions,
                        plan.dataset_version, plan.cutoff_date,
                        relation_conditions=task.scope.relation_conditions,
                        as_of_date=task.qualifiers.as_of_date,
                        exclusions=tool.exclusions,
                    )
                    lines.append(f'[3. 결과 검증] {task.frame_id}: 지표 정의·값·단위·날짜·출처 일치')
                    lines.append(render_semantic_rows(
                        verified, total_count=len(tool.result_rows), display_limit=display_limit,
                        ranked=task.action_id.value == 'rank',
                    ))
                    if tool.exclusions:
                        lines.append('제외/누락: ' + ', '.join(sorted({item.reason_code for item in tool.exclusions})))
                if self._utcnow() >= intent.context.deadline_at:
                    raise PersonalSearchError('PERSONAL_SEARCH_DEADLINE_EXCEEDED')
        except TimeoutError:
            raise PersonalSearchError('PERSONAL_SEARCH_DEADLINE_EXCEEDED') from None
        return PersonalSearchResult(intent, '\n'.join(lines), True)


def create_personal_search(intent_service, project_root: Path, engine: AsyncEngine):
    return PersonalSemanticSearch(
        intent_service, project_root=project_root,
        runner_factory=lambda compiler: ReadOnlySqlRunner(engine, compiler, default_timeout_ms=5000),
        repository=SemanticResultRepository(engine),
    )


def _intent_trace(intent: PersonalIntentResult) -> list[str]:
    output = intent.to_dict()
    lines = [f"질문: {intent.context.question}",
             f"데이터: {intent.context.dataset_version} · 모델: {intent.model_id}",
             f"[1. 의도 분석] 라우팅: {output['route']} · 판정: {output['disposition']}"]
    for frame in output['frames']:
        lines.append(f"{frame['frame_id']}: 작업={','.join(frame['actions'])} · 상품군={','.join(frame['product_families'])}")
        if frame['candidate_contract']:
            lines.append('질의 의미: ' + json.dumps(frame['candidate_contract'], ensure_ascii=False, separators=(',', ':')))
    return lines


def _limitations(intent: PersonalIntentResult) -> list[str]:
    explanations = {
        'SOURCE_ONE_YEAR_RETURN_NOT_PROVIDED': '해외 ETF 원천에 1년 수익률 필드가 없습니다.',
        'PUBLIC_FUND_TOTAL_FEE_DEFINITION_UNVERIFIED': '공모펀드 총보수의 합산 정의와 단위가 검증되지 않았습니다.',
        'PHYSICAL_DEFINITION_UNVERIFIED': '공모펀드 총보수의 합산 정의와 단위가 검증되지 않았습니다.',
        'PHYSICAL_BINDING_NOT_REGISTERED': '요청 지표의 상품군별 원천 연결이 등록되지 않았습니다.',
        'POLICY_BLOCKED': '예측·개인화 투자판단 등 실행할 수 없는 요청입니다.',
        'RELATION_BOOLEAN_SCOPE_UNSUPPORTED': '관계 조건의 부정·또는·제외는 아직 지원하지 않습니다. 조건을 분리해 조회해 주세요.',
        'BOOLEAN_PREDICATE_SCOPE_UNSUPPORTED': '또는 조건을 정확히 보존하는 조회는 아직 연결되지 않았습니다. 조건을 분리해 조회해 주세요.',
        'PRODUCT_SUBTYPE_NOT_SUPPORTED': '이 조회 경로는 ETF 범위입니다. ETN 상품 조회는 아직 연결되지 않았습니다.',
    }
    lines = [f"[제한] {code}: {explanations.get(code, '요청을 안전하게 실행할 조건이 충족되지 않았습니다.')}"
             for code in intent.issue_codes]
    lines.extend(f"[확인 필요] {item['code']}: {item['message']}"
                 for item in personal_clarifications(intent))
    return lines
