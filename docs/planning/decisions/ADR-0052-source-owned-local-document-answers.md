# ADR-0052: Render local document answers only from retrieved sources

- Date: 2026-10-02
- Status: Accepted
- Approval: The user explicitly requested diagnosis and correction of the
  remaining guidance, reference-collision and unsupported-summary issues.
- Scope: ADR-0050 personal local profile. This supersedes the free document
  prose contract used by the September 23 quotation task; ADR-0007's production
  evidence ledger and claim verification remain unchanged.

## Decision

The local document model may return only `citations`, containing all retrieved
source IDs exactly once. Each ID denotes its complete supplied excerpt.
Reject free prose, quote text, spans, offsets, unknown or omitted selections.
The server renders document fields, counts, source links and complete excerpts.
Final document validation requires exact agreement with this source-owned text
and one complete literal quote per source. Literal reference-like strings in
the source remain intact; they do not become application citation references.

Guidance describes the actual query bounds and exact security-name condition,
rather than fixed example counts or a hardcoded common-stock restriction.
Historical free-prose answers remain rejected under the new contract. An
explicit replay may create a separate source-only derivative using saved IDs;
it must preserve the original files, failure verdict and failing exit status.

## Reasons and rejected alternatives

Valid IDs and literal quotes do not prove model-authored prose. A second model
judge remains fallible and adds latency; keyword/negation blacklists cannot
cover arbitrary unsupported claims. Selecting shorter spans can omit conditions
and negations. Rendering whole supplied excerpts is the smallest deterministic
way to eliminate unsupported prose from this local document output path.

## Trade-offs and limits

Free paraphrased summaries are no longer output by this local path. The model
still resolves questions, but does not author document facts. Source fidelity
does not certify upstream PDF extraction, full document context, exact quotation
pages, current market information or promotion into production release evidence.
Original KRX observations and independent manager supplements remain unchanged.
