---
# Biweekly changelog PR bot (GitHub Agentic Workflow).
#
# This is the gh-aw SOURCE file. After editing, regenerate the compiled
# GitHub Actions workflow with:
#
#     gh aw compile changelog-bot
#
# and commit the generated `.github/workflows/changelog-bot.lock.yml` alongside it.

on:
  # Cron cannot express "every other Saturday", so we fire every Saturday at
  # around 12:00 UTC and the prompt gates on ISO-week parity (see the body below).
  schedule: weekly on saturday around 12:00 UTC
  # Allow maintainers to trigger a run on demand (ignores the biweekly gate).
  workflow_dispatch:

permissions:
  contents: read

# The default checkout is shallow (fetch-depth 1) with no tags, which makes the
# agent see only the latest commit. Fetch full history so it can scan the
# commit window and read the commit log. A second checkout
# fetches the documentation repo (all branches) for the shared release-notes PR.
checkout:
  - fetch-depth: 0
  # Second checkout: the shared docs repo where this bot maintains its
  # release-notes island in the single shared changelog PR.
  - repository: canonical/landscape-documentation
    path: ./landscape-documentation
    fetch: ["*"]
    github-token: ${{ secrets.COPILOT_GITHUB_TOKEN }}

engine:
  id: copilot
  model: sonnet

# Only the shell commands the agent needs to inspect history and format dates.
tools:
  bash:
    - "git"
    - "date"
    - "safeoutputs"
  edit:

# The agent never pushes directly; its file edits are turned into a pull request.
# One token governs both PR handlers (gh-aw requirement when two handlers touch
# the same repo); it needs contents+pull-requests write on the docs repo too.
safe-outputs:
  github-token: ${{ secrets.COPILOT_GITHUB_TOKEN }}
  create-pull-request:
    title-prefix: "build: "
    labels: [changelog, automation]
    team-reviewers: [canonical/landscape]
    draft: false
    if-no-changes: ignore
    max: 2 # own-repo changelog PR + docs PR
    allowed-repos: ["canonical/landscape-documentation"]
    preserve-branch-name: true
    # Handles the lifecycle where the previous docs PR was merged and its
    # branch still exists.
    recreate-ref: true
    # The bot only ever touches CHANGELOG.md here or release-notes pages in
    # the docs repo; the handler rejects any other path outright. (gh-aw
    # allowed-files filters by path only, not diff status, so "prepend a new
    # section, never edit existing entries" stays prompt-enforced.)
    allowed-files: ["CHANGELOG.md", "docs/reference/release-notes/*.md"]
  push-to-pull-request-branch:
    target: "*"
    target-repo: canonical/landscape-documentation
    required-labels: [changelog, automation]
    # Docs PR updates may only touch release-notes pages (including index.md).
    allowed-files: ["docs/reference/release-notes/*.md"]
    max: 1
---

# Biweekly changelog update

You maintain the changelog for the landscape-debarchive charm. Your job is to draft a new changelog section summarizing recent user-facing changes and open a pull request with it.

## Hard prohibitions

- In this repository, the only file you ever change is `CHANGELOG.md`. This is mechanically enforced by the pull-request handler: `allowed-files` rejects any other path.
- NEVER edit or delete existing `CHANGELOG.md` entries — only prepend new dated sections. If an existing entry looks wrong, flag it under `Changelog entries to review` instead.

## Biweekly gate

This workflow is scheduled every Saturday but should only act every **other** Saturday. Releases publish on **odd** ISO weeks.

This run was triggered by the `${{ github.event_name }}` event. Use that value literally to decide whether the gate applies:

1. If the triggering event is `workflow_dispatch`, always proceed regardless of the week number (manual runs bypass the biweekly gate entirely).
2. Otherwise (a `schedule` run), run `date +%V` to get the current ISO week number. If that week number is **even**, stop immediately and make no changes — do not open a pull request. Only proceed on **odd** weeks.

## Gather the commits

1. The scan window is time-based: list the commits from the last four weeks with `git log --since="4 weeks ago" --no-merges --pretty=%H%x09%s`. `main` is squash-merged, so each merged PR is a single commit on this list. Do NOT anchor on the last commit that touched `CHANGELOG.md`: anyone can edit the changelog, so a changelog anchor would silently treat undocumented commits as covered whenever an unrelated changelog edit lands. Four weeks against a biweekly schedule gives two weeks of overlap with the previous run, so omissions leapfrogged by later merges are still caught; the deduplication rules below prevent double-filing.
2. Skip any commit whose subject has no trailing pull request reference ` (#1234)`. Such commits cannot carry the ` (#1234)` bullet marker the deduplication relies on, so they can never be filed safely; if one looks user-facing, mention it in the PR body under `Changelog entries to review` instead of filing it.
3. Deduplicate the rest by pull request number. For each commit, extract its PR number `<N>` from the trailing ` (#1234)` reference in the subject. Skip the commit if ANY of the following hold:
   a. Its own commit added a NON-EMPTY changelog entry: run `git show --format= -- CHANGELOG.md <commit>` — if the diff adds one or more bullet lines (lines starting with `- `), the author documented the change themselves and it counts as coverage. If the commit touched `CHANGELOG.md` without adding any bullet (e.g. only a heading or whitespace), it is NOT coverage: do not file an entry for it either (an empty section can be a deliberate choice), and flag it in the review section below instead.
   b. The changelog already covers it: search `CHANGELOG.md` in the working tree for the exact reference `#<N>` (match the full number — `#123` must not match `#1234`). Every bullet this bot writes ends with ` (#<N>)`, so an existing mention means this PR is already covered. Only committed entries on `main` are visible here — if the previous changelog PR is still open, its entries are not in the file yet.

## Select user-facing commits only

Include only conventional commits that a charm operator would notice. Commit subjects in this repo are conventional commits, but match the type prefix case-insensitively and use your judgment for non-conforming subjects.

- **Include**: `feat:`, `fix:`, `perf:`, and any breaking change (a `!` before the colon, e.g. `feat!:` / `fix!:`).
- **Maybe Include**: `refactor: ` commits, only if they are user-facing.
- **Exclude**: `chore:`, `ci:`, `test:`, `build:`, `docs:`, and `style:`, commits,
  plus anything that only touches tooling, tests, or CI.
- **Exception**: any commit that touches `src/snap_revisions.json` is user-facing (it changes which payload snap revisions the charm deploys), so include it even if it is typed `chore:` or `build:`.

Breaking changes are not always flagged in the subject. For every selected commit, also inspect the full commit message with `git show -s --format=%B <sha>` and look for `BREAKING CHANGE:` or `BREAKING-CHANGE:` footers. A commit carrying such a footer is a breaking change even when its subject has no `!` — classify it as breaking and note the breaking nature in the docs island bullet.

For each selected commit, derive a one-line summary from its subject line, including its type prefix and any `(LP: #NNNN)` Launchpad references, but excluding any `(scope)` after the type prefix. Proofread and correct any obvious spelling or grammar errors. Remove Jira issue references such as `LNDENG-5678` wherever they occur in the subject, and strip any trailing GitHub pull request reference such as ` (#1234)` from the summary text. Do **not** strip `(LP: #NNNN)` references. If there are no user-facing commits in the window at all, stop and make no changes.

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

Open a pull request with the change. Use a title like `changelog update for <date>` (the `build: ` prefix is added automatically) and a body that lists the included commits in the sorted order from above, notes the merged PR each entry covers, explains that only user-facing changes were selected, and includes the `Changelog entries to review` heading when any entries were flagged. If no new entries were needed, do nothing — do not open an empty pull request.

## Docs release notes (shared PR)

You also maintain the user-facing release notes. All Landscape changelog bots share ONE pull request against `canonical/landscape-documentation` that drafts the release notes for the in-development Landscape release. Each bot owns exactly one marked section (island) in that PR. NEVER open a separate per-repo docs PR: find the shared PR and push to it.

The docs work happens in the separate `./landscape-documentation` checkout. The hard prohibitions above apply to this repository (landscape-debarchive-operator) only; editing the release-notes page in the docs checkout is expected and allowed.

Your island content derives from ALL user-facing commits selected in the window above — not only the ones newly filed in `CHANGELOG.md`: a PR that brought its own changelog entry still belongs in the release notes. Rewrite those selected commits into docs-appropriate bullets, excluding any entries flagged in `Changelog entries to review`.

1. Determine the in-development Landscape release `YY.MM`: Landscape releases are `YY.04` and `YY.10`. From today's date, the in-development release is the next boundary strictly in the future (before April -> `YY.04`; before October -> `YY.10`; otherwise `(YY+1).04`). As of November 2026 this is **27.04** (betas are underway), so the target page is `docs/reference/release-notes/27.04-release-notes.md`.
2. Find the shared docs PR: use the GitHub tools to list open PRs in `canonical/landscape-documentation` with labels `changelog` and `automation` (title starts with `build: `). If one exists, this is THE docs PR — use it regardless of which `YY.MM` page it targets.
3. If a docs PR exists:
   - In the `./landscape-documentation` checkout, check out that PR's head branch (branches were fetched via the wildcard fetch at setup: `git checkout <branch>`). If the branch is not among the fetched refs, skip the docs work for this run — the agent has no credentials to fetch it.
   - Other Landscape bots push to this same shared branch, so the checkout (fetched at setup time) may be stale and another bot may push while you work. The agent environment has NO git credentials — `git fetch` fails here, so NEVER attempt to fetch or rebase. Work from the PR branch ref as fetched at setup; keep every edit strictly inside your own island markers so it applies cleanly over the other bots' island updates. `push_to_pull_request_branch` applies your patch to the branch's live tip in a credentialed job; if a concurrent push made it conflict, the delivery fails safely — do not retry, the next run redoes the work. NEVER force-push over another bot's commits.
   - Update ONLY your own island (see below). If the release-notes page for the in-development version does not exist on that branch, create it from the template below and add it to the toctree in `docs/reference/release-notes/index.md` (newest non-LTS page goes directly under the LTS entries, matching existing ordering).
   - Commit in the docs checkout and deliver via `push_to_pull_request_branch` with `pull_request_number` set to the docs PR number.
4. If no docs PR exists, skip the docs work for this run entirely: make no changes in the `./landscape-documentation` checkout. NEVER create the shared docs PR yourself — only landscape-server's bot creates it, which avoids several bots racing to create the same PR; every other bot only ever updates an existing one. (Your own-repo changelog PR logic is unaffected.)
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
