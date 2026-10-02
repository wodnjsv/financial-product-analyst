# Personal NVIDIA intent resolution

## Scope and flow

The personal profile uses `scripts/resolve_personal_intent.py` and
`create_personal_intent_service`, with NVIDIA instead of HCX. The historical HCX
adapter and its tests remain available for old artifacts; this entry point never
constructs that adapter. Default model: `z-ai/glm-5.3-flash`.

1. Read the actual manifest hash and cutoff date of `personal-2026-08-24-v1`.
2. Discover catalog names, aliases and identifiers in the raw question, keeping
   exact source positions. Read through `fa_runtime` and read-only transactions.
3. Build the existing V3 compact semantic catalog, typed entity candidates,
   source evidence and explicit product-family locks.
4. Make a structured NVIDIA proposal. JSON object mode and the supplied schema
   guide the model; strict local schema/semantic validation remains authoritative.
   Only the system guidance copy omits repeated source/semantic/entity ID enum
   lists. Their full IDs remain in the view and the original validation schema.
5. Reuse the query-contract solver and deterministic planning compiler. Output
   the interpretation, route, plan or explicit limitation.

This CLI does not execute product queries, generate an answer, activate a dataset
or change data. `execution_performed` is always false. The three existing search
examples still execute through `search_personal_dataset.py`.

## Use

Use the existing local PostgreSQL database and installed personal environment.
The CLI only accepts loopback `financial_agent_local`, sets `fa_runtime` and
read-only mode, and uses a five-second DB statement timeout. Semantic resolution
has a 55-second overall deadline, including entity discovery and routing. One
normal semantic call and the existing shared repair/judge allowance are retained.

```sh
.venv/bin/python scripts/resolve_personal_intent.py \
  --question 'TIGER 미국S&P500의 총보수를 알려줘' \
  --api-key-file /path/to/original-workspace/api.txt
```

Alternatively omit `--api-key-file` and set `NVIDIA_API_KEY` securely in the
environment. The file format is one `Nvidia API = value` line. Keys are not copied
into environment variables, saved or displayed. Set
`FINANCIAL_AGENT_INTENT_MODEL_ID` to change the model. Only the NVIDIA HTTPS API
destination is allowed; redirects and caller-controlled arbitrary hosts are
rejected. Provider errors print stable codes without response bodies or secrets.

The outbound prompt contains the raw question, registered semantic catalog and
DB-matched candidate names, types, product families and internal IDs. It does not
contain the full source workbooks, document bodies or observation table. This is
external metadata transmission and should be understood separately from the
read-only nature of local DB access.

## Output and interpretation

| Field | Meaning |
| --- | --- |
| `interpreted_product_families` | Validated semantic frame interpretation; not an approved execution scope |
| `target_product_families` | Product families in an approved logical plan; empty when no plan is approved |
| `discovered_entities` | Source text and exact positions found in the pinned catalog |
| `frames` | Semantic links, entity roles, readiness and candidate query contracts |
| `selected_contract` | Present only when compilation produces an executable logical plan |
| `route`, `disposition`, `issue_codes` | Supported route or reason to abstain/report a limitation |
| `logical_query_plan`, `planning` | Existing compiler outputs when compilation is available |
| `execution_performed` | Always false for this entry point |

`fast`/`compose` describe compiler eligibility; they do not mean SQL ran.
`explore` describes an unsupported execution requirement or another limitation;
the CLI does not launch an exploration agent. `abstain` means the interpretation
is unresolved or blocked by validation/policy. A syntactically valid proposal
with one candidate contract is not sufficient to approve a plan.

## Improvements and boundaries

- An explicit registered family such as domestic ETF cannot be changed to
  overseas ETF by the model. Generic ETF/fund/bond words retain ambiguity.
- Entity source ranges keep repeated names distinct. Numbers, dates and words
  such as `전자` inside a product/company name do not create query literals or
  false references. Discovery is bounded to 64 matched surfaces and 16 mentions.
- Product types are read from the actual organizer metric names. This repairs
  missing ETF typing without guessing or rewriting the database.
- Every discovered entity must be resolved to one role. A subject product must
  match its selected family. A held security or asset manager cannot silently
  become the product being queried.
- Future dates beyond the stored cutoff and missing physical mappings produce
  explicit limitations. Missing periods remain unresolved rather than receive
  an invented period. No unsupported question is coerced into a domestic sample.
- Model policy flags grounded in offered evidence may add a restriction even
  when the paraphrase has no literal policy cue. This does not guarantee that
  every possible unsupported paraphrase will be detected by the model.
- Decimal points within numeric values are not clause boundaries. Conditions
  such as `0.1% 이하` keep their `lte` operator, decimal value and percent unit.
- V10 guidance separates action/family IDs from metric/relation links and makes
  every frame's non-empty `segment_ids` explicit, including unsupported intents.
  Missing keys remain errors; the service does not inject them into responses.

Exact catalog discovery does not recognize every typo or unnamed description.
Relation operands currently cannot be safely lowered by every existing planning
path; this entry point reports `ENTITY_RELATION_SCOPE_NOT_LOWERABLE` instead of
using a security/manager ID as a product ID. Many metrics still lack physical
SQL bindings, including the general one-year-return semantic path. These limits
are separate from intent interpretation and from the existing fixed search CLI.
Even registered fee bindings can require a unit qualifier absent from a question;
the public-fund fee definition remains physically unverified. Such questions may
have a complete semantic candidate while still lacking an executable plan.

## Verification

Offline tests cover provider errors/schema boundaries, source ranges, family
locks, four-family interpretation, named products, missing periods, cutoff,
policy restrictions and routing limitations. Actual read-only DB probes verified
TIGER/KODEX/SPY family types, Samsung Electronics and an asset manager, including
repeated source positions. No database writes were performed.

The initial live request was rejected by automatic approval review for unclear
metadata-export authorization. The user then explicitly authorized questions,
semantic catalog and matched candidate names/types/families/internal IDs. Live
testing proceeded within that scope; no full source data or hidden reasoning was
sent or logged. Initial failures are retained separately from later successes.

The final GLM-5.3-Flash V10/adapter-V4 run passed all six interpretation/routing
cases with one model call each, no repair/judge calls, and 22.2–36.7-second total
processing times. No product query was executed.

| Question | Verified result |
| --- | --- |
| Domestic ETF fee ≤ 0.1% | `screen`, `fee_rate lte 0.1 percent`, `compose`, logical plan present |
| Overseas ETF one-year returns, top 5 | `P1Y`, descending return order, limit 5; unregistered physical binding limitation |
| TIGER 미국S&P500 fee | Exact catalog product ID, domestic ETF scope; missing unit qualifier limitation |
| Domestic bond maturity | `lookup` of `maturity_date`; unregistered physical binding limitation |
| Public fund fee ≤ 0.3% | Public-fund scope and exact predicate; unverified physical definition limitation |
| Next-year best-performing ETF recommendation | `FUTURE_FORECAST`, `abstain`, `POLICY_BLOCKED`, no plan |

These are six verified examples, not a universal accuracy or latency guarantee.
The backend's native JSON Schema options and alternative hosted model IDs did
not provide a verified replacement in the bounded comparison. Retain JSON mode,
the GLM default, and strict local validation. Details and final offline results
are in the [task plan](../planning/tasks/2026-10-02-nvidia-intent-routing.md).

Provider documentation:
[hosted GLM-5.3-Flash API](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)
and [GLM serving guide](https://docs.nvidia.com/nim/vision-language-models/latest/get-started/advanced/get-started-glm-5-3-flash.html).
