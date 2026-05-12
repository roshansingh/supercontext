"""Fail-closed Terraform literal domain extraction.

V1 scope is top-level `variable` and `resource` blocks with double-quoted
scalar assignments or single-line lists of quoted literals, plus `module.source`
git host literals. It intentionally skips provider, data, locals, output,
terraform, provisioner, nested blocks, interpolation, objects, multi-line lists,
and heredoc values.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

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
    kind: str
    depth: int


SUPPORTED_BLOCK_KINDS = {"module", "variable", "resource"}


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
    in_block_comment = False
    heredoc_marker: str | None = None
    for line_number, raw_line in enumerate(scanned.lines, start=1):
        if heredoc_marker is not None:
            if raw_line.strip() == heredoc_marker:
                heredoc_marker = None
            continue
        uncommented_line, in_block_comment = _strip_comments(raw_line, in_block_comment=in_block_comment)
        line = uncommented_line.strip()
        if not line:
            continue
        if block is None:
            block = _start_block(line)
            continue
        heredoc_marker = _heredoc_start_marker(line)
        if heredoc_marker is not None:
            block.depth += _brace_delta(line)
            if block.depth <= 0:
                block = None
                heredoc_marker = None
            continue
        if block.depth == 1 and not _has_brace_outside_quote(line):
            if block.kind == "module":
                literal = _quoted_assignment_value_for_key(line, "source")
                domain_ref = _module_source_domain(literal) if literal is not None else None
                if domain_ref is not None:
                    _add_terraform_domain(
                        repo,
                        scanned,
                        service_entity,
                        build,
                        line_number,
                        literal or domain_ref,
                        tenant_id,
                        domain_ref=domain_ref,
                        source_kind="terraform_module_source",
                    )
            else:
                for literal in _assignment_literals(line) or ():
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
    return _BlockState(kind=token, depth=depth)


def _quoted_assignment_value(line: str) -> str | None:
    literals = _assignment_literals(line)
    if literals is None or len(literals) != 1:
        return None
    return literals[0]


def _quoted_assignment_value_for_key(line: str, expected_key: str) -> str | None:
    key, separator, raw_value = line.partition("=")
    if not separator or not key.strip():
        return None
    if key.strip() != expected_key:
        return None
    return _quoted_assignment_value(line)


def _assignment_literals(line: str) -> tuple[str, ...] | None:
    key, separator, raw_value = line.partition("=")
    if not separator or not key.strip():
        return None
    value = raw_value.strip()
    if not value:
        return None
    if "${" in value:
        return None
    if value[0] == '"':
        literal, next_index = _quoted_value_at(value, 0)
        if not literal or value[next_index:].strip():
            return None
        return (literal,)
    if value[0] == "[":
        return _quoted_list_values(value)
    return None


def _quoted_list_values(value: str) -> tuple[str, ...] | None:
    if not value.endswith("]"):
        return None
    literals: list[str] = []
    index = 1
    while index < len(value) - 1:
        while index < len(value) - 1 and value[index].isspace():
            index += 1
        if index >= len(value) - 1:
            break
        if value[index] != '"':
            return None
        literal, next_index = _quoted_value_at(value, index)
        if literal is None:
            return None
        literals.append(literal)
        index = next_index
        while index < len(value) - 1 and value[index].isspace():
            index += 1
        if index >= len(value) - 1:
            break
        if value[index] != ",":
            return None
        index += 1
        while index < len(value) - 1 and value[index].isspace():
            index += 1
        if index >= len(value) - 1:
            return None
    return tuple(literals)


def _heredoc_start_marker(line: str) -> str | None:
    _, separator, raw_value = line.partition("=")
    if not separator:
        return None
    value = raw_value.strip()
    if value.startswith("<<-"):
        marker = value[3:].strip()
    elif value.startswith("<<"):
        marker = value[2:].strip()
    else:
        return None
    return marker or None


def _quoted_value_at(value: str, start_index: int) -> tuple[str | None, int]:
    quote = value[start_index]
    chars: list[str] = []
    escaped = False
    for index, char in enumerate(value[start_index + 1 :], start=start_index + 1):
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return "".join(chars).strip(), index + 1
        chars.append(char)
    return None, len(value)


def _module_source_domain(value: str) -> str | None:
    if value.startswith("git::"):
        return _url_host(value.removeprefix("git::"))
    if value.startswith("git@"):
        _, separator, path = value.partition("@")
        if not separator:
            return None
        host, host_separator, _ = path.partition(":")
        if not host_separator:
            return None
        return domain_from_value(host)
    return None


def _url_host(value: str) -> str | None:
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return domain_from_value(parsed.hostname)


def _strip_comments(line: str, *, in_block_comment: bool) -> tuple[str, bool]:
    chars: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        next_char = line[index + 1] if index + 1 < len(line) else ""
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
        elif escaped:
            chars.append(char)
            escaped = False
        elif quote is not None and char == "\\":
            chars.append(char)
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            chars.append(char)
        elif quote is None and char == "#":
            return "".join(chars), in_block_comment
        elif quote is None and char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            return "".join(chars), in_block_comment
        elif quote is None and char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        else:
            chars.append(char)
        index += 1
    return "".join(chars), in_block_comment


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


def _has_brace_outside_quote(line: str) -> bool:
    quote: str | None = None
    escaped = False
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
        elif quote is None and char in {"{", "}"}:
            return True
    return False


def _add_terraform_domain(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    line_number: int,
    literal: str,
    tenant_id: str,
    *,
    domain_ref: str | None = None,
    source_kind: str = "terraform_literal",
) -> None:
    domain_ref = domain_ref or domain_from_value(literal)
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
            "source_kind": source_kind,
            "path": scanned.relative_path,
            "literal": safe_config_literal(literal) or domain_ref,
        },
    )
