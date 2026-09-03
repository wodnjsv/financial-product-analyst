# Stage 05–07 Local Vertical Slice Verification

**Date:** 2026-09-04

**Baseline:** `fce4e31` (`main`)

**Result:** local implementation and non-live verification passed

## Verified scope

- A Graph executor accepts only the registered semantic Graph capability, derives
  one approved relation, limits the SPARQL query to the requested entity IDs, and
  returns only relation rows with Evidence IDs from the pinned dataset version.
- An official-document executor limits retrieval by product, document authority,
  section type, cutoff, and model version; keyword and optional vector candidates
  are fused deterministically and revalidated before Evidence promotion.
- Tool fields become Claims only when exact observation, relation, document-span,
  or registered calculation support is present. Empty bounded results become a
  limitation, not a factual absence.
- The Verifier runs fixed contract/hash, source, cutoff, ontology, calculation, and
  coverage checks. Only the registered one-input identity recipe is recomputed and
  accepted; unregistered formulas and similarity remain fail-closed.
- Claim Gate accepts only the server-owned renderer profile and templates and only
  the complete set of releaseable Claim IDs. The Renderer uses ledger values and
  source locators and emits the competition response fields deterministically.
- Alembic `0012` adds an immutable verified release cache that requires linked,
  scope-consistent VerificationReport, AnswerPlan, and ReleasedAnswer artifacts.

## Verification evidence

### Focused retrieval and release checks

```text
pytest -q tests/graph/test_competency_queries.py \
  tests/orchestration/test_stage05_executors.py \
  tests/release/test_release_pipeline.py

26 passed in 0.74s
```

```text
pytest -q -m 'not jena_integration' \
  tests/release tests/orchestration/test_stage05_executors.py tests/sql tests/graph

447 passed, 14 deselected in 23.24s
```

The 14 deselected checks require the separately installed Jena/Fuseki 6.0.0
runtime and were already an explicit opt-in integration gate. No Jena result is
claimed by this change.

### Clean PostgreSQL 15 broad regression

The dedicated temporary `financial_agent_test` database was dropped, recreated,
initialized with the project extension layout, and used for the broad suite.

```text
pytest -q -m 'not ncp_integration and not clova_integration and not jena_integration'

3475 passed, 8 skipped, 22 deselected in 92.79s
```

The eight skips are explicit scale or real organizer/KRX/SEC/ECOS source gates;
this implementation did not read or modify those source files.

### Migration and object-manifest cycle

```text
python scripts/verify_database_migrations.py

MIGRATION_VERIFICATION_OK head=0012
checks=161,foreign_keys=102,functions=26,indexes=101,
tables=44,triggers=68,views=1
```

This includes `base -> 0012 -> base -> 0012`, Alembic autogenerate drift checks,
permission postflight, and deterministic object inventory comparison.

### Static checks

```text
python -m compileall -q src tests
git diff --check
```

Both completed successfully.

## Deferred gates

- No production calculation executor was enabled. V2 still needs authoritative
  typed operand-value handoff and approved formula recipes.
- Similarity remains non-releaseable until its policy and evidence-coverage rule
  are activated and verified.
- Closed-world no-match Claims remain unavailable until a scope Evidence executor
  can prove complete population coverage.
- Final official structured-source integration, dataset activation, full 52-question
  acceptance, live NCP Graph/Vector latency, HCX promotion, and the public evaluation
  API remain later-stage work.
