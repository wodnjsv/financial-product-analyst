# ADR-0007: Use a Normalized Evidence Ledger and Structured Answer Plans

**Date:** 2026-08-17

**Status:** Accepted

**Related:** [ADR-0005](ADR-0005-bounded-llm-typed-capability-execution.md), [ADR-0006](ADR-0006-separate-disposition-and-bound-recovery.md)

## Context

금융 답변의 JSON 형식이 유효해도 수치·단위·날짜·출처가 실제 근거와 다를 수 있다. Answer Composer가 자유 문장과 출처 문자열을 쓰고 나중에 Claim ID만 확인하면, 잘못된 수치에 올바른 ID가 붙는 경우를 결정론적으로 막기 어렵다.

또한 주최측 데이터, 외부 공식 데이터, Graph 관계, 문서 구절, 환율 환산, 순위와 유사도가 한 답변에 함께 사용된다. 요청별 자유 JSON에 이 모든 것을 복사하면 중복·불일치·역추적 문제가 생긴다. 전체를 Graph에 넣으면 수치·계산·감사 조회가 필요 이상으로 복잡해진다.

## Decision

### Use PostgreSQL as the normalized evidence ledger

PostgreSQL `evidence` 스키마에 다음 논리 구조를 둔다.

- `SourceRecord`: 제공기관, 공식성, 원본 위치, 체크섬
- `EvidenceRecord`: 직접값, 관계, 문서 구절, 검색 범위, 제외, 정책 근거
- `CalculationRecord`: 입력·수식·정책·결과가 결합된 파생 계산
- `AtomicClaim`: 하나의 주체·속성·값 또는 관계를 담은 원자적 주장
- `ClaimSupport`: Claim과 Evidence·Calculation의 다대다 연결

Graph DB는 관계 탐색을 위한 투영본으로 유지하고 PostgreSQL relation·evidence ID를 가리킨다. Vector와 Keyword 검색은 문서 후보를 찾지만, 원문 위치와 출처가 확인된 `EvidenceRecord`로 변환된 뒤에만 Claim을 지지한다.

### Build immutable request-scoped EvidenceBundles

`EvidenceBundle`은 원본을 복사하는 대신 요청에 사용된 Evidence, Calculation, Candidate Claim, 제외와 한계 ID를 묶는다. Bundle은 `dataset_version`, 컷오프, 해시로 고정하고 생성 후 수정하지 않는다.

### Generate atomic claims deterministically

LLM은 Claim을 만들지 않는다. Capability별 생성 등록부가 승인된 Claim 유형과 필수 근거를 적용한다. 파생 Claim은 승인된 `CalculationRecord`와 모든 입력 근거까지 연결된다.

### Verify structured claims with deterministic rules

Verifier는 계약·버전, 출처·공식성, 시간·컷오프, 온톨로지·관계, 계산·비교 가능성, 커버리지·정책 순서로 Claim을 검사한다. 검증된 Claim ID만 `releaseable_claim_ids`에 넣는다.

Graph 0건으로 관계 부재를 단정하지 않는다. 완전성이 정의된 `closed_world_scope`와 완료된 검색 근거가 있어야 부재 주장을 허용한다.

### Replace free-form AnswerDraft with structured AnswerPlan

ADR-0005의 `AnswerDraft`는 이제 `AnswerPlan`이라는 정확한 계약으로 해석한다. Answer Composer는 승인된 Claim ID, 블록, 템플릿, 열, 배치만 선택한다. 상품명, 수치, 날짜, 단위, 계산, 출처 문자열을 만들 수 없다.

Claim Gate는 `AnswerPlan`의 Claim·블록·열·커버리지를 타입 규칙으로 검사한다. Renderer가 검증된 원장에서 `answer`, `retrieved_context`, `think_trace`를 모두 생성한다.

## Reasons

- 최종 표 셀에서 공식 원문까지 역추적할 수 있다.
- 단순 수치와 파생 계산의 입증 방식을 분리한다.
- Composer의 환각된 값·날짜·출처가 출시되는 경로를 제거한다.
- 요청별 중복 원본을 줄이면서 동일 근거를 여러 Claim에 재사용한다.
- Graph는 관계 탐색, PostgreSQL은 수치·계산·감사 조회에 집중한다.
- 같은 원장에서 세 평가 문자열을 만들어 서로 다른 출처를 말하는 문제를 막는다.

## Rejected Alternatives

### Store one nested JSON evidence object per request

구현은 빠르지만 원본·출처·계산이 중복되고, 근거 정정·충돌·재사용을 요청별로 다시 풀어야 한다.

### Store all evidence and calculations in Graph DB

관계 경로는 자연스럽지만 시계열 값, 정렬 모집단, 계산 입력, 감사 레코드의 무결성과 조회가 복잡해진다.

### Let the Composer write prose with inline claim tags

표현은 자유롭지만 잘못된 숫자와 올바른 Claim ID를 같이 쓸 수 있다. 자연어를 다시 해석하는 LLM Verifier를 추가하면 지연과 비결정성이 늘어난다.

### Let a second LLM judge claim support

같은 모델 계열의 오류를 복제하고 검증 결과를 정확히 재현하기 어렵다. 수치·식별자·시간·출처는 규칙 엔진이 권위를 갖는다.

## Consequences

### Positive

- 숫자, 관계, 문서, 계산, 부재, 한계를 하나의 추적 모델로 검증한다.
- `answer`, `retrieved_context`, `think_trace`의 정합성을 구조적으로 보장한다.
- Composer 장애 시에도 검증된 Claim을 결정론적으로 출력할 수 있다.
- 52개 질문 유형을 Claim 유형·검사 규칙·출력 템플릿으로 나눠 테스트할 수 있다.

### Costs and risks

- Claim 유형별 생성기와 표시 정책을 구현해야 한다.
- 템플릿 등록부가 질문 유형을 보전하지 못하면 답변 표현이 제한될 수 있다.
- 근거·계산·Claim 해시와 버전 정책을 운영해야 한다.
- 표 셀까지 Claim을 연결하므로 단순 자유 텍스트 응답보다 초기 구현량이 많다.

## Preserved Decisions

- 정상 경로의 LLM은 Intent Resolver와 Answer Composer 두 번을 넘지 않는다.
- 결정론적 Orchestrator가 실행·재시도·마감을 소유한다.
- `ExecutionOutcome`, `VerificationStatus`, `AnswerDisposition`을 분리한다.
- 필터, 정렬, 순위, 집계, 환산, 유사도는 LLM 밖에서 계산한다.
- 주최측 원본, 외부 수집 스냅샷, 로컬 DB와 임베딩은 Git에 커밋하지 않는다.

## Detailed Design

정확한 논리 필드, 검증 순서, Claim Gate, Renderer, 테스트 기준은 [Evidence, Verification, and Rendering Design](../architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md)을 따른다.
