# Stage 03A Ingestion Container Verification Fix

**Date:** 2026-08-22

**Status:** Complete — local and NCP Linux/amd64 verification passed

## Assumptions

- Commit `c2065fe` is the authoritative Stage 03A baseline.
- The NCP Linux/amd64 build fails because the ingestion image runs contract and
  ingestion tests without copying three files those tests read at runtime.
- The organizer workbooks, Object Storage objects, database contents, and
  ingestion behavior are outside this corrective change.

## Intended outcome

The ingestion verification image copies every tracked configuration input used
by its in-image test command and completes the same locked synthetic verification
on NCP Linux/amd64 without placing organizer data in an image layer.

## Non-goals

- No DDL, repository, mapper, writer, pipeline, or dataset lifecycle change.
- No change to raw organizer data, Object Storage contents, or NCP permissions.
- No dependency refresh or relaxation of an existing lock file.

## Constraints

- Add a regression test before changing the Dockerfile.
- Add only `.dockerignore`, `requirements/contracts.lock`, and
  `docker/contracts.Dockerfile` to the ingestion image's copied inputs.
- Preserve all existing data and secret exclusions.
- Commit and push only the task-related plan, test, and Dockerfile.

## Verification plan

1. Add a focused test for the three required copy inputs and capture the
   expected failure on the current Dockerfile.
2. Add the three `COPY` instructions and rerun the focused test plus the
   existing container-policy tests.
3. Run the non-PostgreSQL contract and ingestion suite, contract schema export,
   compile check, dependency check, and diff/security/data-path audits.
4. Push the verified branch and rerun the no-cache Linux/amd64 build and image
   command on the NCP Ubuntu host.

## Success criteria

- The new regression test fails before and passes after the Dockerfile change.
- All local verification commands exit zero.
- The staged diff contains no organizer data, credentials, generated artifacts,
  dependency changes, or unrelated files.
- The NCP no-cache build and container run both exit zero.

## Local verification evidence

- RED: 3 focused failures for the three missing copy inputs.
- GREEN: 7 focused container-policy tests passed.
- Image-equivalent non-PostgreSQL suite: 355 passed, 12 deselected.
- Broader non-PostgreSQL suite: 492 passed, 319 deselected.
- Contract schema export, compile check, dependency check, and diff check passed.
- Local Docker runtime was unavailable; the required NCP Ubuntu substitute used
  the exact pushed commit and passed the no-cache Linux/amd64 build and run with
  exit code 0.
