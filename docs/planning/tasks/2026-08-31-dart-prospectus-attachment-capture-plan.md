# DART Prospectus Attachment Capture Plan

**Date:** 2026-08-31

**Status:** Completed for two-product proof; full-universe capture remains pending

## Outcome

Capture the full-prospectus PDF attached to an already selected DART filing,
instead of treating the OpenDART original-document ZIP as the complete
prospectus. Verify the reusable path with synthetic tests and one additional
domestic ETF before expanding it to the remaining products.

## Assumptions and constraints

- The selected DART receipt remains the regulatory filing identity.
- The persisted public source locator remains the DART filing viewer URL.
- The full-prospectus attachment must be an official `dart.fss.or.kr` PDF bound
  to the selected receipt and target product.
- The API key, raw PDF, extracted text, and live response bodies remain outside
  Git.
- Existing atomic object capture and SHA-256 behavior are reused.
- Substring or fuzzy matching must not establish the product Entity binding.

## Non-goals

- Summary-prospectus capture
- PDF section extraction or chunking
- VectorDB population
- Full-universe execution
- PostgreSQL or Object Storage writes

## Steps and verification

1. Add failing synthetic attachment-resolution and capture tests.
   - Verify: the tests fail because the DART attachment capture API is absent.
2. Implement strict full-prospectus attachment resolution and immutable capture.
   - Verify: the generated DART report PDF is not selected; one exact official
     attachment is selected; ambiguous, missing, unsafe, or empty responses fail
     closed.
3. Correct DART candidate discovery metadata to point to the filing viewer.
   - Verify: existing DART discovery tests and new locator assertion pass.
4. Run one additional live domestic-ETF capture outside Git.
   - Verify: non-empty PDF, valid page count, target product name, required
     section text, size, and SHA-256.
5. Run focused and broad non-PostgreSQL tests and inspect the final diff.

## Success criteria

- Both live product probes yield valid, non-empty full-prospectus PDFs.
- Synthetic tests prevent selecting the correction-shell PDF or a different
  product attachment.
- No credential, raw source object, extracted text, or live response is tracked.
- No section parsing, chunking, or full-universe collection is introduced.
