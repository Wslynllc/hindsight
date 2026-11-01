# About this fork

This is a fork of [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight), based on
upstream commit `bc5ea195`. It runs on open, locally hosted components only. Nothing is meant to
leave your own network: no telemetry, no vendor cloud, and no hosted AI providers.

The MIT license and upstream's notices are unchanged.

## What changed

**Removed outright**

- Hindsight Cloud: the `hindsight` provider for embeddings, reranking and decision models,
  `hindsight-admin cloud`, and the `hindsight-cloud` skill.
- The hosted Iris file parser.
- `sentry-sdk`, which only arrived through `fastapi[standard]`. The server now depends on `fastapi`
  and `uvicorn[standard]` directly, so `fastapi-cli` and `fastapi-cloud-cli` are gone with it.
- OpenTelemetry trace export. `HINDSIGHT_API_OTEL_*` settings now do nothing, and the OTLP exporter
  and FastAPI instrumentation packages are no longer installed. Prometheus `/metrics` and the
  `llm_trace` table in your own database still work.
- The "Memory Defense Enterprise" sales panel and the Iris wording in the control plane.
- `hindsight-embed`'s runtime downloads: its `curl | bash` CLI installer, its `npx` launch of the
  published control plane, and its `uvx` launch of the published API. Each of those is now a clear
  error instead.

**Added: local-only enforcement**

`hindsight_api/local_only.py` stops the server at startup, with an error naming the setting to
change, if the configuration would reach anything off your network. The same checks run whenever a
provider is built later, such as for a per-bank override. There is no setting to turn this off.

| What | Allowed |
| --- | --- |
| LLM | `ollama`, `lmstudio`, `llamacpp`, `none`, `mock`, and `openai` with a local base URL |
| Embeddings | `local`, `onnx`, `tei`, and `openai` with a local base URL |
| Reranker | `local`, `onnx`, `tei`, `rrf`, `jina-mlx` |
| File parsing | `markitdown` |
| File storage | `native` (PostgreSQL), and `s3` with a local endpoint such as MinIO |

A URL counts as local when its host is loopback, a private RFC 1918 address, a Tailscale-range
address (`100.64.0.0/10`), or a name ending in `.ts.net` or `.local`. That rule also covers TEI,
OCR, S3, decision model URLs and webhooks.

Database URLs follow the same rule, with two additions for databases only: unix sockets, and
single-label names such as a compose service called `db`. A database URL has to state where it
connects, so Oracle's `?dsn=` and libpq's `?service=` are refused. The check covers
`HINDSIGHT_API_DATABASE_URL`, `HINDSIGHT_API_READ_DATABASE_URL` and
`HINDSIGHT_API_MIGRATION_DATABASE_URL` for the server and worker. `hindsight-admin` does not check them.

**Changed defaults**

- The default LLM provider is `none` instead of `openai`. With no LLM, Hindsight stores and searches
  text chunks, but fact extraction, reflect and consolidation are off.
- `HindsightServer` in `hindsight-all` also defaults to `none` instead of `groq`.
- The Docker image downloads its models while building, then runs with `HF_HUB_OFFLINE=1` and
  `TRANSFORMERS_OFFLINE=1`, and with Hugging Face, Next.js and `DO_NOT_TRACK` telemetry off.

**Kept on purpose**

The modules for hosted providers (OpenAI, Anthropic, Groq, LiteLLM, Bedrock and so on) are still in
the tree. They are refused at runtime rather than deleted, because deleting them would turn every
upstream merge into a conflict. Their tests still run, with the guard switched off by
`tests/conftest.py`.

## Why

The owner wants a memory server that can be trusted with private data: what goes in stays on
hardware the owner controls. Refusing to start is deliberate. A setup that quietly falls back to a
hosted service is worse than one that doesn't start.

## Things that will surprise you

- **Docker deployments must use external Postgres.** Set `HINDSIGHT_API_DATABASE_URL`. The embedded
  pg0 database bundles Postgres, but its binary also contains a GitHub API URL and a pgvector
  installer, and nobody has verified that its first start stays offline.
- **`hindsight-embed` needs a local `hindsight-api`.** Install this fork's package next to it, with
  its `local-ml` extra for the default local models. From a checkout it runs `uv run`, which can
  download this fork's locked dependencies.
- **Bare Docker service names are refused, except for the database.** `http://tei-embedding:80` has
  no dot, so it matches none of the rules above. This affects the `tei`, `local-llm` and
  `s3-file-storage` compose examples and the TEI option in the Helm chart. Use an IP address, a
  `.local` name or a `.ts.net` name instead.
- **The `openai` provider still needs an API key** even with a local base URL. Any non-empty value
  works.
- **Compose files that default to `openai`** stop at startup until you set a local base URL.
- **`flashrank` is refused** even though it runs locally. It downloads its model from huggingface.co
  with its own HTTP call, which `HF_HUB_OFFLINE` does not stop.
- **Other models in Docker:** the image runs offline, so any model other than the two preloaded ones
  must be baked in or mounted into the Hugging Face cache. Building with `PRELOAD_ML_MODELS=false`
  means you have to mount them.
- **Outside Docker,** set `HF_HUB_OFFLINE=1` yourself once your models are cached. Otherwise the
  `local` and `onnx` providers check huggingface.co at each start, and `llamacpp` downloads its
  default model.
- **Helm and compose still name upstream's images.** Those images do not include this enforcement.
  Build this fork and point them at your own registry.

## Pulling from upstream

```bash
git remote add upstream https://github.com/vectorize-io/hindsight.git   # first time only
git fetch upstream
git merge upstream/main
```

Then check these, in this order:

1. **`uv.lock`:** don't hand-merge it. Take either side and run `uv lock`, then confirm that
   `sentry-sdk`, `fastapi-cli` and `fastapi-cloud-cli` are still absent from it.
2. **`hindsight-api-slim/pyproject.toml`:** make sure `fastapi[standard]` and the OTLP packages
   didn't come back.
3. **New providers:** a provider upstream adds is refused automatically, because the lists in
   `local_only.py` only name what is allowed. To allow one, add it there.
4. **New outbound calls:** the lists only cover LLM, embeddings, reranking, parsers and storage.
   Search the merge for new HTTP clients and URLs in anything else.
5. **`tracing.py`, `http.py` (`_instrument_app_for_tracing`) and `config.py`:** these hold most of the
   conflicts. Keep this fork's no-op functions and the default of `none`.
6. **Run the guard's tests:**

   ```bash
   cd hindsight-api-slim
   uv run pytest tests/test_local_only.py tests/test_tracing.py -o addopts=""
   ```

## Agent plugins

The Claude Code and Codex, Hermes, OpenClaw and Obsidian plugins have no cloud option. `vectorize.io` hosts are refused. Without a valid configured server, they send nothing. In the coding-agents package, a missing or invalid config is inert, opt-in is the default, self-update and daemon mode are removed, and the repository survey is off by default. Its companion skill no longer tells agents to delete a bank, and for Codex it installs under `~/.codex/skills`.

## Test status

This branch has not passed a complete test run. The full server suite has not run against the final edits, and no Docker image has been built from it. See the plugin READMEs for local install commands.
