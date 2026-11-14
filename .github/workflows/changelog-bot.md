---
# Weekly changelog PR bot (GitHub Agentic Workflow).
#
# This is the gh-aw SOURCE file. After editing, regenerate the compiled
# GitHub Actions workflow with:
#
#     gh aw compile changelog-bot
#
# and commit the generated `.github/workflows/changelog-bot.lock.yml` alongside it.

on:
  # Fire every Saturday at around 12:00 UTC.
  schedule: weekly on saturday around 12:00 UTC
  # Allow maintainers to trigger a run on demand.
  workflow_dispatch:

runs-on: [self-hosted, noble, amd64]
runs-on-slim: self-hosted

# The self-hosted runner image ships a gh too old for 'gh attestation verify'
# in the agent job's AWF install. Install a modern, checksum-verified gh before
# the agent job's setup scripts run.
pre-steps:
  - name: Install modern gh CLI
    run: |
      GH_VERSION="2.83.1"
      GH_SHA256="1c5252d4ce3db07b51c01ff0b909583da6364ff3fdc06d0c2e75e62dc0380a34"
      tmp="$(mktemp -d)"
      curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" -o "$tmp/gh.tgz"
      echo "${GH_SHA256}  $tmp/gh.tgz" | sha256sum -c -
      tar -xzf "$tmp/gh.tgz" -C "$tmp"
      install -m 0755 "$tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh
      rm -rf "$tmp"
      gh version
    env:
      GH_TOKEN: ${{ github.token }}

# The self-hosted runner image does not ship the Docker Compose plugin, so
# AWF's `docker compose up -d` fails with "unknown shorthand flag: 'd' in -d"
# and the agent exits 125. Install the plugin before the agent job's setup
# scripts run (top-level steps run before the agent job's own setup).
steps:
  - name: Install Docker Compose plugin
    run: |
      if docker compose version >/dev/null 2>&1; then
        echo "Docker Compose plugin already present, skipping install."
        docker compose version
        exit 0
      fi
      COMPOSE_VERSION="v5.5.0"
      mkdir -p ~/.docker/cli-plugins
      curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
        -o ~/.docker/cli-plugins/docker-compose
      chmod +x ~/.docker/cli-plugins/docker-compose
      docker compose version

# The runner image's Node is too old for gh-aw's runtime scripts ('Cannot find
# module node:fs' in activation). Set up a modern Node for the activation job.
jobs:
  activation:
    pre-steps:
      - name: Setup modern Node for gh-aw runtime
        uses: actions/setup-node@v4
        with:
          node-version: "24"
  # gh-aw's install_copilot_cli.sh uses --prefer-toolcache, which does not land
  # the copilot binary on PATH on this self-hosted runner image, so the
  # threat-detection job exits 127. Install the CLI globally with npm instead.
  detection:
    pre-steps:
      # The detection job runs its own AWF install, which needs gh >= 2.49
      # for 'gh attestation verify'; the self-hosted runner ships older and
      # the top-level pre-steps only cover the agent job.
      - name: Install modern gh CLI
        run: |
          GH_VERSION="2.83.1"
          GH_SHA256="1c5252d4ce3db07b51c01ff0b909583da6364ff3fdc06d0c2e75e62dc0380a34"
          tmp="$(mktemp -d)"
          curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" -o "$tmp/gh.tgz"
          echo "${GH_SHA256}  $tmp/gh.tgz" | sha256sum -c -
          tar -xzf "$tmp/gh.tgz" -C "$tmp"
          install -m 0755 "$tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh
          rm -rf "$tmp"
          gh version
        env:
          GH_TOKEN: ${{ github.token }}
      - name: Install GitHub Copilot CLI
        run: |
          export NPM_CONFIG_PREFIX="$HOME/.npm-global"
          mkdir -p "$NPM_CONFIG_PREFIX"
          npm install -g @github/copilot@1.0.103
          echo "$NPM_CONFIG_PREFIX/bin" >> "$GITHUB_PATH"
          "$NPM_CONFIG_PREFIX/bin/copilot" --version

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
  # canonical/landscape-documentation is public, so the checkout needs no
  # token; only the push to it needs credentials (see safe-outputs below).
  - repository: canonical/landscape-documentation
    path: ./landscape-documentation
    fetch: ["*"]

engine:
  id: gemini
  # The native Gemini engine uses GEMINI_API_KEY directly and takes an exact
  # model id, avoiding the pi engine's model-grammar rejection of vendored
  # OpenRouter ids (github/gh-aw#77514). Gemini does not resolve gh-aw model
  # aliases, so this must be an exact id.
  model: gemini-3.5-flash
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}

network:
  allowed: [defaults]

# Shell access for inspecting history and formatting dates. The pi engine
# cannot allowlist individual commands, so bash is open; the AWF sandbox,
# network allowlist, and safe-output handlers still confine the run.
tools:
  bash: ["*"]
  edit:

# The agent never pushes directly; its file edits are turned into a pull request.
# gh-aw binds the whole safe_outputs job to a single credential for all its git
# checkouts and pushes (github/gh-aw#77580), so that one credential must be able
# to write both this repo and canonical/landscape-documentation. The default
# GITHUB_TOKEN cannot write to landscape-documentation, so the job runs on
# LANDSCAPE_CHANGELOG_TOKEN, a fine-grained PAT with contents and pull-requests
# read+write on both repos. Every handler below inherits it.
safe-outputs:
  github-token: ${{ secrets.LANDSCAPE_CHANGELOG_TOKEN }}
  runs-on: self-hosted
  threat-detection:
    engine: copilot
    runs-on: [self-hosted, noble, amd64]
  create-pull-request:
    title-prefix: "build: "
    labels: [changelog, automation]
    team-reviewers: [canonical/landscape]
    draft: false
    if-no-changes: ignore
    max: 1 # exactly one own-repo changelog PR per run
    preserve-branch-name: true
    # Handles the lifecycle where the previous changelog PR was merged and its
    # branch still exists.
    recreate-ref: true
    # The bot only ever touches CHANGELOG.md in this repo; the handler rejects
    # any other path outright. (gh-aw allowed-files filters by path only, not
    # diff status, so "prepend a new section, never edit existing entries"
    # stays prompt-enforced.)
    allowed-files: ["CHANGELOG.md"]
  push-to-pull-request-branch:
    target: "*"
    target-repo: canonical/landscape-documentation
    github-token: ${{ secrets.LANDSCAPE_CHANGELOG_TOKEN }}
    required-labels: [changelog, automation]
    # Docs PR updates may only touch release-notes pages (including index.md).
    allowed-files: ["docs/reference/release-notes/*.md"]
    max: 1
---

# Weekly changelog update

You maintain the changelog for the landscape-debarchive charm. Your job is to draft a new changelog section summarizing recent user-facing changes and open a pull request with it.

## Hard prohibitions

- In this repository, the only file you ever change is `CHANGELOG.md`. This is mechanically enforced by the pull-request handler: `allowed-files` rejects any other path.
- NEVER edit or delete existing `CHANGELOG.md` entries — only prepend new dated sections. If an existing entry looks wrong, flag it under `Changelog entries to review` instead.

## Gather the commits

1. The scan window is time-based: list the commits from the last four weeks with `git log --since="4 weeks ago" --no-merges --pretty=%H%x09%s`. `main` is squash-merged, so each merged PR is a single commit on this list. Do NOT anchor on the last commit that touched `CHANGELOG.md`: anyone can edit the changelog, so a changelog anchor would silently treat undocumented commits as covered whenever an unrelated changelog edit lands. Four weeks against a weekly schedule gives three weeks of overlap with the previous run, so omissions leapfrogged by later merges are still caught; the deduplication rules below prevent double-filing.
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
