from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

from source.kg.core.models import JsonObject
from source.kg.product.artifact_consistency import packet_fingerprint
from source.kg.query.snapshot import KgSnapshot


ValidationResult = Literal["pass", "partial", "fail"]
CheckFn = Callable[[KgSnapshot], tuple[ValidationResult, str, JsonObject]]


@dataclass(frozen=True)
class ValidationConfig:
    mercury_snapshot: Path
    true_loop_snapshot: Path
    lattice_snapshot: Path
    goldset_packets: Path
    goldset_answers: Path
    goldset_judgement: Path
    generated_at: str
    evaluation_dir: Path = Path("docs/evaluation")
    strict_smoke_checks: bool = True


def default_generated_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_canonical_validation(config: ValidationConfig) -> JsonObject:
    mercury = KgSnapshot(config.mercury_snapshot)
    true_loop = KgSnapshot(config.true_loop_snapshot)
    lattice = KgSnapshot(config.lattice_snapshot)
    smoke_checks = _run_smoke_checks(
        [
            ("Mercury ML", config.mercury_snapshot, mercury, _mercury_smoke_checks()),
            ("True Loop", config.true_loop_snapshot, true_loop, _true_loop_smoke_checks()),
            ("LatticeAI 23", config.lattice_snapshot, lattice, _lattice_smoke_checks()),
        ],
        strict=config.strict_smoke_checks,
    )
    goldset = _goldset_summary(config)
    return {
        "generated_at": config.generated_at,
        "status": _overall_status(smoke_checks, goldset),
        "inputs": {
            "mercury_snapshot": _report_path(config.mercury_snapshot),
            "true_loop_snapshot": _report_path(config.true_loop_snapshot),
            "lattice_snapshot": _report_path(config.lattice_snapshot),
            "goldset_packets": _report_path(config.goldset_packets),
            "goldset_answers": _report_path(config.goldset_answers),
            "goldset_judgement": _report_path(config.goldset_judgement),
        },
        "snapshot_inventory": [
            _snapshot_inventory("Mercury ML", config.mercury_snapshot, mercury),
            _snapshot_inventory("True Loop", config.true_loop_snapshot, true_loop),
            _snapshot_inventory("LatticeAI 23", config.lattice_snapshot, lattice),
        ],
        "deterministic_smoke": {
            "summary": _result_counts(smoke_checks),
            "checks": smoke_checks,
        },
        "goldset": goldset,
        "supersedes": _superseded_artifacts(config.evaluation_dir),
        "next_feature_recommendation": (
            "Use the config/env citation movement to rescore the LatticeAI goldset, then prioritize the repeated "
            "remaining failure owner rather than adding stack-specific extractors."
        ),
    }


def render_validation_markdown(report: JsonObject) -> str:
    lines = [
        "# Canonical Product Validation Report",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Overall status: **{report['status']}**",
        "",
        "This is the current canonical validation report for low/medium deterministic surfaces and the LatticeAI goldset. "
        "Older dated artifacts are preserved for audit history only.",
        "",
        "## Inputs",
        "",
        "| Input | Path |",
        "|---|---|",
    ]
    for name, path in report["inputs"].items():
        lines.append(f"| {_md_table_cell(f'`{name}`')} | {_md_table_cell(f'`{path}`')} |")

    lines.extend(["", "## Snapshot Inventory", "", "| Corpus | Snapshot | Entities | Facts | Evidence | Coverage |"])
    lines.append("|---|---|---:|---:|---:|---:|")
    for row in report["snapshot_inventory"]:
        snapshot_cell = _code_md_table_cell(row["snapshot"])
        lines.append(
            f"| {_md_table_cell(row['corpus'])} | {snapshot_cell} | "
            f"{row['entities']} | {row['facts']} | {row['evidence']} | {row['coverage']} |"
        )

    smoke = report["deterministic_smoke"]
    lines.extend(
        [
            "",
            "## Low/Medium And Goldset Retrieval Smoke",
            "",
            "Smoke-check IDs are corpus-scoped; the same product query ID can appear for multiple fixtures.",
            "",
            _counts_sentence(smoke["summary"]),
            "",
            "| ID | Difficulty | Corpus | Surface | Result | Notes |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in smoke["checks"]:
        surface_cell = _code_md_table_cell(row["surface"])
        lines.append(
            f"| {_md_table_cell(row['query_id'])} | {_md_table_cell(row['difficulty'])} | "
            f"{_md_table_cell(row['corpus'])} | {surface_cell} | "
            f"{_md_table_cell(row['result'])} | {_md_table_cell(row['notes'])} |"
        )

    goldset = report["goldset"]
    lines.extend(
        [
            "",
            "## LatticeAI Goldset",
            "",
            _counts_sentence(goldset["answer_score_summary"], label="Answer scores"),
            "",
            _counts_sentence(goldset["evidence_summary"], label="Evidence completeness"),
            "",
            _counts_sentence(goldset["artifact_summary"], label="Artifact consistency"),
            "",
            "| Scenario | Artifact | Evidence | Judged Answer | Failure Owner | Notes |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in goldset["scenarios"]:
        raw_artifact_issues = row.get("artifact_issues", [])
        artifact_issues = raw_artifact_issues if isinstance(raw_artifact_issues, list) else []
        artifact_notes = "; ".join(str(issue) for issue in artifact_issues)
        artifact_cell = row.get("artifact_status", "unknown")
        if artifact_notes:
            artifact_cell = f"{artifact_cell}: {artifact_notes}"
        lines.append(
            f"| {_md_table_cell(row['scenario_id'])} | {_md_table_cell(artifact_cell)} | "
            f"{_md_table_cell(row['evidence_completeness'])} | "
            f"{_md_table_cell(row['answer_score'])} | {_md_table_cell(', '.join(row['failure_owners']))} | "
            f"{_md_table_cell(row['notes'])} |"
        )
    if goldset["answer_only_scenarios"]:
        lines.extend(["", "Answer-only scenarios without judgement ground truth:"])
        for row in goldset["answer_only_scenarios"]:
            lines.append(f"- `{row['scenario_id']}`: self-score `{row['self_score']}`, {row['notes']}")
    if goldset["packet_only_scenarios"]:
        lines.extend(["", "Packet-only scenarios without answer or judgement rows:"])
        for row in goldset["packet_only_scenarios"]:
            lines.append(f"- `{row['scenario_id']}`: {row['notes']}")

    lines.extend(
        [
            "",
            "## Product Readout",
            "",
            *_product_readout_lines(goldset, str(report["next_feature_recommendation"])),
            "",
            "## Superseded Artifacts",
            "",
            "The files below are historical run artifacts. Use this report for current product-validation status.",
            "",
            "| Artifact | Status |",
            "|---|---|",
        ]
    )
    for artifact in report["supersedes"]:
        lines.append(f"| {_code_md_table_cell(artifact)} | Superseded by this canonical report |")
    return "\n".join(lines) + "\n"


def _run_smoke_checks(
    suites: list[tuple[str, Path, KgSnapshot, list[tuple[str, str, str, str, CheckFn]]]],
    strict: bool,
) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for corpus, snapshot_path, kg, checks in suites:
        for query_id, difficulty, surface, question, check in checks:
            try:
                result, notes, actual = check(kg)
            except Exception as exc:  # pragma: no cover - defensive reporting path
                if strict:
                    raise
                result, notes, actual = "fail", f"{type(exc).__name__}: {exc}", {}
            rows.append(
                {
                    "query_id": query_id,
                    "difficulty": difficulty,
                    "corpus": corpus,
                    "snapshot": _report_path(snapshot_path),
                    "surface": surface,
                    "question": question,
                    "result": result,
                    "notes": notes,
                    "actual": actual,
                }
            )
    return rows


def _mercury_smoke_checks() -> list[tuple[str, str, str, str, CheckFn]]:
    batch_path = "mercury_ml/intent_based_predictions/batch_predict.py"
    return [
        (
            "Q001",
            "Low",
            "modules-importing",
            "What modules import pandas?",
            _expect_list("pandas importers", lambda kg: kg.modules_importing("pandas", limit=5), 1),
        ),
        (
            "Q003",
            "Low",
            "lookup-symbol",
            "Who calls load_model?",
            _expect_status(lambda kg: kg.lookup_symbol("load_model", limit=5), "ambiguous"),
        ),
        (
            "Q004",
            "Low",
            "find-callees",
            "What does predict_on_session call directly?",
            _expect_count(
                lambda kg: kg.find_callees("predict_on_session", path=batch_path, line=77, limit=10),
                "callee_count",
                5,
            ),
        ),
        (
            "Q005",
            "Low",
            "symbols-in-file",
            "Which symbols are defined in batch_predict.py?",
            _expect_count(lambda kg: kg.symbols_in_file(batch_path), "symbol_count", 1),
        ),
        (
            "Q007",
            "Low",
            "evidence-for-call",
            "Show evidence for predict_on_session -> build_features.",
            _expect_count(
                lambda kg: kg.evidence_for_call("predict_on_session", "build_features", path=batch_path, line=77),
                "match_count",
                1,
            ),
        ),
        (
            "Q009",
            "Low",
            "top-dependencies",
            "What are the top third-party dependencies?",
            _expect_list("top dependencies", lambda kg: kg.top_dependencies(limit=5), 1),
        ),
        (
            "Q013",
            "Low",
            "find-callers",
            "What are direct callers of write_result_on_disk?",
            _expect_count(lambda kg: kg.find_callers("write_result_on_disk", limit=5), "caller_count", 1),
        ),
        (
            "Q017",
            "Medium",
            "who-imports",
            "If openai_instructor changes, which modules import it?",
            _expect_status(lambda kg: kg.who_imports("mercury_ml.chatbot.apis.openai_instructor", limit=10), "resolved"),
        ),
        (
            "Q023",
            "Medium",
            "modules-importing-both",
            "Which modules combine pandas and sklearn?",
            _expect_status(lambda kg: kg.modules_importing_both("pandas", "sklearn", limit=10), "resolved"),
        ),
        (
            "Q026",
            "Medium",
            "dependency-path",
            "What dependency path connects predict_on_session to sklearn?",
            _expect_status(lambda kg: kg.dependency_path("predict_on_session", "sklearn", path=batch_path, line=77, limit=5), "resolved"),
        ),
    ]


def _true_loop_smoke_checks() -> list[tuple[str, str, str, str, CheckFn]]:
    response_path = "src/lib/response-generator.ts"
    return [
        (
            "Q005",
            "Low",
            "symbols-in-file",
            "Which symbols are defined in response-generator.ts?",
            _expect_count(lambda kg: kg.symbols_in_file(response_path), "symbol_count", 1),
        ),
        (
            "Q010",
            "Low",
            "lookup-symbol",
            "Find generateResponseStream.",
            _expect_status(lambda kg: kg.lookup_symbol("generateResponseStream", limit=5), "resolved"),
        ),
        (
            "Q026",
            "Medium",
            "dependency-path",
            "What dependency path connects generateResponseStream to @prisma/client?",
            _expect_status(lambda kg: kg.dependency_path("generateResponseStream", "@prisma/client", limit=5), "resolved"),
        ),
        (
            "Q032",
            "Medium",
            "endpoints",
            "What endpoints are visible in the TS/JS repo?",
            _expect_count(lambda kg: kg.endpoints(limit=10), "endpoint_fact_count", 1),
        ),
    ]


def _lattice_smoke_checks() -> list[tuple[str, str, str, str, CheckFn]]:
    return [
        (
            "Q082",
            "Medium",
            "domain-references",
            "Which clients reference api.shopagain.io?",
            _expect_count(lambda kg: kg.domain_references("api.shopagain.io", limit=100), "reference_count", 1),
        ),
        (
            "Q082",
            "Medium",
            "domain-references",
            "Which code locations read env vars that resolve to api.shopagain.io?",
            _expect_predicate_count(
                lambda kg: kg.domain_references("api.shopagain.io", limit=100),
                "references",
                "REFERENCES_ENV_VAR",
                1,
            ),
        ),
        (
            "Q083",
            "Medium",
            "endpoints",
            "Which token auth endpoints and callers are indexed?",
            _expect_count(lambda kg: kg.endpoints("/api/token", limit=100), "endpoint_fact_count", 1),
        ),
        (
            "Q088",
            "Goldset",
            "event-channels",
            "Which facts exist for la-prod-campaign-messages?",
            _expect_count(lambda kg: kg.event_channels("la-prod-campaign-messages", limit=100), "event_fact_count", 1),
        ),
        (
            "Q088",
            "Goldset",
            "event-channels",
            "Do ConfigParser-backed event facts carry source .ini citations?",
            _expect_source_ref_count(
                lambda kg: kg.event_channels("la-prod-email", limit=100),
                "event_channels",
                1,
            ),
        ),
        (
            "Q095",
            "Medium",
            "deploy-mappings",
            "Which deploy mapping serves prod_shopagain_wsgi.py?",
            _expect_count(lambda kg: kg.deploy_mappings("prod_shopagain_wsgi.py", limit=25), "mapping_count", 1),
        ),
    ]


def _expect_list(label: str, run: Callable[[KgSnapshot], list[JsonObject]], minimum: int) -> CheckFn:
    def check(kg: KgSnapshot) -> tuple[ValidationResult, str, JsonObject]:
        rows = run(kg)
        result = "pass" if len(rows) >= minimum else "fail"
        return result, f"{label}: {len(rows)} rows", {"row_count": len(rows), "sample": rows[:2]}

    return check


def _expect_status(run: Callable[[KgSnapshot], JsonObject], expected: str) -> CheckFn:
    def check(kg: KgSnapshot) -> tuple[ValidationResult, str, JsonObject]:
        actual = run(kg)
        status = str(actual.get("status"))
        result = "pass" if status == expected else "fail"
        return result, f"status `{status}`, expected `{expected}`", _compact_actual(actual)

    return check


def _expect_count(run: Callable[[KgSnapshot], JsonObject], field: str, minimum: int) -> CheckFn:
    def check(kg: KgSnapshot) -> tuple[ValidationResult, str, JsonObject]:
        actual = run(kg)
        if field == "match_count":
            count = len(actual.get("matches", [])) if isinstance(actual.get("matches"), list) else 0
        else:
            count = int(actual.get(field, 0))
        result = "pass" if count >= minimum else "fail"
        return result, f"{field}={count}, expected >= {minimum}", _compact_actual(actual)

    return check


def _expect_predicate_count(
    run: Callable[[KgSnapshot], JsonObject],
    row_key: str,
    predicate: str,
    minimum: int,
) -> CheckFn:
    def check(kg: KgSnapshot) -> tuple[ValidationResult, str, JsonObject]:
        actual = run(kg)
        rows = actual.get(row_key, [])
        if not isinstance(rows, list):
            rows = []
        count = sum(1 for row in rows if isinstance(row, dict) and row.get("predicate") == predicate)
        result = "pass" if count >= minimum else "fail"
        return result, f"{predicate}: {count} rows", {"predicate_count": count, "sample": rows[:2]}

    return check


def _expect_source_ref_count(
    run: Callable[[KgSnapshot], JsonObject],
    row_key: str,
    minimum: int,
) -> CheckFn:
    def check(kg: KgSnapshot) -> tuple[ValidationResult, str, JsonObject]:
        actual = run(kg)
        rows = actual.get(row_key, [])
        if not isinstance(rows, list):
            rows = []
        matching = [
            row
            for row in rows
            if isinstance(row, dict)
            and _row_source_refs(row)
        ]
        result = "pass" if len(matching) >= minimum else "fail"
        return result, f"source_refs: {len(matching)} rows", {"source_ref_count": len(matching), "sample": matching[:2]}

    return check


def _row_source_refs(row: JsonObject) -> object:
    qualifier = row.get("qualifier", {})
    if not isinstance(qualifier, dict):
        return None
    resolution = qualifier.get("resolution", {})
    if not isinstance(resolution, dict):
        return None
    return resolution.get("source_refs")


def _compact_actual(value: JsonObject) -> JsonObject:
    compact: JsonObject = {}
    for key in (
        "status",
        "caller_count",
        "callee_count",
        "symbol_count",
        "endpoint_fact_count",
        "reference_count",
        "event_fact_count",
        "mapping_count",
        "path_count",
        "returned_count",
    ):
        if key in value:
            compact[key] = value[key]
    if isinstance(value.get("matches"), list):
        compact["match_count"] = len(value["matches"])
    return compact


def _snapshot_inventory(corpus: str, snapshot_path: Path, kg: KgSnapshot) -> JsonObject:
    return {
        "corpus": corpus,
        "snapshot": _report_path(snapshot_path),
        "entities": len(kg.entities),
        "facts": len(kg.facts),
        "evidence": len(kg.evidence),
        "coverage": len(kg.coverage),
    }


def _goldset_summary(config: ValidationConfig) -> JsonObject:
    packets = _load_rows(config.goldset_packets, "packets")
    answers = _load_rows(config.goldset_answers, "answers")
    judgement_payload = json.loads(config.goldset_judgement.expanduser().read_text(encoding="utf-8"))
    if not isinstance(judgement_payload, dict):
        raise ValueError(f"{config.goldset_judgement} must contain an object with a 'judgements' list")
    judgements = judgement_payload.get("judgements")
    if not isinstance(judgements, list):
        raise ValueError(f"{config.goldset_judgement} must contain a 'judgements' list")

    packets_by_id = _rows_by_scenario(config.goldset_packets, packets, "packets")
    answers_by_id = _rows_by_scenario(config.goldset_answers, answers, "answers")
    judgement_rows = []
    judged_ids = set()
    for index, judgement in enumerate(judgements):
        if not isinstance(judgement, dict):
            raise ValueError(f"{config.goldset_judgement} judgements[{index}] must be an object")
        scenario_id = _scenario_id(config.goldset_judgement, "judgements", index, judgement)
        if scenario_id in judged_ids:
            raise ValueError(f"{config.goldset_judgement} judgements[{index}] duplicates scenario_id {scenario_id!r}")
        judged_ids.add(scenario_id)
        failure_owners = judgement.get("failure_owners", [])
        if not isinstance(failure_owners, list) or not all(isinstance(owner, str) for owner in failure_owners):
            raise ValueError(f"{config.goldset_judgement} judgements[{index}].failure_owners must be list[str]")
        packet = packets_by_id.get(scenario_id)
        answer = answers_by_id.get(scenario_id)
        artifact_status, artifact_issues = _goldset_artifact_consistency(packet, answer)
        judgement_rows.append(
            {
                "scenario_id": scenario_id,
                "evidence_completeness": judgement.get("evidence_completeness", "unknown"),
                "answer_score": judgement.get("answer_score", "unknown"),
                "failure_owners": failure_owners,
                "evidence_item_count": _list_count(packet.get("evidence_items")) if isinstance(packet, dict) else 0,
                "retrieval_step_count": _list_count(packet.get("retrieval_steps")) if isinstance(packet, dict) else 0,
                "self_score": answer.get("score") if isinstance(answer, dict) else None,
                "artifact_status": artifact_status,
                "artifact_issues": artifact_issues,
                "notes": _goldset_notes(judgement),
            }
        )

    answer_only = []
    for scenario_id, answer in sorted(answers_by_id.items()):
        if scenario_id in judged_ids:
            continue
        answer_only.append(
            {
                "scenario_id": scenario_id,
                "self_score": answer.get("score"),
                "notes": "No judgement ground truth available in PRODUCT-QUERY-SET.",
            }
        )
    packet_only = []
    for scenario_id in sorted(set(packets_by_id) - set(answers_by_id) - judged_ids):
        packet_only.append(
            {
                "scenario_id": scenario_id,
                "notes": "EvidencePacket exists but no synthesized answer or judgement row was found.",
            }
        )

    return {
        "packets_path": _report_path(config.goldset_packets),
        "answers_path": _report_path(config.goldset_answers),
        "judgement_path": _report_path(config.goldset_judgement),
        "scenario_count": len(judgement_rows),
        "answer_score_summary": _result_counts(judgement_rows, key="answer_score"),
        "evidence_summary": _result_counts(judgement_rows, key="evidence_completeness"),
        "artifact_summary": _result_counts(judgement_rows, key="artifact_status"),
        "failure_owner_summary": dict(sorted(Counter(owner for row in judgement_rows for owner in row["failure_owners"]).items())),
        "scenarios": judgement_rows,
        "answer_only_scenarios": answer_only,
        "packet_only_scenarios": packet_only,
    }


def _goldset_artifact_consistency(packet: object, answer: object) -> tuple[str, list[str]]:
    """Classify whether a judgement's answer was synthesized from the current packet.

    Fingerprint mismatches and count mismatches are both stale. Missing fingerprint or
    count metadata is unverified unless another field proves staleness.
    """
    if not isinstance(packet, dict):
        return "missing_packet", ["judgement scenario has no matching EvidencePacket row"]
    if not isinstance(answer, dict):
        return "missing_answer", ["judgement scenario has no matching synthesized answer row"]

    issues: list[str] = []
    mismatch_detected = False
    current_fingerprint = packet_fingerprint(packet)
    answer_fingerprint = answer.get("packet_fingerprint")
    if isinstance(answer_fingerprint, str) and answer_fingerprint.strip():
        if answer_fingerprint != current_fingerprint:
            mismatch_detected = True
            issues.append("answer packet_fingerprint does not match current packet fingerprint")
    else:
        issues.append("answer missing packet_fingerprint; content freshness cannot be verified")

    mismatch_detected |= _compare_count_metadata(
        issues,
        label="evidence_item_count",
        answer_count=answer.get("evidence_item_count"),
        current_count=_list_count(packet.get("evidence_items")),
    )
    mismatch_detected |= _compare_count_metadata(
        issues,
        label="retrieval_step_count",
        answer_count=answer.get("retrieval_step_count"),
        current_count=_list_count(packet.get("retrieval_steps")),
    )
    if not issues:
        return "current", []
    if mismatch_detected:
        return "stale", issues
    return "unverified", issues


def _compare_count_metadata(issues: list[str], label: str, answer_count: object, current_count: int) -> bool:
    if not isinstance(answer_count, int):
        issues.append(f"answer missing integer {label}; cannot verify packet freshness")
        return False
    if answer_count != current_count:
        issues.append(f"answer {label}={answer_count} does not match current packet {label}={current_count}")
        return True
    return False


def _failure_owner_summary(rows: list[JsonObject]) -> str:
    owners = Counter(owner for row in rows for owner in row.get("failure_owners", []) if owner != "none")
    if not owners:
        return ""
    return ", ".join(f"{owner}={count}" for owner, count in sorted(owners.items()))


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _load_rows(path: Path, key: str) -> list[JsonObject]:
    """Load either a root JSON list or an object containing the expected list key."""
    data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    rows = data.get(key) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a list or an object with a {key!r} list")
    return rows


def _report_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _rows_by_scenario(path: Path, rows: list[JsonObject], key: str) -> dict[str, JsonObject]:
    by_scenario: dict[str, JsonObject] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path} {key}[{index}] must be an object")
        scenario_id = _scenario_id(path, key, index, row)
        if scenario_id in by_scenario:
            raise ValueError(f"{path} {key}[{index}] duplicates scenario_id {scenario_id!r}")
        by_scenario[scenario_id] = row
    return by_scenario


def _scenario_id(path: Path, key: str, index: int, row: JsonObject) -> str:
    scenario_id = row.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError(f"{path} {key}[{index}] must include a non-empty scenario_id")
    return scenario_id.strip()


def _goldset_notes(judgement: JsonObject) -> str:
    summary = judgement.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip().replace("\n", " ")
    missing = judgement.get("missing_or_weak_evidence")
    if isinstance(missing, list) and missing:
        return "; ".join(str(item) for item in missing[:2])
    return "No judgement summary provided."


def _result_counts(rows: list[JsonObject], key: str = "result") -> JsonObject:
    return dict(sorted(Counter(str(row.get(key, "unknown")) for row in rows).items()))


def _overall_status(smoke_checks: list[JsonObject], goldset: JsonObject) -> str:
    smoke_failures = [row for row in smoke_checks if row.get("result") == "fail"]
    judged_failures = [
        row
        for row in goldset["scenarios"]
        if row.get("answer_score") == "Fail" and row.get("artifact_status") == "current"
    ]
    partials = [
        row
        for row in goldset["scenarios"]
        if row.get("answer_score") == "Partial" and row.get("artifact_status") == "current"
    ]
    artifact_issues = [row for row in goldset["scenarios"] if row.get("artifact_status") != "current"]
    unknown_scores = [
        row for row in goldset["scenarios"] if row.get("answer_score") not in {"Pass", "Partial", "Fail"}
    ]
    if smoke_failures or judged_failures:
        return "fail"
    if partials or artifact_issues or unknown_scores or goldset["answer_only_scenarios"] or goldset["packet_only_scenarios"]:
        return "partial"
    return "pass"


def _counts_sentence(counts: JsonObject, label: str = "Result counts") -> str:
    if not counts:
        return f"{label}: none."
    parts = [f"{name}={count}" for name, count in counts.items()]
    return f"{label}: " + ", ".join(parts) + "."


def _product_readout_lines(goldset: JsonObject, next_feature_recommendation: str) -> list[str]:
    passing = [
        str(row["scenario_id"])
        for row in goldset["scenarios"]
        if row.get("answer_score") == "Pass"
        and row.get("evidence_completeness") == "complete"
        and row.get("artifact_status") == "current"
    ]
    stale_or_unverified = [row for row in goldset["scenarios"] if row.get("artifact_status") != "current"]
    non_passing = [
        row
        for row in goldset["scenarios"]
        if row.get("answer_score") != "Pass" and row.get("artifact_status") == "current"
    ]
    lines = []
    if passing:
        lines.append(f"- KG-first answers pass independent judgement when indexed facts exist: {', '.join(passing)}.")
    else:
        lines.append("- No judged scenario currently has both complete evidence and a passing answer.")
    if stale_or_unverified:
        scenario_ids = ", ".join(str(row["scenario_id"]) for row in stale_or_unverified)
        lines.append(
            "- Artifact consistency blocks product-gap diagnosis for "
            f"{scenario_ids}; regenerate answers and judgement from the current EvidencePacket rows first."
        )
        pending_owner_summary = _failure_owner_summary(stale_or_unverified)
        if pending_owner_summary:
            lines.append(f"- Suspected failure owners pending re-judgement: {pending_owner_summary}.")
    if non_passing:
        owner_summary = _failure_owner_summary(non_passing)
        if owner_summary:
            lines.append(f"- Remaining judged failures are concentrated in: {owner_summary}.")
        else:
            lines.append("- Remaining judged failures do not have classified failure owners.")
    else:
        lines.append("- No current judged scenario failed or partially passed in this run.")
    lines.append(f"- Recommended next feature: {next_feature_recommendation}")
    return lines


def _md_table_cell(value: object) -> str:
    return str(value).replace("\n", " ").replace("|", r"\|")


def _code_md_table_cell(value: object) -> str:
    return _md_table_cell(f"`{value}`")


def _superseded_artifacts(evaluation_dir: Path) -> list[str]:
    active_files = {
        "CANONICAL-VALIDATION-REPORT.md",
        "PRODUCT-QUERY-SET.md",
        "README.md",
    }
    root = evaluation_dir.expanduser()
    if not root.exists():
        return []
    return sorted(
        f"{root.as_posix()}/{path.name}"
        for path in root.glob("*.md")
        if path.name not in active_files and _is_historical_evaluation_artifact(path.name)
    )


def _is_historical_evaluation_artifact(name: str) -> bool:
    return (
        "-RUN-" in name
        or "-RERUN-" in name
        or name.startswith("LATTICEAI-GOLDSET-")
        or name.startswith("NEXT-GAP-EVALUATION-")
        or name.startswith("CONTRACT-RECONCILIATION-REGRESSION-RUN-")
        or name.startswith("MULTI-REPO-LINKING-SMOKE-")
        or name.startswith("SYMBOL-QUERY-SURFACES-SMOKE-")
    )
