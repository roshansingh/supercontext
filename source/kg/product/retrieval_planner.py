from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


AnchorKind = Literal["DeployTarget", "Domain", "Endpoint", "EventChannel", "Package", "Repo", "Symbol"]
RetrievalCommand = Literal[
    "deploy_mappings",
    "domain_references",
    "endpoints",
    "event_channels",
    "modules_importing",
    "repo_dependencies",
    "symbols",
]


@dataclass(frozen=True)
class RetrievalAnchor:
    kind: AnchorKind
    value: str

    def __post_init__(self) -> None:
        if self.kind not in _ANCHOR_COMMANDS:
            raise ValueError(f"Unsupported retrieval anchor kind: {self.kind}")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("Retrieval anchor requires a non-empty string value")
        object.__setattr__(self, "value", self.value.strip())

    @classmethod
    def from_mapping(cls, row: JsonObject) -> "RetrievalAnchor":
        if not isinstance(row, dict):
            raise ValueError("Retrieval anchor mapping must be a JSON object")
        raw_kind = row.get("kind")
        value = row.get("value")
        if not isinstance(raw_kind, str) or not raw_kind.strip():
            raise ValueError("Retrieval anchor requires a non-empty string kind")
        kind = raw_kind.strip()
        if kind not in _ANCHOR_COMMANDS:
            raise ValueError(f"Unsupported retrieval anchor kind: {kind}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Retrieval anchor requires a non-empty string value")
        return cls(kind=cast(AnchorKind, kind), value=value.strip())


@dataclass(frozen=True)
class RetrievalStep:
    name: str
    command: RetrievalCommand
    args: JsonObject
    purpose: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Retrieval step requires a non-empty string name")
        if self.command not in _VALID_COMMANDS:
            raise ValueError(f"Unsupported retrieval command: {self.command}")
        if not isinstance(self.args, dict):
            raise ValueError("Retrieval step requires args to be a mapping")
        required_arg = _COMMAND_ARG_KEYS[self.command]
        required_value = self.args.get(required_arg)
        if not isinstance(required_value, str) or not required_value.strip():
            raise ValueError(f"Retrieval step command {self.command} requires a non-empty string {required_arg} arg")
        normalized_args = dict(self.args)
        normalized_args[required_arg] = required_value.strip()
        normalized_args["limit"] = _bounded_limit(self.args.get("limit", 25))
        object.__setattr__(self, "args", normalized_args)
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise ValueError("Retrieval step requires a non-empty string purpose")

    def run(self, kg: KgSnapshot) -> JsonObject | list[JsonObject]:
        limit = _bounded_limit(self.args.get("limit", 25))
        if self.command == "deploy_mappings":
            return kg.deploy_mappings(target_query=str(self.args["target"]), limit=limit)
        if self.command == "domain_references":
            return kg.domain_references(str(self.args["domain"]), limit=limit)
        if self.command == "endpoints":
            return kg.endpoints(path_query=str(self.args["path"]), limit=limit)
        if self.command == "event_channels":
            return kg.event_channels(channel_query=str(self.args["channel"]), limit=limit)
        if self.command == "modules_importing":
            return kg.modules_importing(str(self.args["package"]), limit=limit)
        if self.command == "repo_dependencies":
            return kg.repo_dependencies(str(self.args["repo"]), limit=limit)
        if self.command == "symbols":
            return kg.lookup_symbol(str(self.args["query"]), limit=limit)
        raise ValueError(f"Unsupported retrieval command: {self.command}")


_ANCHOR_COMMANDS: dict[str, RetrievalCommand] = {
    "DeployTarget": "deploy_mappings",
    "Domain": "domain_references",
    "Endpoint": "endpoints",
    "EventChannel": "event_channels",
    "Package": "modules_importing",
    "Repo": "repo_dependencies",
    "Symbol": "symbols",
}
_VALID_COMMANDS = set(_ANCHOR_COMMANDS.values())
_COMMAND_ARG_KEYS: dict[RetrievalCommand, str] = {
    "deploy_mappings": "target",
    "domain_references": "domain",
    "endpoints": "path",
    "event_channels": "channel",
    "modules_importing": "package",
    "repo_dependencies": "repo",
    "symbols": "query",
}


def plan_retrieval_steps(
    anchors: list[RetrievalAnchor] | tuple[RetrievalAnchor, ...],
    *,
    limit: int = 25,
) -> tuple[RetrievalStep, ...]:
    bounded_limit = _bounded_limit(limit)
    steps = []
    seen: set[tuple[str, str]] = set()
    for anchor in anchors:
        key = (anchor.kind, anchor.value)
        if key in seen:
            continue
        seen.add(key)
        steps.append(_step_for_anchor(anchor, bounded_limit))
    return tuple(steps)


def plan_retrieval_steps_from_mappings(
    anchors: list[JsonObject] | tuple[JsonObject, ...],
    *,
    limit: int = 25,
) -> tuple[RetrievalStep, ...]:
    return plan_retrieval_steps(tuple(RetrievalAnchor.from_mapping(anchor) for anchor in anchors), limit=limit)


def _step_for_anchor(anchor: RetrievalAnchor, limit: int) -> RetrievalStep:
    command = _ANCHOR_COMMANDS[anchor.kind]
    if anchor.kind == "DeployTarget":
        return RetrievalStep(
            name=_step_name(anchor),
            command=command,
            args={"target": anchor.value, "limit": limit},
            purpose=f"Find deploy mappings matching {anchor.value}.",
        )
    if anchor.kind == "Domain":
        return RetrievalStep(
            name=_step_name(anchor),
            command=command,
            args={"domain": anchor.value, "limit": limit},
            purpose=f"Find domain references for {anchor.value}.",
        )
    if anchor.kind == "Endpoint":
        return RetrievalStep(
            name=_step_name(anchor),
            command=command,
            args={"path": anchor.value, "limit": limit},
            purpose=f"Find endpoint facts matching {anchor.value}.",
        )
    if anchor.kind == "EventChannel":
        return RetrievalStep(
            name=_step_name(anchor),
            command=command,
            args={"channel": anchor.value, "limit": limit},
            purpose=f"Find event-channel facts matching {anchor.value}.",
        )
    if anchor.kind == "Package":
        return RetrievalStep(
            name=_step_name(anchor),
            command=command,
            args={"package": anchor.value, "limit": limit},
            purpose=f"Find modules importing package {anchor.value}.",
        )
    if anchor.kind == "Repo":
        return RetrievalStep(
            name=_step_name(anchor),
            command=command,
            args={"repo": anchor.value, "limit": limit},
            purpose=f"Find cross-repo dependencies for {anchor.value}.",
        )
    if anchor.kind == "Symbol":
        return RetrievalStep(
            name=_step_name(anchor),
            command=command,
            args={"query": anchor.value, "limit": limit},
            purpose=f"Find symbols matching {anchor.value}.",
        )
    raise ValueError(f"Unsupported retrieval anchor kind: {anchor.kind}")


def _step_name(anchor: RetrievalAnchor) -> str:
    return f"{_slug(anchor.kind)}_{_slug(anchor.value)}"


def _slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value.strip()]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug or "anchor"


def _bounded_limit(value: object) -> int:
    try:
        raw_limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Retrieval limit must be an integer") from exc
    return min(max(1, raw_limit), 100)
