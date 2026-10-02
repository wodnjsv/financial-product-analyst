# NVIDIA intent migration and routing improvements — 2026-10-02

## Approval, assumptions and scope

The user requested migrating the existing HCX intent resolver to NVIDIA API
and improving its shortcomings after reviewing the current architecture.
Continue from verified personal commit 3668e1c on codex/nvidia-intent-routing;
latest origin/main is an ancestor and does not yet contain the personal work.
ADR-0053 records this approved personal-use amendment. Historical competition
decisions remain append-only and are not runtime requirements for this profile.

Assumptions: financial_agent_local is the existing read-only snapshot, catalogs
and deterministic compiler contracts are authoritative, and NVIDIA credentials
already exist locally. The intent resolver must preserve product-family and
entity scope rather than coerce arbitrary questions into the three sample plans.

Intended outcome: a tracked raw-question entry point using NVIDIA through the
existing semantic resolver; catalog-grounded entity discovery; explicit routing,
ambiguity and unavailable-executor outcomes; useful reproducible validation.

Non-goals: new raw data, new embeddings, DB writes, Graph activation, free-prose
document generation, public HTTP deployment, main merge or automatic push.
Retain the current server-owned display and exact source policy.

Constraints: bounded entity candidates, at most one normal semantic call plus
existing shared recovery allowance, total deadline, read-only DB, no secret or
reasoning output, deterministic SQL and no silent default into another family.

## Steps and success criteria

1. Test and implement provider-neutral invocation contracts and NVIDIA adapter.
   Verify request format, local schema validation, deadlines, 429/authorization/
   server failures, refusal/truncation and secret-free stable errors.
2. Test and implement bounded entity discovery from raw questions against the
   pinned catalog. Verify exact source ranges, aliases/identifiers, overlapping
   names and limits; preserve ambiguity rather than pick arbitrary entities.
3. Connect a local raw-question service/CLI to existing semantic resolution and
   deterministic route construction. Verify each of four families is explicit,
   metric/period/entity scope survives, and ambiguous/unsupported questions do
   not execute an unrelated query. Add only necessary missing boundaries.
4. Run narrow regression checks, bounded read-only DB/NVIDIA probes and the
   broader offline suite. Inspect the final diff and update README/runbook with
   actual behavior, measured results and remaining execution coverage limits.

The full natural-language flow is not complete merely because the provider
returns HTTP 200 or syntactically valid JSON. Success requires verified semantic
scope and the expected route or explicit limitation for each probe.

## Implemented result

- Added provider-neutral invocation results and the NVIDIA JSON proposal adapter;
  the personal runtime constructs no HCX adapter. Stable errors cover provider,
  JSON, refusal, truncation and deadline boundaries without exposing payloads.
- Added bounded catalog discovery with exact source ranges, case/space-insensitive
  aliases/identifiers, repeated mentions and candidate ID provenance. Corrected
  the organizer metric names used to recover actual ETF entity types.
- Locked explicit registered product families, suppressed name-internal numbers
  and false references, and kept model-grounded policy flags restrictive only.
- Connected raw-question CLI/service to the existing V3 resolver, contract solver
  and compiler. Unresolved entities/families, cutoff violations, unsupported
  relation lowering and missing physical bindings remain explicit limitations.
- Kept candidate contracts separate from approved logical plans in output. Even
  a unique complete semantic contract is not an execution target when physical
  readiness fails. Product query execution is not part of this entry point.
- Versioned changed behavior as normalizer v2, candidate policy v5 and initially prompt v7;
  old runtime versions cannot certify new manifests. Historical records remain.
- Updated README and the personal NVIDIA runbook with commands, outbound prompt
  contents and execution boundaries. No commit, push or database write performed.

## Initial verification and authorization gate

The final raw-question/CLI/routing subset passed 48 tests. Family lock, source ID,
missing physical readiness and stale-version regressions were reproduced before
fixing. The final broader offline result is recorded below after completion.

Pre-live offline verification on the then-current runtime versions: **3,351 passed,
4 skipped, 516 deselected** in 68.11 seconds. External DB/API/performance gates
were excluded and are not claimed as passes. CLI `--help` and final
`git diff --check` passed. A separate read-only scope/secret audit of the 39
changed/new files found no source data, logs, credentials or unrelated edits.

Actual read-only DB checks used `fa_runtime` with `transaction_read_only=on`.
TIGER/KODEX mapped to domestic ETF, SPY to overseas ETF, and Samsung Electronics
and an asset manager retained their distinct types. Repeated source positions
were preserved. Discovery took 568–777 ms; discovery plus typed candidate lookup
took 1.069–1.478 s in the local sample. These measurements do not prove model
accuracy or certify all natural-language entity descriptions.

The initial six-question live NVIDIA request did not execute. Automatic approval review
rejected exporting the raw question plus database-derived semantic/entity
metadata because prior NVIDIA testing authorization did not clearly cover that
payload. The blocked call is not retried indirectly. Explicit authorization for
question + semantic catalog + matched candidate names/types/families/internal
IDs is required before rerunning the bounded live probe. Raw workbooks, full
observations, document bodies, keys and hidden reasoning are not its payload.

Remaining execution work is distinct from this migration: register verified
physical bindings/qualifiers, lower relation operands by their proper types,
then connect supported plans to product SQL and source-owned answer rendering.
No live NVIDIA semantic correctness claim is made while its probe is pending.

## Approved live verification and final result

The user explicitly authorized the question/semantic-catalog/matched-candidate
metadata payload after the initial rejection. Subsequent calls stayed within
that scope, used the read-only DB, and never included source workbooks, full
observations, document bodies, keys or hidden model reasoning in logs.

The first GLM six-case run had two proposal-schema errors and four timeouts.
An isolated original-response replay identified an action/family ID incorrectly
placed in `semantic_links`; its compact catalog allows metrics/relations only.
The provider took 42.533 seconds for a recorded first response, leaving too
little recovery time. Explicit root/frame/ID-role guidance and a smaller system
schema presentation were added, keeping the original closed validation schema.
Only repeated ID enums were removed from the system copy; all offered IDs and
the full semantic catalog remain in the resolver view. The representative
schema guidance fell from 14,179 minified characters to 8,882. Actual final
domestic-filter input usage was 10,615 tokens versus 14,208 in the initial
diagnostic; this measures the combined prompt changes, not a controlled speed
benchmark.

A deterministic parser bug also treated a decimal point as a sentence boundary,
dropping the comparison in `0.1% 이하`. The minimal boundary fix and six regressions
preserve both decimal comparisons and real sentence boundaries. Three raw-input
tests verify domestic/overseas/public-fund thresholds and plan approval limits.

V9 passed four cases, but two responses omitted required `segment_ids`. The
system and bounded repair instructions now explicitly require every frame key,
including non-empty offered source segment IDs for unsupported intents. A
regression ensures missing keys are rejected, never injected, and at most two
model calls are used. Final runtime versions are prompt V10 and NVIDIA adapter
V4, alongside normalizer V2 and candidate policy V5.

Model/API comparisons did not establish a verified replacement: documented
Qwen candidates returned 410, a listed Mistral candidate returned 404, several
native-schema parameter attempts returned 400/500, and alternative JSON-mode
responses failed shape/time constraints. Keep GLM-5.3-Flash with JSON object
mode and authoritative local validation; no automatic model or transport
fallback loop was introduced. Failed runs are preserved separately in ignored
local diagnostics.

The final V10/V4 real NVIDIA run passed **6/6 semantic/routing cases**:

| Case | Verified contract and outcome | Total seconds |
| --- | --- | ---: |
| Domestic ETF threshold | `fee_rate lte 0.1 percent`, domestic scope, `compose`, logical plan present | 28.317 |
| Overseas return rank | `P1Y`, one-year return descending, limit 5; physical binding missing, no plan | 36.719 |
| Named TIGER product | Exact DB product ID, domestic ETF, fee lookup; unit qualifier missing, no plan | 29.441 |
| Domestic bond maturity | Maturity-date lookup, domestic-bond scope; physical binding missing, no plan | 29.233 |
| Public-fund threshold | `fee_rate lte 0.3 percent`, public-fund scope; physical definition unverified, no plan | 26.868 |
| Next-year recommendation | Source-grounded `FUTURE_FORECAST`, `POLICY_BLOCKED`, no contract/plan | 22.244 |

Every final case used one real model call, with no repair or judge. Independent
review compared original metric spans, predicates, qualifiers, ordering, limit,
entity roles/IDs and compiler output against each question. No scope widening or
invented dates were found. `execution_performed` was false for every case; this
certifies six intent/routing examples and explicit limitations, not SQL results,
all future questions or a latency guarantee.

Final offline verification after the live-driven fixes: **3,365 passed,
4 skipped, 516 deselected** in 64.95 seconds. Skipped/excluded external tests
are not counted as passed. No additional test broadening is required after this
successful run unless further implementation changes are made.

Final scope/secret review covered 41 changed/new files and found no raw data,
logs, keys, environment files or unrelated changes. `git diff --check` passed.
Status: the approved intent-provider migration and identified resolver fixes are
verified. Actual product execution/answer integration and broader financial
binding coverage remain subsequent work, not completed by these six probes.
