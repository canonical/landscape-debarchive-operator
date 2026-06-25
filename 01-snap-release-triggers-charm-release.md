# Snap releases are tied to charm releases

Every release of a snapped Landscape service drives a release of the charm that operationalizes it for juju: when revision `N+1` of the landscape-debarchive snap is released to the latest/edge snap channel, a new revision of the landscape-debarchive-operator charm is released to the latest/edge charm channel with that snap revision pinned.

The relationship is one-directional, not one-to-one. The charm can also be released on its own - for example to ship a fix in the charm code - producing new charm revisions that still pin the *same* snap revision. So a given snap revision maps to one _or more_ charm revisions, and charm revision numbers run well ahead of the snap revisions they pin (the snaps also had revisions released before the first charm ever existed).

From a juju operations perspective, refreshing the charm is how any change reaches deployments - a new snap revision _or_ a charm-only fix. The charm pins the exact snap revision (per architecture) it installs, so a new snap revision only reaches units once a charm revision that pins it is released; but not every charm release bumps the snap.

## How this is automated

The trigger is enforced by GitHub Actions across the two repositories: a snap release fans out to a charm release, so nobody cuts a charm release by hand just to deliver a new snap revision. Charm-only changes are released independently, on the operator repo's own workflow, and pin the unchanged snap revision.

### Snap side (this repo, `landscape-go`)

On each snap release, a [`repository_dispatch`](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event) event is sent to this repo. The event is:

  ```jsonc
  {
    "event_type": "snap-released",
    "client_payload": {
      "snap": "landscape-debarchive",
      "channel": "latest/edge",          // snap channel == target charm channel
      "revisions": { "amd64": 42, "arm64": 43 }
    }
  }
  ```

### Charm side (this repo, `landscape-debarchive-operator`)

The `Release Charm` workflow (`.github/workflows/release-charm.yaml`):

- triggers on `repository_dispatch` with `types: [snap-released]`, and also exposes a `workflow_dispatch` with `amd64-revision`, `arm64-revision`, and `charm-channel` inputs so a release can be cut or re-cut manually;
- writes the per-architecture revisions from the payload into the charm's hard-coded snap-revision pin - the `DEBARCHIVE_SNAP_REVISIONS` map in `src/debarchive.py` - via the `.github/scripts/update_snap_revisions.py` helper, which only accepts integer revisions so untrusted dispatch input cannot inject content into the charm source;
- opens a pull request with that change (using `peter-evans/create-pull-request`) rather than committing to `main` directly, so the update lands through the repo's normal `lint`/`unit-test` review gate.

This is the initial version: it stops at opening the PR. Building the charm with `charmcraft` and releasing it to the channel in `client_payload.channel` (the charm channel matching the snap channel) is a planned follow-up.

### Required configuration

- **`CHARM_PR_TOKEN`** secret in this repo (optional but recommended): a PAT used by the `Release Charm` workflow when opening the revision-bump PR. A PR opened with the default `GITHUB_TOKEN` does not trigger other workflows, so without this secret the PR's `lint`/`unit-test` checks won't run automatically. The workflow falls back to `GITHUB_TOKEN` when `CHARM_PR_TOKEN` is unset.
- **`CHARM_DISPATCH_TOKEN`** secret in the snap repo: a fine-grained PAT or GitHub App installation token with `Contents: write` on this operator repo (or a classic PAT with the `repo` scope). The default `GITHUB_TOKEN` cannot dispatch to another repository, so this is what lets the snap release reach this repo.

### Note on multi-architecture revisions

Each architecture gets its own distinct store revision (the `amd64` and `arm64` snaps are uploaded independently), so the payload carries both and the charm pins them per architecture. A single shared revision integer would only ever be correct for one architecture.
