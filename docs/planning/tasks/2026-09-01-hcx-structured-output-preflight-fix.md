# HCX Structured Output Preflight Fix Plan

**Goal:** HCX-007 Structured Outputs 실호출에서 확인된 요청 계약 오류와
동적 mention ID 경계 누락을 최소 수정하고, 비실시간 회귀 및 12개 한국어
질문 실호출로 연결 상태를 다시 검증한다.

**Architecture:** 기존 Phase 1의 단일 HCX 호출, 요청별 제한 스키마,
결정론적 fail-closed 검증 구조를 유지한다. 모델의 자유도를 늘리거나 validator를
완화하지 않는다.

**Authorities:**

- `docs/planning/HARNESS.md`
- `docs/planning/decisions/ADR-0022-use-ontology-grounded-intent-resolution.md`
- `docs/planning/specs/2026-08-31-intent-resolver-design.md`
- `docs/planning/tasks/2026-08-31-stage-06-phase-1-intent-resolver-implementation-plan.md`

## Assumptions and constraints

- HCX-007은 `responseFormat`과 함께 `thinking.effort=none`을 요구한다.
- `entity_hints.mention_id`와
  `reference_hints.candidate_target_mention_ids`는 요청의
  `ResolverView.entity_candidates`가 제공한 mention ID만 선택할 수 있다.
- API 키, 원문 모델 응답, 질문별 상세 출력은 저장하거나 Git에 추가하지 않는다.
- QueryPlan compiler, 라우팅, Orchestrator, candidate recall 개선은 비범위다.
- live 검증은 12개 소규모 연결 스모크 테스트이며 Phase 1 승격 기준을 대체하지
  않는다.

## Success criteria

- [x] adapter가 정확히 한 번의 요청에 `thinking: {effort: none}`을 포함한다.
- [x] 동적 응답 스키마가 제공된 entity/semantic target mention ID만 허용하고,
      해당 종류의 후보가 없으면 mention ID 배열을 `maxItems: 0`으로 닫는다.
- [x] 변경 전 focused test가 의도한 이유로 실패하고 변경 후 통과한다.
- [x] 전체 intent/evaluation/contract 관련 비실시간 검사가 통과한다.
- [x] production adapter를 사용한 12개 HCX-007 요청의 성공률, validation 결과,
      latency와 token 집계만 보고한다.
- [x] 최종 diff와 Git 상태에서 자격증명 및 생성된 실호출 artifact가 없다.

## Tasks

### 1. HCX 요청 계약을 테스트로 잠근다

- `tests/intent/test_clova.py`에서 `thinking.effort=none`을 요구한다.
- RED를 확인한 뒤 `src/financial_agent/intent/clova.py`에 해당 필드만 추가한다.

### 2. mention ID 경계를 테스트로 잠근다

- `tests/intent/test_prompt.py`에 제공 후보/무후보 양쪽 schema 단언을 추가한다.
- RED를 확인한 뒤 `src/financial_agent/intent/prompt.py`가 entity mention ID를
  요청별 enum으로 제한하도록 수정한다.

### 3. 회귀 및 live preflight를 재실행한다

- focused test부터 전체 관련 비실시간 검사 순으로 실행한다.
- 저장소 밖 임시 runner로 simple/compound/context/OOD 각 3개, 총 12개를
  production adapter에 통과시킨다.
- 집계 결과만 남기고, 실패 시 추가 구현 전에 원인을 분리한다.

### 4. 실호출에서 드러난 schema/validator 간극을 닫는다

- HCX가 자유형 설명을 `Identifier` 필드에 쓰지 않도록 reason code를 제한된
  enum으로 제공한다.
- 동일 입력의 평가 재현성을 위해 승인된 HCX 설정의 `seed=42`를 요청에
  포함한다.
- slot kind별로 선택 가능한 value ID 집합을 분리해 entity/concept/literal
  ID 종류가 섞이지 않게 한다.
- 모델이 근거 문자열은 정확히 복사했지만 Unicode offset만 틀린 경우, 해당
  문자열이 원문 segment에 정확히 한 번 존재할 때만 offset을 결정론적으로
  정규화한다. 0회 또는 여러 번이면 기존처럼 fail closed 한다.
- lexical/domain OOD 상태 표현은 별도의 계약 변경이므로 이번 보정으로 숨기지
  않고 live 결과의 잔여 blocker로 기록한다.
