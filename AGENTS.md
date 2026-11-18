# AGENTS.md

<!-- BEGIN Wslynllc fork section: the fork's only addition, kept in one block so an upstream sync is one hunk. -->
## Wslynllc fork

`Wslynllc/hindsight` forks `vectorize-io/hindsight`. Upstream's title and `CLAUDE.md` pointer stay as they were,
and `CLAUDE.md` is untouched: read it for commands, architecture and coding conventions.

- Shared standards win: `Wslynllc/project-standards` (`README.md`, `Owner approval.md`, `Delivery gates.md`,
  `CI and runners.md`). This section only adds this repository's values.
- Owner tap (`rkroelin-yes`) is required only for `/hindsight-integrations/hermes/` (its `*.md` and `tests/` are
  unowned) and `/.github/` (workflows and CODEOWNERS), as `.github/CODEOWNERS` defines. Everything else, upstream
  code, docs and tests included, merges after an independent agent review. Never edit CODEOWNERS to skip a tap.
- What merging to `main` does:
  - `hindsight-docs/**` or `deploy-docs.yml`: the push runs `deploy-docs.yml`, which publishes the docs to GitHub
    Pages (writes live).
  - `hindsight-integrations/hermes/`: changes what later Hermes installs get. This fork installs from its own
    checkout, not the upstream catalog pin (that README, "Install").
  - Anything else deploys nothing: the memory server runs the upstream image, not a build of this fork
    (`.github/CODEOWNERS`).
- Tags are the live path. A `v*` tag runs `release.yml` and an `integrations/**` tag runs
  `release-integration.yml`; both publish packages with repository credentials, and `owner-gate` does not hold
  tags (project-standards `Gates/README.md`). Never push a tag or run `scripts/release*.sh`.
- Stop switch: none in the tree (no workflow reads a repository variable). Whether the fork holds the `pypi` and
  `npm` environment credentials is unknown.
- No `Makefile`, so no `make check`. Lint as CI does: `LINT_ALL=1 ./scripts/hooks/lint.sh`. Hermes provider:
  `cd hindsight-integrations/hermes && uv sync && uv run pytest tests -v` (stubbed Hermes core, no server).
  `test.yml` (PRs to `main`) also reads provider API secrets, so it is not a credential-free check. The
  `owner-gate` ruleset has no required status checks; which CI jobs should be required is unknown.
- Hooks are opt-in (`scripts/setup-hooks.sh`, `.githooks/pre-commit`). With hooks off, run `lint.sh` by hand.
- Generated, never hand-edited: `hindsight-docs/docs-integrations/hermes.md` (`node
  hindsight-docs/scripts/sync-hermes-doc.mjs`, from the Hermes README), the OpenAPI spec and `hindsight-clients/`
  (`scripts/generate-openapi.sh`, `scripts/generate-clients.sh`), and the coding-agents `skill/SKILL.md` and docs
  page. Run `lint.sh` before regenerating. No "Unreleased" changelog entries. All in `CLAUDE.md`.
- Before a push: `trufflehog git file://$PWD --no-update --no-verification` must find nothing. `.env` is
  git-ignored and `.env.example` is the name-only template. Check `git remote -v`: push to `Wslynllc/hindsight`,
  never `vectorize-io/hindsight`.
- Read first: `README.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `.claude/skills/code-review/SKILL.md` (coding
  standards), `hindsight-integrations/hermes/README.md` ("Development"),
  `hindsight-docs/docs/developer/configuration.mdx` and `hindsight-system-tests/README.md`.
- Related repos: `vectorize-io/hindsight` (upstream; sync policy unknown), `Wslynllc/Homelab-Memory` (shared
  homelab memory: design, deployment and status, per its GitHub description), `NousResearch/hermes-agent` (hosts
  the Hermes plugin catalog; the fork does not bump its pin) and `Wslynllc/project-standards`.
- Kanban: no lane board for this repo (`hermes kanban boards list`, 2026-11-18).
- Unknown: how the provider reaches live Hermes clients, and protection on the `pypi` and `npm` environments.
<!-- END Wslynllc fork section -->

See [CLAUDE.md](./CLAUDE.md) for project documentation and coding conventions.
