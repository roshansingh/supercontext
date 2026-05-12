"""Fail-closed Terraform literal domain extraction.

V1 scope is top-level `variable` and `resource` blocks with double-quoted
scalar assignments. It intentionally skips module, provider, data, locals,
output, terraform, provisioner, nested blocks, interpolation, lists, objects,
and heredoc values.
"""

from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    domain_entity,
)
from source.kg.extraction.config.domain_literals import domain_from_value, safe_config_literal


@dataclass
class _BlockState:
    depth: int


SUPPORTED_BLOCK_KINDS = {"variable", "resource"}


def extract_terraform(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    if scanned.path.suffix != ".tf":
        return
    block: _BlockState | None = None
    for line_number, raw_line in enumerate(scanned.lines, start=1):
        line = _strip_inline_comment(raw_line).strip()
        if not line:
            continue
        if block is None:
            block = _start_block(line)
            continue
        if block.depth == 1:
            literal = _quoted_assignment_value(line)
            if literal is not None:
                _add_terraform_domain(repo, scanned, service_entity, build, line_number, literal, tenant_id)
        block.depth += _brace_delta(line)
        if block.depth <= 0:
            block = None


def _start_block(line: str) -> _BlockState | None:
    if "{" not in line:
        return None
    token = line.split(maxsplit=1)[0]
    if token not in SUPPORTED_BLOCK_KINDS:
        return None
    depth = _brace_delta(line)
    if depth <= 0:
        return None
    return _BlockState(depth=depth)


def _quoted_assignment_value(line: str) -> str | None:
    key, separator, raw_value = line.partition("=")
    if not separator or not key.strip():
        return None
    value = raw_value.strip()
    if not value or value[0] != '"':
        return None
    if "${" in value:
        return None
    return _quoted_value(value, value[0])


def _quoted_value(value: str, quote: str) -> str | None:
    chars: list[str] = []
    escaped = False
    for char in value[1:]:
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return "".join(chars).strip()
        chars.append(char)
    return None


def _strip_inline_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        if escaped:
            escaped = False
        elif quote is not None and char == "\\":
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif quote is None and char == "#":
            return line[:index]
        elif quote is None and char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            return line[:index]
        index += 1
    return line


def _brace_delta(line: str) -> int:
    quote: str | None = None
    escaped = False
    delta = 0
    for char in line:
        if escaped:
            escaped = False
        elif quote is not None and char == "\\":
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif quote is None and char == "{":
            delta += 1
        elif quote is None and char == "}":
            delta -= 1
    return delta


def _add_terraform_domain(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    line_number: int,
    literal: str,
    tenant_id: str,
) -> None:
    domain_ref = domain_from_value(literal)
    if domain_ref is None:
        return
    domain_ref_entity = domain_entity(repo, domain_ref, tenant_id)
    add_entity_evidence(build, repo, domain_ref_entity, scanned.path, line_number)
    add_fact(
        build,
        "REFERENCES_DOMAIN",
        service_entity,
        domain_ref_entity,
        repo,
        scanned.path,
        line_number,
        qualifier={
            "source_kind": "terraform_literal",
            "path": scanned.relative_path,
            "literal": safe_config_literal(literal) or domain_ref,
        },
    )
