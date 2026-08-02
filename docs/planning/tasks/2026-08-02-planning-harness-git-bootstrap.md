# Planning Harness and Git Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-local planning harness, protect competition data and secrets from Git, and connect the workspace to the approved GitHub repository with a verified initial commit.

**Architecture:** Stable product intent and trade-off rules live in `docs/planning/HARNESS.md`, while append-only decisions live under `docs/planning/decisions/` and task-specific plans live under `docs/planning/tasks/`. `AGENTS.md` acts only as the operating gate that requires those documents to be read and approved before implementation.

**Tech Stack:** Markdown, Git, GitHub CLI, GitHub HTTPS remote

## Global Constraints

- Do not commit organizer-provided raw workbooks or the competition PDF to the personal GitHub repository.
- Do not commit credentials, environment files, private keys, local databases, generated indexes, caches, or logs.
- Do not commit analysis-only work; commit only a reviewed, independently useful deliverable.
- The initial repository bootstrap may create and push `main`; subsequent work must use `codex/<topic>` branches.
- Never force-push, rewrite published history, or merge to `main` without explicit user approval.
- Stop all automatic pushes when the competition submission freeze becomes effective.

---

### Task 1: Create the project-local planning harness

**Files:**
- Create: `.gitignore`
- Create: `AGENTS.md`
- Create: `docs/planning/HARNESS.md`
- Create: `docs/planning/decisions/ADR-0001-planning-harness.md`
- Create: `docs/planning/decisions/ADR-0002-repository-data-policy.md`

**Interfaces:**
- Consumes: The approved planning-harness principles and Git policy from the user conversation.
- Produces: A stable project brief, an implementation approval gate, and append-only decision records.

- [x] **Step 1: Add repository exclusions**

Create `.gitignore` rules covering `data/`, organizer PDFs, secrets, local databases, indexes, caches, build artifacts, and logs.

- [x] **Step 2: Add the operating gate**

Create `AGENTS.md` requiring every meaningful task to read `docs/planning/HARNESS.md`, inspect accepted decisions, define success criteria, receive approval, and verify results before commit or push.

- [x] **Step 3: Add the stable project harness**

Create `docs/planning/HARNESS.md` with the financial-product problem definition, five ordered decision criteria, hard constraints, scope, non-goals, success measures, and safe defaults for unresolved contest questions.

- [x] **Step 4: Record accepted decisions**

Record why the project uses local planning documents instead of a conversation-only prompt or an immediate global skill, and why organizer-provided files remain outside the personal repository.

- [x] **Step 5: Verify document completeness**

Run:

```bash
rg -n "TB[D]|TO[D]O|implement[[:space:]]+later|fill[[:space:]]+in" AGENTS.md docs/planning .gitignore
rg -n "Problem|Criteria|Constraints|Decision|Verification|Git" AGENTS.md docs/planning
```

Expected: The placeholder scan returns no matches; the structure scan finds the required sections.

### Task 2: Initialize and audit the Git repository

**Files:**
- Create: `.git/` through Git initialization
- Inspect: all files selected by Git

**Interfaces:**
- Consumes: `.gitignore` and the governance documents from Task 1.
- Produces: A local `main` branch connected to the approved `origin` URL with only safe files staged.

- [x] **Step 1: Initialize the repository**

Run:

```bash
git init -b main
git remote add origin https://github.com/wodnjsv/financial-product-analyst.git
```

- [x] **Step 2: Verify the remote and branch**

Run:

```bash
git branch --show-current
git remote -v
```

Expected: branch is `main`; both fetch and push URLs point to the approved repository.

- [x] **Step 3: Audit ignore behavior**

Run:

```bash
git check-ignore -v data/*.xlsx docs/*.pdf .DS_Store
git status --short --ignored
```

Expected: all organizer-provided workbooks, the competition PDF, and `.DS_Store` are ignored.

- [x] **Step 4: Stage only governance files**

Run:

```bash
git add .gitignore AGENTS.md docs/planning
git diff --cached --check
git diff --cached --stat
git status --short
```

Expected: no whitespace errors; no file under `data/` and no PDF is staged.

### Task 3: Commit and push the verified bootstrap

**Files:**
- Commit: `.gitignore`, `AGENTS.md`, and `docs/planning/**`
- Push: initial `main` branch to `origin`

**Interfaces:**
- Consumes: The staged and audited files from Task 2.
- Produces: A traceable initial commit and a GitHub branch that future `codex/<topic>` branches can use as their base.

- [ ] **Step 1: Create the initial commit**

Run:

```bash
git commit -m "chore: establish planning harness"
```

Expected: one root commit containing only the approved governance files.

- [ ] **Step 2: Re-authenticate GitHub if required**

Run:

```bash
gh auth login -h github.com -p https -w
gh auth setup-git
gh auth status
```

Expected: GitHub reports the `wodnjsv` account as authenticated. Browser confirmation remains a user-controlled step.

- [ ] **Step 3: Push the initial branch**

Run:

```bash
git push -u origin main
```

Expected: `main` tracks `origin/main` and no rejected or force update occurs.

- [ ] **Step 4: Verify remote state**

Run:

```bash
git status --short --branch
git log -1 --oneline --decorate
git ls-remote --heads origin main
```

Expected: the working tree is clean, local `HEAD` equals `origin/main`, and the remote reports the same commit hash.
