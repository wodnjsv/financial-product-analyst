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
from financial_agent.planning.semantic_compiler import SemanticQueryPlanCompilation
from financial_agent.release.local_semantic_contract import validate_semantic_task, LocalSemanticContractError
from financial_agent.release.local_semantic_results import validate_semantic_rows, render_semantic_rows
from financial_agent.release.personal_verification import (
    PersonalVerificationReport, VerificationHarness, seal_answer_section,
    seal_semantic_section, validate_final_text, evidence_artifact,
)
from financial_agent.sql.compiler import SemanticSqlCompiler, SemanticSqlRuntimeBinder
from financial_agent.sql.executor import ReadOnlySqlRunner, SqlExecutionError
from financial_agent.sql.dataset_pin import assert_dataset_pin, DatasetPinChanged

from .personal import PersonalIntentResult, PersonalIntentService
from .personal_clarification import personal_clarifications
from .view import ActiveDatasetPin


class PersonalSearchError(RuntimeError):
    def __init__(self, code: str, verification_report: PersonalVerificationReport | None = None) -> None:
        self.code = code
        self.verification_report = verification_report
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PersonalSearchResult:
    intent: PersonalIntentResult
    text: str
    execution_performed: bool
    verification_report: PersonalVerificationReport | None = None


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


class _PersonalSqlRunner:
    """Keep compiler-validated screen counts beside the bounded execution."""

    def __init__(self, runner, compiler, harness, requests, repository, display_limit):
        self._runner, self._compiler, self._harness, self._requests = runner, compiler, harness, requests
        self._repository, self._display_limit = repository, display_limit
        self.screen_counts: dict[str, int] = {}
        self.verified_rows = {}
        self.verification_failure = None

    async def execute(self, request, logical_plan, **kwargs):
        try:
            self._compiler.validate_request_for_execution(
                request, logical_plan, readiness_facts=kwargs.get('readiness_facts'),
            )
        except (ValueError, TypeError):
            self._harness.failed('query', 'EXECUTION_REQUEST_REJECTED', task_id=request.task_id)
            raise SqlExecutionError('EXECUTION_REQUEST_REJECTED') from None
        self._requests[request.task_id] = request
        self._harness.passed('query', request, task_id=request.task_id,
                             rule_ids=('compiler-execution-ownership.v1',))
        try:
            mapped = await self._runner.execute(request, logical_plan, **kwargs)
        except asyncio.CancelledError:
            self._harness.failed('execution', 'SQL_TASK_CANCELLED', task_id=request.task_id)
            raise
        except Exception as error:
            cause = error.__cause__
            sqlstate = getattr(getattr(cause, 'orig', None), 'sqlstate', None)
            code = ('DATASET_PIN_CHANGED' if isinstance(error, SqlExecutionError) and error.args == ('DATASET_PIN_CHANGED',)
                    else 'SQL_STATEMENT_TIMEOUT' if sqlstate == '57014' else 'SQL_EXECUTION_FAILED')
            self._harness.failed('execution', code, task_id=request.task_id)
            raise
        self._harness.passed('execution', mapped, task_id=request.task_id,
                             rule_ids=('pinned-readonly-result-mapping.v1',))
        try:
            await self._verify_result(request, logical_plan, mapped)
        except PersonalSearchError as error:
            self.verification_failure = error
            raise
        return mapped

    async def _verify_result(self, request, logical_plan, mapped):
        task = request.render_manifest.logical_task
        if request.render_manifest.screen_display_limit is not None:
            if mapped.screen_population_count is None:
                raise PersonalSearchError('SCREEN_POPULATION_COUNT_MISSING')
        total_count = (mapped.screen_population_count if request.render_manifest.screen_display_limit is not None
                       else len(mapped.result_rows))
        try:
            facts = await self._repository.load(
                logical_plan.dataset_version, mapped.evidence_refs,
                expected_pin=logical_plan.dataset_pin, cutoff_date=logical_plan.cutoff_date,
            )
        except asyncio.CancelledError:
            self._harness.failed('evidence_loading', 'EVIDENCE_LOADING_CANCELLED', task_id=task.task_id)
            raise
        except Exception as error:
            code = 'DATASET_PIN_CHANGED' if isinstance(error, DatasetPinChanged) else 'LOCAL_RESULT_HYDRATION_FAILED'
            self._harness.failed('evidence_loading', code, task_id=task.task_id)
            raise PersonalSearchError(code) from None
        self._harness.passed('evidence_loading', {'dataset_pin': logical_plan.dataset_pin,
                                                'lineage': list(mapped.evidence_refs)}, task_id=task.task_id,
                             rule_ids=('pinned-evidence-hydration.v1',))
        try:
            verified = validate_semantic_rows(
                mapped.result_rows, facts, mapped.evidence_refs, request.render_manifest.binding_definitions,
                logical_plan.dataset_version, logical_plan.cutoff_date,
                relation_conditions=task.scope.relation_conditions, as_of_date=task.qualifiers.as_of_date,
                exclusions=mapped.exclusions,
            )
        except Exception as error:
            code = 'LOCAL_RESULT_EVIDENCE_INVALID'
            self._harness.failed('evidence', code, task_id=task.task_id)
            raise PersonalSearchError(code) from None
        artifact = evidence_artifact(verified) | {'lineage': list(mapped.evidence_refs)}
        self._harness.passed('evidence', artifact, task_id=task.task_id,
                             rule_ids=('source-observation-lineage.v1',))
        try:
            rules = validate_semantic_task(request, verified, total_count=total_count,
                                           display_limit=self._display_limit)
        except LocalSemanticContractError as error:
            self._harness.failed('result_contract', error.code, task_id=task.task_id)
            raise PersonalSearchError(error.code) from None
        self._harness.passed('result_contract', artifact | {'total_count': total_count},
                             task_id=task.task_id, rule_ids=rules)
        self.verified_rows[task.task_id] = verified
        if request.render_manifest.screen_display_limit is not None:
            self.screen_counts[task.task_id] = total_count


class SemanticResultRepository:
    """Read source lineage in one dataset-pinned batch, never change the ledger."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load(self, dataset_version: str, evidence_refs: tuple[str, ...], *,
                   expected_pin: str, cutoff_date) -> tuple[dict, ...]:
        ids = sorted({ref.removeprefix('evidence:') for ref in evidence_refs if ref.startswith('evidence:')})
        async with self._engine.connect() as connection:
            async with connection.begin():
                await connection.execute(sa.text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                await connection.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
                await assert_dataset_pin(connection, dataset_version, expected_pin, cutoff_date)
                if not ids:
                    return ()
                rows = (await connection.execute(sa.text('''
                    SELECT e.dataset_version, e.evidence_id, e.source_id, e.evidence_kind,
                           e.subject_id, e.predicate_id, e.normalized_value, e.value_or_object_id, e.unit,
                           e.currency, e.applicable_date, e.vintage_date, e.published_at,
                           e.available_at, e.cutoff_status, e.locator_uri_or_object_key,
                           e.locator_sheet, e.locator_row, e.locator_column,
                           s.eligible_for_claim, s.source_title, s.source_locator_root,
                           s.publisher, s.publisher_type, s.source_type, s.authority_tier,
                           s.content_checksum, p.product_family AS subject_product_family,
                           n.canonical_name, o.observation_id, o.entity_id, o.metric_id,
                           o.metric_definition_version, o.value_status, o.numeric_value,
                           o.date_value, o.text_value, o.boolean_value, o.unit AS observation_unit,
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
                    LEFT JOIN catalog.product p
                      ON p.dataset_version=e.dataset_version AND p.entity_id=e.subject_id
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
        sections = [seal_answer_section('intent', '\n'.join(lines))]
        view_pin = intent.attempt.view.active_dataset_pin
        compilation = intent.compilation
        plan = compilation.logical_query_plan if compilation else None
        harness = VerificationHarness(
            intent.context.dataset_version, view_pin.manifest_hash,
            intent.context.request_key, intent.context.cutoff_date,
            task_ids=tuple(task.task_id for task in plan.tasks) if plan else (),
        )
        if plan is None:
            harness.not_run('plan', 'NO_EXECUTABLE_PLAN')
            limited = _limitations(intent)
            lines.extend(limited)
            if limited:
                sections.append(seal_answer_section('limitation', '\n'.join(limited)))
            return _release_search_result(intent, lines, sections, harness, False)
        try:
            SemanticQueryPlanCompilation.model_validate_json(compilation.model_dump_json())
            if (plan.dataset_version != intent.context.dataset_version
                    or plan.dataset_pin != view_pin.manifest_hash
                    or view_pin.dataset_version != intent.context.dataset_version
                    or plan.cutoff_date != intent.context.cutoff_date
                    or plan.request_key != intent.context.request_key
                    or plan.run_id != intent.context.run_id):
                raise ValueError('PLAN_PIN_MISMATCH')
        except (ValueError, TypeError):
            harness.failed('plan', 'PLAN_CONTRACT_INVALID')
            raise PersonalSearchError('PLAN_CONTRACT_INVALID', harness.finish('failed')) from None
        harness.passed('plan', compilation, rule_ids=('registered-plan-and-pins.v1',))
        if any(task.action_id.value not in ('lookup', 'screen', 'rank', 'compare')
               or any(step.execution_route is not LogicalExecutionRoute.SEMANTIC_SQL
                      for step in task.execution_steps) for task in plan.tasks):
            limited = [
                '[제한] LOCAL_RESULT_SHAPE_NOT_SUPPORTED: 이 로컬 출력 경로에 연결되지 않은 작업입니다.',
            ]
            lines.extend(limited)
            sections.append(seal_answer_section('limitation', '\n'.join(limited)))
            return _release_search_result(intent, lines, sections, harness, False)
        remaining = (intent.context.deadline_at - self._utcnow()).total_seconds()
        if remaining <= 0:
            harness.failed('execution', 'PERSONAL_SEARCH_DEADLINE_EXCEEDED')
            raise PersonalSearchError('PERSONAL_SEARCH_DEADLINE_EXCEEDED', harness.finish('failed'))
        pin = ActiveDatasetPin(dataset_version=plan.dataset_version, manifest_hash=plan.dataset_pin)
        compiler = SemanticSqlCompiler(self._bindings, self._policies, self._planning, pin)
        requests = {}

        def compile_request(logical_plan, task):
            bounded_screen = task.action_id.value == 'screen' and not task.produced_result_bindings
            outcome = compiler.compile_task(
                logical_plan, task.task_id,
                screen_display_limit=display_limit if bounded_screen else None,
            )
            if outcome.request is None:
                harness.failed('query', outcome.rejection.code, task_id=task.task_id)
                raise PersonalSearchError(outcome.rejection.code)
            requests[task.task_id] = outcome.request
            return outcome.request

        runner = _PersonalSqlRunner(self._runner_factory(compiler), compiler, harness, requests,
                                    self._repository, display_limit)
        executor = _PersonalSqlExecutor(
            runner, runtime_binder=SemanticSqlRuntimeBinder(compiler),
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
                    if runner.verification_failure is not None:
                        raise runner.verification_failure
                    if executor.row_limit_exceeded:
                        raise PersonalSearchError('SQL_RESULT_ROW_LIMIT_EXCEEDED')
                    if any(item.code == 'TASK_TIMEOUT' for item in execution.failures):
                        raise PersonalSearchError('PERSONAL_SQL_TIMEOUT')
                    raise PersonalSearchError('PERSONAL_SQL_EXECUTION_FAILED')
                lines.append('[2. 데이터 조회] 승인된 계획 → 컴파일러 SQL → fa_runtime 읽기 전용 실행')
                sections.append(seal_answer_section('execution', lines[-1]))
                for task in plan.tasks:
                    if f'semantic-execution:{task.task_id}' in execution.skipped_task_ids:
                        lines.append(f'{task.frame_id}: 선행 조회 결과 0건으로 후속 조회를 생략했습니다.')
                        sections.append(seal_answer_section(task.task_id, lines[-1]))
                        for stage in ('query', 'execution', 'evidence_loading', 'evidence', 'result_contract'):
                            harness.not_run(stage, 'PRIOR_RESULT_EMPTY', task_id=task.task_id)
                        continue
                    tool = next(result for result in execution.tool_results
                                if result.task_id == f'semantic-execution:{task.task_id}')
                    verified = runner.verified_rows[task.task_id]
                    total_count = runner.screen_counts.get(task.task_id, len(tool.result_rows))
                    lines.append(f'[3. 결과 검증] {task.frame_id}: 지표 정의·값·단위·날짜·출처 일치')
                    sections.append(seal_answer_section(f'{task.task_id}-verification', lines[-1]))
                    render_options = dict(total_count=total_count, display_limit=display_limit,
                        ranked=task.action_id.value == 'rank',
                        bounded_screen=task.task_id in runner.screen_counts,
                    )
                    sections.append(seal_semantic_section(task.task_id, verified, **render_options))
                    lines.append(render_semantic_rows(verified, **render_options))
                    contract = next(group.complete_candidates[0].contract
                                    for group in intent.attempt.candidates.frames
                                    if group.frame_id == task.frame_id)
                    if any(item.source_ref == 'personal-organizer-bond-saleability.v1'
                           for item in contract.provenance):
                        lines.append(
                            '[구매 가능 가정] 공식 공지의 구매 가능 가정에 따라 '
                            f'{plan.cutoff_date.isoformat()} 이후 만기·원천 잔여일수 양수인 후보입니다. '
                            '실시간 판매 가능 여부를 확인한 결과는 아닙니다.'
                        )
                        sections.append(seal_answer_section(f'{task.task_id}-availability', lines[-1]))
                    if any(item.source_ref.startswith('active-dataset-as-of.v1')
                           for item in contract.provenance):
                        lines.append(
                            f'[기준일 기본값] 원천에서 단일 날짜를 확인한 '
                            f'{task.qualifiers.as_of_date.isoformat()} 자료를 사용했습니다.'
                        )
                        sections.append(seal_answer_section(f'{task.task_id}-as-of', lines[-1]))
                    if tool.exclusions:
                        lines.append('제외/누락: ' + ', '.join(sorted({item.reason_code for item in tool.exclusions})))
                        sections.append(seal_answer_section(f'{task.task_id}-exclusions', lines[-1]))
                if self._utcnow() >= intent.context.deadline_at:
                    raise PersonalSearchError('PERSONAL_SEARCH_DEADLINE_EXCEEDED')
        except TimeoutError:
            harness.failed('execution', 'PERSONAL_SEARCH_DEADLINE_EXCEEDED')
            raise PersonalSearchError('PERSONAL_SEARCH_DEADLINE_EXCEEDED', harness.finish('failed')) from None
        except PersonalSearchError as error:
            if error.verification_report is None:
                if not any(item.status == 'fail' for item in harness.finish('failed').checks):
                    harness.failed('execution', error.code)
                error.verification_report = harness.finish('failed')
            raise
        return _release_search_result(intent, lines, sections, harness, True)


def _render_final_text(lines):
    return '\n'.join(lines)


def _release_search_result(intent, lines, sections, harness, executed):
    summary = ('[4. 최종 검증] 서버가 검증한 값·건수·날짜·출처와 출력 일치' if executed
               else '[4. 최종 검증] 검증된 제한 안내와 출력 일치 · 상품 조회 미실행')
    lines.append(summary)
    sections.append(seal_answer_section('final-verification', summary))
    text = _render_final_text(lines)
    try:
        digest = validate_final_text(sections, text)
    except ValueError as error:
        code = str(error)
        harness.failed('final', code)
        raise PersonalSearchError(code, harness.finish('failed')) from None
    harness.passed('final', {'output_hash': digest}, rule_ids=('canonical-final-rendering.v1',))
    return PersonalSearchResult(intent, text, executed,
                                harness.finish('verified' if executed else 'limited', text=text))


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
        'PREDICATE_OPERATOR_REQUIRED': '조건 비교식이 완성되지 않아 DB 조회를 실행하지 않았습니다.',
        'REQUESTED_FIELD_ROLE_MISSING': '요청한 조건·지표를 모두 포함한 조회 계획을 구성하지 못했습니다.',
    }
    lines = [f"[제한] {code}: {explanations.get(code, '요청을 안전하게 실행할 조건이 충족되지 않았습니다.')}"
             for code in intent.issue_codes]
    lines.extend(f"[확인 필요] {item['code']}: {item['message']}"
                 for item in personal_clarifications(intent))
    return lines
