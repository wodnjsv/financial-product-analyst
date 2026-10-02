# Server-owned local document quotes — 2026-09-23

The user approved the next original-quotation fix. Continue the personal local
worktree under ADR-0050 and the deterministic rendering principle of ADR-0007.

Assumption: retrieval supplies trusted, already bounded verbatim excerpts.
The model returns only answer prose and citation IDs; the server copies each
referenced excerpt into quotes, preserving whitespace exactly. Choosing shorter
spans is deferred: whole bounded excerpts are simpler and avoid model-authored
text or character offsets. This validates quotation fidelity to supplied excerpts,
not upstream PDF extraction or truth of free-form summary prose.

1. Add regression tests first: exact Unicode/whitespace preservation, no input
   mutation, bad/unknown/duplicate/missing references, model-authored quotes.
2. Add a strict local document draft contract, prompt, and renderer connected
   to the existing local answer validator. Invalid input yields explicit failure.
3. Add an explicit replay option for the saved legacy document response. Keep
   original validation failures visible, derive a new draft without old quote
   text, and render new server quotes. Never overwrite or relabel old responses.
4. Run related tests and replay Q3. All generated quotes must equal stored
   excerpts; the malformed original D1 quote must remain rejected separately.

No API calls, SQL behavior changes, source supplementation, production release
integration, or automated repair of summary facts are included.

## Results

- Regression test collection initially failed because the new renderer did not
  exist; after implementation all 85 release/answer-contract tests passed,
  including 18 new quotation cases.
- Explicit legacy Q3 replay: original QUOTE_NOT_VERBATIM remains visible;
  server-rendered quotes cover all three documents and exactly equal the
  1,288 characters of stored excerpts, including whitespace.
- Original response SHA256 unchanged. Derived output is untracked in the parent
  workspace: data/personal-search-20260918/server-quotes-replay-20260923.json.
- Existing prose remains unchanged, including its known incorrect description
  of matched_documents; quotation fidelity does not certify summary accuracy.
- The prompt and renderer are available for the next live local test; no live
  model test or production-service integration was performed in this task.
- git diff --check passed. No commit, push, model call, or DB write.
