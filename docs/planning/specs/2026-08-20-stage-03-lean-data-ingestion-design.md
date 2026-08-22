# Stage 03 경량 데이터 수집·표준화 설계

**Date:** 2026-08-20

**Status:** Approved baseline

**Scope:** Stage 03 전체 경계와 Stage 03A 주최 측 4개 마스터 수집·표준화 구조

**Related:** [Competition Stage Roadmap](../ROADMAP.md), [Stage 02 PostgreSQL Plan](../tasks/2026-08-17-stage-02-postgresql-storage-implementation-plan.md), [ADR-0013](../decisions/ADR-0013-use-lean-source-specific-ingestion.md)

## 1. 결정 요약

Stage 03은 범용 데이터 플랫폼을 새로 만드는 단계가 아니다. 확정된 공식 금융 데이터를 `2026-07-11` 컷오프와 Stage 02 저장 계약에 맞게 재현 가능한 PostgreSQL 원장으로 만드는 단계다.

따라서 다음 경량 구조를 사용한다.

```text
읽기 전용 원본
    ↓ SHA-256·헤더·행 수 검사
SourceSpec + iter_workbook_rows
    ↓
소스별 명시적 순수 매핑 함수 4개
    ↓
정상 / 제한 / 격리 + 정규화 레코드
    ↓
DatasetBuildWriter
    ↓
Stage 02 PostgreSQL building 데이터셋
    ↓
BuildReport
```

새 규칙 DSL, YAML 매핑 언어, 범용 플러그인 프레임워크, 소스별로 복제된 독립 스크립트는 만들지 않는다. 새 서비스 클래스는 배치 쓰기 경계를 소유하는 `DatasetBuildWriter` 하나를 기본으로 하고, 나머지는 작은 불변 데이터 구조와 순수 함수로 구현한다.

## 2. Stage 03 하위 경계

### Stage 03A — 주최 측 4개 마스터

- 국내채권 `PRBD01N001`
- 국내 ETF·ETN `PREF01N001`
- 해외 ETF·ETN `PREF02N001`
- 공모펀드 `PRFD01N001`
- 네 원본의 필드 단위 매핑·결측·센티널·중복·단위·통화·날짜 규칙
- 답변 가능 사실의 Source·Evidence 계보
- 로컬 읽기 전용 원본과 NCP Private Object Storage 원본의 SHA-256 동일성
- 폐기 가능한 비운영 PostgreSQL `building` 검증본

### Stage 03B — 승인된 공식 외부 정형 데이터

- ETF 구성종목과 편입비중
- 증권·기업·기관 공식 식별자
- 기업 지배·상장 관계
- 동일 기준일 가격·NAV·성과와 환율
- 질문 지원 범위가 입증된 나머지 P0 정형 데이터

외부 소스는 소스별 승인 이후에만 추가한다. KRX·ECOS·FRED는 의무 연결 목록이 아니라 필요한 공백을 공식적으로 채우는 후보군이다.

### Stage 03C — 공식 문서·청크·최종 품질 게이트

- 상품 설명·정책·위험·시장 문서의 원본 위치와 컷오프 검증
- 상품 ID·문서 ID·페이지·절·문장 범위를 보존한 청크
- 52개 질문의 `supported`, `limited`, `requires_data`, `unsupported` 확정
- 03A·03B·03C의 모든 승인 원천 manifest 동결
- 최종 NCP PostgreSQL `building` 버전의 전체 재현

03A와 03B는 최종 NCP 데이터셋을 부분적으로 변경하지 않는다. Stage 02의 `operations.dataset_version.manifest_hash`가 불변이기 때문에, 각 하위 단계는 폐기 가능한 검증본에서 동작을 증명한다. 모든 원천이 확정된 03C에서만 최종 manifest로 NCP `building` 버전을 생성한다.

## 3. 동결 입력과 권위 경계

### Stage 01 재사용

- 새로운 tagged-value 코덱을 만들지 않는다.
- Evidence 값은 Stage 01 `ContractValue`와 canonical JSON/hash 규칙을 사용한다.
- `Decimal`, `date`, `datetime`, Boolean, 문자열의 타입을 추측하지 않는다.

### Stage 02 재사용

- Alembic `0001`~`0005`와 7개 논리 스키마를 그대로 사용한다.
- `catalog`, `observation`, `relation`, `evidence`, `operations` 테이블을 우회하는 임의 테이블을 만들지 않는다.
- Source·Evidence의 정확한 재시도 충돌 의미와 `building` 상태 변경 제한을 유지한다.
- `fa_build`만 정규화 데이터 적재에 사용한다.
- Stage 03A에서 `0006` 마이그레이션을 만들지 않는다. 실제 매핑 테스트가 기존 DDL로 표현할 수 없는 필수 사실을 증명할 때만 별도 설계·사용자 승인 후 검토한다.

### 원천 우선순위

1. 같은 평가 필드는 주최 측 마스터가 권위다.
2. 외부 공식 데이터는 주최 측에 없는 필드와 관계를 보완한다.
3. 충돌값은 조용히 덮어쓰지 않고 양쪽 Source와 충돌 상태를 보존한다.
4. 파일명 날짜와 실제 필드 기준일을 분리한다.

## 4. 최소 내부 계약

### `SourceSpec`

한 원본 워크북의 고정 구조만 표현한다.

```python
@dataclass(frozen=True, slots=True)
class SourceSpec:
    source_code: str
    table_id: str
    data_file_name: str
    data_sheet_name: str
    schema_file_name: str
    schema_sheet_name: str
    expected_columns: tuple[str, ...]
    expected_row_count: int
    natural_key: tuple[str, ...]
    parser_version: str
    mapping_version: str
```

실제 로컬 경로, Object Storage bucket, 자격증명과 원본 SHA-256은 코드 상수나 Git 문서에 넣지 않는다. 실행 시 데이터·스키마 workbook의 SHA-256을 각각 검증하고 BuildReport에 결합한다. 값 Claim의 SourceRecord는 data workbook을 가리키며, schema workbook은 필드 의미와 재현성을 고정하는 비값 원천으로 별도 SourceRecord 또는 manifest entry를 가진다.

### `MappingIssue`

```python
@dataclass(frozen=True, slots=True)
class MappingIssue:
    source_code: str
    row_number: int | None
    column: str | None
    code: str
    severity: Literal["limited", "quarantined", "fatal"]
```

원본의 상품명·식별자·값을 오류 메시지에 복제하지 않는다. 문제 위치는 원본 행 번호와 컬럼으로 추적한다.

### `MappedRow`

```python
@dataclass(frozen=True, slots=True)
class MappedRow:
    row_number: int
    disposition: Literal["accepted", "limited", "quarantined"]
    records_by_table: Mapping[str, tuple[Mapping[str, object], ...]]
    issues: tuple[MappingIssue, ...]
```

`records_by_table`은 Stage 02 SQLAlchemy Table에 들어가는 타입 검증된 payload다. 소스별 mapper는 SQL을 실행하지 않는다.

### `BuildReport`

```python
@dataclass(frozen=True, slots=True)
class BuildReport:
    dataset_version: str
    cutoff_date: date
    dataset_manifest_hash: str
    source_counts: Mapping[str, Mapping[str, int]]
    table_counts: Mapping[str, int]
    issue_counts: Mapping[str, int]
    component_hashes: Mapping[str, str]
    passed: bool
```

별도의 Source·Mapping·PostgreSQL·Evidence·Dataset 보고서 파일을 각각 만들지 않는다. 원본별 manifest 정보와 매핑·적재 결과를 하나의 canonical BuildReport에 담고, 전체 hash와 PostgreSQL·Evidence component hash를 계산한다.

## 5. 주최 측 원본 프로파일

| 소스 | 원본 행 | 필드 | 자연키 및 필수 검증 |
| --- | ---: | ---: | --- |
| 국내채권 `PRBD01N001` | 42,394 | 40 | `PD_NO`; 전 행 고유·비결측 |
| 국내 ETF·ETN `PREF01N001` | 1,734 | 73 | 제공 복합키 보존, 조회 대표키 `pd_itm_no`; ETF 1,202·ETN 532 |
| 해외 ETF·ETN `PREF02N001` | 5,646 | 49 | `pd_itm_no`; ETF 5,587·ETN 59; ISIN 단독키 금지 |
| 공모펀드 `PRFD01N001` | 95,619 | 45 | `itm_no + prfd_attr_cd + zrin_fd_ivst_risk_gcd`; `itm_no` 11,139개, 유효 대표펀드군 2,626개 |

원본 행 수·헤더·자연키 기대값이 달라지면 자동 보정하지 않는다. 소스 전체를 끝까지 읽어 문제 보고서는 만들 수 있지만 해당 소스 검증은 실패하고 데이터셋은 출시 후보가 되지 않는다.

## 6. 매핑 정책

### 필드 완전성

네 mapper는 모든 원본 컬럼을 다음 중 정확히 하나로 분류한다.

- `identifier`: 원천 식별자 또는 보조 식별자
- `catalog`: 상품·증권·기관·지수의 이름과 유형
- `relation`: 공식 의미가 확인된 13개 관계 중 하나
- `observation`: 수치·텍스트·Boolean·날짜 관측값
- `evidence_only`: 원본 위치와 값은 근거로 보존하지만 직접 조회 필드로 출시하지 않음
- `ignored`: 답변에 쓰지 않으며 고정된 이유를 기록

이 분류는 YAML이나 범용 `FieldRule` 엔진이 아니라 소스별 Python 상수와 명시적 분기문으로 작성한다. `handled_columns ∪ ignored_columns`가 실제 헤더와 정확히 같아야 한다.

### 식별자

- 상품 entity ID는 소스 코드와 검증된 자연키로 UUIDv5를 생성하며 데이터셋 버전과 무관하게 안정적이다.
- observation·relation·evidence ID는 소스 ID, 원본 record key, 원본 컬럼 또는 predicate를 포함한 UUIDv5다.
- 레코드 hash는 `created_at`을 제외한 실제 저장 payload의 canonical hash다.
- 이름만 같은 기관·기업을 소스 간 자동 병합하지 않는다. 03A는 source-local 기관 ID를 만들고, 03B의 공식 식별자가 결합을 입증한다.

### 결측과 센티널

- 빈칸, 문자열 `NULL`, 숫자 `0`, 날짜 `0`, 날짜 `99991231`, 통화 `000`, 수익률 `-100` 후보, 문장형 미제공 값은 소스·필드별로 구분한다.
- 실제 0은 `value_status="zero"`, 비어 있음은 `missing`, 명시적 대체문구는 `placeholder`, 의미가 정의되지 않은 코드는 `unknown`으로 저장한다.
- 결측을 0으로, 결측 Boolean을 `False`로, 미제공 지수명을 실제 Index entity로 바꾸지 않는다.
- 원본 표현은 답변 가능 사실의 Evidence `raw_value_repr`에 보존하고 정규값과 분리한다.

### 행 판정

- `accepted`: 자연키와 필수 구조가 유효하고 사용 필드에 제한이 없음
- `limited`: 상품은 적재 가능하지만 일부 필드가 missing·placeholder·unknown이거나 의미 제한이 있음
- `quarantined`: 자연키 부재, 타입 파싱 실패, 한 행 내부의 필수 불변식 위반으로 해당 행을 안전하게 적재할 수 없음
- `fatal`: 헤더·필드 수 변경, 기대 고유키 중복, 알 수 없는 새 구조, 컷오프 위반 등 데이터셋 전체 판단이 필요한 문제

모든 원본 행은 accepted·limited·quarantined 중 정확히 하나로 집계한다. fatal 문제는 별도로 누적하고 `BuildReport.passed=False`로 만든다.

### Evidence 범위

모든 원본 셀에 Evidence를 만들지 않는다. 식별자, catalog 사실, relation, observation 중 실제 질문 답변과 검증에 사용 가능한 사실에만 Source·Evidence를 만든다. 한 Evidence는 정확한 원본 workbook, sheet, row, column, record key, parser version, mapping version, 실제 기준일과 cutoff 상태를 가진다.

Stage 02는 Evidence origin을 observation·relation·document 중 하나로 제한한다. 따라서 상품명·식별자처럼 catalog 조회에 사용하면서 답변 Claim도 지지해야 하는 사실은 catalog 레코드만 만들고 끝내지 않는다. 같은 원본 필드에서 companion text observation을 만들고, 그 observation을 origin으로 하는 Evidence를 연결한다. relation 사실은 relation origin을 사용한다. 새 catalog-origin 테이블은 추가하지 않는다.

## 7. 저장과 재실행

### 입력 manifest

데이터셋 manifest hash는 다음 canonical 구조의 hash다.

```json
{
  "cutoff_date": "2026-07-11",
  "sources": [
    {
      "source_code": "PRBD01N001",
      "data_sha256": "<runtime value>",
      "schema_sha256": "<runtime value>",
      "header_hash": "<runtime value>",
      "row_count": 42394,
      "parser_version": "1",
      "mapping_version": "1"
    }
  ]
}
```

실제 hash 값은 Git에 고정하지 않는다. 네 source entry는 `source_code` 순으로 정렬한다. manifest는 원본·parser·mapping 조합을 고정하고, 실제 출력 건수와 component hash는 BuildReport와 validation report가 고정한다.

### 배치 저장 순서

한 batch는 다음 FK 순서를 따른다.

```text
dataset_version
→ publisher institution
→ source_record
→ metric_definition
→ entity / product / security / institution
→ identifier / alias
→ relation_record
→ observation_record
→ evidence_record + matching origin
```

`DatasetBuildWriter`는 한 batch에 한 연결과 한 명시적 transaction을 사용한다. 기본 batch 크기는 1,000행이며 합성·실데이터 측정으로만 조정한다.

같은 batch 안에서 공모펀드 반복행처럼 동일 ID가 여러 번 나오면 writer는 먼저 전체 payload를 비교한다. 모두 같을 때 한 건으로 축약하고, 하나라도 다르면 데이터베이스 쓰기 전에 batch conflict로 실패한다.

### 멱등성과 충돌

- 동일 ID·동일 canonical payload 재실행은 기존 행으로 수렴한다.
- 동일 ID·다른 payload는 안정적인 build conflict로 실패한다.
- `ON CONFLICT DO NOTHING`만으로 차이를 숨기지 않는다. 삽입되지 않은 ID는 저장 payload를 다시 읽어 전체 비교한다.
- source·evidence payload 비교는 Stage 02 `EvidenceLedgerRepository`의 의미와 같아야 한다.
- active 또는 validated 데이터셋에는 적재하지 않는다.

## 8. 원본 저장 경계

### 로컬

- `/data` 아래 원본은 읽기 전용 입력이다.
- loader는 workbook을 수정하거나 저장하지 않는다.
- 원본 경로와 파일명은 실행 설정으로 전달하고 Git에 복제하지 않는다.

### NCP Object Storage

- private bucket과 HTTPS S3-compatible endpoint를 사용한다.
- object key 기본형은 `organizer/2026-07-11/{table_id}/{file_name}`이다.
- 업로드 전 로컬 SHA-256, 업로드 후 다시 읽은 object SHA-256, SourceRecord checksum이 모두 같아야 한다.
- ETag를 SHA-256으로 간주하지 않는다.
- Access Key·Secret Key·bucket 이름·계정 식별자는 Git·BuildReport·로그에 남기지 않는다.
- 일반 단위 테스트는 네트워크를 사용하지 않는다. 실제 Object Storage 검증은 명시적 환경변수와 marker가 있을 때만 실행한다.

## 9. 테스트 구조

테스트를 여섯 개 이상의 형식적 계층으로 나누지 않는다. 다음 네 경계만 유지한다.

1. **순수 매핑 단위 테스트** — 필드 타입, 센티널, ID, 기간·통화·기준일
2. **합성 workbook 통합 테스트** — 실제 XLSX read-only 스트리밍, 전체 헤더 coverage, 행 판정
3. **PostgreSQL 통합 테스트** — batch transaction, FK 순서, Evidence origin, 멱등 재시도, 충돌 rollback
4. **명시적 실데이터·NCP 인수 테스트** — 실제 4개 행 수·키·분포·checksum, Object Storage 동일성, 전체 BuildReport

합성 fixture는 실제 상품명과 식별자를 포함하지 않는다. 실데이터 인수 테스트 결과에는 집계값과 안전한 오류 코드만 출력한다.

## 10. 03A 완료 게이트

1. 207개 원본 필드가 mapper 또는 이유가 있는 ignored 분류로 100% 설명된다.
2. 네 원본의 행 수·필드 수·자연키·ETF/ETN·펀드 중복 구조가 기준 분석과 일치한다.
3. 모든 행이 accepted·limited·quarantined 중 하나이며 합계가 원본 행 수와 같다.
4. 알 수 없는 구조, 컷오프 위반, 자연키 중복은 `passed=False`를 만든다.
5. 답변 가능 사실이 Source·Evidence와 정확한 원본 위치로 역추적된다.
6. 동일 입력 재실행은 같은 ID·hash·건수로 수렴하고 payload 차이는 충돌한다.
7. `fa_build`만 쓰기를 수행하며 active·validated 버전 변경이 거부된다.
8. 실제 로컬 원본과 private Object Storage 사본의 SHA-256이 일치한다.
9. 비운영 PostgreSQL `building` 검증본은 전체 적재·검사를 통과하지만 활성화되지 않는다.
10. 원본 workbook, 원본 행, 자격증명, DB dump, BuildReport 실데이터 파일은 Git에 포함되지 않는다.

## 11. 명시적 비범위

- 외부 공식 API·구성종목·환율 수집은 03B다.
- 공식 문서 parsing·chunking은 03C다.
- RDF·SHACL·Fuseki·embedding·pgvector 투영과 데이터 활성화는 Stage 04다.
- SQL/SPARQL 검색, 수익률 환산, 순위와 유사도 계산은 Stage 05다.
- LLM, 질문 라우팅, 답변 생성은 Stage 06 이후다.
- 원본 보정, 결측 추정, 이름만으로 기관·기업 병합은 하지 않는다.
- `0006` DDL, 삭제·정리 job, 범용 ingestion SDK, UI는 03A에 포함하지 않는다.

## 12. 구현 전 필수 매핑 게이트

03A 구현의 첫 산출물은 네 원본 207개 필드의 source-to-target matrix다. 각 행은 원본 필드, 원본 타입, 분류, target table/column 또는 metric/predicate, 값 상태 규칙, 날짜·기간·단위·통화, Evidence 여부, 제외 이유를 가진다.

이 matrix는 기존 네 master reference와 실제 schema workbook header로 검증하고 사용자 승인을 받은 뒤 mapper 구현을 시작한다. 이 게이트는 새 추상화를 추가하기 위한 것이 아니라 불확실한 금융 의미를 코드에 숨기지 않기 위한 것이다.
