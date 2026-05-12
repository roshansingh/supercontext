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
READOUT_UNRUN_DISPLAY_CAP = 8
CANONICAL_FAILURE_OWNERS = (
    "missing KG fact",
    "bad retrieval plan",
    "bad synthesis",
    "bad ground truth",
    "coverage gap",
)
NO_FAILURE_OWNER = "none"
PRODUCT_QUERY_UNMEASURED_REASON = "No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet."
DEFAULT_NEXT_FEATURE_RECOMMENDATION = (
    "Use the current judgement rows as the source of truth: if any scenario is Partial or Fail, prioritize the "
    "classified failure owners before expanding scope; if all judged scenarios pass, expand judged goldset coverage "
    "or add harder scenarios."
)


@dataclass(frozen=True)
class ValidationConfig:
    mercury_snapshot: Path
    true_loop_snapshot: Path
    private_snapshot: Path
    goldset_packets: Path
    goldset_answers: Path
    goldset_judgement: Path
    generated_at: str
    product_query_set: Path | None = Path("docs/evaluation/PRODUCT-QUERY-SET.md")
    evaluation_dir: Path = Path("docs/evaluation")
    strict_smoke_checks: bool = True
    private_smoke_fixtures: Path = Path("examples/private-goldset/smoke_fixtures.json")
    next_feature_recommendation: str = DEFAULT_NEXT_FEATURE_RECOMMENDATION


def default_generated_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_canonical_validation(config: ValidationConfig) -> JsonObject:
    mercury = KgSnapshot(config.mercury_snapshot)
    true_loop = KgSnapshot(config.true_loop_snapshot)
    private_kg = KgSnapshot(config.private_snapshot)
    private_smoke_fixtures = _load_private_smoke_fixtures(config.private_smoke_fixtures)
    smoke_checks = _run_smoke_checks(
        [
            ("Mercury ML", config.mercury_snapshot, mercury, _mercury_smoke_checks()),
            ("True Loop", config.true_loop_snapshot, true_loop, _true_loop_smoke_checks()),
            ("Private Goldset", config.private_snapshot, private_kg, _private_fixture_smoke_checks(private_smoke_fixtures)),
        ],
        strict=config.strict_smoke_checks,
    )
    goldset = _goldset_summary(config)
    product_query_matrix = _product_query_matrix(config.product_query_set, smoke_checks, goldset)
    return {
        "generated_at": config.generated_at,
        "status": _overall_status(smoke_checks, goldset),
        "quality_status": _quality_status(smoke_checks, goldset),
        "coverage_status": _coverage_status(goldset),
        "inputs": _validation_inputs(config),
        "snapshot_inventory": [
            _snapshot_inventory("Mercury ML", config.mercury_snapshot, mercury),
            _snapshot_inventory("True Loop", config.true_loop_snapshot, true_loop),
            _snapshot_inventory("Private Goldset", config.private_snapshot, private_kg),
        ],
        "deterministic_smoke": {
            "summary": _result_counts(smoke_checks),
            "checks": smoke_checks,
        },
        "goldset": goldset,
        "product_query_matrix": product_query_matrix,
        "supersedes": _superseded_artifacts(config.evaluation_dir),
        "next_feature_recommendation": config.next_feature_recommendation,
    }


def _validation_inputs(config: ValidationConfig) -> JsonObject:
    inputs = {
        "mercury_snapshot": _report_path(config.mercury_snapshot),
        "true_loop_snapshot": _report_path(config.true_loop_snapshot),
        "private_snapshot": _report_path(config.private_snapshot),
        "goldset_packets": _report_path(config.goldset_packets),
        "goldset_answers": _report_path(config.goldset_answers),
        "goldset_judgement": _report_path(config.goldset_judgement),
    }
    if config.product_query_set is not None:
        inputs["product_query_set"] = _report_path(config.product_query_set)
    return inputs


def render_validation_markdown(report: JsonObject) -> str:
    lines = [
        "# Canonical Product Validation Report",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Overall status: **{report['status']}**",
        f"Quality status: **{report.get('quality_status', report['status'])}**",
        f"Coverage status: **{report.get('coverage_status', report['status'])}**",
        "",
        "This is the current canonical validation report for low/medium deterministic surfaces and the private goldset. "
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
    planned_scenario_count = int(goldset.get("planned_scenario_count", 0) or 0)
    planned_judged_count = int(goldset.get("planned_judged_count", 0) or 0)
    lines.extend(
        [
            "",
            "## Private Goldset",
            "",
            _counts_sentence(goldset["answer_score_summary"], label="Answer scores"),
            "",
            _counts_sentence(goldset["evidence_summary"], label="Evidence completeness"),
            "",
            _counts_sentence(goldset["artifact_summary"], label="Artifact consistency"),
        ]
    )
    if planned_scenario_count:
        lines.extend(
            [
                "",
                f"Goldset plan coverage: {planned_judged_count} judged / {planned_scenario_count} planned.",
            ]
        )
    lines.extend(
        [
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
    unrun_planned_scenarios = goldset.get("unrun_planned_scenarios", [])
    if unrun_planned_scenarios:
        lines.extend(["", "Planned goldset scenarios not yet judged:"])
        for row in unrun_planned_scenarios[:READOUT_UNRUN_DISPLAY_CAP]:
            lines.append(f"- `{row['scenario_id']}`: {row['user_query']}")
        remaining_count = len(unrun_planned_scenarios) - READOUT_UNRUN_DISPLAY_CAP
        if remaining_count > 0:
            lines.append(f"- ...and {remaining_count} more planned scenario(s).")
    judged_but_not_planned_scenarios = goldset.get("judged_but_not_planned_scenarios", [])
    if judged_but_not_planned_scenarios:
        lines.extend(["", "Judged scenarios not marked as planned goldset:"])
        for scenario_id in judged_but_not_planned_scenarios:
            lines.append(f"- `{scenario_id}`")

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


def render_product_query_matrix_markdown(report: JsonObject) -> str:
    matrix = report["product_query_matrix"]
    lines = [
        "# Product Query Set Run",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Product query set: `{matrix['product_query_set'] or 'disabled'}`",
        "",
        "This report is the Debate 12 Step 1 measurement matrix. It records every product query as measured or "
        "`unmeasured` without pretending unsupported surfaces have an executable harness.",
        "",
        "## Summary",
        "",
        f"- Unique queries: {matrix['query_count']}",
        f"- Query/corpus tuples: {matrix['tuple_count']}",
        f"- Measured queries: {matrix['measured_query_count']} / {matrix['query_count']}",
        f"- Unmeasured queries: {matrix['unmeasured_query_count']} / {matrix['query_count']}",
        f"- Measured query coverage: {matrix['measured_query_coverage_pct']}%",
        f"- Current harness sources: {', '.join(matrix['harness_sources']) if matrix['harness_sources'] else 'none'}",
        "",
        _counts_sentence(matrix["status_summary"], label="Status counts"),
        "",
        _counts_sentence(matrix["difficulty_summary"], label="Difficulty counts"),
        "",
        "## Failure Owners",
        "",
        _counts_sentence(matrix["failure_owner_summary"], label="Failure-owner counts"),
        "",
        "| Failure owner | Query/corpus tuples |",
        "|---|---:|",
    ]
    for owner, count in matrix["failure_owner_summary"].items():
        lines.append(f"| {_md_table_cell(owner)} | {count} |")

    lines.extend(
        [
            "",
            "## Matrix",
            "",
            "| ID | Difficulty | Corpus | Status | Failure Owner | Harness | Notes |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in matrix["rows"]:
        lines.append(
            f"| {_md_table_cell(row['query_id'])} | {_md_table_cell(row['difficulty'])} | "
            f"{_md_table_cell(row['corpus'])} | {_md_table_cell(row['status'])} | "
            f"{_md_table_cell(', '.join(row['failure_owners']))} | {_md_table_cell(row['harness'])} | "
            f"{_md_table_cell(row['notes'])} |"
        )

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


def _private_fixture_smoke_checks(fixture: JsonObject | None) -> list[tuple[str, str, str, str, CheckFn]]:
    if fixture is None:
        return []
    domain = _fixture_string(fixture, "api_domain")
    token_path = _fixture_string(fixture, "token_endpoint_path")
    primary_channel = _fixture_string(fixture, "primary_event_channel")
    source_ref_channel = _fixture_string(fixture, "source_ref_event_channel")
    return [
        (
            "Q082",
            "Medium",
            "domain-references",
            "Which clients reference the private API domain fixture?",
            _expect_count(lambda kg: kg.domain_references(domain, limit=100), "reference_count", 1),
        ),
        (
            "Q082",
            "Medium",
            "domain-references",
            "Which code locations read env vars that resolve to the private API domain fixture?",
            _expect_predicate_count(
                lambda kg: kg.domain_references(domain, limit=100),
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
            _expect_count(lambda kg: kg.endpoints(token_path, limit=100), "endpoint_fact_count", 1),
        ),
        (
            "Q088",
            "Goldset",
            "event-channels",
            "Which facts exist for the primary private event-channel fixture?",
            _expect_count(lambda kg: kg.event_channels(primary_channel, limit=100), "event_fact_count", 1),
        ),
        (
            "Q088",
            "Goldset",
            "event-channels",
            "Do ConfigParser-backed event facts carry source .ini citations?",
            _expect_source_ref_count(
                lambda kg: kg.event_channels(source_ref_channel, limit=100),
                "event_channels",
                1,
            ),
        ),
    ]


def _load_private_smoke_fixtures(path: Path) -> JsonObject | None:
    fixture_path = path.expanduser()
    if not fixture_path.exists():
        return None
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{fixture_path} must contain a JSON object")
    fixture = payload.get("private_smoke")
    if not isinstance(fixture, dict):
        raise ValueError(f"{fixture_path} must contain an object field 'private_smoke'")
    return fixture


def _fixture_string(fixture: JsonObject, key: str) -> str:
    value = fixture.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"private smoke fixture field {key!r} must be a non-empty string")
    return value


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
    planned = _planned_goldset_scenarios(config.product_query_set)
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
    planned_by_id = {row["scenario_id"]: row for row in planned}
    unrun_planned = [
        planned_by_id[scenario_id]
        for scenario_id in sorted(set(planned_by_id) - judged_ids)
    ]
    judged_but_not_planned = sorted(judged_ids - set(planned_by_id)) if config.product_query_set else []

    return {
        "packets_path": _report_path(config.goldset_packets),
        "answers_path": _report_path(config.goldset_answers),
        "judgement_path": _report_path(config.goldset_judgement),
        "planned_path": _report_path(config.product_query_set) if config.product_query_set else None,
        "planned_scenario_count": len(planned),
        "planned_judged_count": len(set(planned_by_id) & judged_ids),
        "unrun_planned_scenarios": unrun_planned,
        "judged_but_not_planned_scenarios": judged_but_not_planned,
        "scenario_count": len(judgement_rows),
        "answer_score_summary": _result_counts(judgement_rows, key="answer_score"),
        "evidence_summary": _result_counts(judgement_rows, key="evidence_completeness"),
        "artifact_summary": _result_counts(judgement_rows, key="artifact_status"),
        "failure_owner_summary": dict(sorted(Counter(owner for row in judgement_rows for owner in row["failure_owners"]).items())),
        "scenarios": judgement_rows,
        "answer_only_scenarios": answer_only,
        "packet_only_scenarios": packet_only,
    }


def _planned_goldset_scenarios(path: Path | None) -> list[JsonObject]:
    if path is None:
        return []
    query_set_path = path.expanduser()
    if not query_set_path.exists():
        raise FileNotFoundError(f"Product query set not found: {query_set_path}")
    planned: list[JsonObject] = []
    seen: set[str] = set()
    header: list[str] | None = None
    matched_goldset_table = False
    for raw_line in query_set_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            header = None
            continue
        cells = _split_markdown_table_row(line)
        if not cells:
            header = None
            continue
        if _is_markdown_separator_row(cells):
            continue
        normalized_cells = [_normalize_table_header(cell) for cell in cells]
        if "id" in normalized_cells and "goldset?" in normalized_cells:
            header = normalized_cells
            matched_goldset_table = True
            continue
        if header is None or len(cells) != len(header):
            continue
        row = dict(zip(header, cells, strict=True))
        if row.get("goldset?", "").strip().lower() != "yes":
            continue
        scenario_id = row.get("id", "").strip()
        if not scenario_id:
            continue
        if scenario_id in seen:
            raise ValueError(f"{query_set_path} contains duplicate planned goldset scenario ID {scenario_id!r}")
        seen.add(scenario_id)
        planned.append(
            {
                "scenario_id": scenario_id,
                "difficulty": row.get("difficulty", "").strip(),
                "surface": row.get("surface", "").strip(),
                "persona": row.get("persona", "").strip(),
                "scope": row.get("scope", "").strip(),
                "user_query": row.get("user query", "").strip(),
            }
        )
    if not matched_goldset_table:
        raise ValueError(f"{query_set_path} does not contain a markdown table with ID and Goldset? columns")
    return planned


def _product_query_matrix(path: Path | None, smoke_checks: list[JsonObject], goldset: JsonObject) -> JsonObject:
    query_rows = _product_query_rows(path)
    if path is None:
        return {
            "product_query_set": None,
            "query_count": 0,
            "tuple_count": 0,
            "measured_query_count": 0,
            "unmeasured_query_count": 0,
            "measured_query_coverage_pct": 0.0,
            "harness_sources": [],
            "status_summary": {},
            "difficulty_summary": {},
            "failure_owner_summary": _matrix_failure_owner_summary([]),
            "rows": [],
        }
    query_by_id = {str(row["query_id"]): row for row in query_rows}
    measured_rows = _aggregate_product_query_rows(_measured_product_query_rows(smoke_checks, goldset))
    measured_tuples = {(str(row["query_id"]), str(row["corpus"])) for row in measured_rows}
    rows = measured_rows
    for query in query_rows:
        for unmeasured_row in _unmeasured_product_query_rows(query):
            key = (str(unmeasured_row["query_id"]), str(unmeasured_row["corpus"]))
            if key not in measured_tuples:
                rows.append(unmeasured_row)
    rows = [_enrich_product_query_matrix_row(row, query_by_id.get(str(row["query_id"]))) for row in rows]
    rows = sorted(rows, key=lambda row: (str(row["query_id"]), str(row["corpus"]), str(row["harness"])))
    query_ids = {str(row["query_id"]) for row in query_rows}
    measured_query_ids = {str(row["query_id"]) for row in rows if row["status"] != "unmeasured"}
    unmeasured_query_ids = query_ids - measured_query_ids
    return {
        "product_query_set": _report_path(path) if path else None,
        "query_count": len(query_rows),
        "tuple_count": len(rows),
        "measured_query_count": len(measured_query_ids),
        "unmeasured_query_count": len(unmeasured_query_ids),
        "measured_query_coverage_pct": _coverage_percentage(len(measured_query_ids), len(query_rows)),
        "harness_sources": _matrix_harness_sources(rows),
        "status_summary": _result_counts(rows, key="status"),
        "difficulty_summary": _result_counts(query_rows, key="difficulty"),
        "failure_owner_summary": _matrix_failure_owner_summary(rows),
        "rows": rows,
    }


def _enrich_product_query_matrix_row(row: JsonObject, query: JsonObject | None) -> JsonObject:
    if query is None:
        return row
    enriched = dict(row)
    if not enriched.get("difficulty") or enriched.get("difficulty") not in {"Low", "Medium", "Hard"}:
        enriched["difficulty"] = query.get("difficulty", "")
    enriched["surface"] = query.get("surface", "")
    enriched["persona"] = query.get("persona", "")
    enriched["fixture"] = query.get("fixture", "")
    enriched["user_query"] = query.get("user_query", "")
    enriched["expected_answer_shape"] = query.get("expected_answer_shape", "")
    enriched["capabilities"] = query.get("capabilities", "")
    enriched["goldset"] = query.get("goldset", False)
    return enriched


def _matrix_harness_sources(rows: list[JsonObject]) -> list[str]:
    sources = set()
    for row in rows:
        for source in str(row.get("harness", "")).split(","):
            source = source.strip()
            if source and source != "none":
                sources.add(source)
    return sorted(sources)


def _product_query_rows(path: Path | None) -> list[JsonObject]:
    if path is None:
        return []
    query_set_path = path.expanduser()
    if not query_set_path.exists():
        raise FileNotFoundError(f"Product query set not found: {query_set_path}")
    rows: list[JsonObject] = []
    seen: set[str] = set()
    header: list[str] | None = None
    matched_query_table = False
    for raw_line in query_set_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            header = None
            continue
        cells = _split_markdown_table_row(line)
        if not cells:
            header = None
            continue
        if _is_markdown_separator_row(cells):
            continue
        normalized_cells = [_normalize_table_header(cell) for cell in cells]
        if "id" in normalized_cells and "difficulty" in normalized_cells:
            header = normalized_cells
            matched_query_table = True
            continue
        if header is None or len(cells) != len(header):
            continue
        row = dict(zip(header, cells, strict=True))
        query_id = row.get("id", "").strip()
        difficulty = row.get("difficulty", "").strip()
        if not query_id.startswith("Q") or difficulty not in {"Low", "Medium", "Hard"}:
            continue
        if query_id in seen:
            raise ValueError(f"{query_set_path} contains duplicate product query ID {query_id!r}")
        seen.add(query_id)
        rows.append(
            {
                "query_id": query_id,
                "difficulty": difficulty,
                "surface": row.get("tool / surface", row.get("surface", "")).strip(),
                "persona": row.get("persona", "").strip(),
                "fixture": row.get("fixture", row.get("scope", "")).strip(),
                "user_query": row.get("user question", row.get("user query", "")).strip(),
                "expected_answer_shape": row.get("expected answer shape", "").strip(),
                "capabilities": row.get("main capabilities exercised", row.get("capability tested", "")).strip(),
                "goldset": row.get("goldset?", "").strip().lower() == "yes",
            }
        )
    if not matched_query_table:
        raise ValueError(f"{query_set_path} does not contain a markdown table with ID and Difficulty columns")
    if not rows:
        raise ValueError(f"{query_set_path} does not contain any valid product query rows")
    return rows


def _measured_product_query_rows(smoke_checks: list[JsonObject], goldset: JsonObject) -> list[JsonObject]:
    grouped_smoke: dict[tuple[str, str], list[JsonObject]] = {}
    for row in smoke_checks:
        key = (str(row["query_id"]), str(row["corpus"]))
        grouped_smoke.setdefault(key, []).append(row)

    measured = [
        _product_query_row_from_smoke(query_id, corpus, rows)
        for (query_id, corpus), rows in grouped_smoke.items()
    ]
    measured.extend(_product_query_row_from_judgement(row) for row in goldset.get("scenarios", []))
    return measured


def _aggregate_product_query_rows(rows: list[JsonObject]) -> list[JsonObject]:
    grouped: dict[tuple[str, str], list[JsonObject]] = {}
    for row in rows:
        grouped.setdefault((str(row["query_id"]), str(row["corpus"])), []).append(row)
    return [
        _merge_product_query_matrix_rows(grouped_rows)
        for grouped_rows in grouped.values()
    ]


def _merge_product_query_matrix_rows(rows: list[JsonObject]) -> JsonObject:
    first = rows[0]
    status = _aggregate_matrix_status([str(row["status"]) for row in rows])
    failure_owners = sorted(
        {
            owner
            for row in rows
            for owner in row.get("failure_owners", [])
            if owner != NO_FAILURE_OWNER
        }
    )
    return {
        **first,
        "status": status,
        "failure_owners": failure_owners or [NO_FAILURE_OWNER],
        "harness": ", ".join(sorted({str(row["harness"]) for row in rows})),
        "notes": "; ".join(str(row.get("notes", "")).strip() for row in rows if str(row.get("notes", "")).strip()),
        "sources": [source for row in rows for source in row.get("sources", [])],
    }


def _product_query_row_from_smoke(query_id: str, corpus: str, rows: list[JsonObject]) -> JsonObject:
    statuses = [str(row.get("result", "fail")) for row in rows]
    status = _aggregate_matrix_status(statuses)
    return {
        "query_id": query_id,
        "difficulty": _first_non_empty(row.get("difficulty") for row in rows),
        "corpus": corpus,
        "status": status,
        "failure_owners": _failure_owners_for_status(status, "deterministic smoke"),
        "harness": "deterministic smoke",
        "notes": "; ".join(str(row.get("notes", "")).strip() for row in rows if str(row.get("notes", "")).strip()),
        "sources": [_report_path(Path(str(row.get("snapshot", "")))) for row in rows if row.get("snapshot")],
    }


def _product_query_row_from_judgement(row: JsonObject) -> JsonObject:
    answer_score = str(row.get("answer_score", "unknown"))
    status = {
        "Pass": "pass",
        "Partial": "partial",
        "Fail": "fail",
    }.get(answer_score, "fail")
    failure_owners = row.get("failure_owners", [])
    if not _is_valid_failure_owner_list(failure_owners):
        failure_owners = _failure_owners_for_status(status, "goldset judgement")
    return {
        "query_id": row["scenario_id"],
        "difficulty": "",
        "corpus": "Private Goldset",
        "status": status,
        "failure_owners": failure_owners,
        "harness": "goldset judgement",
        "notes": str(row.get("notes", "")).strip(),
        "sources": [],
    }


def _unmeasured_product_query_rows(query: JsonObject) -> list[JsonObject]:
    return [
        {
            "query_id": query["query_id"],
            "difficulty": query["difficulty"],
            "corpus": corpus,
            "status": "unmeasured",
            "failure_owners": ["coverage gap"],
            "harness": "none",
            "notes": PRODUCT_QUERY_UNMEASURED_REASON,
            "sources": [],
        }
        for corpus in _corpus_labels_for_query(query)
    ]


def _corpus_labels_for_query(query: JsonObject) -> list[str]:
    fixture = str(query.get("fixture", "")).lower()
    if "both fixture orgs" in fixture:
        return ["llm-app-stack", "otel-demo"]
    if "llm-app-stack" in fixture:
        return ["llm-app-stack"]
    if "otel-demo" in fixture:
        return ["otel-demo"]
    if _query_id_number(query.get("query_id")) >= 81:
        return ["Private Goldset"]
    if "$py_repo" in fixture or "$broken_file" in fixture or "$entry_symbol" in fixture or "$caller_symbol" in fixture:
        return ["Mercury ML"]
    if "pr input" in fixture:
        return ["PR fixture"]
    return ["Unspecified fixture"]


def _query_id_number(value: object) -> int:
    text = str(value or "")
    if not text.startswith("Q"):
        return 0
    suffix = text[1:]
    if not suffix.isdigit():
        return 0
    return int(suffix)


def _aggregate_matrix_status(statuses: list[str]) -> str:
    if not statuses:
        return "unmeasured"
    if "fail" in statuses:
        return "fail"
    if "partial" in statuses:
        return "partial"
    if "refused correctly" in statuses:
        return "refused correctly"
    if all(status == "pass" for status in statuses):
        return "pass"
    return "fail"


def _failure_owners_for_status(status: str, harness: str) -> list[str]:
    if status in {"pass", "refused correctly"}:
        return [NO_FAILURE_OWNER]
    if status == "unmeasured":
        return ["coverage gap"]
    if harness == "deterministic smoke":
        return ["missing KG fact"]
    return ["coverage gap"]


def _is_valid_failure_owner_list(value: object) -> bool:
    valid_owners = set(CANONICAL_FAILURE_OWNERS) | {NO_FAILURE_OWNER}
    return (
        isinstance(value, list)
        and all(isinstance(owner, str) for owner in value)
        and all(owner in valid_owners for owner in value)
    )


def _matrix_failure_owner_summary(rows: list[JsonObject]) -> JsonObject:
    counts = Counter(
        owner
        for row in rows
        for owner in row["failure_owners"]
        if owner != NO_FAILURE_OWNER
    )
    return {owner: counts.get(owner, 0) for owner in CANONICAL_FAILURE_OWNERS}


def _first_non_empty(values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _coverage_percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _split_markdown_table_row(line: str) -> list[str]:
    cells = []
    current: list[str] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line) and line[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current).strip())
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _is_markdown_separator_row(cells: list[str]) -> bool:
    return all(cell and set(cell.replace(":", "").replace("-", "")) <= {" "} for cell in cells)


def _normalize_table_header(value: str) -> str:
    return value.strip().lower().replace("`", "")


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
    owners = Counter(owner for row in rows for owner in row.get("failure_owners", []) if owner != NO_FAILURE_OWNER)
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
    quality_status = _quality_status(smoke_checks, goldset)
    coverage_status = _coverage_status(goldset)
    if quality_status == "fail":
        return "fail"
    if quality_status == "partial" or coverage_status == "partial":
        return "partial"
    return "pass"


def _quality_status(smoke_checks: list[JsonObject], goldset: JsonObject) -> str:
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
    if (
        partials
        or artifact_issues
        or unknown_scores
        or goldset["answer_only_scenarios"]
        or goldset["packet_only_scenarios"]
    ):
        return "partial"
    return "pass"


def _coverage_status(goldset: JsonObject) -> str:
    if goldset.get("unrun_planned_scenarios") or goldset.get("judged_but_not_planned_scenarios"):
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
    unrun = goldset.get("unrun_planned_scenarios", [])
    planned_count = int(goldset.get("planned_scenario_count", 0) or 0)
    if unrun and planned_count:
        visible_unrun = unrun[:READOUT_UNRUN_DISPLAY_CAP]
        lines.append(
            f"- Product-validation breadth is incomplete: {planned_count - len(unrun)}/{planned_count} planned "
            f"goldset scenarios have judgement rows; next run should cover "
            f"{', '.join(row['scenario_id'] for row in visible_unrun)}"
            f"{'...' if len(unrun) > READOUT_UNRUN_DISPLAY_CAP else ''}."
        )
    judged_but_not_planned = goldset.get("judged_but_not_planned_scenarios", [])
    if judged_but_not_planned:
        lines.append(
            "- Goldset metadata drift: judged scenarios not marked `Goldset? = Yes` in the query set: "
            f"{', '.join(str(row) for row in judged_but_not_planned)}."
        )
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
    if not name.endswith(".md"):
        return False
    return _has_iso_date_stamp(Path(name).stem) or _has_legacy_historical_marker(name)


def _has_iso_date_stamp(value: str) -> bool:
    parts = value.split("-")
    for index in range(len(parts) - 2):
        candidate = "-".join(parts[index : index + 3])
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
        except ValueError:
            continue
        return True
    return False


def _has_legacy_historical_marker(name: str) -> bool:
    if name.endswith("-SCENARIO-AUDIT.md"):
        return False
    return (
        "-RUN-" in name
        or "-RERUN-" in name
        or "-GOLDSET-" in name
        or name.startswith("NEXT-GAP-EVALUATION-")
        or name.startswith("CONTRACT-RECONCILIATION-REGRESSION-RUN-")
        or name.startswith("MULTI-REPO-LINKING-SMOKE-")
        or name.startswith("SYMBOL-QUERY-SURFACES-SMOKE-")
    )
