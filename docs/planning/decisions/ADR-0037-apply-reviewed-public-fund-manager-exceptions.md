# ADR-0037: Apply Reviewed Public-Fund Manager Exceptions

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user approved the two official-manager
bindings and directed that `WTREWRWE` be treated as unavailable data.

**Supersedes in part:** [ADR-0036](ADR-0036-canonicalize-organizer-asset-managers.md)

## Context

The organizer public-fund master normally exposes only source-local manager
codes, so ADR-0036 forbids translating those codes into official manager
identities without reviewed evidence. A real-data audit found five
representative-fund groups whose member rows carry more than one manager code.
Official manager pages, distributor disclosures, the complete organizer code
distribution, and the OpenDART corporation list resolve two groups and expose
one invalid representative value:

- representative `032280034925` is 한국투자신종법인용MMF15호 and is managed
  by 한국투자신탁운용 (`DART_CORP_CODE=00324548`);
- representative `032530069031` is 베어링글로벌다이나믹자산배분 and is
  managed by 베어링자산운용 (`DART_CORP_CODE=00260480`);
- `WTREWRWE` is not a usable representative-fund identifier and incorrectly
  groups unrelated Mirae Asset and Hanwha products.

The 제이앤제이 and 삼성 H클럽 groups remain unresolved because their source
codes correspond to distinct legal entities and no cutoff-eligible fund-level
change disclosure has yet established one manager.

## Decision

- Resolve public-fund manager identity only for the exact reviewed pairs of
  representative value and source manager code in the two approved groups.
- Map both manager-code variants within `032280034925` to
  한국투자신탁운용 and both variants within `032530069031` to
  베어링자산운용.
- Preserve the organizer manager code and its field-level Evidence unchanged;
  only the normalized relation object becomes the reviewed canonical manager.
- Do not infer a global crosswalk from these exceptions. The same source code
  outside an approved representative group remains source-local.
- Treat `WTREWRWE` as a representative-field placeholder. Preserve its raw
  Evidence, create no representative product, and create no `hasShareClass`
  relation.
- Keep every product row. Missing representative data does not delete or merge
  a product.
- Leave the 제이앤제이 and 삼성 H클럽 groups unchanged until an official,
  cutoff-eligible fund document resolves them.

## Rejected Alternatives

### Translate the source manager codes globally

Rejected because the codes can represent different legal entities elsewhere,
and the reviewed evidence is fund-specific rather than an authoritative
institution-code master.

### Select the majority manager in every conflicting group

Rejected because class count is not legal evidence of the fund manager.

### Drop the rows containing `WTREWRWE`

Rejected because only the representative value is invalid. The organizer
product rows and their other facts remain authoritative.

## Consequences

- The two reviewed public-fund groups can expose one official manager for
  DART discovery while retaining the original organizer codes.
- `WTREWRWE` no longer creates a false representative group.
- The unresolved multi-manager audit is reduced to the two groups that still
  require official fund-level evidence.
- A rebuild of the organizer dataset is required before the stored graph and
  DART target inventory reflect this decision.
