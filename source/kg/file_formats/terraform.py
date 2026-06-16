"""Fail-closed Terraform literal domain extraction.

V1 domain-literal scope is top-level `variable` and `resource` blocks with
double-quoted scalar assignments or single-line lists of quoted literals, plus
`module.source` git host literals. Runtime extraction has a separate typed
CloudFront/S3 pass. Other provider, data, locals, output, terraform,
provisioner, interpolation, objects, multi-line lists, and heredoc values remain
fail-closed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from source.kg.core.models import Coverage, Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    domain_entity,
    event_channel_entity,
)
from source.kg.file_formats._shared.channel_normalization import (
    NormalizedChannel,
    normalize_aws_stream_arn,
    normalize_sns_arn,
    normalize_sns_topic_name,
    normalize_sqs_arn,
    normalize_sqs_queue_name,
)
from source.kg.file_formats._shared.domain_literals import domain_from_value, safe_config_literal
from source.kg.file_formats._shared.hcl import (
    brace_delta,
    has_brace_outside_quote,
    heredoc_start_marker,
    quoted_value_at,
    strip_comments,
)
from source.kg.file_formats.terraform_runtime import (
    TerraformAssignment,
    TerraformBlock,
    TerraformResourceRef,
    extract_terraform_runtime_routes,
    terraform_block_directory,
    terraform_quoted_scalar,
    terraform_resource_ref,
    terraform_top_level_blocks,
)


@dataclass
class _BlockState:
    kind: str
    depth: int
    labels: tuple[str, ...] = ()


SUPPORTED_BLOCK_KINDS = {"module", "variable", "resource"}


def extract_terraform(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    """Extract legacy single-file Terraform domain literals.

    Runtime topology extraction requires the full Terraform file set so variable
    defaults and resources can be resolved within a Terraform root. Use
    `extract_terraform_files` in production paths. This entry point remains for
    tests and back-compat callers that intentionally want only per-file
    domain-literal extraction. If this legacy path sees a CloudFront
    distribution, it emits coverage noting that runtime route extraction
    requires the file-set API.
    """

    _extract_terraform_domain_literals(
        repo,
        scanned,
        service_entity,
        build,
        tenant_id,
        emit_runtime_skipped_coverage=True,
    )


def extract_terraform_files(
    repo: RepoSnapshot,
    files: Iterable[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    files = tuple(files)
    terraform_blocks = [
        block for scanned in files if scanned.path.suffix == ".tf" for block in terraform_top_level_blocks(scanned)
    ]
    for scanned in files:
        _extract_terraform_domain_literals(
            repo,
            scanned,
            service_entity,
            build,
            tenant_id,
            skip_cloudfront_aliases=True,
        )
    _extract_terraform_event_sources(repo, terraform_blocks, service_entity, build, tenant_id)
    extract_terraform_runtime_routes(repo, files, service_entity, build, tenant_id, blocks=terraform_blocks)


def _extract_terraform_event_sources(
    repo: RepoSnapshot,
    blocks: list[TerraformBlock],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    channels_by_ref = _terraform_event_channels_by_ref(blocks)
    for block in blocks:
        if block.kind != "resource" or len(block.labels) < 2:
            continue
        resource_type = block.labels[0]
        if resource_type == "aws_lambda_event_source_mapping":
            assignment = block.assignments.get("event_source_arn")
            channel = _channel_from_terraform_arn_assignment(
                assignment,
                channels_by_ref,
                terraform_block_directory(block),
            )
            source_kind = "terraform_lambda_event_source_mapping"
        elif resource_type == "aws_sns_topic_subscription":
            assignment = block.assignments.get("topic_arn")
            channel = _channel_from_terraform_arn_assignment(
                assignment,
                channels_by_ref,
                terraform_block_directory(block),
            )
            source_kind = "terraform_sns_topic_subscription"
        else:
            continue
        if assignment is None or channel is None:
            continue
        _add_terraform_event_source(repo, build, service_entity, tenant_id, block, assignment.line, channel, source_kind)


def _terraform_event_channels_by_ref(
    blocks: list[TerraformBlock],
) -> dict[tuple[str, TerraformResourceRef], NormalizedChannel]:
    channels_by_ref: dict[tuple[str, TerraformResourceRef], NormalizedChannel] = {}
    seen_refs: set[tuple[str, TerraformResourceRef]] = set()
    for block in blocks:
        if block.kind != "resource" or len(block.labels) < 2:
            continue
        resource_ref = TerraformResourceRef(resource_type=block.labels[0], resource_name=block.labels[1])
        key = (terraform_block_directory(block), resource_ref)
        if block.labels[0] == "aws_sqs_queue":
            channel = _named_terraform_sqs_queue(block)
        elif block.labels[0] == "aws_sns_topic":
            channel = _named_terraform_sns_topic(block)
        else:
            continue
        if key in seen_refs:
            channels_by_ref.pop(key, None)
            continue
        seen_refs.add(key)
        if channel is not None:
            channels_by_ref[key] = channel
    return channels_by_ref


def _named_terraform_sqs_queue(block: TerraformBlock) -> NormalizedChannel | None:
    assignment = block.assignments.get("name")
    if assignment is None:
        return None
    literal = terraform_quoted_scalar(assignment.raw_value)
    return normalize_sqs_queue_name(literal) if literal is not None else None


def _named_terraform_sns_topic(block: TerraformBlock) -> NormalizedChannel | None:
    assignment = block.assignments.get("name")
    if assignment is None:
        return None
    literal = terraform_quoted_scalar(assignment.raw_value)
    return normalize_sns_topic_name(literal) if literal is not None else None


def _channel_from_terraform_arn_assignment(
    assignment: TerraformAssignment | None,
    channels_by_ref: dict[tuple[str, TerraformResourceRef], NormalizedChannel],
    directory: str,
) -> NormalizedChannel | None:
    if assignment is None:
        return None
    raw_value = assignment.raw_value
    literal = terraform_quoted_scalar(raw_value)
    if literal is not None:
        return normalize_sqs_arn(literal) or normalize_sns_arn(literal) or normalize_aws_stream_arn(literal)
    ref = _terraform_arn_resource_ref(raw_value)
    if ref is None:
        return None
    return channels_by_ref.get((directory, ref))


def _terraform_arn_resource_ref(raw_value: str) -> TerraformResourceRef | None:
    value = raw_value.strip()
    if not value.endswith(".arn"):
        return None
    return terraform_resource_ref(value)


def _add_terraform_event_source(
    repo: RepoSnapshot,
    build: ConfigKgBuild,
    service_entity: Entity,
    tenant_id: str,
    block: TerraformBlock,
    line_number: int,
    channel_ref: NormalizedChannel,
    source_kind: str,
) -> None:
    channel = event_channel_entity(
        repo,
        channel_ref.broker_kind,
        channel_ref.channel_address,
        tenant_id=tenant_id,
        properties=channel_ref.properties,
    )
    path = repo.root / block.relative_path
    add_entity_evidence(build, repo, channel, path, line_number)
    add_fact(
        build,
        "CONSUMES_EVENT",
        service_entity,
        channel,
        repo,
        path,
        line_number,
        qualifier={
            "source_kind": source_kind,
            "path": block.relative_path,
            "resource_type": block.labels[0],
            "resource_name": block.labels[1],
            "raw_literal": channel_ref.properties.get("raw_literal"),
            "broker_kind": channel_ref.broker_kind,
            "channel_address": channel_ref.channel_address,
        },
    )


def _extract_terraform_domain_literals(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
    *,
    skip_cloudfront_aliases: bool = False,
    emit_runtime_skipped_coverage: bool = False,
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
        uncommented_line, in_block_comment = strip_comments(raw_line, in_block_comment=in_block_comment)
        line = uncommented_line.strip()
        if not line:
            continue
        if block is None:
            block = _start_block(line)
            if block is not None and emit_runtime_skipped_coverage and _is_cloudfront_distribution_block(block):
                _add_legacy_runtime_skipped_coverage(repo, scanned, build, tenant_id, line_number, block)
            continue
        heredoc_marker = heredoc_start_marker(line)
        if heredoc_marker is not None:
            block.depth += brace_delta(line)
            if block.depth <= 0:
                block = None
                heredoc_marker = None
            continue
        if block.depth == 1 and not has_brace_outside_quote(line):
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
            elif not skip_cloudfront_aliases or not _is_cloudfront_alias_assignment(block, line):
                for literal in _assignment_literals(line) or ():
                    _add_terraform_domain(repo, scanned, service_entity, build, line_number, literal, tenant_id)
        block.depth += brace_delta(line)
        if block.depth <= 0:
            block = None


def _start_block(line: str) -> _BlockState | None:
    if "{" not in line:
        return None
    token = line.split(maxsplit=1)[0]
    if token not in SUPPORTED_BLOCK_KINDS:
        return None
    depth = brace_delta(line)
    if depth <= 0:
        return None
    return _BlockState(kind=token, depth=depth, labels=_quoted_labels_before_open_brace(line))


def _is_cloudfront_alias_assignment(block: _BlockState, line: str) -> bool:
    return _is_cloudfront_distribution_block(block) and _assignment_key(line) == "aliases"


def _is_cloudfront_distribution_block(block: _BlockState) -> bool:
    return block.kind == "resource" and block.labels[:1] == ("aws_cloudfront_distribution",)


def _assignment_key(line: str) -> str | None:
    key, separator, _ = line.partition("=")
    if not separator:
        return None
    key = key.strip()
    return key or None


def _quoted_labels_before_open_brace(line: str) -> tuple[str, ...]:
    before_brace, _, _ = line.partition("{")
    labels: list[str] = []
    quote: str | None = None
    escaped = False
    chars: list[str] = []
    for char in before_brace:
        if escaped:
            if quote is not None:
                chars.append(char)
            escaped = False
        elif quote is not None and char == "\\":
            escaped = True
        elif char == '"':
            if quote == '"':
                labels.append("".join(chars))
                chars = []
                quote = None
            elif quote is None:
                quote = '"'
        elif quote is not None:
            chars.append(char)
    return tuple(labels)


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
        literal, next_index = quoted_value_at(value, 0)
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
        literal, next_index = quoted_value_at(value, index)
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


def _add_legacy_runtime_skipped_coverage(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    build: ConfigKgBuild,
    tenant_id: str,
    line_number: int,
    block: _BlockState,
) -> None:
    build.coverage.append(
        Coverage(
            tenant_id=tenant_id,
            predicate="ROUTES_DOMAIN_TO_DEPLOY",
            scope_ref={
                "repo": repo.name,
                "path": scanned.relative_path,
                "line": line_number,
                "resource_type": "aws_cloudfront_distribution",
                "resource_name": block.labels[1] if len(block.labels) > 1 else "",
                "reason": "terraform_runtime_requires_file_set_api",
            },
            state="partially_instrumented",
            source_system=CONFIG_SOURCE_SYSTEM,
        )
    )
