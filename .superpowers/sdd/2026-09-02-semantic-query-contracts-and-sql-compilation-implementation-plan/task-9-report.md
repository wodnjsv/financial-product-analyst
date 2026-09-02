# Task 9 implementation report

## Scope and base

- Base: `9a814e9cbd2f59d8001d6b72b1271dcaf3e9ecef`
- Commit: `96d2609ded6b0532b86d4b19bd9780b8126d8c31`
- Scope: read-only semantic SQL execution and evidence-preserving result mapping only.
- Preserved: V1 execution inputs, orchestration integration, migrations, provider setup, organizer data, and non-SQL executors.

## RED

Command:

```text
.venv/bin/python -m pytest tests/sql/test_executor.py tests/sql/test_result_mapping.py -q
```

Observed: collection failed because `financial_agent.sql.executor` and
`financial_agent.sql.result_mapping` did not exist.

Subsequent narrow RED assertions exposed and then closed:

- non-deterministic product-row serialization when the database row order changed;
- missing metric/binding and unit ownership validation;
- COUNT result/product cardinality mismatch acceptance;
- aggregate metadata and lineage arrays insufficiently validated.

## GREEN implementation

- Added `ReadOnlySqlRunner` with an injected async engine and active
  `SemanticSqlCompiler`.
- Before opening a connection, the runner:
  - rechecks SELECT/WITH-only syntax;
  - calls Task 8 `validate_request_for_execution` with the authoritative
    `LogicalQueryPlanV2`, active registries, active dataset pin, and optional
    representative-population facts;
  - bounds the transaction-local timeout to 1..55,000 ms.
- Inside one transaction it executes `SET TRANSACTION READ ONLY`, applies a
  transaction-local PostgreSQL `statement_timeout`, and executes the compiled
  business statement exactly once. There is no retry, replan, mutation, or
  scheduler authority.
- Added exact result-shape validation for product queries, ranks, comparisons,
  scalar/grouped aggregates, and COUNT. Unexpected/missing columns, malformed
  arrays, invented metrics, wrong units, mixed aggregate metadata, duplicate
  rows, and excess cardinality fail closed.
- Existing `ResultRow`, `ResultField`, `Exclusion`, and `ResultWarning` types are
  retained. Observation, evidence, and source IDs are kept in one flat,
  namespaced evidence-reference tuple. Zero remains zero; null/sentinel values
  produce exclusions and warnings.
- Product result order is canonicalized for operations without semantic order;
  rank order remains the compiler-owned order. COUNT entity arrays and lineage
  arrays are canonicalized.
- Extended only the synthetic DB fixture with product, metric, observation,
  zero/missing, evidence-origin, mixed-family, representative-fund, tie, and
  injection-shaped values.
- Added PostgreSQL conformance scenarios for lookup, compound screen, rank
  ties, compare, executable SUM/AVG/MIN/MAX/COUNT, grouping, as-of/unit filters,
  split domestic/overseas execution, representative-fund aggregation, zero,
  missingness, injection-shaped text, and evidence lineage.
- `COUNT_DISTINCT`, `DISTRIBUTION`, and period requests are explicitly tested
  as fail-closed where Task 8 currently has no verified physical aggregate or
  qualifier lowering; Task 9 does not invent one.

## Verification

Focused offline:

```text
.venv/bin/python -m pytest tests/sql/test_executor.py tests/sql/test_result_mapping.py -q
17 passed
```

Task 7/8 plus SQL regression:

```text
.venv/bin/python -m pytest tests/sql tests/planning/test_semantic_compiler.py tests/planning/test_logical_query.py tests/planning/test_plan_readiness.py tests/planning/test_physical_bindings.py -q
304 passed
```

PostgreSQL:

```text
.venv/bin/python -m pytest -m postgres tests/integration/test_semantic_sql_postgres.py -q
3 skipped
```

Status: explicitly **unmeasured**, because
`FINANCIAL_AGENT_TEST_DATABASE_URL` is not configured. SQLite was not used as a
substitute.

Broad offline:

```text
.venv/bin/python -m pytest -m "not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration" -q
2137 passed, 1 expected skip, 451 deselected
```

Additional checks:

- Python compilation: passed.
- `git diff --check`: passed.
- secret/data path scan: no task secret, `.env`, organizer workbook/PDF, or
  `data/` path found.
- `uv.lock`: absent.

## Known unmeasured boundary

The PostgreSQL test code is present and collected, but its SQL/runtime behavior
has not been measured in this environment. Promotion must remain deferred until
the three tests run against an explicitly approved PostgreSQL test URL.

## Review fix round 1

Base: `96d2609ded6b0532b86d4b19bd9780b8126d8c31`.

RED was observed with `12 failed, 8 passed` in the focused executor/result
suite. The failures covered every requested review boundary: exact metadata,
COUNT empty-population arrays and grouped lineage, bounded fetching, and lookup
missing-state preservation.

Changes:

- Result metadata is now checked against the manifest-owned storage unit and
  requested currency/as-of semantics. Null metadata is not a wildcard for a
  non-null business value. Aggregate arrays reject mixed null/non-null and
  conflicting unit, currency, or date values before a result is labeled.
- Semantic unit conversion remains explicit: a `percent` request for fee rate
  is returned in its compiler-owned storage unit, `percentage_point`, rather
  than relabeled as the input unit.
- Lookup SQL preserves `value_status` and `reason_code` in its one statement.
  Missing/placeholder/unavailable/inapplicable/unknown values become stable
  exclusions and warnings; zero remains a normal value. Screen, rank, and
  aggregate paths retain their exclusion policy.
- COUNT maps PostgreSQL's null `array_agg` result to an empty identifier tuple
  only when the count is zero. Nonzero counts require product identifiers, and
  grouped counts require flat observation, evidence, and source lineage.
- The runner uses `fetchmany(max_rows + 1)` instead of `.all()`, rejects the
  overflow row before mapping, and still executes the business statement once.
- The synthetic PostgreSQL fixture now contains the exact manifest-owned
  `share-a/share-b`, `relation-a/relation-b`, relation evidence/source pairs,
  and `observation-a` ownership tuple. Extra share-class observations prove
  that the representative-product result remains isolated at 330.

Round 1 verification:

```text
.venv/bin/pytest -q tests/sql/test_result_mapping.py tests/sql/test_executor.py tests/sql/test_compiler.py tests/sql/test_property_matrix.py
175 passed

.venv/bin/pytest -q tests/sql tests/planning/test_semantic_compiler.py tests/planning/test_logical_query.py tests/planning/test_plan_readiness.py tests/planning/test_physical_bindings.py
308 passed

.venv/bin/pytest -q -m "not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration"
2141 passed, 1 skipped, 451 deselected

.venv/bin/pytest -q tests/integration/test_semantic_sql_postgres.py
3 skipped
```

The three PostgreSQL cases remain explicitly **unmeasured** because
`FINANCIAL_AGENT_TEST_DATABASE_URL` is not configured. No SQLite substitute
was used.
