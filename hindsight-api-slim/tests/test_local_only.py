"""This fork refuses hosted providers and public URLs when it starts.

The contract is the owner's: nothing is sent off the local network, so a setup that
would send it must stop the process with an error naming the setting to change. Each
factory gets a case here because a request can build a provider long after startup
(per-bank overrides), and the entrypoints get theirs because a server running several
workers builds nothing in the parent process.

conftest.py turns the guard off for the rest of the suite, which still exercises
upstream's hosted providers against fakes. The ``local_only`` marker keeps it on here.
"""

import os
import subprocess
import sys

import pytest

from hindsight_api.config import HindsightConfig, clear_config_cache
from hindsight_api.engine.cross_encoder import create_cross_encoder_from_env
from hindsight_api.engine.embeddings import create_embeddings_from_env
from hindsight_api.engine.llm_wrapper import create_llm_provider
from hindsight_api.engine.storage import create_file_storage
from hindsight_api.local_only import LocalOnlyError, check_config, check_database_url, check_url
from hindsight_api.webhooks.url_guard import WebhookURLError, parse_allowlist, validate_url_syntax

pytestmark = pytest.mark.local_only


def test_the_default_configuration_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("HINDSIGHT_API_"):
            monkeypatch.delenv(name)
    clear_config_cache()

    config = HindsightConfig.from_env()

    assert config.llm_provider == "none"
    check_config(config)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:1234/v1",
        "http://[::1]:8080",
        "http://[::ffff:10.0.0.5]:8080",
        "http://10.0.0.5:8080",
        "http://172.16.0.1:8080",
        "http://172.31.255.254:8080",
        "http://192.168.1.20:8080",
        "http://100.64.0.1:8080",
        "http://100.127.255.254:8080",
        "https://gpu.tailnet-1234.ts.net/v1",
        "https://GPU.Tailnet-1234.TS.NET./v1",
        "http://nas.local:9000",
    ],
)
def test_a_url_on_the_local_network_is_accepted(url: str) -> None:
    check_url(url, "setting")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://8.8.8.8",
        # Next to an allowed range, not in it.
        "http://172.32.0.1",
        "http://100.128.0.1",
        "http://11.0.0.1",
        # Cloud metadata and the unspecified address are not "local".
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0:8080",
        # An allowed name or address used as a label of a public name.
        "http://10.0.0.1.evil.example",
        "http://ts.net.evil.example",
        "http://localhost.evil.example",
        "http://evil.example/.ts.net",
        "http://ts.net",
        # Parsers disagree about these, so the host we check may not be the one dialled.
        "http://10.0.0.1@evil.example/",
        "http://evil.example#@10.0.0.1/",
        "http://evil.example\\@10.0.0.1/",
        "http://evil.example%2f.ts.net/",
        "http://evil.example\t.ts.net/",
        # Numeric spellings the OS resolver maps onto an address.
        "http://2130706433",
        "http://0x7f.0.0.1",
        "http://0177.0.0.1",
        # Not an http(s) URL at all.
        "ftp://10.0.0.1/",
        "file:///etc/passwd",
        "localhost:11434/v1",
        "",
    ],
)
def test_a_url_off_the_local_network_is_refused(url: str) -> None:
    with pytest.raises(LocalOnlyError, match="setting"):
        check_url(url, "setting")


def test_the_refusal_never_repeats_a_password_from_the_url() -> None:
    with pytest.raises(LocalOnlyError) as refused:
        check_url("https://user:hunter2@api.example.com/v1", "setting")
    assert "hunter2" not in str(refused.value)


@pytest.mark.parametrize(
    "url",
    [
        "pg0",
        "pg0://hindsight-mcp",
        "pg0://user:pwd@instance:5433?max_connections=300",
        "postgresql://user:pw@10.0.0.5:5432/hindsight",
        "postgresql+asyncpg://user:pw@db.tailnet-1234.ts.net/hindsight?ssl=require",
        "postgres://user:pw@nas.local/hindsight",
        "postgresql://user:pw@[::1]:5432/hindsight",
        # A compose service, which is why the database alone accepts a single label.
        "postgresql://user:pw@db:5432/hindsight",
        "postgresql://user:pw@hindsight_db/hindsight",
        # Unix sockets, in each way they are written.
        "postgresql:///hindsight",
        "postgresql://user@/hindsight",
        "postgresql://user@/hindsight?host=/var/run/postgresql",
        "postgresql://user@%2Fvar%2Frun%2Fpostgresql/hindsight",
        # Every host of a list is local.
        "postgresql://user:pw@db-1:5432,db-2:5432,10.0.0.7:5432/hindsight",
        "oracle://user:pw@db:1521/FREEPDB1",
        "oracle+oracledb://user:pw@10.0.0.8:1521/FREEPDB1",
    ],
)
def test_a_database_on_the_local_network_is_accepted(url: str) -> None:
    check_database_url(url, "setting")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pw@db.example.com:5432/hindsight",
        "postgresql+asyncpg://user:pw@8.8.8.8/hindsight",
        "oracle://user:pw@db.example.com:1521/FREEPDB1",
        # One public host in a list is enough to leave the network.
        "postgresql://user:pw@db:5432,db.example.com:5432/hindsight",
        # The query overrides the host, so a local-looking host proves nothing.
        "postgresql://user:pw@10.0.0.5/hindsight?host=db.example.com",
        "postgresql://user:pw@/hindsight?host=db.example.com",
        "postgresql://user:pw@/hindsight?host=/tmp,db.example.com",
        "postgresql://user:pw@10.0.0.5/hindsight?hostaddr=8.8.8.8",
        # Numbers the resolver turns into an address: this one is 8.8.8.8.
        "postgresql://user:pw@134744072/hindsight",
        "postgresql://user:pw@0x08080808/hindsight",
        # Not a single label: the trailing dot makes it an absolute name, a top-level domain.
        "postgresql://user:pw@ai./hindsight",
        # The real destination is somewhere this URL does not say.
        "oracle://user:pw@/?dsn=(DESCRIPTION=(ADDRESS=(HOST=db.example.com)))",
        "oracle://user:pw@/?dsn=cloud_alias",
        "postgresql://user:pw@/hindsight?service=prod",
        # Hides the host behind encoding, or leaves it ambiguous.
        "postgresql://user:pw@db%2Eexample%2Ecom/hindsight",
        "postgresql://user@db.example.com@10.0.0.5/hindsight",
        "postgresql://evil.example\\@10.0.0.5/hindsight",
        "postgresql://user:pw@evil.example\t.ts.net/hindsight",
        # Not a database URL this server can read.
        "sqlite:///hindsight.db",
        "postgresql:hindsight",
        "db.example.com:5432/hindsight",
    ],
)
def test_a_database_off_the_local_network_is_refused(url: str) -> None:
    with pytest.raises(LocalOnlyError, match="setting"):
        check_database_url(url, "setting")


def test_single_labels_are_for_the_database_alone() -> None:
    with pytest.raises(LocalOnlyError):
        check_url("http://db:5432", "setting")


@pytest.mark.parametrize("name", ["PGHOST", "PGHOSTADDR", "PGSERVICE"])
def test_a_url_with_no_host_is_held_to_what_the_environment_supplies(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "8.8.8.8")
    with pytest.raises(LocalOnlyError):
        check_database_url("postgresql:///hindsight", "setting")


def test_the_database_refusal_never_repeats_a_password() -> None:
    with pytest.raises(LocalOnlyError) as refused:
        check_database_url("postgresql://user:hunter2@db.example.com/hindsight", "setting")
    assert "hunter2" not in str(refused.value)


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("openai", ""),  # The default, which the SDK would send to api.openai.com.
        ("openai", "https://api.openai.com/v1"),
        ("ollama", "https://ollama.com/v1"),
        ("lmstudio", "http://8.8.8.8:1234/v1"),
        # Hosted by nature: a private URL does not make these local.
        ("groq", "http://10.0.0.5:8080"),
        ("anthropic", ""),
        ("gemini", ""),
        ("bedrock", ""),
        ("litellm", "http://10.0.0.5:4000"),
        ("litellmrouter", ""),
        ("openrouter", ""),
        ("ollama-cloud", ""),
        ("claude-code", ""),
    ],
)
def test_the_llm_factory_refuses_a_hosted_provider(provider: str, base_url: str) -> None:
    with pytest.raises(LocalOnlyError):
        create_llm_provider(provider, "key", base_url, "model", None)


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("openai", "http://10.0.0.5:8000/v1"),
        ("openai", "https://gpu.tailnet-1234.ts.net/v1"),
        ("ollama", "http://192.168.1.20:11434/v1"),
        ("lmstudio", "http://localhost:1234/v1"),
        ("none", ""),
        ("mock", ""),
    ],
)
def test_the_llm_factory_builds_a_local_provider(provider: str, base_url: str) -> None:
    assert create_llm_provider(provider, "key", base_url, "model", None) is not None


@pytest.mark.parametrize(
    "env",
    [
        {"HINDSIGHT_API_EMBEDDINGS_PROVIDER": "cohere", "HINDSIGHT_API_EMBEDDINGS_COHERE_API_KEY": "key"},
        {"HINDSIGHT_API_EMBEDDINGS_PROVIDER": "openai", "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": "key"},
        {"HINDSIGHT_API_EMBEDDINGS_PROVIDER": "tei", "HINDSIGHT_API_EMBEDDINGS_TEI_URL": "https://tei.example.com"},
    ],
    ids=["hosted", "openai-without-a-url", "tei-on-a-public-url"],
)
def test_the_embeddings_factory_refuses_a_hosted_setup(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    clear_config_cache()
    with pytest.raises(LocalOnlyError):
        create_embeddings_from_env()


@pytest.mark.parametrize(
    "env",
    [
        {"HINDSIGHT_API_RERANKER_PROVIDER": "cohere", "HINDSIGHT_API_RERANKER_COHERE_API_KEY": "key"},
        # FlashRank fetches its model with `requests`, which HF_HUB_OFFLINE does not stop.
        {"HINDSIGHT_API_RERANKER_PROVIDER": "flashrank"},
        {"HINDSIGHT_API_RERANKER_PROVIDER": "tei", "HINDSIGHT_API_RERANKER_TEI_URL": "https://tei.example.com"},
    ],
    ids=["hosted", "flashrank", "tei-on-a-public-url"],
)
def test_the_reranker_factory_refuses_a_hosted_setup(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    clear_config_cache()
    with pytest.raises(LocalOnlyError):
        create_cross_encoder_from_env()


@pytest.mark.parametrize(
    "env",
    [
        {"HINDSIGHT_API_FILE_STORAGE_GCS_BUCKET": "bucket"},
        {"HINDSIGHT_API_FILE_STORAGE_S3_BUCKET": "bucket"},
    ],
    ids=["gcs", "s3-on-the-default-aws-endpoint"],
)
def test_object_storage_off_the_local_network_is_refused(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    clear_config_cache()
    with pytest.raises(LocalOnlyError):
        create_file_storage("gcs" if "GCS" in next(iter(env)) else "s3")


def test_a_webhook_to_a_public_host_is_refused_even_when_allowlisted() -> None:
    with pytest.raises(WebhookURLError):
        validate_url_syntax("https://hooks.example.com/in", parse_allowlist(["hooks.example.com"]))


# With several workers the parent builds no engine, so only the entrypoint's own check
# can stop it. Port 0, since nothing may depend on what else is using the default.
SERVER = ("hindsight_api.main", "--workers", "2", "--port", "0")
WORKER = ("hindsight_api.worker.main",)


@pytest.mark.parametrize(
    ("command", "env", "named"),
    [
        (SERVER, {"HINDSIGHT_API_LLM_PROVIDER": "groq"}, "groq"),
        (SERVER, {"HINDSIGHT_API_LLM_PROVIDER": "openai"}, "HINDSIGHT_API_LLM_BASE_URL"),
        (
            SERVER,
            {"HINDSIGHT_API_LLM_PROVIDER": "ollama", "HINDSIGHT_API_LLM_BASE_URL": "https://ollama.com/v1"},
            "ollama.com",
        ),
        (SERVER, {"HINDSIGHT_API_RETAIN_LLM_PROVIDER": "anthropic"}, "anthropic"),
        (SERVER, {"HINDSIGHT_API_LLM_1_PROVIDER": "openrouter", "HINDSIGHT_API_LLM_1_API_KEY": "k"}, "openrouter"),
        (SERVER, {"HINDSIGHT_API_EMBEDDINGS_PROVIDER": "cohere"}, "cohere"),
        (SERVER, {"HINDSIGHT_API_RERANKER_PROVIDER": "cohere"}, "cohere"),
        (SERVER, {"HINDSIGHT_API_FILE_PARSER_LLAMA_PARSE_API_KEY": "k"}, "llama_parse"),
        (SERVER, {"HINDSIGHT_API_DATABASE_URL": "postgresql://u:p@db.example.com/h"}, "db.example.com"),
        (SERVER, {"HINDSIGHT_API_READ_DATABASE_URL": "postgresql://u:p@db.example.com/h"}, "db.example.com"),
        (WORKER, {"HINDSIGHT_API_DATABASE_URL": "postgresql://u:p@db.example.com/h"}, "db.example.com"),
        (WORKER, {"HINDSIGHT_API_LLM_PROVIDER": "groq"}, "groq"),
    ],
)
def test_a_process_stops_at_startup_on_a_hosted_setup(
    command: tuple[str, ...], env: dict[str, str], named: str, tmp_path
) -> None:
    clean = {name: value for name, value in os.environ.items() if not name.startswith("HINDSIGHT_API_")}
    result = subprocess.run(
        [sys.executable, "-m", *command],
        capture_output=True,
        text=True,
        cwd=tmp_path,  # No .env from the checkout.
        env={**clean, "HINDSIGHT_API_LLM_API_KEY": "key", **env},
        timeout=60,
    )

    assert result.returncode != 0
    assert "LocalOnlyError" in result.stderr
    assert named in result.stderr
