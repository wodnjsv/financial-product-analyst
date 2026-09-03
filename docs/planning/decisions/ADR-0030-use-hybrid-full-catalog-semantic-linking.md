# ADR-0030: Use Hybrid Full-Catalog Semantic Linking

**Date:** 2026-09-03

**Status:** Accepted

**Approved:** 2026-09-03 — the user approved replacing candidate-gated
semantic selection with the hybrid design described in this decision.

**Supersedes:** [ADR-0022](ADR-0022-use-ontology-grounded-intent-resolution.md)
only where request-local semantic candidates are the complete set of concept
IDs selectable by HCX and where candidate recall at five is itself a promotion
gate.

**Amends:** [ADR-0023](ADR-0023-use-server-owned-intent-identities-and-explicit-semantic-coverage.md),
[ADR-0024](ADR-0024-use-bounded-entity-type-registry-and-role-aware-entity-hints.md),
[ADR-0028](ADR-0028-separate-axis-resolution-from-task-slot-binding.md), and
[ADR-0029](ADR-0029-use-semantic-query-contracts-and-deterministic-sql-compilation.md)
only at the model-facing semantic-selection boundary. Their server-owned IDs,
exact locks, deterministic contract solving, physical-schema isolation, and
fail-closed execution rules remain accepted.

**Related:** [Hybrid Semantic Linking Design](../specs/2026-09-03-hybrid-full-catalog-semantic-linking-design.md),
[Planning Harness](../HARNESS.md)

## Context

The current resolver has two independent quality bottlenecks.

First, deterministic semantic candidate generation is a closed-world gate.
Only concepts reached through the Korean overlay or canonical IDs enter the
request-scoped `ResolverView`; HCX cannot recover a valid concept that the
candidate generator omitted. The current held-out evidence is:

- candidate recall at five is `123/196` (`62.76%`);
- recall at three, recall at five, and recall over every generated candidate are
  identical, so the missing 73 gold concepts are absent rather than poorly
  ranked;
- 42 semantic concepts exist, but only 9 have any overlay-backed Korean
  candidate surface; and
- overlay V2 to V3 increased candidate recall from `119/196` to `123/196`.

Second, the HCX proposal is structurally larger than its normal-path semantic
task requires. In the latest 16-case live run, all provider calls succeeded,
but only 11 responses passed strict validation. Four failures selected a
relation-object entity role without its required relation and one used an
invalid frame reference. Among the 11 valid resolutions, all 11 family choices
and 10 action choices were exact. This indicates that output structure, not
only Korean axis understanding, is a material failure source.

Ontology, semantic-contract, and physical-binding work remains valuable, but it
cannot repair a concept omitted before HCX. The ontology is authoritative for
types, relation endpoints, and applicability; physical bindings are
authoritative for execution. Neither is a Korean lexical retrieval index.

## Decision

### Make semantic candidates advisory rather than exhaustive

Deterministic preparation continues to produce exact locks and ranked semantic
hints. These preserve high-precision explicit facts and improve model focus,
but they no longer define the complete set of concepts HCX may select.

An exact canonical or unique direct-alias match remains server-owned and cannot
be removed or contradicted by HCX. Group, ambiguous, fuzzy, and model-selected
matches remain non-locking evidence.

### Offer the complete compact semantic catalog

Every valid request receives a generated, bounded `CompactSemanticCatalog`
containing all registered semantic concept IDs. Each model-facing concept card
contains only:

- canonical semantic ID;
- Korean preferred label and concise Korean definition;
- concept kind and value kind;
- applicable product-family IDs;
- required semantic qualifiers; and
- bounded disambiguation information for explicitly confusable concepts.

ProductFamily and Action continue to be offered as complete registered axes.
The compact catalog is generated from the semantic catalog, Korean NLU overlay,
and approved ontology constraints. It is not a new handwritten source of truth.

HCX does not receive raw RDF/TTL, SHACL, SQL, table names, column names,
physical metric IDs, joins, formulas, or execution recipes.

### Generate meaning-neutral mention spans

The server generates bounded source-preserving mention spans without first
assigning them a semantic concept. Exact alias and literal spans have priority;
normalized contiguous Korean phrase spans provide coverage for unseen
paraphrases. Every span has a server-owned ID, segment ID, exact source range,
and text.

Exceeding the configured bound fails closed or marks semantic coverage
unresolved. Span truncation must never silently remove a source range already
used by an exact lock, literal, reference, or entity mention.

### Let HCX link spans to registered meanings

The normal HCX call returns one or more atomic frames containing:

- Action and ProductFamily choices;
- `semantic_links` from offered mention IDs to registered compact-catalog IDs;
- explicit `unmapped_mention_ids` or ambiguous mappings where appropriate;
- typed references only when the request contains offered reference evidence;
  and
- entity hints only when the request contains an offered entity mention.

The model cannot author offsets, evidence text, IDs, SQL, contract variants,
slot values, defaults, or physical bindings. It can select any registered
semantic concept, even when that concept was not present in deterministic
candidate hints.

### Generate the smallest valid response schema per request

Simple non-entity, non-reference questions receive a minimal frame and
semantic-link schema. Entity, relation, and context structures are enabled only
when their required server-owned evidence exists. When a branch is unavailable,
its array has `maxItems: 0` or the field is absent from the request-specific
closed schema.

This shaping may remove impossible output branches but may not hide a semantic
concept from the compact catalog.

### Validate and solve deterministically

The server validates every model-selected semantic link against:

- registered IDs and offered mention IDs;
- exact-lock consistency;
- ProductFamily applicability;
- ontology subject/object constraints for relations;
- value-kind and qualifier compatibility; and
- explicit covered, ambiguous, or unmapped status.

Validated links become non-locking field offers for the existing bounded
contract solver. Exact locks, literals, operators, registered defaults, contract
variants, policies, and physical bindings remain deterministic.

Unknown or incompatible concepts cannot become executable SQL. They route to
Explore, Limitation, or Abstain under the existing four-path policy.

### Keep one normal-path model call

The normal path retains one HCX resolver call. The existing mutually exclusive
repair-or-candidate-judge allowance remains. Three parallel axis calls are not
promoted by this decision.

### Use registered qualifier defaults only

Omitted qualifiers may be filled only by an explicit server policy. For
snapshot metrics such as AUM, the first implementation may use the active
dataset's verified observation date as `as_of` when the corresponding policy is
registered, pinned, applicable, and disclosed. HCX cannot invent a date or
default.

## Evaluation and Promotion Gates

The old candidate recall-at-five metric remains a diagnostic of hint quality;
it no longer measures whether a valid semantic concept is selectable.

The hybrid resolver is not promoted until:

- compact-catalog selectability is `100%` for registered concepts;
- exact-lock precision is `100%`;
- held-out requested semantic-link recall is at least `99%`;
- first-pass structured validity is at least `99%`;
- held-out joint frame exact match is at least `90%`;
- supported complete-contract exact match is at least `95%` on the complete
  adjudicated denominator;
- OOD false-fast rate is at most `2%`;
- unknown semantic-ID and physical-schema acceptance are both zero;
- every current 16-case live probe reports provider, schema, semantic, contract,
  and latency outcomes separately; and
- the five representative contracts are evaluated per case, without converting
  one missing observation into five failures and without treating equivalent
  registered policy representation as an intent error.

All existing fail-closed validation, deterministic execution, evidence, and
deadline requirements continue to apply.

## Rejected Alternatives

### Expand a comprehensive handwritten Korean alias dictionary

Rejected as the primary coverage mechanism because Korean paraphrases and
compound descriptions are open-ended. High-precision aliases remain useful for
locks and hints.

### Give HCX raw ontology or SQL schema

Rejected because raw ontology serialization contains execution-oriented graph
detail rather than a concise Korean interpretation vocabulary, while physical
schema exposure would weaken deterministic compilation and safety boundaries.

### Remove deterministic candidate generation

Rejected because exact aliases, literals, operators, and family anchors provide
high-precision facts, stable evidence, lower ambiguity, and deterministic
fallback value.

### Add a second general semantic-linking model call

Rejected for the normal path because the compact full catalog fits the current
bounded vocabulary, while another call would increase latency, recovery
coupling, and rate-limit exposure.

## Consequences

### Positive

- A missing Korean alias no longer makes a registered semantic concept
  impossible to select.
- HCX uses its Korean sentence-level understanding within a closed server-owned
  vocabulary.
- Exact expressions remain deterministic and cannot disappear from model
  output.
- Ontology and physical bindings retain their validation and execution roles.
- Simpler request-specific schemas reduce unrelated entity and context errors.
- Hint quality, model semantic linking, contract solving, and physical planning
  can be measured independently.

### Costs and risks

- Every concept requires a concise, reviewed Korean model-facing definition.
- Full-catalog prompts increase a fixed portion of input tokens, although
  removing impossible schema branches should offset part of that cost.
- HCX may force an unknown phrase to the nearest concept, so explicit unmapped
  output and OOD measurement are mandatory.
- Proposal, ResolverView, prompt, validator, fixtures, persistence, and reports
  require coordinated versioning.
- The existing promotion report must preserve historical metrics while adding
  hybrid-specific denominators.

## Preserved Decisions

- One HCX Intent Resolver and one Answer Composer remain the normal path.
- Only the deterministic Orchestrator schedules models and executors.
- SQL, Graph, Search, calculations, policies, and evidence remain server-owned.
- Filtering, ranking, comparison, aggregation, and calculations remain
  deterministic.
- No cross-request memory, personalized advice, order execution, or unsupported
  forecast is introduced.
- The public `GET /answer` contract is unchanged.

## Non-Approval

This ADR records the accepted architecture. It does not by itself approve a
runtime promotion, database activation, deployment, push, merge, or relaxation
of any existing safety gate.
