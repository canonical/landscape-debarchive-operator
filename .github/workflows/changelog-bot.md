---
# Weekly changelog PR bot (GitHub Agentic Workflow).
#
# This is the gh-aw SOURCE file. After editing, regenerate the compiled
# GitHub Actions workflow with:
#
#     gh aw compile changelog-bot
#
# and commit the generated `.github/workflows/changelog-bot.lock.yml` alongside it.
#
# Requires gh-aw v1.3.0 exactly — verify with `gh aw version` before compiling.
# v1.3.0 is what emits the commit-hash-pinned import reference (older compilers
# leave the import floating on a branch) and what accepts the shared component's
# two-slash OpenRouter model id; compiling this file with an older gh aw silently
# rewrites the lockfile and drops both, so check the version first.
#
# The shared plumbing (engine, runner setup, gh/node/compose installs, threat
# detection, docs push handler) comes from the shared component imported below.
# What stays here is only what differs for this repo: the trigger, the runners,
# the changelog PR's allowed-files, and the prompt body.

on:
  # Fire every Saturday at around 12:00 UTC.
  schedule: weekly on saturday around 12:00 UTC
  # Allow maintainers to trigger a run on demand.
  workflow_dispatch:

permissions:
  contents: read
  # The agent must list open pull requests to enforce "never open a second
  # changelog PR". Without this the token is Contents:read only and every
  # list_pull_requests call returns 403 "Resource not accessible by integration".
  pull-requests: read

# The agent and threat-detection jobs need Docker/AWF, so they target the noble
# amd64 runners; the framework and safe_outputs jobs use the generic
# self-hosted label. These cannot live in a shared component.
runs-on: [self-hosted, noble, amd64]
runs-on-slim: self-hosted

imports:
  - canonical/landscape-internal-docs/.github/workflows/shared/changelog-bot-infra.md@d627562cfa37544175061045d201f4304154a62e

safe-outputs:
  # The bot only ever touches CHANGELOG.md in this repo; the handler rejects any
  # other path outright. (gh-aw allowed-files filters by path only, not diff
  # status, so "prepend a new section, never edit existing entries" stays
  # prompt-enforced.)
  create-pull-request:
    title-prefix: "build: "
    labels: [changelog, automation]
    team-reviewers: [canonical/landscape]
    draft: false
    if-no-changes: ignore
    max: 1 # exactly one own-repo changelog PR per run
    preserve-branch-name: true
    signed-commits: false
    # Handles the lifecycle where the previous changelog PR was merged and its
    # branch still exists.
    recreate-ref: true
    allowed-files: ["CHANGELOG.md"]
---
# Weekly changelog update

You maintain the changelog for the landscape-debarchive charm. Your job is to draft a new changelog section summarizing recent user-facing changes and open a pull request with it.

## Hard prohibitions

- In this repository, the only file you ever change is `CHANGELOG.md`. This is mechanically enforced by the pull-request handler: `allowed-files` rejects any other path.
- NEVER edit or delete existing `CHANGELOG.md` entries — only prepend new dated sections. If an existing entry looks wrong, flag it under `Changelog entries to review` instead.

## Gather the commits

1. The scan window is time-based: list the commits from the last four weeks against the repository's default branch, not the ref this run was dispatched on: `git log --since="4 weeks ago" --no-merges --pretty=%H%x09%s origin/main`. Always use `origin/main` for the range — a `workflow_dispatch` run may check out a bot or feature branch whose own commits are automation churn, and those must never be classified as product changes. If `origin/main` is not present locally, use the checked-out HEAD and say so in the run output. `main` is squash-merged, so each merged PR is a single commit on this list. Do NOT anchor on the last commit that touched `CHANGELOG.md`: anyone can edit the changelog, so a changelog anchor would silently treat undocumented commits as covered whenever an unrelated changelog edit lands. Four weeks against a weekly schedule gives three weeks of overlap with the previous run, so omissions leapfrogged by later merges are still caught; the deduplication rules below prevent double-filing.
2. Skip any commit whose subject has no trailing pull request reference ` (#1234)`. Such commits cannot carry the ` (#1234)` bullet marker the deduplication relies on, so they can never be filed safely; if one looks user-facing, mention it in the PR body under `Changelog entries to review` instead of filing it.
3. Deduplicate the rest by pull request number. For each commit, extract its PR number `<N>` from the trailing ` (#1234)` reference in the subject. Skip the commit if ANY of the following hold:
   a. Its own commit added a NON-EMPTY changelog entry: run `git show --format= <commit> -- CHANGELOG.md` and read only the ADDED side of that diff — lines beginning with `+`, ignoring the `+++ b/CHANGELOG.md` header. If any added line is itself a changelog bullet — that is, a line starting with `+- ` — the author documented the change themselves and it counts as coverage. Never count removed lines or the `--- a/CHANGELOG.md` header: `-` is both the diff's removal marker and the changelog's bullet marker, so a commit that only deletes, rewraps, or moves bullets adds none of its own and is not coverage. If the commit touched `CHANGELOG.md` without adding any bullet (e.g. only a heading or whitespace), it is NOT coverage: do not file an entry for it either (an empty section can be a deliberate choice), and flag it in the review section below instead.
   b. The changelog already covers it: search `CHANGELOG.md` in the working tree for the exact reference `#<N>` (match the full number — `#123` must not match `#1234`). Every bullet this bot writes ends with ` (#<N>)`, so an existing mention means this PR is already covered. Only committed entries on `main` are visible here — if the previous changelog PR is still open, its entries are not in the file yet.

## Select user-facing commits only

Do not decide from memory or by skimming. Work from the exact `git log` output you collected and classify every commit, one line at a time.

First, write out a classification table with one row per commit, in this exact format:

```
| # | type | user-facing? | subject |
|---|------|--------------|---------|
| 1 | feat | yes | add resolute base support |
```

Rules for the `user-facing?` column:

- **yes**: `feat:`, `fix:`, `perf:`, and any breaking change (a `!` before the colon, e.g. `feat!:` / `fix!:`). Commit subjects in this repo are conventional commits, but match the type prefix case-insensitively and use your judgment for non-conforming subjects.
- **maybe**: `refactor:` commits, only if they are user-facing.
- **no**: `chore:`, `ci:`, `test:`, `build:`, `docs:`, and `style:` commits, plus anything that only touches tooling, tests, or CI.
- **Exception**: any commit that touches `src/snap_revisions.json` is user-facing (it changes which payload snap revisions the charm deploys), so mark it **yes** even if it is typed `chore:` or `build:`.

After the table, write the count: `Included: N of M`. `N` is the number of rows marked `yes` (count a `maybe` as included only if you marked it yes). If the table has fewer rows than the number of lines in your `git log` output, you dropped commits — redo the table until every commit appears.

**Only if `N` is 0** may you skip drafting a new changelog section and opening a pull request. In that case do not stay silent: find the open changelog pull request in this repository (label `changelog`) and post a comment on it containing the full classification table and the line `Included: 0 of M`, so a human can see exactly which commits were considered and why nothing was drafted. If no open changelog PR exists, report the table in your run summary instead.

If `N` is 1 or more, you MUST continue and open (or update) a pull request. Never stop just because most commits are chores; a single `feat:` or `fix:` means proceed.

Breaking changes are not always flagged in the subject. For every selected commit, also inspect the full commit message with `git show -s --format=%B <sha>` and look for `BREAKING CHANGE:` or `BREAKING-CHANGE:` footers. A commit carrying such a footer is a breaking change even when its subject has no `!` — classify it as breaking and note the breaking nature in the docs island bullet.

For each selected commit, derive a one-line summary from its subject line, including its type prefix and any `(LP: #NNNN)` Launchpad references, but excluding any `(scope)` after the type prefix. Proofread and correct any obvious spelling or grammar errors. Remove Jira issue references such as `LNDENG-5678` wherever they occur in the subject, and strip any trailing GitHub pull request reference such as ` (#1234)` from the summary text. Do **not** strip `(LP: #NNNN)` references.

## Sort the commits

Group the commits by their type. Adhere to the following order.

- Breaking changes (a `!` in the subject or a `BREAKING CHANGE:`/`BREAKING-CHANGE:` footer)
- `feat`
- `fix`
- `perf`
- `refactor`

Within each group, maintain the relative ordering of the commits. Use this ordering when listing the new entries in the pull request body.

## Compose the new section

Charm releases are Charmhub revisions assigned at publish time, not versions recorded in this repository, so changelog sections are dated, not versioned. There is no version to compute and no other file to bump.

Prepend a new dated section to the top of `CHANGELOG.md`, keeping newest first. If the file does not exist yet, create it with this exact header:

```
# Changelog

All notable user-facing changes to this charm are documented here, newest first.
```

Then add the new section directly below that header (or, for an existing file, above the previous topmost section):

```
## YYYY-MM-DD

### Features

- <summary> (#1234)
```

- Use `date +%F` for the section date (e.g. `2026-07-18`).
- Use these section headings, in this order: `### Breaking changes`, `### Features`, `### Fixes`, `### Performance`, `### Refactors`. Omit any heading whose group is empty.
- Each bullet begins with `- ` and carries one user-facing commit summary. End every bullet with ` (#<N>)` naming the merged pull request it covers (e.g. `- feat: add resolute base support (#1234)`). Later runs rely on this marker to recognize already-covered PRs, so never omit it.
- Include only commits that passed the deduplication rules above. If every selected commit is already covered, make no changelog changes.

## Review existing changelog entries

The deduplication rules only check whether a change is covered. For each commit in the window that touched `CHANGELOG.md`, plus every `fix:` commit, check for mismatches. Do NOT edit or delete the entries. List them under a `Changelog entries to review` heading in the PR body, one bullet per PR with the reason and evidence (commit/PR links).

- **Empty entry on a user-facing change**: the commit touched `CHANGELOG.md` but added no bullet, while matching "Select user-facing commits". Propose an entry. If the change is only reachable in a non-default configuration, make this reasoning clear.
- **Non-empty entry with no user impact**: the commit added a `CHANGELOG.md` bullet, but every other path in `git show --name-only --format= <commit>` is a test (`tests/`), CI/tooling (`.github/`, `tox.ini`), or docs file.
- **Fix for an unreleased regression**: for a `fix:` commit F, take the hunks F modified (`git show -U0 F`) and run `git blame --porcelain -L <start>,<end> F^ -- <file>` to find the commits that introduced those lines. If they all fall inside the window, the bug never shipped and no entry should be filed. A PR title or body that references another PR merged in the same window is supporting evidence. If blame results are mixed, mark the entry "possible", not certain.

Exclude flagged entries from the changelog update and from the docs release-notes island. If a pull request is opened, list the flagged entries under a `Changelog entries to review` heading in its body. If no pull request is opened (no new entries to file), report the flagged entries in your run summary instead — do not open a pull request that contains no changes.

## Open the pull request

Before making any edit, create your working branch from the default branch, not from the ref this run was dispatched on: `git checkout -b <branch> origin/main`. The dispatch ref may be a bot or feature branch carrying automation commits; if you commit on top of it, the resulting PR contains all of those commits. The PR must contain ONLY the changelog commit on top of `origin/main`.

First check for an existing open changelog pull request in this repository (label `changelog`). Exactly one should ever be open at a time.

- If one is already open, do NOT open a second. Check whether its changelog section already covers the commits you selected (the date and the listed subjects). If it does, make no changes and note that the existing PR is already current. If it is missing any of your selected commits, post the missing entries as a comment on that PR with `add_comment` and stop; there is no handler that pushes to an existing own-repo pull request branch, so do not claim you updated it and do not open a second PR.
- Only if no changelog PR is open, open one with the change. Use a title like `changelog update for <date>` (the `build: ` prefix is added automatically) and a body that lists the included commits in the sorted order from above, notes the merged PR each entry covers, explains that only user-facing changes were selected, and includes the `Changelog entries to review` heading when any entries were flagged. If no new entries were needed (`Included: 0 of M`), do not open a pull request — post the classification table as a comment on the existing changelog PR instead, as described above.

Never open a second changelog PR while one is open.

## Docs release notes (shared PR)

You also maintain the user-facing release notes. All Landscape changelog bots share ONE pull request against `canonical/landscape-documentation` that drafts the release notes for the in-development Landscape release. Each bot owns exactly one marked section (island) in that PR. The shared PR — titled `build: draft release notes for Landscape YY.MM`, labeled `changelog` and `automation`, based on `develop` — is created centrally every Friday around 12:00 UTC by the `release-notes-draft` workflow in canonical/landscape-documentation, which also pre-seeds the release-notes page with all eight islands. No changelog bot ever creates that PR; NEVER open a docs PR yourself: find the shared PR and push to it.

The docs work happens in the separate `./landscape-documentation` checkout. The hard prohibitions above apply to this repository (landscape-debarchive-operator) only; editing the release-notes page in the docs checkout is expected and allowed.

Your island content derives from ALL user-facing commits selected in the window above — not only the ones newly filed in `CHANGELOG.md`: a PR that brought its own changelog entry still belongs in the release notes. Rewrite those selected commits into docs-appropriate bullets, excluding any entries flagged in `Changelog entries to review`.

1. Determine the in-development Landscape release `YY.MM`: Landscape releases are `YY.04` and `YY.10`. From today's date, the in-development release is the next boundary strictly in the future (before April -> `YY.04`; before October -> `YY.10`; otherwise `(YY+1).04`). As of November 2026 this is **27.04** (betas are underway), so the target page is `docs/reference/release-notes/27.04-release-notes.md`.
2. Find the shared docs PR: use the GitHub tools to list open PRs in `canonical/landscape-documentation` with labels `changelog` and `automation` (titled `build: draft release notes for Landscape YY.MM`, based on `develop`). If one exists, this is THE docs PR — use it regardless of which `YY.MM` page it targets.
3. If a docs PR exists:
   - In the `./landscape-documentation` checkout, check out that PR's head branch (branches were fetched via the wildcard fetch at setup: `git checkout <branch>`). If the branch is not among the fetched refs, skip the docs work for this run — the agent has no credentials to fetch it.
   - Other Landscape bots push to this same shared branch, so the checkout (fetched at setup time) may be stale and another bot may push while you work. The agent environment has NO git credentials — `git fetch` fails here, so NEVER attempt to fetch or rebase. Work from the PR branch ref as fetched at setup; keep every edit strictly inside your own island markers so it applies cleanly over the other bots' island updates. `push_to_pull_request_branch` applies your patch to the branch's live tip in a credentialed job; if a concurrent push made it conflict, the delivery fails safely — do not retry, the next run redoes the work. NEVER force-push over another bot's commits.
   - Update ONLY your own island (see below). If the release-notes page for the in-development version does not exist on that branch, create it from the template below and add it to the toctree in `docs/reference/release-notes/index.md` (newest non-LTS page goes directly under the LTS entries, matching existing ordering).
   - Commit in the docs checkout and deliver via `push_to_pull_request_branch` with `pull_request_number` set to the docs PR number.
4. If no docs PR exists, skip the docs work for this run entirely: make no changes in the `./landscape-documentation` checkout. NEVER create the shared docs PR yourself — it is created weekly by the `release-notes-draft` workflow in canonical/landscape-documentation; every changelog bot only ever pushes to that existing PR. (Your own-repo changelog PR logic is unaffected.)
5. If you have no user-facing changes this cycle, leave your island untouched; do not create or update the docs PR. (Your own-repo changelog PR logic is unaffected.)

### Your island

Island markers (HTML comments, invisible in rendered docs). Your slug is `landscape-debarchive-operator`. The full island set, in this fixed order:

1. `landscape-server` — Landscape Server
2. `landscape-client` — Landscape Client
3. `landscape-ui` — Web portal
4. `landscape-go` — Snaps (debarchive, outbox, task-handler services)
5. `landscape-server-operator` — Landscape Server charm
6. `landscape-client-charm` — Landscape Client charm
7. `landscape-debarchive-operator` — Debarchive charm
8. `landscape-task-handler-operator` — Task handler charm

Island format inside `## Additional updates`:

```markdown
<!-- changelog-bot:landscape-debarchive-operator:start -->
### Debarchive charm

#### Features
- <docs-appropriate bullet>

#### Fixes
- <docs-appropriate bullet>
<!-- changelog-bot:landscape-debarchive-operator:end -->
```

Rules:
- BEFORE writing, read `.github/instructions/release-notes.instructions.md` and `.github/instructions/documentation.instructions.md` in the docs checkout and follow them (applicability: state self-hosted vs SaaS and the component; factual, non-promotional; do not invent benefits, migration steps, or breaking-change claims).
- Rewrite your selected commits into user-facing docs bullets: no conventional-commit prefixes, no `(scope)`, no `(#1234)`, no Jira keys. Keep Launchpad references but format them as `[LP: #NNNN](https://bugs.launchpad.net/landscape/+bug/NNNN)`. Write in the style of existing release notes (see any `docs/reference/release-notes/*.md` page): complete sentences, no trailing period inconsistency, admin-focused.
- Omit `#### Features` / `#### Fixes` when empty. If your island has no entries yet, put `(pending)` as the island body.
- NEVER edit outside your own island markers. Other sections belong to other bots.
- When creating the page, include ALL eight islands in the fixed order above (yours filled, the rest with `(pending)`), so later bot runs find their markers.

### New-page template

File `docs/reference/release-notes/YY.MM-release-notes.md` (dots in the filename, matching `26.10-release-notes.md`; anchor uses dashes):

```markdown
---
myst:
  html_meta:
    description: "Release notes for Landscape YY.MM. Draft; updated automatically until release."
---

(reference-release-notes-YY-MM)=
# YY.MM release notes

> Landscape Server YY.MM runs on Ubuntu 26.04 LTS Resolute Raccoon, 24.04 LTS Noble Numbat, or 22.04 LTS Jammy Jellyfish.

```{note}
This page is a draft maintained automatically until release.
```

## Highlights

(pending - written at release time)

## Additional updates

(eight islands here)

## Upgrade

(pending - written at release time)

## Bug fixes

(pending - written at release time)
```
