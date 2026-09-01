# Intent Resolver Phase 1 비라이브 검증 보고서

**Measured:** 2026-09-01; promotion/container hardening fix reverified 2026-09-01

**Resolver implementation base:** `397b731ba60cd4fee9532962a6a19287cc0643dc`

**Measured hardened code revision:** `4d41325f47c36318820bb950335c234728604936`

**Status:** Phase 1 implemented; promotion blocked

**Scope:** 로컬 비라이브·폐기 가능 PostgreSQL 검증만 수행

검증 tree는 위 base와 이 보고서를 포함하는 Task 12 변경으로 구성된다. 이
보고서는 집계 결과만 기록한다. 질문 원문, 모델 응답, chain of thought,
자격증명, 계정 식별자, 주최 측 원본 데이터는 포함하지 않는다. 이 보고서를
포함하는 Git 커밋은 자기 참조 해시 대신 저장소 이력으로 식별한다.

## 1. 검증 경계

- 실행 호스트: macOS `arm64`
- Python: CPython `3.12.13`
- PostgreSQL: Homebrew PostgreSQL `15.19`, 임시 디렉터리와 임의 로컬 포트
- HyperCLOVA X/NCP: 호출하지 않음
- Linux/amd64 컨테이너: 실행하지 않음
- QueryPlan compiler·Orchestrator: 구현하거나 검증하지 않음

컨테이너 검증 정의는 명시적 `COPY` allowlist, 비라이브 명령 체인, 기존
PostgreSQL health dependency, 테스트 DB URL만 포함한 Compose 환경을 사용한다.
`.env`, `data/`, 주최 측 PDF·workbook, build report, raw response, 로컬 DB,
Parquet, index/vector/model cache, credential, Git metadata는 build context에서
제외한다.

## 2. TDD 근거

첫 RED에서 새 경계 테스트는 `12 failed, 1 passed`였다. 실패 원인은 resolver
Dockerfile·Compose service·민감 입력 ignore 규칙·fail-closed promotion API가
없었기 때문이다. unsafe `COPY .`와 `|| true`를 거부하는 음성 정책 테스트만
통과했다.

최소 구현 후 focused 결과는 `13 passed`였다. 그 뒤 컨테이너 내부 정적 테스트에
필요한 세 입력이 image에 없다는 추가 RED `1 failed`를 만들고,
`.dockerignore`, resolver Dockerfile, Compose 파일만 allowlist에 추가해 다시
GREEN을 확인했다. 잘못된 platform·lock·install·marker·DB-manifest 명령과
coverage/metric denominator 불일치를 각각 거부하는 추가 RED는 `6 failed`였고,
최종 focused 결과는 `19 passed`다. 새 Compose service로 인해 기존 service 수를 정확히
2로 가정하던 DB 테스트의 RED `1 failed`도 기존 `postgres`와 `db-check`를
각각 검사하도록 최소 수정했다.

### Review fix round 1

리뷰에서 promotion 증거가 고정 평가 모집단에 결합되지 않아 작은 완벽 표본으로
통과할 수 있고, Docker CMD 정책이 승인 명령의 존재만 검사해 조기 성공·pipe·순서
변경을 허용할 수 있음이 확인됐다. 회귀 테스트를 먼저 추가한 focused RED는
`14 failed, 26 passed`였다. 실패는 runtime contracts gate 누락 1건,
`exit 0;`·`| true`·gate 순서/중복·DB 조건 반전 5건, 작은 모집단·누락/오류 dataset
SHA·고정 모집단 불일치 8건이었다.

최소 수정 후 focused GREEN은 `40 passed`다. Promotion 판정은 frozen v3 dataset
SHA와 정확한 metric·coverage 모집단을 함께 요구한다. Docker CMD는 schema 두 개,
intent/evaluation, runtime contracts, 선택적 DB migration·정확한 DB test·object
manifest 순서의 한정된 실패 전파 체인만 허용한다. 정책은 `sh -n`과 semantic
token 비교로 조기 `exit`, 세미콜론, pipe/background, `||`, gate 누락·순서 변경·
중복·조건 반전·추가 명령을 거부한다.

### Review fix round 2

후속 리뷰는 Pydantic `model_copy`·`model_construct`로 validation을 우회한 기존
`PromotionEvidence` 인스턴스가 판정기에 직접 전달될 수 있음을 확인했다. 새
focused RED는 `9 failed, 41 passed`였다. Top-level extra, nested float·bool·string,
음수·분자 초과, invalid coverage, 잘못된 nested type, subclass가 정상 계약 경계로
재검증되지 않는 실패를 재현했다.

판정기 입구는 exact `PromotionEvidence` type과 actual stored field key 집합을 먼저
검사한 뒤, declared stored value를 primitive JSON으로 직렬화하고 strict
`model_validate_json` 경계를 다시 통과시킨다. Pydantic typed serializer가 우회
저장된 bool을 `1/0`으로 바꾸는 중간 실패 `2 failed, 48 passed`도 확인해 raw
stored primitive를 보존하는 JSON encoder로 보정했다. 최종 focused GREEN은
`50 passed`다. Invalid evidence는 승격 결과를 반환하지 않고 예외로 fail-closed한다.

## 3. 재현 가능한 로컬 검증

| Gate | 실행 명령 요약 | 측정 결과 |
| --- | --- | --- |
| Container/promotion focused | `pytest tests/intent/test_container_verification.py -q` | `50 passed` |
| Intent non-live | `pytest tests/intent -m 'not clova_integration' -q` | `202 passed, 1 deselected` |
| Evaluation | `pytest tests/evaluation/intent -q` | `46 passed` |
| Runtime contracts | `pytest tests/contracts -q` | `225 passed` |
| Contract schema freshness | `python scripts/export_contract_schemas.py --check` | exit `0` |
| Intent schema freshness | `python scripts/export_intent_schemas.py --check` | exit `0` |
| Python compile | `python -m compileall -q src tests/intent tests/evaluation/intent` | exit `0` |
| Migration cycle | `python scripts/verify_database_migrations.py` | prior Task 12: head `0007`, exit `0`; fix round not rerun |
| Database non-live | `pytest tests/db -m 'not performance and not ncp_integration' -q` | prior Task 12: `492 passed, 5 deselected`; fix round not rerun |
| Database object manifest | `python scripts/export_database_objects.py --check --database-url-env FINANCIAL_AGENT_TEST_DATABASE_URL` | prior Task 12: exit `0`; fix round not rerun |
| Broad non-live | approved seven-marker exclusion command | `1171 passed, 1 expected PostgreSQL skip, 376 deselected` |
| Deterministic evaluation CLI | `scripts/evaluate_intent_resolver.py --mode deterministic` | exit `0` |
| Fixture/label freeze | literal hashes and v2→v3 candidate-label preservation | `2 passed` |

Broad non-live 명령은 `postgres`, `organizer_data`, `object_storage`,
`official_data`, `ncp_integration`, `jena_integration`, `clova_integration`
marker를 제외했다. 이 제외된 범위를 통과로 해석하지 않는다.

두 fix round는 promotion 판정·container policy/Docker CMD·focused test만
변경했다. Migration, repository, SQL, Alembic, DB manifest 동작은 변경하지
않았으므로 disposable PostgreSQL을 재기동하지 않았다. 아래 PostgreSQL 결과는
최초 Task 12의 실측이며 fix round의 새 실행으로 표현하지 않는다.

### PostgreSQL 생명주기

임시 클러스터는 `mktemp` 하위에 생성하고 사용 가능한 임의 loopback port를
선택했다. `0001 → 0007 → base → 0007` migration, 두 번의 Alembic no-drift,
repository 테스트와 object manifest 검사를 수행했다. 최종 객체 집계는
checks `125`, foreign keys `86`, functions `22`, indexes `90`, tables `39`,
triggers `62`, views `1`이다. PostgreSQL을 초기화한 실행은 종료 trap을
사용했고 최종 실행에서 `POSTGRES_STOPPED`와 `POSTGRES_TEMP_REMOVED`를
확인했다. sandbox가 loopback port preflight를 거부한 첫 시도에서 만들어진
빈 임시 디렉터리 한 개도 최종 audit에서 `rmdir`로 제거했으며 Task 12 임시
디렉터리가 남지 않았음을 다시 확인했다.

## 4. 결정론적 산출물 provenance

| 항목 | 값 |
| --- | --- |
| Catalog version | `semantic-query-catalog.v1` |
| Catalog hash | `c1e88ebd353e6306e8f61f4bef31d23fbed802adf4811a8ea287e40dbde73076` |
| Overlay version | `korean-nlu-overlay.v1` |
| Overlay hash | `a157a8ad4bdce11636f68d30b544038fef70ec8ef4a7c24aca5f12f7d9d60c45` |
| Candidate policy | `intent-candidate-v1` |
| Normalizer | `intent-normalizer-v1` |
| Resolver schema | `1.0` |
| Build manifest hash | `378c49ca88dff4d6bab61bdf86eb3f236afa4489fb4547b37c601e640587ba91` |
| Dataset | `intent-resolver-heldout-ko-v3`, 160 cases |
| Dataset SHA-256 | `f0cb6313d7954a9f75d1fe1c691a2021c0b2e53d6681f07eb0f3e2787a9944b4` |
| Measured build revision | `4d41325f47c36318820bb950335c234728604936` |
| Deterministic report hash | `82de4aceadb2372f1e90bd5e6b2348af21d8d2bc852b6d8caa59ef2199dc6e04` |
| Prompt/adapter/model | deterministic mode에서 not applicable; live 미실행 |

결정론적 report는 `build_revision`을 provenance에 포함한다. 이전 Task 12의
`0cd299812c4457ce9311e57542106a0e8740ffdfd31820612e67cce0fc63417c`
hash는 당시 측정 HEAD `397b731ba60cd4fee9532962a6a19287cc0643dc`에
결합됐다. Round 1 code revision `8abd38f...`의 report hash는 `467429f...`였다.
Round 2 promotion trust-boundary 코드·테스트를 먼저 `4d41325...`로 커밋한 뒤 그
clean code revision에서 fresh CLI를 실행했으므로 최신 report는 해당 SHA를
`build_revision`으로 기록한다. 이 provenance 변화로 report hash가 바뀌었고,
candidate 결과와 catalog·ontology·dataset·build manifest hash는 변하지 않았다.
이 보고서 자체의 revision은 Git 이력으로 식별하며 measured code revision과
구분한다.

Ontology hashes는 build manifest에 결합되어 있으며 개별 값은 다음과 같다.

| Ontology input | SHA-256 |
| --- | --- |
| `ontology/common.ttl` | `0ec989031086b4c1f3cc9d38e1cbf35a122a0b75584629d01c8206552a7195c0` |
| `ontology/bond_kr.ttl` | `4ef7dd8f8aaa838fadb62e48b22ebb5266b4341783daaaa3cce5dda7bf854d2f` |
| `ontology/etf_kr.ttl` | `6de17457fc1c7f608f8abbd75d68ac41b1b2bf184cc23497e184094b18ae7e1c` |
| `ontology/etf_gl.ttl` | `db2b23b5269a270cfc66c91c29f6776c18c5f32181394bc6b79c3cf6f444018d` |
| `ontology/fund_pub.ttl` | `67c6202f465234b85d1ab57234c523f93000a3d14a10c1ccc5db4585e7425c5d` |
| `ontology/shapes/common.shacl.ttl` | `22d84ef670ec875a8a6cafe65b69ce95b3cb961aac60daeb295b19f3c749389` |
| `ontology/shapes/domain.shacl.ttl` | `9d33f6cbb97714379396b24290306a661da947be3c12a5e3e6c28c6dd2c31eee` |

## 5. Promotion 판정

모든 gate는 frozen v3 dataset SHA와 그 fixture에서 파생된 정확한 모집단에
결합되고 threshold를 만족해야 한다. Unknown/invalid probe denominator는 각각
`10`, probe coverage는 `20/20`, candidate reproducibility와 coverage는
`155/155`, recall@5 denominator는 `196`, first-pass denominator는 `155`,
frame/context denominator는 각각 `160`, OOD denominator는 `30`이다. 다른 SHA,
다른 모집단, 불완전 coverage, `0/0`, 누락 metric은 통과가 아니라
`unmeasured`다.

| Stable gate name | Threshold | Evidence | Status |
| --- | --- | --- | --- |
| `unknown_registered_id_acceptance` | `= 0` | live/stored validation evidence 없음 | `unmeasured` |
| `invalid_context_graph_acceptance` | `= 0` | live/stored validation evidence 없음 | `unmeasured` |
| `deterministic_candidate_reproducibility` | `= 100%` | `155/155` with coverage `155/155` | `passed` |
| `candidate_recall_at_5` | `>= 99%` | `118/196` (`60.2040816%`) | `failed` |
| `first_pass_structured_output_validity` | `>= 99%` | live model evidence 없음 | `unmeasured` |
| `held_out_joint_frame_exact_match` | `>= 90%` | live model evidence 없음 | `unmeasured` |
| `held_out_context_link_exact_match` | `>= 95%` | live model evidence 없음 | `unmeasured` |
| `ood_false_fast_rate` | `<= 2%` | live model evidence 없음 | `unmeasured` |

자동 판정 결과는 `eligible=false`다. 안정적인 blocker 이름은 다음과 같다.

```text
unknown_registered_id_acceptance
invalid_context_graph_acceptance
candidate_recall_at_5
first_pass_structured_output_validity
held_out_joint_frame_exact_match
held_out_context_link_exact_match
ood_false_fast_rate
```

Candidate recall 실패 하나만으로도 승격은 차단된다. threshold, validator,
fixture, gold label은 변경하지 않았다.

## 6. 실행하지 않은 검증과 제한

Runtime discovery 결과는 다음과 같다.

```text
docker: command not found
podman: command not found
nerdctl: command not found
finch: command not found
colima: command not found
```

따라서 `docker build --platform linux/amd64`, `docker run`, `docker compose`
명령은 **not run**이다. 정적 container test 통과를 Linux/amd64 실행 성공으로
표현하지 않는다.

Live HCX 호출은 사용자 비용 승인 checkpoint 전이므로 **not run**이다. 모델 ID,
Structured Outputs 실제 지원, first-pass validity, frame/context/OOD metric,
p50/p95 latency, token 합계, repair 수와 비용은 모두 `unmeasured`다. NCP,
organizer/official data, Object Storage, Jena도 이 보고서의 완료 근거로
실행하지 않았다.

## 7. 저장소 경계

커밋 전 staged diff는 승인된 Task 12 경로 8개뿐이었다. `git diff --cached
--check`는 exit `0`이었고, 추가된 줄의 bearer token·private key·`sk-` 패턴
검사와 staged 경로의 `data/`·`.env`·PDF/workbook·DB·Parquet·N-Quads·vector/
model cache·build/raw-response/credential 경로 검사는 일치 항목이 없었다.
생성된 deterministic JSON report는 기존 `build/` ignore 경계에 남기고
stage하지 않았다.

Round 1 code commit에는 Dockerfile·promotion evaluator·focused test 세 경로만,
Round 2 code commit에는 promotion evaluator·focused test 두 경로만 stage했다.
Documentation commit은 이 보고서와 STATUS 두 경로뿐이다. 각 staged diff의
`--check`는 exit `0`이었고 동일한 secret·data/generated-path scan은 일치 항목이
없었다. Ignored progress/task report와 generated deterministic JSON은 tracked
commit에 포함하지 않았다.

## 8. 결론

Intent Resolver Phase 1 구현은 로컬 비라이브·PostgreSQL 경계에서 검증됐다.
Fix round는 고정 모집단 promotion 판정, invalid existing-instance 재검증,
container 실패 전파 정책을 추가로 검증했지만 Docker runtime은 여전히 없어
Linux/amd64 실행은 하지 않았다. Default 승격은 `candidate_recall_at_5` 실패와
여섯 required gate의 미측정 상태로 차단된다. 다음 상태는 live HCX
checkpoint이며, 별도 사용자 승인 없이는 호출하지 않는다.
