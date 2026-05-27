"""Zappa event-source extraction for SQS-backed Lambda consumers."""

from __future__ import annotations

import json

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.channel_normalization import normalize_sqs_arn
from source.kg.file_formats._shared.domain_literals import domain_from_value
from source.kg.file_formats._shared.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    deploy_target_entity,
    domain_entity,
    event_channel_entity,
)


def extract_zappa_event_sources(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    try:
        data = json.loads(scanned.text)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    for stage_name, stage_config in data.items():
        if not isinstance(stage_config, dict):
            continue
        _extract_zappa_http_deploy(repo, scanned, service_entity, build, tenant_id, str(stage_name), stage_config)
        events = stage_config.get("events")
        if not isinstance(events, list):
            continue
        for event_source in events:
            if not isinstance(event_source, dict):
                continue
            source = event_source.get("event_source")
            if not isinstance(source, dict):
                continue
            arn = source.get("arn")
            if not isinstance(arn, str):
                continue
            function = event_source.get("function")
            channel_ref = normalize_sqs_arn(arn)
            if channel_ref is None:
                continue
            line_number = _line_number_for(scanned, channel_ref.properties["raw_literal"])
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
                "CONSUMES_EVENT",
                service_entity,
                channel,
                repo,
                scanned.path,
                line_number,
                qualifier={
                    "source_kind": "zappa_event_source",
                    "stage": str(stage_name),
                    "function": function if isinstance(function, str) else "",
                    "path": scanned.relative_path,
                    "raw_literal": channel_ref.properties["raw_literal"],
                    "broker_kind": channel_ref.broker_kind,
                    "channel_address": channel_ref.channel_address,
                    "normalized_channel": channel_ref.channel_address,
                },
                derivation_class="authoritative_static",
            )


def _extract_zappa_http_deploy(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
    stage_name: str,
    stage_config: dict,
) -> None:
    app_function = stage_config.get("app_function")
    if not isinstance(app_function, str) or not app_function.strip():
        return
    app_function = app_function.strip()
    target = deploy_target_entity(repo, "zappa_lambda", f"{stage_name}:{app_function}", tenant_id)
    app_line = _line_number_for(scanned, app_function)
    add_entity_evidence(build, repo, target, scanned.path, app_line)
    add_fact(
        build,
        "DEPLOYS_VIA_CONFIG",
        service_entity,
        target,
        repo,
        scanned.path,
        app_line,
        qualifier={
            "source_kind": "zappa_settings",
            "target_type": "zappa_lambda",
            "stage": stage_name,
            "app_function": app_function,
            "path": scanned.relative_path,
        },
    )

    if stage_config.get("apigateway_enabled") is False:
        return
    raw_domain = stage_config.get("domain")
    if not isinstance(raw_domain, str):
        return
    domain = domain_from_value(raw_domain)
    if domain is None:
        return
    domain_line = _line_number_for(scanned, raw_domain)
    domain_ref = domain_entity(repo, domain, tenant_id)
    add_entity_evidence(build, repo, domain_ref, scanned.path, domain_line)
    add_fact(
        build,
        "REFERENCES_DOMAIN",
        service_entity,
        domain_ref,
        repo,
        scanned.path,
        domain_line,
        qualifier={"source_kind": "zappa_domain", "stage": stage_name, "literal": raw_domain, "path": scanned.relative_path},
    )
    add_fact(
        build,
        "ROUTES_DOMAIN_TO_DEPLOY",
        domain_ref,
        target,
        repo,
        scanned.path,
        # Route evidence should cite the route declaration. The deploy fact above
        # separately preserves the app_function line for the same target.
        domain_line,
        qualifier={
            "source_kind": "zappa_domain",
            "target_type": "zappa_lambda",
            "stage": stage_name,
            "app_function": app_function,
            "path": scanned.relative_path,
        },
    )


def _line_number_for(scanned: ScannedFile, needle: str) -> int:
    for line_number, line in enumerate(scanned.lines, start=1):
        if needle in line:
            return line_number
    return 1
