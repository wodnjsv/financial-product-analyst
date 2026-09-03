# Hybrid Full-Catalog Semantic Linking Verification

**Measured:** 2026-09-04 KST

**Implementation commit:** `d2f143a0d83f62f65b53edd869a41993ef19745e`

**Status:** implementation verified locally; V3 is shadow-only; promotion failed
closed and remains deferred

## Result

The hybrid V3 Intent Resolver is implemented as a shadow path. Its compact
catalog exposes all `196/196` registered held-out concept occurrences, exact
locks are `140/140`, and required source spans are preserved `253/253` in the
deterministic report. The narrow V3 suite, the full Intent Resolver/evaluation
suite, the environment-corrected broad offline suite, compilation, and V2/V3
schema freshness checks pass. V2 remains the default resolver.

V3 is **not promoted**. The authorized HCX-007 V3 shadow run measured first-pass
structured validity `5/21`, repaired structured validity `0/16`, Action exact
`3/21`, ProductFamily exact `3/21`, semantic-link exact `0/5`, joint-frame exact
`0/5`, complete-contract exact `0/5`, and provider success `19/21`. It observed
zero false-fast outcomes in the single OOD case (`0/1`), but one case is not the
complete OOD promotion population. PostgreSQL conformance remains unmeasured.
These results are substantially below the accepted V3 promotion thresholds,
and ADR-0030 also requires a separate explicit promotion decision after every
gate passes.

## Frozen inputs and registries

| Input | SHA-256 |
| --- | --- |
| 52 core questions | `03de130a2a67fd21e782e81ba10524d6a6e769494cfeedc95b05b584ae3618a2` |
| 160-case / 209-frame held-out set | `bd40481c57975d66a84a98005b771761c023ae5461cbd3c232508522bbf4c7de` |
| Five representative semantic contracts | `16e3097ee17a26a2df8dd2418ac0eacd3baecc1a44f4ab6fc1a16de527f66f38` |
| Supported per-action population | `b592ab53537497d85136b03a69a61aae82c884b68231995a03601cf3809140c8` |
| Unsupported per-action population | `b3acfa3fd9d77079b5aa67985db65e958e5afc71af8b6474903f047a2261d323` |
| Semantic catalog | `c1e88ebd353e6306e8f61f4bef31d23fbed802adf4811a8ea287e40dbde73076` |
| Query contract registry | `06c2f97da35f07ccaa237e0a63a7d2d9a8a2c14040dd2e09e97d0bcb86d88baf` |
| Query operator registry | `d9f1775b563cea24b0b8eaa1e79d9bd864df9defa483ad17aec0738af88f53ba` |
| Query semantic-policy registry | `1dbb8eedf8340aae5b359692cd04c869d07d66681e3609a25623f7208513ce3a` |
| Physical binding registry | `9d5d25b1b7b35097e8e84404ee5d083d6b1e5f9ab43a679ec1e1897ef3427193` |
| Physical policy registry | `cf4f5065eb4fdae76902a1c0bd817700129ad077fe56795c05ab95d76937abf4` |
| Planning registry | `3dd0449e770815d07deee300a938cbd315c1dec93cfbef3d618963c1b3c51f00` |

Both sanitized reports contain these exact pins and the same `52 / 160 / 209 /
199 / 10` core, held-out-case, held-out-frame, supported-frame, and
unsupported-frame counts. Recomputing SHA-256 over each canonical payload after
removing its `report_hash` field reproduced the embedded report hash exactly.

## Deterministic V3 evidence

| Metric | Evidence | State |
| --- | ---: | --- |
| Compact-catalog selectability | `196/196` | measured |
| Exact-lock precision | `140/140` | measured |
| Required span preservation | `253/253` | measured |
| Hint recall at 5 | `123/196` | measured diagnostic; not a closed-world V3 selector |
| Action exact | no live prediction in offline report | unmeasured offline |
| ProductFamily exact | no live prediction in offline report | unmeasured offline |
| Semantic-link recall/exact | no live prediction in offline report | unmeasured offline |
| Joint-frame/context exact | no live prediction in offline report | unmeasured offline |
| Complete-contract exact/readiness | requires runtime context | unmeasured offline |
| Provider and repair metrics | provider disabled by `--offline` | unmeasured offline |

Static contract coverage remains `199/199` supported, `10/10` unsupported
reason coverage, and `0/10` false-complete. The 199 supported frames still
partition into 43 measured contract-role frames, 151 frames with incomplete
role gold, and 5 intentionally blocked calculation frames. Therefore the
observed `43/43` contract candidate recall and exact match remain `unmeasured`
for promotion against the required 194-frame denominator.

## Authorized HCX-007 evidence

The controller supplied the already-produced sanitized live report at
`/private/tmp/hybrid-semantic-query-live-verified.json`. This verification did
not repeat the costly live benchmark. It parsed only the sanitized report,
checked its canonical integrity hash, and did not read, copy, or stage the
protected raw-response file named by the report.

### Hybrid V3 shadow path

| Metric | Exact evidence |
| --- | ---: |
| Cases | `21` |
| Provider case success | `19/21` |
| Provider calls / successful calls | `38 / 30` |
| Call types | primary `21`, repair `16`, judge `1` |
| First-pass structured validity | `5/21` |
| Repaired structured validity | `0/16` |
| Action exact | `3/21` |
| ProductFamily exact | `3/21` |
| Semantic-link exact | `0/5` |
| Semantic-link recall | `0/4` |
| Joint-frame exact | `0/5` |
| Context-link exact | `1/5` |
| Complete-contract exact | `0/5` |
| Planning readiness | `0/16` |
| OOD false-fast | `0/1` |
| Prompt / completion tokens | `322,298 / 37,099` |
| p50 / p95 provider-call latency | `18,706 / 50,547 ms` |

The V3 telemetry records `MODEL_PROPOSAL_SCHEMA_INVALID=10`,
`MODEL_RATE_LIMITED=2`, and `MODEL_TIMEOUT=14` as stable error counts. Its
provider-call error summary separately records one rate-limited call and seven
timed-out calls. These are distinct report fields and are not combined or
inferred.

### Existing V2 live comparison paths

| Metric | Production one-axis | Parallel three-axis challenger |
| --- | ---: | ---: |
| Cases | `16` | `16` |
| Provider case success | `16/16` | `12/16` |
| Structured validity | `12/16` | `11/16` |
| Action exact | `11/16` | `2/16` |
| ProductFamily exact | `12/16` | `6/16` |
| Complete contract | `4/16` | not applicable |
| Representative contract exact | `2/5` | not applicable |
| Representative population integrity | `false` | not applicable |
| Provider calls / successful calls | `23 / 23` | `48 / 40` |
| Call types | primary `16`, repair `6`, judge `1` | action `16`, family `16`, tag `16` |
| Prompt / completion tokens | `132,917 / 16,541` | `4,889 / 266` |
| p50 / p95 provider-call latency | `12,170 / 16,259 ms` | `653 / 2,185 ms` |
| Rate-limited calls | `0` | `8` |

The report's existing top-level `live_production_provider_success` gate refers
to the V2 `production_one_axis` path and is `16/16 pass`; it must not be read as
V3 provider evidence. V3's separately recorded shadow result is `19/21` and
does not satisfy a 100% provider-success promotion requirement.

## Promotion gates

| Gate | Threshold | Evidence | Status |
| --- | --- | --- | --- |
| Supported representability | `100%` | `199/199` | `pass` |
| Unsupported reason coverage | `100%` | `10/10` | `pass` |
| False-complete unsupported | `0` | `0/10` | `pass` |
| Exact-lock precision | `100%` authoritative complete population | positive subset is not accepted by the top-level gate | `unmeasured` |
| Complete-contract candidate recall | `>=99%` over `194` | observed `43/43`; 151 gold frames incomplete | `unmeasured` |
| Decoupled contract exact match | `>=95%` over `194` | observed `43/43`; 151 gold frames incomplete | `unmeasured` |
| Executable deterministic compile success | `100%` authoritative population | authoritative population undefined | `unmeasured` |
| Byte equivalence | `100%` authoritative population | authoritative population undefined | `unmeasured` |
| Legacy ADR candidate recall at 5 | `>=99%` | `123/196` | `fail` |
| Full-population first-pass validity | `>=99%` over `155` | V3 live subset `5/21` | `unmeasured` top-level and below threshold on measured subset |
| Full-population joint-frame exact | `>=90%` over `155` | V3 live representative subset `0/5` | `unmeasured` top-level and below threshold on measured subset |
| Full-population context-link exact | `>=95%` over `155` | V3 live representative subset `1/5` | `unmeasured` top-level and below threshold on measured subset |
| OOD false-fast | `<=2%` over complete OOD population | V3 live `0/1`; complete population absent | `unmeasured` |
| PostgreSQL conformance | `100%` | no approved URL configured | `unmeasured` |
| Public-fund physical definition | verified | fee and representative-grain definitions absent | `unmeasured` |
| V2 production provider success | `100%` over 16-case path | `16/16` | `pass` |
| V2 representative contract exact | `5/5` | `2/5` | `fail` |
| V2 representative population integrity | `true` | `false` | `fail` |
| V3 shadow provider success | `100%` | `19/21` | below threshold |
| V3 shadow complete-contract exact | `100%` representative set | `0/5` | below threshold |

The sanitized report's overall status is `deferred`. This verification preserves
that fail-closed outcome. It does not infer a pass from a partial denominator,
a deterministic subset, the V2 live gate, or the absence of a false-fast result
in one OOD case.

## Reproducible verification commands

All local commands used the repository virtual environment on implementation
commit `d2f143a0d83f62f65b53edd869a41993ef19745e`.

| Command | Result |
| --- | --- |
| `.venv/bin/pytest tests/intent/test_compact_catalog.py tests/intent/test_mention_spans.py tests/intent/test_hybrid_proposal.py tests/intent/test_hybrid_prompt.py tests/intent/test_hybrid_assembler.py tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_service.py -q` | `139 passed in 1.15s` |
| `.venv/bin/pytest tests/intent tests/evaluation/intent tests/evaluation/query_contract -q` | `806 passed in 21.74s` |
| `.venv/bin/pytest -m "not ncp and not live and not postgres" -q` | `2419 passed, 13 skipped, 438 deselected, 13 failed`; every failure was `jena_integration` because `RUN_JENA_INTEGRATION`, Jena `6.0.0`, and Fuseki `6.0.0` were absent |
| `.venv/bin/pytest -m "not ncp and not live and not postgres and not jena_integration" -q` | `2419 passed, 13 skipped, 451 deselected in 56.65s` |
| `.venv/bin/python -m compileall -q src scripts tests` | exit `0` |
| `.venv/bin/python scripts/export_intent_schemas.py --check --schema-version 2.0 --output-dir schemas/intent/v2` | exit `0` |
| `.venv/bin/python scripts/export_intent_schemas.py --check --schema-version 3.0 --output-dir schemas/intent/v3` | exit `0` |
| `git diff --check` | exit `0` before documentation edits |
| `.venv/bin/python scripts/run_semantic_query_benchmark.py --offline --include-hybrid-v3 --sanitized-report /private/tmp/hybrid-semantic-query-offline.json` | exit `0`; `overall_status=deferred` |

The unadjusted broad command is retained verbatim because it is the plan's exact
command and did not pass in this environment. The corrected command is the
accepted environment-aware broad gate: the hybrid Intent Resolver does not
modify the separately provisioned Jena/Fuseki runtime, and the 13 Jena tests are
deselected alongside NCP, live, and PostgreSQL integration tests rather than
reported as product regressions.

## Report integrity

| Artifact | Embedded canonical report hash | Complete sanitized file SHA-256 | Mode |
| --- | --- | --- | --- |
| Offline report | `620f1ca0b39e2016e37ed1721ed8d996377c9c6f9720e4f30dbaab268299353a` | `d8d6623e399d230409467123ca3f0f333da89b026edbcc3a77c4067aecea2f3b` | `0600` |
| Authorized live report | `4796116bb817710b8e2b6b59ddfe1029c3be4a99a938bb966bae74705833eccc` | `4a2d6de6163029c33c187b9aecbd231c67d8f95e4af0fada2512b31934c3f703` | `0600` |

The raw live output remains outside Git under `/private/tmp` with controller-
verified mode `0600`. It was not read, copied, hashed, or staged during this
closeout. Neither sanitized aggregate is committed.

## Residual limitations

- PostgreSQL migration, stored-artifact database round-trip, and SQL conformance
  are unmeasured because no approved PostgreSQL URL is configured. SQLite is not
  substituted for PostgreSQL evidence.
- The 151 incomplete supported contract-role frames must be adjudicated before
  the contract accuracy denominator is complete.
- Production `public_fund.fee_rate` and representative product grain remain
  unverified, so their production paths stay `LIMITED`.
- Graph, Keyword/Search, and Calculation production executors remain outside
  this shadow resolver task.
- The V3 live result needs prompt/schema and semantic-link quality work before a
  new complete-denominator benchmark can justify reconsidering promotion.

## Security and repository boundary

The final audit is limited to the verification document, planning status, and
implementation plan. It checks that no `.env`, credential, raw HCX payload,
organizer workbook/PDF, `data/` path, database, Parquet file, generated report,
or runtime log is staged. No runtime default, deployment, merge, or push is part
of this verification task.
