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

## Review fix round 2

Base: `00af45b57a67259148372fe184779bf5f5bdca2c`.

RED was observed in two focused tests: the nonzero ungrouped COUNT mapper
rejected newly required lineage columns, and the compiled COUNT statement did
not project any population lineage.

The COUNT value query now remains independent from a second whole-population
lineage aggregation. The two one-row subqueries are joined only after the
distinct product count is complete, so observation/evidence joins cannot
multiply the count. Nonzero COUNT results require nonempty flat
`observation_ids`, `evidence_ids`, and `source_ids`; a zero count alone may map
PostgreSQL null aggregate arrays to empty tuples. Product identifier cardinality
checking and the numeric zero value are unchanged.

For a representative public-fund COUNT, the lineage branch is additionally
restricted to the manifest-owned entity, metric, observation, evidence, and
source tuple. Ordinary source-product COUNT has no metric binding in its
logical contract, so it retains the complete scoped observation lineage rather
than inventing metric ownership.

The PostgreSQL conformance case now requires the six-product COUNT to retain
nonempty observation/evidence lineage and `source:source-one`.

Round 2 verification:

```text
.venv/bin/pytest -q tests/sql/test_result_mapping.py tests/sql/test_executor.py tests/sql/test_compiler.py tests/sql/test_property_matrix.py
176 passed

.venv/bin/pytest -q tests/sql tests/planning/test_semantic_compiler.py tests/planning/test_logical_query.py tests/planning/test_plan_readiness.py tests/planning/test_physical_bindings.py
309 passed

.venv/bin/pytest -q -m "not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration"
2142 passed, 1 skipped, 451 deselected

.venv/bin/pytest -q tests/integration/test_semantic_sql_postgres.py
3 skipped
```

PostgreSQL remains explicitly **unmeasured** because the approved URL is not
configured. No SQLite substitute was used.

## Review fix round 3

Base: `32bd352cd90f55734a16a4bf617e4eb5d382970a`.

RED reproduced three focused failures: filtered COUNT emitted suffixed duplicate
lineage labels, all COUNT shapes expected undeclared evidence columns, and
metric-definition identity was absent from the result contract.

Changes:

- Ungrouped COUNT now bypasses the ordinary aggregate-lineage projector. Its
  predicate joins only constrain the numeric population; the separate
  whole-population lineage branch is the sole owner of final lineage labels.
  Generated filtered COUNT SQL has no `evidence_ids_1` or `source_ids_1`, and
  the exact synthetic returned shape maps successfully.
- The closed SQL render manifest now pins the active COUNT-lineage metric IDs.
  This preserves deterministic rerendering for unbound source-product COUNT
  while preventing returned metric definitions outside active family bindings.
- COUNT lineage SQL projects only the categories listed in
  `evidence_projection_ids`. Metric definitions are flat exact
  `metric_id:definition_version` identities; observation, evidence, and source
  arrays appear only when declared.
- Result mapping emits namespaced references only for declared categories,
  rejects missing/extra columns and unowned metric-definition identities, and
  verifies that every nonempty result supplies exactly the requested evidence
  categories. Representative population relation/evidence/source proof is
  sourced only from its pinned manifest.
- The PostgreSQL COUNT assertion now specifies and checks the exact two metric
  definitions, twelve observation IDs, twelve evidence IDs, and one source ID
  for the six-product synthetic population.

Round 3 verification:

```text
.venv/bin/pytest -q tests/sql/test_result_mapping.py tests/sql/test_executor.py tests/sql/test_compiler.py tests/sql/test_property_matrix.py tests/sql/test_contracts.py
198 passed

.venv/bin/pytest -q tests/sql tests/planning/test_semantic_compiler.py tests/planning/test_logical_query.py tests/planning/test_plan_readiness.py tests/planning/test_physical_bindings.py
311 passed

.venv/bin/pytest -q -m "not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration"
2144 passed, 1 skipped, 451 deselected

.venv/bin/pytest -q tests/integration/test_semantic_sql_postgres.py
3 skipped
```

PostgreSQL remains explicitly **unmeasured** because the approved URL is not
configured. No SQLite substitute was used.

## Review fix round 4

Base: `be31661b8b559954c64668c4d1e97ed38f3a87b8`.

The focused RED run reproduced six failures with 13 existing passes. The
representative COUNT result contract did not contain `relation_ids`, and the
mapper could not distinguish exact manifest lineage from unrelated
observation/evidence/source identifiers or a fabricated metric-definition
version. This confirmed that category and identifier syntax checks had been
mistaken for lineage ownership checks.

Changes:

- Physical observation bindings now register exact active
  `metric_id:definition_version` references. Those references are included in
  binding hashes and are pinned in `PhysicalSqlRenderManifest`, so canonical
  rerender uses the same full identities rather than an ID-prefix allowlist.
- Representative population ownership records also carry the exact metric
  definition version. COUNT lowering filters on both metric ID and definition
  version.
- Representative COUNT SQL returns relation IDs plus the observation and
  relation evidence/source paths already required by the verified population
  manifest. The returned relation, observation, evidence, and source sets are
  checked against the exact manifest tuples applicable to the returned
  representative-product IDs.
- Non-representative COUNT keeps query-population lineage dynamic, but returned
  metric-definition references must match one exact binding-owned full
  reference. Observation/evidence/source columns remain produced only by the
  compiler-owned observation-origin bridge.
- A zero COUNT accepts only null or empty arrays for every declared lineage
  category. Any nonempty metric-definition, observation, relation, evidence,
  or source lineage fails closed.
- Direct malicious-row tests cover unrelated observation/evidence/source and
  relation IDs, a fake definition version, and nonempty zero-count lineage.
  A positive representative case requires the complete exact set.

Verification:

```text
.venv/bin/python -m pytest tests/sql/test_result_mapping.py tests/sql/test_compiler.py -q
45 passed

.venv/bin/python -m pytest tests/sql tests/planning/test_physical_bindings.py tests/planning/test_plan_readiness.py tests/planning/test_logical_query.py tests/planning/test_semantic_router.py tests/planning/test_semantic_compiler.py -q
325 passed

.venv/bin/python -m pytest -m postgres tests/integration/test_semantic_sql_postgres.py -q
3 skipped

.venv/bin/python -m pytest -m "not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration" -q
2152 passed, 1 skipped, 451 deselected
```

The three PostgreSQL cases remain explicitly **unmeasured** because
`FINANCIAL_AGENT_TEST_DATABASE_URL` is not configured. No SQLite substitute
was used. Python compilation and `git diff --check` passed.
