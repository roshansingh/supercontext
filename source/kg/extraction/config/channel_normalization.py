from __future__ import annotations

import configparser
from dataclasses import dataclass
from urllib.parse import urlparse

from source.kg.core.models import Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    event_channel_entity,
)


CHANNEL_TOKEN_DELIMITERS = set(" \t\r\n'\"`<>()[]{};,")
SQS_MAX_QUEUE_NAME_LENGTH = 80
SQS_MAX_FIFO_BASE_LENGTH = 75


@dataclass(frozen=True)
class NormalizedChannel:
    broker_kind: str
    channel_address: str
    properties: JsonObject


def normalize_sqs_arn(arn: str) -> NormalizedChannel | None:
    components = parse_arn_components(arn)
    if components is None or components["service"] != "sqs":
        return None
    raw_arn = str(components["arn"])
    queue_name = str(components["name"])
    if not is_sqs_queue_name(queue_name):
        return None
    return NormalizedChannel(
        broker_kind="sqs",
        channel_address=queue_name,
        properties={
            "raw_literal": raw_arn,
            "arn": raw_arn,
            "region": components["region"],
            "account_id": components["account_id"],
            "queue_name": queue_name,
        },
    )


def normalize_sns_arn(arn: str) -> NormalizedChannel | None:
    components = parse_arn_components(arn)
    if components is None or components["service"] != "sns":
        return None
    raw_arn = str(components["arn"])
    topic_name = str(components["name"])
    if not _is_simple_aws_resource_name(topic_name):
        return None
    return NormalizedChannel(
        broker_kind="sns",
        channel_address=topic_name,
        properties={
            "raw_literal": raw_arn,
            "arn": raw_arn,
            "region": components["region"],
            "account_id": components["account_id"],
            "topic_name": topic_name,
        },
    )


def normalize_sqs_url(url: str) -> NormalizedChannel | None:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host_parts = parsed.netloc.split(".")
    if len(host_parts) < 4 or host_parts[0] != "sqs" or host_parts[2:] != ["amazonaws", "com"]:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return None
    region = host_parts[1]
    account_id, queue_name = parts
    if not _is_aws_region(region) or not account_id.isdigit() or not is_sqs_queue_name(queue_name):
        return None
    raw_url = url.strip()
    return NormalizedChannel(
        broker_kind="sqs",
        channel_address=queue_name,
        properties={
            "raw_literal": raw_url,
            "queue_url": raw_url,
            "region": region,
            "account_id": account_id,
            "queue_name": queue_name,
        },
    )


def normalize_sqs_queue_name(name: str) -> NormalizedChannel | None:
    queue_name = name.strip()
    if not is_sqs_queue_name(queue_name):
        return None
    return NormalizedChannel(
        broker_kind="sqs",
        channel_address=queue_name,
        properties={
            "raw_literal": queue_name,
            "queue_name": queue_name,
        },
    )


def parse_arn_components(arn: str) -> JsonObject | None:
    value = arn.strip()
    parts = value.split(":", 5)
    if len(parts) != 6:
        return None
    prefix, partition, service, region, account_id, name = parts
    if prefix != "arn" or partition != "aws":
        return None
    if service not in {"sqs", "sns"}:
        return None
    if not _is_aws_region(region) or not account_id.isdigit() or not name:
        return None
    return {
        "service": service,
        "region": region,
        "account_id": account_id,
        "name": name,
        "arn": value,
    }


def normalized_channels_in_text(text: str) -> list[NormalizedChannel]:
    channels: list[NormalizedChannel] = []
    # Dedupe only within this text chunk; callers still get separate evidence
    # rows when the same channel appears on different source lines.
    seen: set[tuple[str, str, str]] = set()
    for token in _candidate_channel_tokens(text):
        channel = normalize_sqs_arn(token) or normalize_sns_arn(token) or normalize_sqs_url(token)
        if channel is None:
            continue
        key = (channel.broker_kind, channel.channel_address, str(channel.properties.get("raw_literal", "")))
        if key in seen:
            continue
        seen.add(key)
        channels.append(channel)
    return channels


def normalized_ini_queue_channels(scanned: ScannedFile) -> list[tuple[int, NormalizedChannel]]:
    if scanned.path.suffix.lower() != ".ini":
        return []
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(scanned.text)
    except configparser.Error:
        return []
    line_by_option = _ini_option_lines(scanned)
    channels: list[tuple[int, NormalizedChannel]] = []
    for option, value in parser.defaults().items():
        channel = _normalized_ini_queue_value(value)
        if channel is not None:
            channels.append((line_by_option.get(("default", option.casefold()), 1), channel))
    for section in parser.sections():
        section_key = section.casefold()
        for option in sorted(option for candidate_section, option in line_by_option if candidate_section == section_key):
            if option not in parser[section]:
                continue
            channel = _normalized_ini_queue_value(parser[section][option])
            if channel is not None:
                channels.append((line_by_option.get((section_key, option), 1), channel))
    return channels


def add_event_channel_reference(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    service_entity: Entity,
    build: ConfigKgBuild,
    channel_ref: NormalizedChannel,
    source_kind: str,
    tenant_id: str,
) -> None:
    if not channel_ref.channel_address:
        return
    channel = event_channel_entity(
        repo,
        channel_ref.broker_kind,
        channel_ref.channel_address,
        tenant_id=tenant_id,
        properties=channel_ref.properties,
    )
    add_entity_evidence(build, repo, channel, scanned.path, line_number)
    add_fact(
        build,
        "REFERENCES_EVENT_CHANNEL",
        service_entity,
        channel,
        repo,
        scanned.path,
        line_number,
        qualifier={
            "source_kind": source_kind,
            "path": scanned.relative_path,
            "raw_literal": channel_ref.properties.get("raw_literal"),
            "broker_kind": channel_ref.broker_kind,
            "channel_address": channel_ref.channel_address,
            "normalized_channel": channel_ref.channel_address,
        },
    )


def is_sqs_queue_name(name: str) -> bool:
    if name.endswith(".fifo"):
        base_name = name[: -len(".fifo")]
        return 1 <= len(base_name) <= SQS_MAX_FIFO_BASE_LENGTH and _is_sqs_queue_stem(base_name)
    return 1 <= len(name) <= SQS_MAX_QUEUE_NAME_LENGTH and _is_sqs_queue_stem(name)


def _candidate_channel_tokens(text: str) -> list[str]:
    candidates: list[str] = []
    for marker in ("arn:aws:", "http://sqs.", "https://sqs."):
        start = 0
        while True:
            marker_index = text.find(marker, start)
            if marker_index < 0:
                break
            end = marker_index
            while end < len(text) and text[end] not in CHANNEL_TOKEN_DELIMITERS:
                end += 1
            candidates.append(_clean_channel_token(text[marker_index:end]))
            start = end + 1
    return [candidate for candidate in candidates if candidate]


def _clean_channel_token(value: str) -> str:
    return value.strip().strip("'\"`<>()[]{}.,;")


def _is_sqs_queue_stem(name: str) -> bool:
    return bool(name) and all(_is_ascii_alnum(character) or character in {"_", "-"} for character in name)


def _is_aws_region(region: str) -> bool:
    return bool(region) and all(_is_ascii_alnum(character) or character == "-" for character in region)


def _is_simple_aws_resource_name(name: str) -> bool:
    return bool(name) and all(_is_ascii_alnum(character) or character in {"_", "-"} for character in name)


def _is_ascii_alnum(character: str) -> bool:
    return ("a" <= character <= "z") or ("A" <= character <= "Z") or ("0" <= character <= "9")


def _normalized_ini_queue_value(value: str) -> NormalizedChannel | None:
    if not _looks_like_queue_config_value(value):
        return None
    return normalize_sqs_queue_name(value)


def _looks_like_queue_config_value(value: str) -> bool:
    channel = normalize_sqs_queue_name(value)
    if channel is None:
        return False
    if not any(character.isalpha() for character in value):
        return False
    return "-" in value or "_" in value or value.endswith(".fifo")


def _ini_option_lines(scanned: ScannedFile) -> dict[tuple[str, str], int]:
    current_section: str | None = None
    lines: dict[tuple[str, str], int] = {}
    for line_number, raw_line in enumerate(scanned.lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().casefold()
            continue
        if current_section is None:
            continue
        key, separator, _ = line.partition("=")
        if not separator:
            key, separator, _ = line.partition(":")
        if separator:
            lines[(current_section, key.strip().casefold())] = line_number
    return lines
