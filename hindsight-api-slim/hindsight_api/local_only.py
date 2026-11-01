"""Local-only enforcement: this fork sends nothing off the operator's own network.

Hindsight upstream ships many hosted providers. This fork keeps their modules so that
upstream merges stay cheap, and refuses to use them here instead. There is no setting
that turns this off.

Each factory calls its check, so a provider built late (a per-bank override, a
failover member) is covered too. ``check_config`` runs the same checks when the server
starts, because with several workers it builds nothing in the parent: without this a
refused setup would show up as uvicorn respawning workers forever.

The module is standard library only: ``config`` imports it.
"""

import ipaddress
import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

#: Providers that speak to a server of the operator's own. ``openai`` here means the
#: OpenAI-compatible wire format: it needs a base URL, or the SDK goes to api.openai.com.
LLM_PROVIDERS = frozenset({"openai", "ollama", "lmstudio", "llamacpp", "none", "mock"})
#: In-process models, plus servers whose URL is checked. ``openai`` as for the LLM.
EMBEDDINGS_PROVIDERS = frozenset({"local", "onnx", "tei", "openai"})
#: flashrank runs locally but is left out: it fetches its model with ``requests`` from
#: huggingface.co on first use, which HF_HUB_OFFLINE does not stop.
RERANKER_PROVIDERS = frozenset({"local", "onnx", "tei", "rrf", "jina-mlx"})
#: llama_parse uploads each file to LlamaCloud.
FILE_PARSERS = frozenset({"markitdown"})
#: "native" is PostgreSQL; s3 is allowed for an endpoint on the local network (MinIO).
FILE_STORAGE_TYPES = frozenset({"native", "s3"})

_LOCAL_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT, which is what Tailscale hands out.
)
_LOCAL_NAME_SUFFIXES = (".ts.net", ".local")
# An allowlist of what a DNS name may contain: a character outside it (%, a backslash, a
# full-width dot) is one that an HTTP client may read differently from this module.
_DNS_NAME = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")
# Database hosts only: a compose service such as `db`, which Docker resolves on its own
# network. Underscores because compose allows them in service names.
_SERVICE_NAME = re.compile(r"[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?")
# A resolver reads these as an address, not a name: 134744072 is 8.8.8.8.
_NUMERIC_HOST = re.compile(r"[0-9]+|0x[0-9a-f]+")
# One entry of a libpq host list: name, IPv4 or [IPv6], with an optional port.
_HOST_SPEC = re.compile(r"(\[[^\]]*\]|[^:\[\]]*)(?::[0-9]*)?")
_DATABASE_SCHEMES = frozenset({"postgresql", "postgres", "oracle"})

_POLICY = "this fork only talks to the local network"
_URL_RULE = "loopback, RFC1918, 100.64.0.0/10, or a name ending in .ts.net or .local"
_DATABASE_RULE = f"{_URL_RULE}, or a unix socket or single-label service name"


class LocalOnlyError(ValueError):
    """The configuration would send data to something off the local network."""


def _is_local_host(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not _DNS_NAME.fullmatch(host):
            return False
        return host == "localhost" or host.endswith(_LOCAL_NAME_SUFFIXES)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback or any(address in network for network in _LOCAL_NETWORKS)


def _local_host(url: str) -> str | None:
    """The URL's host when it is an http(s) URL on the local network; None otherwise."""
    # urlsplit drops tabs and newlines and treats a backslash as part of the authority,
    # while HTTP clients do neither, so such a URL can dial a host other than the one read here.
    if "\\" in url or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in url):
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises on a malformed port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    host = host.lower().removesuffix(".")
    return host if _is_local_host(host) else None


def check_url(url: str, setting: str) -> None:
    """Refuse a URL whose host is not on the local network.

    Args:
        url: The URL the process would connect to.
        setting: What the URL configures, named in the error so it can be fixed.
    """
    if _local_host(url) is None:
        # Only the host is repeated: the URL itself can carry a password.
        try:
            shown = urlsplit(url).hostname or "no usable host"
        except ValueError:
            shown = "no usable host"
        raise LocalOnlyError(f"{setting}: {shown} is not allowed, {_POLICY} ({_URL_RULE})")


def _is_local_database_host(host: str) -> bool:
    """As for any URL, plus unix sockets and compose service names."""
    if host.startswith("/"):
        return True
    name = host.lower()
    if _is_local_host(name.removesuffix(".")):
        return True
    return _SERVICE_NAME.fullmatch(name) is not None and _NUMERIC_HOST.fullmatch(name) is None


def _database_hosts(url: str) -> list[str] | None:
    """Every host a database URL can connect to, or None when the URL does not say.

    A hostname alone is not enough here. libpq and asyncpg take a comma-separated list
    of hosts, ``host`` and ``hostaddr`` in the query override the authority, and a URL
    with no host at all reads the environment. An empty list means the local socket.
    """
    if "://" not in url or "\\" in url or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in url):
        return None
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
    except ValueError:
        return None
    if parts.scheme.split("+")[0] not in _DATABASE_SCHEMES:
        return None
    # Each names a destination kept elsewhere: an Oracle descriptor or alias, a pg_service.conf entry.
    if "dsn" in query or "service" in query:
        return None
    # Clients disagree on which "@" ends the credentials. An "@" in a password can be percent-encoded.
    if parts.netloc.count("@") > 1:
        return None

    hosts: list[str] = []
    for spec in parts.netloc.rpartition("@")[2].split(","):
        match = _HOST_SPEC.fullmatch(spec)
        if match is None:
            return None
        hosts.append(unquote(match[1].strip("[]")))
    for key in ("host", "hostaddr"):
        for value in query.get(key, ()):
            hosts.extend(value.split(","))
    hosts = [host for host in hosts if host]

    if not hosts:
        if os.environ.get("PGSERVICE"):
            return None
        for name in ("PGHOST", "PGHOSTADDR"):
            hosts.extend(host for host in os.environ.get(name, "").split(",") if host)
    return hosts


def check_database_url(url: str, setting: str) -> None:
    """Refuse a database off the local network.

    Wider than ``check_url`` on purpose: a compose Postgres service is the expected
    setup, so unix sockets and single-label names are accepted here and nowhere else.

    Args:
        url: The database URL. ``pg0`` is the embedded database, which has no host.
        setting: The variable it came from, named in the error so it can be fixed.
    """
    if url == "pg0" or url.startswith(("pg0?", "pg0://")):
        return
    hosts = _database_hosts(url)
    if hosts is None:
        raise LocalOnlyError(
            f"{setting}: cannot tell where this URL connects, {_POLICY}. Use a postgresql:// or oracle:// "
            "URL with its host in the URL, with any @ in the password percent-encoded"
        )
    for host in hosts:
        if not _is_local_database_host(host):
            raise LocalOnlyError(f"{setting}: {host} is not allowed, {_POLICY} ({_DATABASE_RULE})")


def check_databases(config: Any, database_url: str | None = None) -> None:
    """Refuse a database off the local network, across the three URLs a process can use.

    Args:
        config: The raw configuration.
        database_url: The URL in use, when a caller was handed one directly.
    """
    check_database_url(database_url or config.database_url, "HINDSIGHT_API_DATABASE_URL")
    if config.read_database_url:
        check_database_url(config.read_database_url, "HINDSIGHT_API_READ_DATABASE_URL")
    if config.migration_database_url:
        check_database_url(config.migration_database_url, "HINDSIGHT_API_MIGRATION_DATABASE_URL")


def _check_allowed(kind: str, name: str, allowed: frozenset[str]) -> None:
    if name not in allowed:
        raise LocalOnlyError(f"{kind} {name!r} is not allowed, {_POLICY}. Allowed: {', '.join(sorted(allowed))}")


def check_llm(provider: str, base_url: str | None) -> None:
    """Refuse an LLM that is hosted, or an OpenAI-compatible one with nowhere local to go."""
    name = provider.lower()
    _check_allowed("LLM provider", name, LLM_PROVIDERS)
    if name in ("none", "mock"):
        return
    if base_url:
        check_url(base_url, f"HINDSIGHT_API_LLM_BASE_URL for provider {name!r}")
    elif name == "openai":
        raise LocalOnlyError(
            f"LLM provider 'openai' needs HINDSIGHT_API_LLM_BASE_URL, {_POLICY}: "
            "without it the OpenAI SDK sends everything to api.openai.com"
        )


def check_embeddings(provider: str, url: str | None) -> None:
    """Refuse hosted embeddings. ``url`` is the TEI or OpenAI-compatible server, if any."""
    name = provider.lower()
    _check_allowed("Embeddings provider", name, EMBEDDINGS_PROVIDERS)
    if name == "openai" and not url:
        raise LocalOnlyError(
            f"Embeddings provider 'openai' needs HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL, {_POLICY}: "
            "without it the OpenAI SDK sends everything to api.openai.com"
        )
    if name in ("tei", "openai") and url:
        check_url(url, f"Embeddings URL for provider {name!r}")


def check_reranker(provider: str, url: str | None) -> None:
    """Refuse a hosted reranker. ``url`` is the TEI server, if any."""
    name = provider.lower()
    _check_allowed("Reranker provider", name, RERANKER_PROVIDERS)
    if name == "tei" and url:
        check_url(url, "HINDSIGHT_API_RERANKER_TEI_URL")


def check_file_parser(name: str) -> None:
    """Refuse a parser that uploads files to a hosted service."""
    _check_allowed("File parser", name.lower(), FILE_PARSERS)


def check_file_storage(storage_type: str, s3_endpoint: str | None) -> None:
    """Refuse object storage off the local network. An S3 bucket with no endpoint is AWS."""
    name = storage_type.lower()
    _check_allowed("File storage", name, FILE_STORAGE_TYPES)
    if name == "s3":
        if not s3_endpoint:
            raise LocalOnlyError(
                f"File storage 's3' needs HINDSIGHT_API_FILE_STORAGE_S3_ENDPOINT, {_POLICY}: "
                "without it the client talks to AWS"
            )
        check_url(s3_endpoint, "HINDSIGHT_API_FILE_STORAGE_S3_ENDPOINT")


def check_config(config: Any) -> None:
    """Refuse a hosted setup before a process does any work.

    Called by the server entrypoint after the .env is loaded rather than from
    ``HindsightConfig.validate``: a module may read the config at import scope, before
    the .env that completes it has been applied.

    Decision models are not here: ``decision_model_config`` checks its own URL.
    """
    check_databases(config)

    base_url = config.get_llm_base_url()
    for prefix in ("", "retain_", "reflect_", "consolidation_", "mental_model_refresh_"):
        check_llm(
            getattr(config, f"{prefix}llm_provider") or config.llm_provider,
            getattr(config, f"{prefix}llm_base_url") or base_url,
        )
        for member in getattr(config, f"{prefix}llm_members"):
            check_llm(member.provider, member.base_url)

    embeddings_provider = config.embeddings_provider.lower()
    check_embeddings(
        embeddings_provider,
        config.embeddings_tei_url if embeddings_provider == "tei" else config.embeddings_openai_base_url,
    )
    for member in config.reranker_chain():
        check_reranker(member.provider, member.tei_url)

    for parser in config.file_parser:
        check_file_parser(parser)
    if config.file_parser_llama_parse_api_key:
        check_file_parser("llama_parse")
    if config.file_parser_markitdown_ocr_enabled and config.file_parser_markitdown_ocr_base_url:
        check_url(config.file_parser_markitdown_ocr_base_url, "HINDSIGHT_API_FILE_PARSER_MARKITDOWN_OCR_BASE_URL")

    check_file_storage(config.file_storage_type, config.file_storage_s3_endpoint)
