# ADR-0057: Connect deterministic verification stages for personal search

- Date: 2026-10-12
- Status: Accepted
- Approval: The user requested verification enhancement using the supplied pipeline harness proposal.
- Related: ADR-0007, ADR-0020, ADR-0032, ADR-0050, ADR-0052, ADR-0054–0056.

## Decision

Add a request-scoped verification harness to the existing personal semantic
search path. It records actual plan, query ownership, evidence, local result
contract and final rendering verification under one dataset/manifest/cutoff.
Checks are deterministic and fail closed. A failed stage blocks dependent work;
unrun and not-applicable stages cannot be counted as passing. Provider/system
failures remain distinct from intentional limitations and factual success.

Reuse the current semantic compiler/execution ownership and source/evidence
validators. Add independent result-contract checks for scope, predicates,
qualifiers, ranking and counts, and exact final rendering verification. Preserve
existing AtomicClaim/ClaimSupport/CalculationRecord and production ClaimGate
contracts; this local bridge does not promote a request to the production ledger.

Keep QueryPlan/LogicalQueryPlanV2 as the query contract. AnswerPlan retains its
existing post-verification layout-only meaning. Keep organizer-field ownership,
NULL preservation, approved document authorities and manager supplement
separation. No new source tier or document fallback is admitted.

## Alternatives and reasons

Creating another claim DB/SQL verifier duplicates approved authorities and could
weaken compiler ownership. Reuse them. Regex number membership misses wrong
entity/date bindings and misclassifies quoted text, dates and source locators;
verify canonical server rendering from approved structures instead.

An additional LLM semantic/style judge changes the accepted call/recovery
boundary and cannot override hard checks. It is not enabled here. Dataset
activation/Fuseki rebuilding conflicts with the personal building profile;
unused projection checks are explicitly not applicable in this path.

## Verification

Normal and adversarial question tests assert stage outcomes and downstream
blocking. Cover tampered pins/query parameters, wrong predicate/scope/date,
rank/order/count errors, wrong source/lineage, missing versus zero, Seoul cutoff
boundaries, duplicate subjects/fields and changed final text/citations. Reuse
existing release/graph/document/calculation tests without claiming unused stages
ran. Local DB tests are read-only; NVIDIA failures remain failed live validation.
