"""Terraform runtime topology extraction.

This module intentionally handles a narrow, structured Terraform subset:
top-level directory-scoped variable defaults plus CloudFront distributions with
alias and origin attributes. It accepts scalar assignments and bracketed literal
lists, but does not evaluate Terraform expressions; unresolved references fail
closed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

from source.kg.core.models import Coverage, Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    deploy_target_entity,
    domain_entity,
)
from source.kg.file_formats._shared.domain_literals import domain_from_value, safe_config_literal
from source.kg.file_formats._shared.hcl import (
    brace_delta,
    has_brace_outside_quote,
    heredoc_start_marker,
    quoted_value_at,
    strip_comments,
)


TERRAFORM_CLOUDFRONT_TARGET_TYPE = "cloudfront_distribution"


@dataclass(frozen=True)
class TerraformAssignment:
    key: str
    raw_value: str
    line: int


@dataclass
class TerraformNestedBlock:
    kind: str
    line: int
    assignments: dict[str, TerraformAssignment]
    malformed_assignments: frozenset[str]


@dataclass(frozen=True)
class TerraformBlock:
    kind: str
    labels: tuple[str, ...]
    line: int
    relative_path: str
    assignments: dict[str, TerraformAssignment]
    nested_blocks: tuple[TerraformNestedBlock, ...]
    malformed_assignments: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TerraformResourceRef:
    resource_type: str
    resource_name: str

    @property
    def address(self) -> str:
        return f"{self.resource_type}.{self.resource_name}"


def terraform_top_level_blocks(scanned: ScannedFile) -> list[TerraformBlock]:
    return _top_level_blocks(scanned)


def terraform_block_directory(block: TerraformBlock) -> str:
    return _block_directory(block)


def terraform_quoted_scalar(value: str) -> str | None:
    return _quoted_scalar(value)


def terraform_resource_ref(value: str) -> TerraformResourceRef | None:
    return _resource_ref(value)


_BLOCK_HEADER_RE = re.compile(r'^(?P<kind>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<labels>(?:"[^"]+"\s*)+)\{')
_NESTED_BLOCK_RE = re.compile(r"^(?P<kind>[A-Za-z_][A-Za-z0-9_]*)\s*\{")
_RESOURCE_REF_RE = re.compile(
    r"(?P<type>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z0-9_]+"
)


def extract_terraform_runtime_routes(
    repo: RepoSnapshot,
    files: Iterable[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
    blocks: Iterable[TerraformBlock] | None = None,
) -> None:
    files = tuple(files)
    terraform_files = [scanned for scanned in files if scanned.path.suffix == ".tf"]
    if blocks is None and not terraform_files:
        return

    parsed_blocks = (
        list(blocks)
        if blocks is not None
        else [block for scanned in terraform_files for block in _top_level_blocks(scanned)]
    )
    variable_defaults = _variable_domain_defaults_by_directory(parsed_blocks)
    s3_buckets = _resource_refs_by_directory(parsed_blocks, resource_type="aws_s3_bucket")
    emitted_targets: set[str] = set()

    for block in parsed_blocks:
        if block.kind != "resource" or block.labels[:1] != ("aws_cloudfront_distribution",) or len(block.labels) < 2:
            continue
        aliases = _cloudfront_alias_domains(block, variable_defaults)
        origins = _cloudfront_s3_origins(block, s3_buckets.get(_block_directory(block), set()))
        if not aliases:
            _add_cloudfront_coverage(repo, build, tenant_id, block, reason=_cloudfront_alias_skip_reason(block))
            continue
        _add_cloudfront_alias_references(repo, build, tenant_id, service_entity, block, aliases)
        if not origins:
            _add_cloudfront_coverage(repo, build, tenant_id, block, reason=_cloudfront_origin_skip_reason(block))
            continue

        target = deploy_target_entity(
            repo,
            TERRAFORM_CLOUDFRONT_TARGET_TYPE,
            f"{block.relative_path}#aws_cloudfront_distribution.{block.labels[1]}",
            tenant_id,
        )
        if target.entity_id not in emitted_targets:
            add_entity_evidence(build, repo, target, repo.root / block.relative_path, block.line)
            add_fact(
                build,
                "DEPLOYS_VIA_CONFIG",
                service_entity,
                target,
                repo,
                repo.root / block.relative_path,
                block.line,
                qualifier={
                    "source_kind": "terraform_cloudfront_distribution",
                    "target_type": TERRAFORM_CLOUDFRONT_TARGET_TYPE,
                    "resource_type": "aws_cloudfront_distribution",
                    "resource_name": block.labels[1],
                    "origin_resources": [origin.address for origin in origins],
                    "path": block.relative_path,
                    "match_basis": "cloudfront_distribution_with_s3_origin",
                },
            )
            emitted_targets.add(target.entity_id)

        for alias in aliases:
            domain_ref = domain_entity(repo, alias.domain, tenant_id)
            add_fact(
                build,
                "ROUTES_DOMAIN_TO_DEPLOY",
                domain_ref,
                target,
                repo,
                repo.root / block.relative_path,
                alias.line,
                qualifier={
                    "source_kind": "terraform_cloudfront_alias",
                    "target_type": TERRAFORM_CLOUDFRONT_TARGET_TYPE,
                    "resource_type": "aws_cloudfront_distribution",
                    "resource_name": block.labels[1],
                    "origin_resources": [origin.address for origin in origins],
                    "path": block.relative_path,
                    "match_basis": "cloudfront_alias_to_s3_origin",
                },
            )


def _add_cloudfront_alias_references(
    repo: RepoSnapshot,
    build: ConfigKgBuild,
    tenant_id: str,
    service_entity: Entity,
    block: TerraformBlock,
    aliases: tuple[_ResolvedAlias, ...],
) -> None:
    for alias in aliases:
        domain_ref = domain_entity(repo, alias.domain, tenant_id)
        add_entity_evidence(build, repo, domain_ref, repo.root / block.relative_path, alias.line)
        add_fact(
            build,
            "REFERENCES_DOMAIN",
            service_entity,
            domain_ref,
            repo,
            repo.root / block.relative_path,
            alias.line,
            qualifier={
                "source_kind": "terraform_cloudfront_alias",
                "path": block.relative_path,
                "literal": alias.literal,
                "expression": alias.expression,
                "resource_type": "aws_cloudfront_distribution",
                "resource_name": block.labels[1],
            },
        )


def _add_cloudfront_coverage(
    repo: RepoSnapshot,
    build: ConfigKgBuild,
    tenant_id: str,
    block: TerraformBlock,
    *,
    reason: str,
) -> None:
    build.coverage.append(
        Coverage(
            tenant_id=tenant_id,
            predicate="ROUTES_DOMAIN_TO_DEPLOY",
            scope_ref={
                "repo": repo.name,
                "path": block.relative_path,
                "resource_type": "aws_cloudfront_distribution",
                "resource_name": block.labels[1] if len(block.labels) > 1 else "",
                "reason": reason,
            },
            state="partially_instrumented",
            source_system=CONFIG_SOURCE_SYSTEM,
        )
    )


def _cloudfront_alias_skip_reason(block: TerraformBlock) -> str:
    assignment = block.assignments.get("aliases")
    if assignment is None:
        if "aliases" in block.malformed_assignments:
            return "cloudfront_alias_malformed"
        return "cloudfront_alias_missing"
    if not _list_items(assignment.raw_value):
        return "cloudfront_alias_empty"
    return "cloudfront_alias_unresolved"


def _cloudfront_origin_skip_reason(block: TerraformBlock) -> str:
    for nested in block.nested_blocks:
        if nested.kind == "origin" and "domain_name" in nested.malformed_assignments:
            return "cloudfront_origin_domain_malformed"
    return "cloudfront_no_s3_origin"


@dataclass(frozen=True)
class _ResolvedAlias:
    domain: str
    literal: str
    expression: str
    line: int


def _variable_domain_defaults_by_directory(blocks: list[TerraformBlock]) -> dict[str, dict[str, str]]:
    defaults_by_directory: dict[str, dict[str, str]] = {}
    for block in blocks:
        if block.kind != "variable" or len(block.labels) != 1:
            continue
        assignment = block.assignments.get("default")
        if assignment is None:
            continue
        literal = _quoted_scalar(assignment.raw_value)
        domain = domain_from_value(literal) if literal is not None else None
        if domain is not None:
            defaults_by_directory.setdefault(_block_directory(block), {})[block.labels[0]] = domain
    return defaults_by_directory


def _resource_refs_by_directory(
    blocks: list[TerraformBlock],
    *,
    resource_type: str,
) -> dict[str, set[TerraformResourceRef]]:
    refs_by_directory: dict[str, set[TerraformResourceRef]] = {}
    for block in blocks:
        if block.kind != "resource" or len(block.labels) < 2 or block.labels[0] != resource_type:
            continue
        refs_by_directory.setdefault(_block_directory(block), set()).add(
            TerraformResourceRef(resource_type=block.labels[0], resource_name=block.labels[1])
        )
    return refs_by_directory


def _cloudfront_alias_domains(
    block: TerraformBlock,
    variable_defaults_by_directory: dict[str, dict[str, str]],
) -> tuple[_ResolvedAlias, ...]:
    assignment = block.assignments.get("aliases")
    if assignment is None:
        return ()
    aliases = []
    seen_domains: set[str] = set()
    variable_defaults = variable_defaults_by_directory.get(_block_directory(block), {})
    for raw_item in _list_items(assignment.raw_value):
        domain = None
        literal = _quoted_scalar(raw_item)
        if literal is not None:
            domain = domain_from_value(literal)
        else:
            variable_name = _variable_ref(raw_item)
            if variable_name is not None:
                domain = variable_defaults.get(variable_name)
                literal = domain
        if domain is not None and literal is not None and domain not in seen_domains:
            aliases.append(
                _ResolvedAlias(
                    domain=domain,
                    literal=safe_config_literal(literal) or domain,
                    expression=raw_item.strip(),
                    line=assignment.line,
                )
            )
            seen_domains.add(domain)
    return tuple(aliases)


def _block_directory(block: TerraformBlock) -> str:
    path = block.relative_path.replace("\\", "/")
    directory, separator, _ = path.rpartition("/")
    return directory if separator else "."


def _cloudfront_s3_origins(
    block: TerraformBlock,
    s3_buckets: set[TerraformResourceRef],
) -> tuple[TerraformResourceRef, ...]:
    origins = []
    for nested in block.nested_blocks:
        if nested.kind != "origin":
            continue
        assignment = nested.assignments.get("domain_name")
        if assignment is None:
            continue
        ref = _resource_ref(assignment.raw_value)
        if ref is not None and ref in s3_buckets:
            origins.append(ref)
    return tuple(sorted(set(origins), key=lambda ref: ref.address))


def _top_level_blocks(scanned: ScannedFile) -> list[TerraformBlock]:
    if scanned.path.suffix != ".tf":
        return []
    blocks: list[TerraformBlock] = []
    current: tuple[str, tuple[str, ...], int, list[tuple[int, str]]] | None = None
    depth = 0
    in_block_comment = False
    heredoc_marker: str | None = None

    for line_number, raw_line in enumerate(scanned.lines, start=1):
        if heredoc_marker is not None:
            if raw_line.strip() == heredoc_marker:
                heredoc_marker = None
            if current is not None:
                current[3].append((line_number, ""))
            continue
        uncommented_line, in_block_comment = strip_comments(raw_line, in_block_comment=in_block_comment)
        line = uncommented_line.strip()
        if current is None:
            match = _BLOCK_HEADER_RE.match(line)
            if match is None:
                continue
            labels = tuple(re.findall(r'"([^"]+)"', match.group("labels")))
            current = (match.group("kind"), labels, line_number, [])
            depth = brace_delta(line)
            if depth <= 0:
                kind, labels, start_line, body = current
                blocks.append(_parse_block_body(scanned, kind, labels, start_line, body))
                current = None
            continue

        marker = heredoc_start_marker(line)
        if marker is not None:
            heredoc_marker = marker
            current[3].append((line_number, ""))
        else:
            current[3].append((line_number, line))
        depth += brace_delta(line)
        if depth <= 0:
            kind, labels, start_line, body = current
            blocks.append(_parse_block_body(scanned, kind, labels, start_line, body))
            current = None
            depth = 0
            heredoc_marker = None
    return blocks


def _parse_block_body(
    scanned: ScannedFile,
    kind: str,
    labels: tuple[str, ...],
    start_line: int,
    body: list[tuple[int, str]],
) -> TerraformBlock:
    assignments: dict[str, TerraformAssignment] = {}
    malformed_assignments: set[str] = set()
    nested_blocks: list[TerraformNestedBlock] = []
    nested_kind: str | None = None
    nested_line = 0
    nested_depth = 0
    nested_assignments: dict[str, TerraformAssignment] = {}
    nested_malformed_assignments: set[str] = set()

    index = 0
    while index < len(body):
        line_number, line = body[index]
        if not line:
            index += 1
            continue
        if nested_kind is None:
            if line == "}":
                index += 1
                continue
            nested_match = _NESTED_BLOCK_RE.match(line)
            if nested_match is not None:
                nested_kind = nested_match.group("kind")
                nested_line = line_number
                nested_depth = brace_delta(line)
                nested_assignments = {}
                nested_malformed_assignments = set()
                if nested_depth <= 0:
                    nested_blocks.append(
                        TerraformNestedBlock(
                            nested_kind,
                            nested_line,
                            nested_assignments,
                            frozenset(nested_malformed_assignments),
                        )
                    )
                    nested_kind = None
                index += 1
                continue
            # At top-level-in-resource scope, unexpected structural braces are
            # already represented in the outer block body. We only keep parsed
            # assignments and malformed assignment keys for coverage reasons.
            assignment, index, _, malformed_key = _assignment_at(body, index)
            if assignment is not None:
                assignments[assignment.key] = assignment
            elif malformed_key is not None:
                malformed_assignments.add(malformed_key)
            continue

        assignment, next_index, line_brace_delta, malformed_key = _assignment_at(body, index)
        if assignment is not None and nested_depth == 1:
            nested_assignments[assignment.key] = assignment
        elif malformed_key is not None and nested_depth == 1:
            nested_malformed_assignments.add(malformed_key)
        nested_depth += line_brace_delta
        if nested_depth <= 0:
            nested_blocks.append(
                TerraformNestedBlock(
                    nested_kind,
                    nested_line,
                    nested_assignments,
                    frozenset(nested_malformed_assignments),
                )
            )
            nested_kind = None
        index = next_index

    if nested_kind is not None:
        nested_blocks.append(
            TerraformNestedBlock(
                nested_kind,
                nested_line,
                nested_assignments,
                frozenset(nested_malformed_assignments),
            )
        )

    return TerraformBlock(
        kind=kind,
        labels=labels,
        line=start_line,
        relative_path=scanned.relative_path,
        assignments=assignments,
        nested_blocks=tuple(nested_blocks),
        malformed_assignments=frozenset(malformed_assignments),
    )


def _assignment_at(lines: list[tuple[int, str]], index: int) -> tuple[TerraformAssignment | None, int, int, str | None]:
    line_number, line = lines[index]
    parsed = _assignment_parts(line, line_number)
    if parsed is None:
        return None, index + 1, brace_delta(line), None
    key, value, start_line = parsed

    bracket_delta = _bracket_delta(value)
    if bracket_delta < 0:
        return None, index + 1, brace_delta(line), key
    if bracket_delta == 0:
        return TerraformAssignment(key=key, raw_value=value, line=start_line), index + 1, 0, None
    if not value.startswith("["):
        return None, index + 1, brace_delta(line), key

    raw_values = [value]
    next_index = index + 1
    failed = False
    while next_index < len(lines) and bracket_delta > 0:
        _, next_line = lines[next_index]
        if has_brace_outside_quote(next_line):
            failed = True
        raw_values.append(next_line.strip())
        bracket_delta += _bracket_delta(next_line)
        next_index += 1
    if failed or bracket_delta != 0:
        # The malformed value is consumed as an assignment expression, not as
        # HCL block structure, so callers should not apply its internal braces
        # to nested block depth. If this consumes the rest of the current block,
        # the resource fails closed with coverage rather than resuming from a
        # guessed structural point.
        return None, next_index, 0, key
    return TerraformAssignment(key=key, raw_value=" ".join(raw_values), line=start_line), next_index, 0, None


def _assignment_parts(line: str, line_number: int) -> tuple[str, str, int] | None:
    key, separator, raw_value = line.partition("=")
    if not separator:
        return None
    key = key.strip()
    if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return None
    value = raw_value.strip()
    if not value or has_brace_outside_quote(value):
        return None
    return key, value, line_number


def _list_items(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value.startswith("[") or not value.endswith("]"):
        return ()
    body = value[1:-1].strip()
    if not body:
        return ()
    items: list[str] = []
    quote: str | None = None
    escaped = False
    start = 0
    for index, char in enumerate(body):
        if escaped:
            escaped = False
        elif quote is not None and char == "\\":
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif char == "," and quote is None:
            item = body[start:index].strip()
            if not item:
                return ()
            items.append(item)
            start = index + 1
    final = body[start:].strip()
    if not final:
        return tuple(items)
    items.append(final)
    return tuple(items)


def _quoted_scalar(value: str) -> str | None:
    value = value.strip()
    if not value.startswith('"'):
        return None
    literal, next_index = quoted_value_at(value, 0)
    if literal is None or value[next_index:].strip():
        return None
    return literal


def _variable_ref(value: str) -> str | None:
    value = value.strip()
    if not value.startswith("var."):
        return None
    name = value.removeprefix("var.")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return None
    return name


def _resource_ref(value: str) -> TerraformResourceRef | None:
    match = _RESOURCE_REF_RE.fullmatch(value.strip())
    if match is None:
        return None
    return TerraformResourceRef(resource_type=match.group("type"), resource_name=match.group("name"))


def _bracket_delta(line: str) -> int:
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
        elif quote is None and char == "[":
            delta += 1
        elif quote is None and char == "]":
            delta -= 1
    return delta
