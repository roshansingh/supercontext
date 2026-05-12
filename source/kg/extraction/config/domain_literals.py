"""Shared domain and URL literal recognition for config extractors."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from source.kg.extraction.config.common import IGNORED_DOMAIN_SUFFIXES


URL_SCHEMES = {"http", "https", "ws", "wss"}


def value_kind(value: str, *, secret_like: bool = False) -> str:
    if secret_like:
        return "secret_like"
    if url_hostname(value):
        return "url"
    if bare_domain(value):
        return "domain"
    return "literal"


def safe_config_literal(value: str) -> str:
    hostname = url_hostname(value)
    if hostname:
        parsed = urlparse(value)
        netloc = hostname
        port = _safe_port(parsed)
        if port:
            netloc = f"{netloc}:{port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
    return bare_domain_literal(value) or ""


def domain_from_value(value: str) -> str | None:
    return url_hostname(value) or bare_domain(value)


def url_hostname(value: str) -> str | None:
    try:
        parsed = urlparse(value.strip())
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in URL_SCHEMES:
        return None
    return normalize_domain_ref(hostname) if hostname else None


def bare_domain(value: str) -> str | None:
    bare = bare_domain_ref(value)
    return bare[0] if bare else None


def bare_domain_literal(value: str) -> str | None:
    bare = bare_domain_ref(value)
    return bare[1] if bare else None


def bare_domain_ref(value: str) -> tuple[str, str] | None:
    candidate = value.strip().strip("'\"`<>()[]{}.,;")
    if "://" in candidate or "/" in candidate:
        return None
    if candidate.endswith(IGNORED_DOMAIN_SUFFIXES):
        return None
    host, port = split_host_port(candidate)
    normalized = normalize_domain_ref(host)
    if not normalized or not is_domain_name(normalized):
        return None
    literal = f"{normalized}:{port}" if port else normalized
    return normalized, literal


def split_host_port(value: str) -> tuple[str, str | None]:
    host, separator, port = value.rpartition(":")
    if not separator:
        return value, None
    if not host or not port.isdigit():
        return value, None
    return host, port


def normalize_domain_ref(domain: str | None) -> str:
    return (domain or "").strip().lower().strip(" \t\r\n'\"`<>()[]{}.,;")


def is_domain_name(value: str) -> bool:
    labels = value.split(".")
    if len(labels) < 2:
        return False
    if len(labels[-1]) < 2 or not labels[-1].isalpha():
        return False
    for label in labels:
        if not label:
            return False
        if label[0] == "-" or label[-1] == "-":
            return False
        if not all(char.isalnum() or char == "-" for char in label):
            return False
    return True


def _safe_port(parsed_url) -> int | None:
    try:
        return parsed_url.port
    except ValueError:
        return None
