# Stage 04 Graph Phase 1 설계

**Date:** 2026-08-30

**Status:** Approved direction 2026-08-30; written specification review pending

**Scope:** Vector 문서 코퍼스와 아직 확보되지 않은 공식 관계 데이터를 기다리지
않고 구현할 수 있는 최소 TBox·SHACL·RDF ABox 투영·로컬 Fuseki/TDB2 검증

**Related:** [Planning Harness](../HARNESS.md),
[Competition Stage Roadmap](../ROADMAP.md),
[Financial Ontology Architecture](../architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md),
[NCP Deployment Architecture](../architecture/NCP_DEPLOYMENT_ARCHITECTURE.md),
[ADR-0018](../decisions/ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md),
[ADR-0021](../decisions/ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md),
[Question Capability Contract](2026-08-29-question-capability-contract-normalization-design.md)

## 1. 문제

현재 PostgreSQL에는 버전화된 canonical entity, `relation.relation_record`,
Evidence 원장과 `operations.dataset_readiness`가 구현되어 있다. 질문 계약 schema
`1.3`은 52개 질문 중 Graph 경로가 필요한 23개 질문을 승인된 13개 domain
predicate로 제한한다. 그러나 제출용 TTL, SHACL, RDF ABox 변환기, Fuseki 설정,
SPARQL 읽기 경로는 아직 없다.

Vector 문서 코퍼스는 별도 작업에서 구현 중이다. 전체 Stage 04 완료를 기다리면
문서와 독립적인 운용사·발행사·지수·보유종목·펀드클래스 관계의 Graph 구현과
검증도 불필요하게 지연된다. 반대로 현재 데이터를 최종 Graph로 활성화하면
미확보 기업·상장·테마·문서 관계를 완료된 것으로 오해할 수 있다.

## 2. 목표와 비목표

### 목표

1. ADR-0018·0021의 클래스와 13개 predicate를 제출 구조의 TTL로 구현한다.
2. domain/range, 배타·복수 typing, 관계 Evidence와 시간 조건을 SHACL로 검증한다.
3. PostgreSQL entity·relation·Evidence 행을 결정론적 RDF named graph로 투영한다.
4. 같은 입력에서 바이트가 동일한 N-Quads와 component manifest를 생성한다.
5. RDFLib·pySHACL 기본 테스트와 Apache Jena 6 호환성 테스트를 모두 제공한다.
6. TDB2 적재와 읽기 전용 Fuseki SPARQL smoke path를 로컬에서 검증한다.
7. 현재 확보된 관계만 지원하고 미확보 관계는 명시적인 coverage로 남긴다.

### 비목표

- 문서 임베딩, pgvector 또는 Keyword 인덱스 구현
- `documentedBy`, `hasRiskFactor`의 최종 DocumentChunk 연결
- 기업 지배·상장·산업·테마·지수 구성종목의 새 공식 데이터 수집
- Stage 05 federated retrieval 또는 금융 계산 구현
- NCP Fuseki 배포, 공개 endpoint, HA, 백업·복구 훈련
- PostgreSQL migration 또는 organizer·공식 원천 재적재
- `operations.active_dataset` 변경이나 데이터 버전 활성화
- 23개 Graph 질문 전체의 실데이터 지원 완료 선언

## 3. 선택한 접근

### 3.1 Hybrid validation

기본 개발·CI 게이트는 Python 3.12의 RDFLib `7.x`와 pySHACL `0.40.x`를
사용한다. 이 게이트는 Docker나 외부 서버 없이 TTL 파싱, SHACL 양·음성 fixture,
N-Quads 결정성과 SPARQL competency query를 반복 검증한다.

실제 런타임 호환성 게이트는 Java 21 이상과 Apache Jena/Fuseki `6.0.x` binary
distribution을 사용한다. 저장소에 Jena binary나 TDB2 데이터를 커밋하지 않고,
검증 runner가 `JENA_HOME`과 `FUSEKI_HOME`을 입력으로 받아 다음 공식 명령을
실행한다.

```text
riot
shacl validate
tdb2.tdbloader
tdb2.tdbquery
fuseki-server
```

Mac의 Docker 부재는 기본 게이트를 막지 않는다. Jena gate는 로컬 Java 24 또는
후속 Linux 검증 환경에서 같은 fixture와 query를 재사용한다.

### 3.2 기각한 접근

#### Jena-only 필수 게이트

실제 엔진과 가장 가깝지만 모든 빠른 테스트가 다운로드된 binary와 서버 수명
주기에 의존한다. 현재 Vector·Stage 03 작업과 병행하기에는 피드백 시간이 길고
개발 환경 재현성이 낮아 기본 게이트로 사용하지 않는다.

#### Python in-memory graph만 구현

빠르지만 실제 TDB2 적재, named graph, Fuseki endpoint와 Jena SHACL 차이를
검증하지 못한다. 제출·배포 엔진이 Apache Jena로 승인되어 있으므로 최종
호환성 게이트를 생략하지 않는다.

#### 관계를 Fuseki의 권위 사실로 직접 적재

PostgreSQL의 RelationAssertion·Evidence 권위를 깨고 복구·버전 활성화를 어렵게
하므로 기각한다. Fuseki는 언제든 PostgreSQL에서 재생성 가능한 투영본이다.

## 4. 논리·물리 경계

### 4.1 TBox와 제어 어휘

온톨로지 ID는 ADR-0018의 `urn:ontology:financial-product:v1`을 유지한다. 다음
제출 파일을 만든다.

```text
ontology/
├─ common.ttl
├─ bond_kr.ttl
├─ etf_kr.ttl
├─ etf_gl.ttl
├─ fund_pub.ttl
└─ shapes/
   ├─ common.shacl.ttl
   └─ domain.shacl.ttl
```

`common.ttl`은 공통 클래스, 13개 predicate, RelationAssertion, Evidence 연결과
시간·버전 property를 소유한다. 상품군 TTL은 공통 클래스를 재정의하지 않고
해당 상품군의 subclass, 허용 복수 typing과 제어 어휘만 추가한다.

`ProductRiskGrade`와 `CreditGrade`는 별도 스킴이다. `Region`, `AssetClass`, 통화,
상태, 적격성, 환헤지, 공모 유형과 금리 구조는 controlled attribute vocabulary로
정의하되 상품별 값을 Graph 권위 사실로 복제하지 않는다.

### 4.2 ABox named graph

한 dataset version은 두 개의 named graph를 가진다.

```text
urn:data:financial-product:{dataset_version}
urn:evidence:financial-product:{dataset_version}
```

Data graph에는 entity typing, 승인 direct edge와 `RelationAssertion` node를
넣는다. Evidence graph에는 SourceRecord·Evidence 식별자와 relation assertion의
근거 연결만 넣는다. 원문 payload와 비밀 locator는 넣지 않는다.

IRI 규칙은 다음과 같다.

```text
entity:             urn:financial-agent:entity:{percent_encoded_entity_id}
relation assertion: urn:financial-agent:relation:{dataset_version}:{percent_encoded_relation_id}
evidence:           urn:financial-agent:evidence:{dataset_version}:{percent_encoded_evidence_id}
source:             urn:financial-agent:source:{dataset_version}:{percent_encoded_source_id}
```

canonical entity IRI에는 dataset version을 넣지 않는다. typing과 edge는 named
graph가 버전화한다. Relation, Evidence와 Source는 버전별 불변 record이므로 IRI에
dataset version을 포함한다. 모든 동적 ID segment는 UTF-8 percent encoding을
사용하며 역변환 가능해야 한다.

### 4.3 Direct edge와 RelationAssertion

질의 편의를 위한 direct edge와 감사 가능한 assertion node를 함께 생성한다.

```text
ProductA  fp:holdsSecurity  SecurityB .

RelationH001 a fp:RelationAssertion ;
  fp:subject ProductA ;
  fp:predicate fp:holdsSecurity ;
  fp:object SecurityB ;
  fp:relationId "relation-H001" ;
  fp:datasetVersion "2026-08-24-v1" ;
  fp:validFrom "2026-08-22"^^xsd:date ;
  fp:supportedBy EvidenceH001 .
```

한 relation에 Evidence가 여러 개면 assertion node 하나에 `supportedBy`를 여러
번 기록한다. `relation.relation_record.relation_id`가 질문 계약의
`relation_assertion_id` 역할을 한다. direct edge만 반환한 결과는 Claim 근거가
될 수 없으며, SPARQL competency query는 같은 subject·predicate·object의
assertion과 Evidence ID를 함께 반환해야 한다.

## 5. 투영 데이터 흐름

```text
PostgreSQL read-only snapshot
  → entity rows
  → approved relation rows
  → evidence_relation_origin + evidence_record + source_record
  → typed projection records
  → IRI·literal validation
  → sorted N-Quads
  → RDF parse + SHACL validation
  → graph component manifest
  → TDB2 temporary load
  → SPARQL competency queries
  → optional local read-only Fuseki smoke test
```

PostgreSQL 조회는 하나의 `dataset_version`을 명시하고 read-only transaction에서
실행한다. exporter는 승인된 13개 predicate allowlist 밖의 relation을 만나면
해당 edge를 생략하지 않고 전체 빌드를 실패시킨다. subject·object entity,
relation Evidence, source 또는 dataset version이 일치하지 않아도 실패한다.

N-Quads는 normalized IRI와 literal을 lexical order로 정렬하고 LF newline로
끝낸다. manifest는 다음 입력의 SHA-256을 포함한다.

- ontology와 SHACL 파일별 hash
- data N-Quads hash
- evidence N-Quads hash
- exporter version
- dataset version과 cutoff date
- predicate별 assertion 수
- entity type별 node 수
- validation report hash

Phase 1은 manifest를 계산하고 검증하지만 `record_dataset_readiness`나
`activate_dataset`을 호출하지 않는다. Graph·Vector·Evidence component가 같은
최종 데이터로 검증되는 후속 단계에서만 readiness를 기록한다.

## 6. SHACL 경계

공통 shape는 다음을 검증한다.

- 13개 predicate의 domain과 range
- 모든 assertion의 subject·predicate·object·relation ID·dataset version
- assertion마다 하나 이상의 Evidence 연결
- `valid_to >= valid_from`
- dataset cutoff 이후의 적용·유효·게시·가용 날짜 금지
- `documentedBy` domain은 `FinancialProduct`, `Organization`, `PolicyProgram`
- `hasRiskFactor`는 DocumentChunk span Evidence 없이는 최종 적격으로 보지 않음

도메인 shape는 다음을 검증한다.

- `ETF`와 `ETN` 동시 typing 금지
- 공식 exact identity가 있는 `DomesticETF`와 `FundShareClass` 복수 typing 허용
- `ProductRiskGrade`와 `CreditGrade` 스킴 분리
- 신용등급 순서 값은 `credit_grade_v1`에만 허용
- 보유비중 요구 relation은 적용일과 weight observation 연결 필요

문서와 위험요인 shape는 Phase 1에 정의하지만, 실제 문서 ABox가 없는 fixture
외에는 적재하지 않는다. 이를 통해 Vector 완료 후 vocabulary 변경 없이 같은
shape에 실제 DocumentChunk Evidence를 연결한다.

## 7. SPARQL 읽기 경계

Phase 1 read client는 query endpoint만 노출한다. update, delete, admin endpoint는
애플리케이션 API에서 사용할 수 없다. 최소 반환 필드는 다음과 같다.

```text
subject_id
predicate_id
object_id
relation_assertion_id
evidence_id
dataset_version
valid_from
valid_to
```

현재 데이터로 검증할 competency path는 다음과 같다.

- 상품 → `managedBy` → 운용사
- 채권·상품 → `issuedBy` → 발행사
- ETF·펀드 → `tracksIndex` → 지수
- ETF → `holdsSecurity` → 증권
- 대표펀드 → `hasShareClass` → 펀드클래스

13개 predicate 모두에는 합성 양성·음성 fixture를 둔다. 실제 원천이 없는
predicate는 합성 fixture 통과를 실데이터 지원으로 표현하지 않는다.

Graph 0건은 `closed_world_scope`와 완료된 조회 Evidence가 없으면 관계 부재가
아니다. client는 빈 binding과 함께 dataset version·query ID·coverage 상태를
반환하며 자연어 결론을 생성하지 않는다.

## 8. 오류 처리

다음 오류는 Graph build 전체를 실패시킨다.

- 승인 predicate 밖의 relation
- IRI로 안전하게 정규화할 수 없는 식별자
- subject 또는 object entity 부재
- relation Evidence 또는 SourceRecord 부재
- dataset version 불일치
- cutoff 이후 시간 값
- SHACL non-conformance
- 동일 입력의 manifest hash 불일치

Fuseki가 없거나 시작되지 않은 상태는 기본 RDF build 실패가 아니다. Jena
integration gate에서는 명시적인 환경 차단으로 보고하며 통과로 간주하지 않는다.
부분 적재된 TDB2 directory는 readiness 후보가 아니고 임시 경로에서 폐기 가능해야
한다.

## 9. 검증 전략

### 항상 실행하는 테스트

- 모든 TTL·SHACL parse
- 13개 predicate allowlist와 질문 계약 일치
- 각 domain/range의 양성·음성 fixture
- ETF/ETN 배타성과 ETF/FundShareClass 복수 typing
- 등급 스킴 분리
- Evidence·시간·버전 누락 실패
- entity·relation·Evidence projection unit test
- 입력 순서가 다른 동일 row 집합의 N-Quads·manifest byte equality
- RDFLib SPARQL competency query
- 기존 contract·DB·ingestion 비-live 회귀

### Jena integration gate

- `riot`으로 제출 TTL과 N-Quads parse
- `shacl validate` 결과 conforms 확인
- 임시 TDB2에 named graph load
- `tdb2.tdbquery`로 competency query 결과 확인
- `fuseki-server` read-only endpoint 시작
- HTTP SELECT 결과가 로컬 TDB2 결과와 일치하는지 확인
- update endpoint가 노출되지 않았는지 확인

Jena binary, TDB2 directory와 validation output은 추적하지 않는다. 테스트용 RDF
fixture만 저장소에 커밋한다.

## 10. 구현 파일 경계

```text
ontology/                         제출 TTL·SHACL
config/fuseki/                    read-only TDB2 assembler와 logging 설정
src/financial_agent/graph/
├─ contract.py                    predicate·IRI·projection record 계약
├─ repository.py                  PostgreSQL read-only projection 조회
├─ exporter.py                    결정론적 named graph N-Quads 생성
├─ validator.py                   RDF parse·pySHACL 결과 계약
├─ manifest.py                    graph component manifest
└─ client.py                      read-only SPARQL SELECT client
scripts/graph/verify_jena.py      외부 Jena binary 호환성 runner
tests/graph/                      unit·contract·SPARQL·Jena integration tests
tests/fixtures/graph/             합성 RDF·SHACL 양성·음성 fixture
```

Graph 모듈은 ingestion mapper를 import하지 않는다. PostgreSQL schema와 typed
projection contract만 경계로 사용한다. 기존 relation·Evidence 테이블을 변경하지
않으며 새 migration을 만들지 않는다.

## 11. 완료 기준

1. 제출 TTL 5개와 SHACL 2개가 RDFLib와 Apache Jena에서 parse된다.
2. 13개 predicate 이외의 Graph relation은 테스트와 exporter에서 거부된다.
3. 모든 direct edge가 같은 relation assertion과 하나 이상의 Evidence로
   역추적된다.
4. 동일 row 집합은 입력 순서와 무관하게 동일 N-Quads와 manifest를 만든다.
5. 양성 fixture는 SHACL conforms, 각 필수 위반 fixture는 non-conforms다.
6. 현재 확보된 5개 관계 path의 SPARQL 결과가 합성 expected binding과 일치한다.
7. Jena/TDB2와 Fuseki read-only smoke gate가 같은 query 결과를 반환한다.
8. Graph component는 readiness를 기록하거나 데이터셋을 활성화하지 않는다.
9. 전체 비-live 회귀가 기존 기준보다 감소하지 않는다.
10. 최종 diff에 원본 데이터, Jena binary, TDB2 파일, credential, Vector 구현,
    Stage 03 ingestion 변경 또는 PostgreSQL migration이 없다.

## 12. 후속 Phase 2 인계

Vector 문서 코퍼스와 남은 공식 관계 데이터가 완료되면 별도 승인 계획에서 다음을
추가한다.

- `documentedBy`, `hasRiskFactor` 실제 DocumentChunk Evidence
- `controlsCompany`, `listedOn`, `classifiedAsIndustry`,
  `associatedWithTheme`, `containsSecurity`의 승인 실데이터
- 23개 Graph 질문 전체의 dataset-relative coverage 검증
- PostgreSQL·Graph·Vector·Evidence manifest 일치
- `operations.dataset_readiness` 기록과 원자적 활성화·복구
- NCP Private Subnet Fuseki 배포와 실제 지연·복구 검증

Phase 2는 Phase 1 vocabulary를 확장하는 작업이 아니라 승인된 13개 관계에 실제
데이터와 문서 Evidence를 완성하는 작업이다. 새 predicate가 필요하면 기존 ADR을
조용히 수정하지 않고 별도 ADR과 질문 competency 근거를 요구한다.
