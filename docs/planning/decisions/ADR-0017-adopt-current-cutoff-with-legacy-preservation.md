# ADR-0017: Adopt the Current Cutoff While Preserving Legacy Datasets

**Date:** 2026-08-25

**Status:** Accepted

**Approved:** 2026-08-25 — the user approved the database and ontology
rebaseline direction based on the reviewed `2026-08-24` organizer data.

**Related:** [ADR-0016](ADR-0016-use-2026-08-24-organizer-baseline.md), [Rebaseline Design](../specs/2026-08-24-stage-03-organizer-rebaseline-design.md), [Stage 01 Contracts](../architecture/RUNTIME_CONTRACTS.md)

## Context

The new organizer baseline requires a current cutoff of `2026-08-24`, but the implemented system enforces `2026-07-11` in three independent places:

- `RuntimeArtifact` validates one exact Python cutoff constant;
- `operations.dataset_version` has a database CHECK for one exact date;
- ingestion, capture, preflight, fixtures, manifests, and object keys use the old literal.

The fact, relation, observation, and Evidence tables can represent all 280 fields. The incompatibility is the frozen cutoff guard, not the normalized fact model. Existing NCP rows from the old capacity probes must remain historical and must not be deleted, relabeled, reused, or activated.

## Decision

- Keep the Stage 01 JSON contract shape and `schema_version=1.0`. The schema version describes the artifact shape; the competition baseline is carried by `dataset_version` and `cutoff_date`.
- Change the current runtime and ingestion cutoff constant to `2026-08-24`.
- Add Alembic `0006` that replaces the exact-date CHECK with the explicit approved set `{2026-07-11, 2026-08-24}`. This is solely for preserving historical rows while admitting the current baseline; it is not a general arbitrary-date policy.
- Make activation reject every dataset whose cutoff is not `2026-08-24`, with a stable database error. Legacy datasets may remain `building`, `failed`, `validated`, or `retired`, but never become active.
- Make every new organizer or combined build require `2026-08-24`. No public CLI path may create a new `2026-07-11` build.
- Keep Evidence cutoff evaluation relative to each dataset's stored `cutoff_date`; the existing trigger and eligible-Evidence view already do this dynamically.
- Update NCP preflight, the database object manifest, source manifests, object prefixes, fixtures, and tests to distinguish legacy preservation from current creation and activation.
- Do not mutate existing dataset cutoff dates or source Evidence.

## Alternatives

### Replace the database CHECK with exactly `2026-08-24`

Rejected because existing `2026-07-11` capacity-probe rows would violate the new constraint. Deleting or relabeling those rows would destroy audit history.

### Permit any cutoff on or before `2026-08-24`

Rejected because it weakens a competition invariant and permits accidental builds for unapproved dates.

### Introduce contract schema version `1.1`

Rejected for this change because no field, tagged-value shape, or artifact structure changes. A second contract version would add adapters and fixture branches without improving cutoff safety. A future structural contract change still requires a new schema version.

### Keep the database at `2026-07-11` and label only external manifests as `2026-08-24`

Rejected because runtime artifacts, Evidence eligibility, and active-dataset checks would disagree with the official evaluation baseline.

## Consequences

- Stage 02 normalized tables remain unchanged, but the earlier statement that no migration is required is false; one minimal boundary migration is mandatory.
- Migration verification must cover `0005 → 0006 → 0005 → 0006`, preservation of legacy rows, rejection of arbitrary dates, and rejection of legacy activation.
- Contract and ingestion tests must prove that new artifacts accept only `2026-08-24` while database history may still contain `2026-07-11`.
- No new organizer mapper or NCP rebuild may run until `0006` and the current cutoff contract pass locally and on the private NCP database.
