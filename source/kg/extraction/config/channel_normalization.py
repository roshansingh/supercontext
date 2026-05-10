from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from source.kg.core.models import JsonObject


ARN_RE = re.compile(r"\barn:aws:(?P<service>sqs|sns):(?P<region>[A-Za-z0-9-]+):(?P<account_id>\d+):(?P<name>[A-Za-z0-9_.-]+)\b")
SQS_URL_RE = re.compile(r"\bhttps?://sqs\.(?P<region>[A-Za-z0-9-]+)\.amazonaws\.com/(?P<account_id>\d+)/(?P<queue_name>[A-Za-z0-9_.-]+)\b")
SQS_QUEUE_NAME_RE = re.compile(r"^(?:[A-Za-z0-9_-]{1,80}|[A-Za-z0-9_-]{1,75}\.fifo)$")


@dataclass(frozen=True)
class NormalizedChannel:
    broker_kind: str
    channel_address: str
    properties: JsonObject


def normalize_sqs_arn(arn: str) -> NormalizedChannel | None:
    components = parse_arn_components(arn)
    if components is None or components["service"] != "sqs":
        return None
    queue_name = components["name"]
    if not SQS_QUEUE_NAME_RE.fullmatch(queue_name):
        return None
    return NormalizedChannel(
        broker_kind="sqs",
        channel_address=queue_name,
        properties={
            "raw_literal": arn,
            "arn": arn,
            "region": components["region"],
            "account_id": components["account_id"],
            "queue_name": queue_name,
        },
    )


def normalize_sns_arn(arn: str) -> NormalizedChannel | None:
    components = parse_arn_components(arn)
    if components is None or components["service"] != "sns":
        return None
    topic_name = components["name"]
    return NormalizedChannel(
        broker_kind="sns",
        channel_address=topic_name,
        properties={
            "raw_literal": arn,
            "arn": arn,
            "region": components["region"],
            "account_id": components["account_id"],
            "topic_name": topic_name,
        },
    )


def normalize_sqs_url(url: str) -> NormalizedChannel | None:
    match = SQS_URL_RE.search(url)
    if match:
        queue_name = match.group("queue_name")
        if not SQS_QUEUE_NAME_RE.fullmatch(queue_name):
            return None
        return NormalizedChannel(
            broker_kind="sqs",
            channel_address=queue_name,
            properties={
                "raw_literal": match.group(0),
                "queue_url": match.group(0),
                "region": match.group("region"),
                "account_id": match.group("account_id"),
                "queue_name": queue_name,
            },
        )

    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.netloc.startswith("sqs.") or ".amazonaws.com" not in parsed.netloc:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return None
    region = parsed.netloc.split(".")[1]
    account_id, queue_name = parts
    if not account_id.isdigit() or not SQS_QUEUE_NAME_RE.fullmatch(queue_name):
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
    if not SQS_QUEUE_NAME_RE.fullmatch(queue_name):
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
    match = ARN_RE.search(arn)
    if not match:
        return None
    return {
        "service": match.group("service"),
        "region": match.group("region"),
        "account_id": match.group("account_id"),
        "name": match.group("name"),
        "arn": match.group(0),
    }
