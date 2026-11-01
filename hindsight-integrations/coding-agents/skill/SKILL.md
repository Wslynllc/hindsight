---
name: hindsight-coding-agent
description: How this machine's Hindsight coding-agent memory works — the plugin behind the 🧠 banner. Use when the user says "store/remember this in hindsight", asks what the memory/knowledge pages are, wants to configure per-repo memory (disable, rename banks, git depth), or something memory-related looks broken.
---

<!-- GENERATED from README.md (its skill:begin regions) + skill-src/preamble.md.
     Edit those, then run: npm run skill:build -->

# Hindsight Coding-Agent Memory

This machine runs the `hindsight-coding-agents` plugin: long-term project memory for coding
sessions, backed by a Hindsight server. You (the agent) are already wired into it — this skill
explains what happens automatically, which tools you have, and how to configure or debug it.

## What happens automatically (no action needed)

- **Per-repo memory bank**: each repository resolves to a bank (shown in the session banner:
  `↳ memory bank “coding-agent::<repo>”`). Worktrees share the main repo's bank.
- **Opt-in**: memory runs only when a server is configured and the repo is under `optInPaths`.
  Anywhere else the plugin is inert.
- **Ingestion builds itself**: every session start, a background engine sets up the bank and its 5
  knowledge pages. Git history (`gitIngest`) and the codebase survey (`codebaseSurvey`) are off unless
  configured. There is NO ingest command to run.
- **Session context**: by default, the first prompt of a session recalls memories into context.
  `autoInject` switches the source: `reflect` (one deep synthesis), `pages` (knowledge page search
  hits), or `none` (nothing injected; the agent searches the knowledge pages first and reflects only
  when they are too shallow).
- **Write-back**: the session transcript is retained into the bank automatically at session end
  (per-turn on opencode). The user never needs to "save" a conversation.

## Storing things deliberately

When the user says "store this in hindsight" / "remember this":

- The **current conversation** is captured automatically at session end — say so; no tool needed.
- An **external document, notes, or durable findings** → `hindsight_ingest_document(title, content)`.
- A **new feature/initiative being started** → `hindsight_capture_initiative(title, summary)`,
  right after the plan is agreed and before code is written.
- A **plan that materially changed** (goal, scope, or rationale — including mid-implementation) →
  call `hindsight_capture_initiative` again with `relates_to_page_id` set to that initiative's page
  id, summarising the _current_ intent. Same page, updated plan — never a second page. Trivial
  course-corrections don't count.

## Retrieving

- `hindsight_search_knowledge_pages(query)` — FIRST STOP for project questions (components,
  conventions, past decisions, initiatives). Server-side hybrid search, fast.
- `hindsight_read_knowledge_page(page_id)` / `hindsight_list_knowledge_pages` — read pages fully.
- `hindsight_reflect(query)` — deep reasoning over the whole memory for WHY questions and exact
  decided values; slower (seconds), use deliberately.
- Credit visibly whenever memory informs an answer: start that part with
  `🧠 From Hindsight memory (<page>): …` — and never credit memory that didn't contribute.

## Correcting wrong or stale memory

If you verify that something Hindsight served is wrong or outdated (the code, git, or an external
source contradicts it), FIX THE RECORD — don't just ignore it. Call
`hindsight_ingest_document` with:

- **title**: `Correction: <topic>` (e.g. `Correction: retry policy 4xx set`)
- **content**: (1) what memory claimed, (2) what is verifiably true now, (3) the evidence you
  checked (file/commit/output). Quote exact values verbatim.

Newer facts supersede older ones in retrieval, so one clear correction permanently outranks the
stale memory. Do this whenever you catch a wrong injected memory, a stale knowledge-page claim, or
an outdated decision — silent disregard leaves the trap armed for the next session.

## Install / update

Build once, then install from `hindsight-integrations/coding-agents` in the checkout:

```bash
npm ci && npm run skill:build && npm run build
node dist/installer.js install claude-code codex --server self-hosted --api-url http://<server>:8888
node dist/installer.js uninstall claude-code codex   # removes exactly what install added
node dist/installer.js update                        # re-stage the runtime only, no rewiring
node dist/installer.js stats                         # how often each agent uses Hindsight
```

`install` takes an explicit target — `all`, or one or more harness names. A bare `install` changes
nothing and prints the choice. It copies the runtime to `~/.hindsight/coding-agents`, so later
rebuilds reach the agents only when you run `update` (or `install`) again. To update, pull, rebuild
and run `update`.

Memory stays off until both of these hold: a server is configured (`apiUrl`), and the project is
opted in (`optInPaths`). See [Opt-in only](#opt-in-only).

## Configuration

Configuration is **one JSON file**: `~/.hindsight/coding-agent.json`. Layering, later wins per field:

1. built-in defaults
2. environment variables — `HINDSIGHT_API_URL`, `HINDSIGHT_API_TOKEN`, and one per scalar setting
   (`HINDSIGHT_<FIELD_IN_CAPS>`), for containers and CI that inject config rather than write a file
3. the file's top level
4. its `harnesses.<name>` section — per-agent override
5. its `paths.<prefix>` section — per-directory override, applied after the bank is resolved
   (see [Per-directory overrides](#per-directory-overrides--pathsprefix))
6. its `banks.<resolvedBankId>` section — per-repo override, applied after the bank is resolved
   (see [Per-repo opt-in/out](#per-repo-opt-inout--banksbankid))

Environment variables are a **fallback**: the file wins wherever it sets a value, so adding env to
an existing setup changes nothing. The two list-valued settings, `retainTags` and `optInPaths`, take
a comma-separated value (`HINDSIGHT_RETAIN_TAGS="project:{gitProject},env:work"`); entries are
trimmed and blanks dropped.
The map-valued settings (`mapPathToBank`, `harnesses`, `paths`, `banks`, `retainMetadata`) are file-only —
per-key branching doesn't survive flattening into one variable. `maxParallelRetains` is available
as `HINDSIGHT_MAX_PARALLEL_RETAINS` for containers and CI.

`HINDSIGHT_CONFIG` moves the file itself — point it at another path for a container or a test
harness where `$HOME` is not the right anchor. It is still exactly one file; only its location
changes. (The other variables that are not settings are `HINDSIGHT_LOG_FILE`, `HINDSIGHT_DIAG_FILE`,
`HINDSIGHT_USAGE_FILE` and `HINDSIGHT_LOG_LEVEL` — see [Diagnostics & logging](#diagnostics--logging).)

### When a change takes effect

Config is read when a process starts — the file is not watched — so when an edit applies depends on
what reads it:

| host                                                                                                        | reads the file                                                      | an edit applies            |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------- |
| hook harnesses (Claude Code, Codex CLI, Cursor CLI, GitHub Copilot CLI, Grok Build, Antigravity CLI, Devin) | once per hook invocation — each hook is its own short-lived process | on your next prompt        |
| persistent plugins (opencode, opencode 2, Kilo CLI, Cline CLI, pi, Prime Agent, DeepSeek Harness)           | once per workspace, when the host loads the plugin                  | after restarting the agent |
| the MCP server behind the `hindsight_*` tools                                                               | once at startup                                                     | in your next session       |

`apiToken` is the exception. Every host re-reads it when the server rejects a request, so enabling
authentication or rotating the key is picked up on the next call with nothing to restart —
otherwise a rotation would leave a long-running agent failing every memory call until it was
restarted. Everything else follows the table: `apiUrl`, `disabled`, bank routing, `gitIngest`, and
the survey and knowledge-page settings.

`hindsight_diagnose` reports both sides of that gap — what the file says now, and what the running
client is actually using.

### Opt-in only

Nothing is remembered until you say so. `optInOnly` is on by default, so name the projects that may
use memory:

```jsonc
{
  "apiUrl": "http://localhost:8888",
  "optInPaths": ["~/work/client-x", "~/oss"],
}
```

Anything outside those paths is **inert**: no bank is created, nothing is retained, no seed runs,
and the agent behaves exactly as it would without the plugin. Approving costs nothing else —
`optInPaths` says _which projects_, not _which bank_, so an approved repo keeps its usual
`coding-agent::{gitProject}` name. Paths are prefixes, so approving `~/work` approves every repo
under it while each still gets its own bank.

A `mapPathToBank` entry counts as opted in too, since routing a path to a named bank already
declares that project. A bare `bankId` does not: it names a bank rather than a project, so it
cannot say which work may be remembered, and a privacy switch has to fail closed.

There is no per-repo opt-in file, for the same reason there is no repo-carried config at all: a
cloned repository must not be able to turn memory on.

There is deliberately no repo-carried config file — per-repo bank routing is `mapPathToBank`,
per-agent differences are `harnesses.<name>`.

Each entry point knows which harness it _is_ (the opencode plugin is loaded by opencode, the codex
hook by Codex...), so one shared config serves several agents side by side:

```jsonc
{
  "apiUrl": "http://localhost:8888",
  "harnesses": {
    "opencode": { "reflectTimeoutMs": 60000 },
    "claude-code": { "disabled": true }, // e.g. memory off for Claude only
  },
}
```

### Reference

| field                   | default                              | meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ----------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apiUrl`                | —                                     | http(s) base URL of your Hindsight server, e.g. `http://localhost:8888`. Without one the plugin is inert, and a `vectorize.io` host is refused. A `paths` or `banks` section can change the server but cannot supply the only one                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `apiToken`              | —                                    | bearer token for your server, if it requires one. Picked up without restarting the agent: a long-lived host re-reads it after a rejected request, so enabling auth or rotating the key mid-session recovers on the next call                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `serverMode`            | `self-hosted`                        | leave it unset. `self-hosted` is the only mode; any other value leaves the plugin inert |
| `bankId`                | —                                    | **explicit static bank**; unset ⇒ per-repo dynamic resolution (below)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `dynamicBankId`         | dynamic iff no `bankId`              | force dynamic (`true`) or static (`false`) resolution                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `bankIdTemplate`        | `"coding-agent::{gitProject}"`       | dynamic bank id format; the default makes every agent share one bank per repo                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `mapPathToBank`         | —                                    | absolute path → bank; **longest prefix wins**; linked worktrees inherit their main checkout's mapping; overrides everything                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `optInOnly`             | `true`                                | run memory ONLY in opted-in projects — everything else is inert, with no bank created; see [Opt-in only](#opt-in-only)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `optInPaths`            | —                                    | directories opted in, matched as prefixes with `~` expanded; each repo beneath and its linked worktrees are approved while keeping their own dynamic bank                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `resolveWorktrees`      | `true`                               | linked worktrees inherit the main checkout's bank identity, path approval, and mapping                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `retainTags`            | —                                    | extra tags on every document written by the integration, e.g. `["project:{gitProject}"]` — see **Recording where a memory came from** below                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `retainMetadata`        | —                                    | extra metadata on every document written by the integration, e.g. `{"repo": "{gitProject}"}`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `retainContext`         | see description                      | the `context` sent with every session write-back. Extraction reads it to decide whose claim a sentence is, so the default names both speakers, and asks for an agent's own "fixed" or "passes" to be stored as its claim rather than as fact. Accepts the same `{placeholder}` templates as `retainTags`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `manageBankConfig`      | `true`                               | let the plugin shape the bank's own configuration — the retain strategies it writes under, the `knowledge` entity-label group, and, on a bank that has none, the missions. Writing is **additive**: it adds what the bank does not define and never overwrites what is there, so your control-plane edits survive — the one exception is the extraction mode of its own strategies, which follows `retainExtractionMode`. Set `false` to keep it out of the bank config entirely — see **A bank you shape yourself** below                                                                                                                                                                                                                                                                                                                                                                                      |
| `retainExtractionMode`  | `"concise"`                          | how the server extracts memories from sessions, commits and documents: `"concise"`, `"verbose"`, `"verbatim"` or `"chunks"` (store the text, no extraction). Every Stop writes the session back, so this is what each turn costs — `"verbose"` pulls more detail for several times the tokens. Kept in sync on the plugin's own retain strategies every session, so a change reaches existing banks too (not with `manageBankConfig: false`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `defaultBankConfig`     | —                                    | bank-config fields of your own for the banks the plugin shapes, e.g. `{"enable_observations": false, "enable_auto_consolidation": false, "mental_model_min_refresh_interval_seconds": 21600}`. Keys are the bank-config API's own field names. Written under the same additive rule as the rest: only where the bank does not define the field, so a bank the plugin creates is born with these instead of the server's defaults and a value you set in the control plane is never overwritten. Wins over the template on a key both name (`enable_observations`); `retain_strategies`, `entity_labels` and `retain_extraction_mode` are refused, since the plugin governs them itself. Ignored with `manageBankConfig: false` — see **A bank you shape yourself** below. File-only, like `recallOptions`; in a `banks.<id>` section it replaces the global map rather than merging into it                     |
| `observationScopes`     | `"shared"`                           | how consolidation groups observations: `"shared"` (default) = ONE global scope per bank, so every agent on a repo builds one set of beliefs; also `"combined"` (the server default), `"per_tag"`, `"all_combinations"`, `[["t"]]`; `"per_source"` adds a scope per `source:` kind alongside the global one, so commit knowledge and conversation knowledge consolidate apart                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `disabled`              | `false`                              | hard off-switch (inert plugin/hook — a no-memory baseline)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `reflectTimeoutMs`      | `20000`                              | **automatic** session-reflect timeout; on hook harnesses the installer registers a 30s prompt-hook timeout, so going above ~20s also means raising that hook's `timeout` in the host's config, or the host kills the hook mid-reflect; on timeout or a 5xx the hook falls back to knowledge-page search, then to a raw recall of observations (recorded)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `reflectToolTimeoutMs`  | `330000`                             | timeout for the agent-invoked `hindsight_reflect` tool — a call the agent waits on, whose high-budget synthesis on a populated bank runs for minutes. Defaults above the server's own reflect wall timeout (`HINDSIGHT_API_REFLECT_WALL_TIMEOUT`, 300s) so the server decides when to give up. Unset, it inherits an explicitly raised `reflectTimeoutMs`, but a short one never lowers it                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `injectTimeoutMs`       | `7000`                               | retrieval timeout in milliseconds for `autoInject: "pages"` and `autoInject: "recall"`; also the **shared** budget for page search then recall after a reflect timeout/5xx (recall gets only the time left after page search). Set e.g. `2000` to limit turn latency or `15000` for a slower self-hosted bank. Environment fallback: `HINDSIGHT_INJECT_TIMEOUT_MS`. On hook harnesses, injection must fit the host's prompt-hook timeout (30s by default); for reflect with fallback, allow for **`reflectTimeoutMs` + `injectTimeoutMs`**, and raise the host hook's `timeout` when needed                                                                                                                                                                                                                                                                                                                     |
| `reflectBudget`         | `"high"`                             | reflect budget for the `hindsight_reflect` tool: `"low"`, `"mid"` or `"high"`. Drop it on a large bank where high-budget synthesis exceeds the server's wall timeout. The automatic session-start reflect always uses `"low"` to fit its hook window and is unaffected                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `autoInject`            | `"recall"`                            | what to inject once, on the session's **first prompt**: `"reflect"` = a low-budget reflect synthesis (on timeout/5xx it falls back to page search, then recall); `"pages"` = the knowledge pages matching the prompt by search; `"recall"` = the bank's memories recalled for the prompt (what it asks for is `recallOptions`, observations by default); `"none"` = nothing — the agent searches knowledge pages first and reflects only when they are too shallow. `"pages"` and `"recall"` are retrieval only (no LLM), their time budget is `injectTimeoutMs`, and when one finds nothing for the prompt it tries again on the next one, up to 5 prompts                                                                                                                                                                                                                                                     |
| `autoReflect`           | —                                     | **deprecated** — use `autoInject`. Still honoured (`false` = `autoInject: "none"`), ignored when `autoInject` is set, and logs a deprecation warning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `pageSearchLimit`       | `3`                                  | knowledge pages ONE search returns. Applies to every search of the bank — the `autoInject: "pages"` injection, the reflect fallback, and the agent's own `hindsight_search_knowledge_pages` tool — because the limit lives on the client they all share                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `recallOptions`         | see description                      | overrides merged key-by-key into the body of every recall — the `autoInject: "recall"` source and the reflect fallback. Keys are the API's own recall parameters, passed straight through, so anything recall accepts is settable without a new option here; `query` is the one field it cannot replace. The default body is `{"types": ["observation"], "budget": "low", "max_tokens": 2000, "include": {"entities": null}}`, and what you set is merged over it one key at a time — `{"max_tokens": 4000}` changes the budget and leaves the rest alone. Observations are the consolidated layer, so they answer best per token, but a bank with **consolidation disabled never grows any** and the default recall comes back empty on it: set `{"types": ["world", "experience"]}` there, or `{"types": null}` for every type. File-only, like `retainMetadata` — an object does not flatten into an env var |
| `toolGuideExtra`        | —                                    | your own guidance on how the agent should treat memory, added **after** the built-in tool guide (at session start and on every refresh) and after the crediting note returned with `hindsight_search_knowledge_pages` results. It adds to the built-in text, never replaces it. Set it per harness or per bank like any other key, e.g. `"Memory is a past record, not current state: verify any claim against the code before acting on it."`                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `pageRefreshEveryTurns` | `1`                                  | refetch the knowledge pages and re-inject the page roster + tool guide every N user turns (`0` also means 1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `pageTriggerType`       | `"manual"`                            | when NEW knowledge pages refresh, i.e. what keeping them current costs — `"manual"` (default) never on their own, `"cron"` on `pageTriggerCron` only and only when actually stale, `"auto-refresh"` after every consolidation that produced new material. Naming a `pageTriggerCron` without a type selects `"cron"`. Auto-refresh is the most current and by far the most expensive: one synthesis per page per consolidation. Maps to the page's `trigger.refresh_cron`, or `trigger.refresh_after_consolidation` in the Hindsight API (`true` for auto-refresh, `false` for manual)                                                                                                                                                                                                                                                                                                                                                                                      |
| `pageTriggerCron`       | `"H * * * *"`                        | schedule for `pageTriggerType: "cron"` — UTC, standard 5-field cron, e.g. `"0 3 * * *"`. The default is hourly, each page on its own hashed minute. Sets the page's `trigger.refresh_cron`, which the API treats as mutually exclusive with `refresh_after_consolidation`; a scheduled refresh is skipped when nothing changed. Write a field as `H` to give each page its own value there — see **Spreading refreshes with `H`** below                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `pages`                 | every page                           | per-page configuration for the seeded knowledge pages, keyed by page name (case-insensitive): `false` skips a page entirely, `{"source_query": "..."}` seeds it with your question instead of the built-in one. Omitted, all five pages are seeded with their built-in queries. This is the supported way to own a page's wording — the plugin re-syncs a page whose live query differs from the one it is configured to have, so a query edited through the API or the control plane is replaced on the next session. A skipped page is **not deleted**: one already seeded keeps its content and stops being re-synced. The scoping clause is appended to your query too, so a reworded page cannot start reporting a dependency's decisions as this project's. File-only, like `recallOptions`; in a `banks.<id>` section it replaces the global map rather than merging into it                             |
| `customPages`           | —                                    | knowledge pages of your own, seeded alongside the five above and keyed by the name they get: `{"Security posture": {"source_query": "...", "tags": ["knowledge:decision"]}}`. `source_query` is required; `tags` picks which facts feed the page and is optional — omitted, the page draws on everything the bank holds. A separate setting from `pages` on purpose, so that an unknown name there stays a typo warning rather than quietly creating a page. File-only, and replaced (not merged) by a `banks.<id>` section                                                                                                                                                                                                                                                                                                                                                                                     |
| `autoSeed`              | `true`                               | SessionStart: auto-seed a cold repo's bank from git history                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `seedLimit`             | `300`                                | git-log document size: a full write keeps the newest commits, between half of this and this many (the window moves in steps of half), and logs how many older ones it drops                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `codebaseSurvey`        | `false`                               | SessionStart: headless survey of a cold repo's structure, run under the current harness's own CLI (claude/codex/antigravity/opencode), falling back to any available agent. Off by default because that CLI uses its own model provider, usually a hosted one                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `surveyModel`           | `haiku`                              | model for the survey — Claude recipe only (`claude -p --model`); other agents use their configured default                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `surveyBudgetUsd`       | `2`                                  | survey spend cap — Claude recipe only (`claude -p --max-budget-usd`); other agents rely on their read-only sandbox                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `surveyRefreshCommits`  | `20`                                 | re-run the survey at SessionStart once this many commits have accrued since the last one, so the structural pages track an architecture that keeps moving (`0` = survey a cold repo only, never again)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `retainSessions`        | `true`                               | session write-back, honored by every harness: hook harnesses write the transcript on Stop, Factory Droid also writes on its cancellation notification, and plugin harnesses (opencode, opencode 2, Kilo) upsert it every turn plus an idle flush that captures the reply the per-turn pass can't see. Set `false` - globally, per harness, or per bank - to stop writing transcripts (the background history import stops with it) while recall, git ingest and the memory tools keep working                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `maxParallelRetains`    | `10`                                 | cap on concurrent retain-related requests: drain()'s per-op polls plus deepen's chat/git retain pools. The API rate-limits bursts, not single requests — if you see 429s, lower this rather than raising it                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `logLevel`              | `"info"`                             | plugin-log verbosity (`"debug"` \| `"info"` \| `"warn"` \| `"error"`); `HINDSIGHT_LOG_LEVEL` env overrides                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `gitIngest`             | `"none"`                              | git depth for seeding AND staying current (same engine): `"message"` = commit messages only (one doc, re-upserted when HEAD has a commit it lacks); `"full"` = messages + per-commit full diffs (progressive, newest first); `"none"` = git off                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `harnesses.<name>`      | —                                    | per-harness override of any field above                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `harness`               | `opencode`                           | **deepen engine only**: which session format `--conversations` is read as                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

## Per-repo opt-in/out — `banks.<bankId>`

Per-repo control lives in the SAME file, keyed by the **resolved bank id** (shown in the session
banner) and applied AFTER bank resolution — so it works regardless of where the repo lives, and
survives directory moves:

```jsonc
{
  "banks": {
    "coding-agent::secret-client": { "disabled": true }, // blacklist: no memory at all
    "coding-agent::old-name": { "bank": "team::shared" }, // rename / converge banks
    "coding-agent::big-mono": { "gitIngest": "full", "retainSessions": false },
  },
}
```

Any behavioral field can be overridden per bank, and `bank` **renames the destination** (single
hop: the section is selected by the resolved id, the target is literal — several ids may converge
on one shared bank, and the target's own section is not consulted). Other bank-resolution fields
are ignored inside a bank section.

### Recipe: two repos, one shared bank

Two ways, by what the natural key is:

**By resolved id** — you know the repo names; works wherever the repos live (and keeps working if
they move). Both ids converge on one literal target:

```jsonc
{
  "banks": {
    "coding-agent::backend": { "bank": "team::product" },
    "coding-agent::frontend": { "bank": "team::product" },
  },
}
```

**By path prefix** — the repos live under one directory; a single `mapPathToBank` entry covers
every repo (present and future) beneath it:

```jsonc
{
  "mapPathToBank": { "/Users/me/work/client-x": "client-x-memory" },
}
```

Rule of thumb: converge by **id** for a hand-picked set of repos; map by **path** when a folder is
the boundary ("everything I clone under `work/client-x` shares memory").

## Diagnostics & logging

All logs live in `~/.hindsight/coding-agents-logs/` (owner-only). Each file rotates to `<file>.1`
at 10 MB.

**Leveled plugin log** (humans debugging): `~/.hindsight/coding-agents-logs/plugin.log` (override
`HINDSIGHT_LOG_FILE`) — timestamped `LEVEL [scope] message` lines from every component, including
the ingestion engine. Level defaults to `info`; set `"logLevel": "debug"` in config or
`HINDSIGHT_LOG_LEVEL=debug` for ad-hoc debugging (at `debug`, every diag event below is mirrored
here too, so one file tells the whole story).

**Structured diag events** (machines/harnesses): every reflect and page-fetch outcome is appended
as a JSON line to `~/.hindsight/coding-agents-logs/diag.jsonl` (override with
`HINDSIGHT_DIAG_FILE`):

```json
{
  "ts": "2026-07-27T07:05:52Z",
  "harness": "claude-code",
  "event": "reflect_ok",
  "ms": 14210,
  "chars": 792,
  "query": "..."
}
```

`reflect_failed` / `pages_failed` record the error; if you're comparing memory-on vs memory-off,
check this file — a run whose reflects failed is a no-memory run. When the failure was a timeout or
a 5xx, the hook falls back to knowledge-page search and, if no page matches, to a raw recall of the
bank's memories: `reflect_fallback_pages` / `reflect_fallback_observations` record what each
step returned (`*_failed` when it errored). Seed starts are logged as
`seed_started`.

When `autoInject` names a retrieval source instead of reflect, that source records its own
outcome with the number of items it returned: `inject_pages` for `"pages"`, `inject_recall` for
`"recall"` (`inject_pages_failed` / `inject_recall_failed` when the call errored). No reflect
event is written on those turns — nothing reflected.

**Tool usage** (is the agent using Hindsight?): one JSON line per finished user turn in
`~/.hindsight/coding-agents-logs/usage.jsonl` (override `HINDSIGHT_USAGE_FILE`) — the `hindsight_*`
tools the agent called during that turn, and whether its reply credited Hindsight memory ("From
Hindsight memory"). The credit rate counts only turns that called a retrieval tool (search, list,
read, reflect); saving a document is not expected to be credited. Recorded at the end of each turn,
whether or not `retainSessions` writes the session back. It never leaves your machine. Summarize it per agent with:

```bash
node dist/installer.js stats
```

### Is the memory ready yet?

`hindsight_sync_status` — the agent-facing tool, `dist/status.js` for scripts — answers exactly
that: `"synced": true` means the seeded memory is queryable. It also reports gitlog freshness, how
far per-commit deepening has got, the codebase survey's state (`surveyBaseline` is the HEAD the last
survey started from, `surveyDocs` counts the findings documents that have landed, 0–4 — a baseline
with no findings retries automatically, at most three times per commit), and the extraction
operations still in flight. Each survey agent that could not be found, failed to launch or exited
with an error leaves one `[survey]` line in the plugin log.

### Resetting a repo's memory

This integration has no reset command, and an agent must not delete a bank on anyone's behalf: a
bank holds that repo's whole history and deletion cannot be undone. If memory is wrong, correct it
with `hindsight_ingest_document`. To stop memory in a repo, set `disabled` under `banks.<bankId>`.
Whether to remove a bank is the server operator's decision.

### Marker documents you may notice

Two document ids exist for the machinery's own bookkeeping. Both are safe to ignore and safe to
delete:

- `survey-baseline:<sha>` — reads "🛰️ researching…" while a codebase survey runs and flips to
  "✅ completed" once its findings land. It is retained under the `survey` strategy, whose marker
  rule extracts **nothing** from a status marker, and it drives the re-survey cadence
  (`surveyRefreshCommits`) and `surveyBaseline` in sync status.
- `gitlog:<repo>` — the aggregated commit-message seed document, oldest commit first. Once seeded it
  is kept current by **appending** only the commits since the one its `gitlog-head:<sha>` tag
  names, so a new commit costs the extraction of its own message, not of the whole log. It is
  written in full again (bounded by `seedLimit`) only when an append cannot describe HEAD: the
  recorded commit is no longer an ancestor of HEAD (a rebase, a force-push), more than `seedLimit`
  commits are new, or the server cannot append safely.

### When memory seems to be missing

Failures never break the agent: a reflect, page fetch or retain that fails degrades to an ordinary
memoryless turn and is recorded in the logs. "No memory" is therefore a log question — check the
diag file for whether `session_start` and `deepen_started` ever fired for that bank. A session that
was already running when the plugin was installed has no SessionStart behind it; its first prompt
after the install self-heals.
