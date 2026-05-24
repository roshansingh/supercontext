from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VALID_WINNERS = {"mcp_off", "mcp_on", "tie"}
NON_WINNERS = {"mcp_off", "tie"}
RUBRIC_ASPECTS = ("correctness", "evidence", "completeness", "actionability")


@dataclass(frozen=True)
class RawArmEvidence:
    task_id: str
    run_group_id: str
    arm: str
    path: Path
    messages_path: Path | None
    mcp_tools_called: tuple[str, ...]
    non_mcp_tools_called: tuple[str, ...]
    mcp_tool_attempt_count: int
    non_mcp_tool_attempt_count: int


@dataclass(frozen=True)
class CaveatEvidence:
    task_id: str
    result: str
    classification: str
    summary: str


@dataclass(frozen=True)
class FocusedRerunEvidence:
    task_id: str
    judge_winner: str
    judge_confidence: float
    path: Path
    mcp_tools_called: tuple[str, ...] | None
    mcp_tool_attempt_count: int | None


@dataclass(frozen=True)
class PostPr119Evidence:
    status: str
    evidence: str


@dataclass(frozen=True)
class ClassifiedRow:
    task_id: str
    phase: str
    difficulty: str
    judge_winner: str
    judge_confidence: float
    aspect_winners: dict[str, str]
    mcp_tool_count_on: int
    non_mcp_tool_count_on: int | None
    raw_evidence_status: str
    mcp_tools_called: tuple[str, ...]
    non_mcp_tools_called: tuple[str, ...]
    raw_record_path: Path | None
    raw_messages_path: Path | None
    report_classification: str
    report_summary: str
    bucket: str
    note: str
    post_pr119_status: str | None = None
    post_pr119_evidence: str | None = None


@dataclass(frozen=True)
class ClassificationResult:
    report_json_path: Path
    raw_root: Path | None
    report_md_path: Path | None
    run_id: str
    report_sha256: str
    source_winner_counts: dict[str, int]
    non_wins: tuple[ClassifiedRow, ...]
    wins: tuple[ClassifiedRow, ...]


def classify_non_wins(
    report_json_path: Path,
    raw_root: Path | None = None,
    *,
    report_md_path: Path | None = None,
    post_pr119_paths: list[Path] | None = None,
) -> ClassificationResult:
    report = _load_report_json(report_json_path)
    rows = report["rows"]
    raw_records = _load_raw_records(raw_root) if raw_root is not None else {}
    caveats = _load_caveats(report_md_path) if report_md_path is not None else {}
    focused_reruns = _load_post_pr119(post_pr119_paths or [])

    source_winner_counts = {winner: 0 for winner in sorted(VALID_WINNERS)}
    classified_non_wins: list[ClassifiedRow] = []
    classified_wins: list[ClassifiedRow] = []
    report_task_ids = {row["task_id"] for row in rows}
    unknown_post_task_ids = sorted(set(focused_reruns) - report_task_ids)
    if unknown_post_task_ids:
        raise ValueError(f"Post-pr119 task_id not found in report rows: {', '.join(unknown_post_task_ids)}")
    for row in rows:
        winner = row["judge_winner"]
        source_winner_counts[winner] += 1
        classified = _classify_row(
            row,
            raw_records.get(row["task_id"]),
            caveats.get(row["task_id"]),
            focused_reruns.get(row["task_id"]),
        )
        if winner in NON_WINNERS:
            classified_non_wins.append(classified)
        else:
            classified_wins.append(classified)

    return ClassificationResult(
        report_json_path=report_json_path,
        raw_root=raw_root,
        report_md_path=report_md_path,
        run_id=_infer_run_id(report_json_path),
        report_sha256=_sha256(report_json_path),
        source_winner_counts=source_winner_counts,
        non_wins=tuple(classified_non_wins),
        wins=tuple(classified_wins),
    )


def render_markdown(result: ClassificationResult) -> str:
    lines = [
        f"# {result.run_id} Non-Win Classification",
        "",
        f"Generated from the sanitized {result.run_id} A/B report plus available local raw records.",
        "",
        "## Sources",
        "",
        f"- Report JSON: `{result.report_json_path}`",
        f"- Report JSON sha256: `{result.report_sha256}`",
        f"- Report Markdown: `{result.report_md_path}`" if result.report_md_path else "- Report Markdown: n/a",
        f"- Raw root: `{result.raw_root}`" if result.raw_root else "- Raw root: n/a",
        "",
        "## Baseline",
        "",
        "| Winner | Count |",
        "|---|---:|",
    ]
    for winner in ("mcp_off", "mcp_on", "tie"):
        lines.append(f"| `{winner}` | {result.source_winner_counts.get(winner, 0)} |")

    lines.extend(
        [
            "",
            "## Non-Win Rows",
            "",
            "| Task | Phase | Winner | Confidence | Raw | MCP Tools | Non-MCP Tools | Bucket | Post-pr119 |",
            "|---|---|---|---:|---|---:|---:|---|---|",
        ]
    )
    for row in result.non_wins:
        lines.append(
            "| {task} | {phase} | `{winner}` | {confidence} | {raw} | {mcp_count} | {non_mcp_count} | {bucket} | {post} |".format(
                task=row.task_id,
                phase=row.phase,
                winner=row.judge_winner,
                confidence=_format_number(row.judge_confidence),
                raw=row.raw_evidence_status,
                mcp_count=row.mcp_tool_count_on,
                non_mcp_count="n/a" if row.non_mcp_tool_count_on is None else row.non_mcp_tool_count_on,
                bucket=_escape_table(row.bucket),
                post=_escape_table(row.post_pr119_status or ""),
            )
        )

    lines.extend(["", "## Non-Win Evidence", ""])
    for row in result.non_wins:
        lines.extend(_row_evidence_lines(row))

    lines.extend(
        [
            "## Win Inventory",
            "",
            "| Task | Phase | Confidence | MCP Tool Count | Raw |",
            "|---|---|---:|---:|---|",
        ]
    )
    for row in result.wins:
        lines.append(
            f"| {row.task_id} | {row.phase} | {_format_number(row.judge_confidence)} | "
            f"{row.mcp_tool_count_on} | {row.raw_evidence_status} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_markdown(result: ClassificationResult, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(result), encoding="utf-8")


def _classify_row(
    row: dict[str, Any],
    raw: RawArmEvidence | None,
    caveat: CaveatEvidence | None,
    focused_rerun: FocusedRerunEvidence | None,
) -> ClassifiedRow:
    tool_health = row["mcp_on_tool_health"]
    mcp_tool_count = _require_int(tool_health.get("attempts"), f"{row['task_id']}.mcp_on_tool_health.attempts")
    raw_status = "available" if raw is not None else "missing"
    report_classification = caveat.classification if caveat is not None else ""
    report_summary = caveat.summary if caveat is not None else ""
    post = _derive_post_pr119_evidence(row["judge_winner"], focused_rerun)
    return ClassifiedRow(
        task_id=row["task_id"],
        phase=row["phase"],
        difficulty=row["difficulty"],
        judge_winner=row["judge_winner"],
        judge_confidence=_require_number(row["judge_confidence"], f"{row['task_id']}.judge_confidence"),
        aspect_winners=dict(row["judge_aspect_winners"]),
        mcp_tool_count_on=mcp_tool_count,
        non_mcp_tool_count_on=raw.non_mcp_tool_attempt_count if raw is not None else None,
        raw_evidence_status=raw_status,
        mcp_tools_called=raw.mcp_tools_called if raw is not None else (),
        non_mcp_tools_called=raw.non_mcp_tools_called if raw is not None else (),
        raw_record_path=raw.path if raw is not None else None,
        raw_messages_path=raw.messages_path if raw is not None else None,
        report_classification=report_classification,
        report_summary=report_summary,
        bucket=report_classification,
        note=report_summary,
        post_pr119_status=post.status if post is not None else None,
        post_pr119_evidence=post.evidence if post is not None else None,
    )


def _load_report_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Report JSON path is not a file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Report JSON must be an object")
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Report JSON must contain rows list")
    seen_task_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"rows[{index}] must be an object")
        _validate_report_row(row, f"rows[{index}]")
        task_id = row["task_id"]
        if task_id in seen_task_ids:
            raise ValueError(f"Duplicate report task_id: {task_id}")
        seen_task_ids.add(task_id)
    return data


def _validate_report_row(row: dict[str, Any], label: str) -> None:
    for field in ("task_id", "phase", "difficulty", "judge_winner"):
        _require_clean_string(row.get(field), f"{label}.{field}")
    winner = row["judge_winner"]
    if winner not in VALID_WINNERS:
        raise ValueError(f"{label}.judge_winner unsupported value: {winner!r}")
    _require_number(row.get("judge_confidence"), f"{label}.judge_confidence")
    aspects = row.get("judge_aspect_winners")
    if not isinstance(aspects, dict):
        raise ValueError(f"{label}.judge_aspect_winners must be an object")
    for aspect in RUBRIC_ASPECTS:
        value = aspects.get(aspect)
        if value not in VALID_WINNERS:
            raise ValueError(f"{label}.judge_aspect_winners.{aspect} unsupported value: {value!r}")
    health = row.get("mcp_on_tool_health")
    if not isinstance(health, dict):
        raise ValueError(f"{label}.mcp_on_tool_health must be an object")
    for field in ("attempts", "denials", "errors", "successes"):
        _require_int(health.get(field), f"{label}.mcp_on_tool_health.{field}")


def _load_raw_records(raw_root: Path) -> dict[str, RawArmEvidence]:
    if not raw_root.exists():
        raise ValueError(f"Raw root does not exist: {raw_root}")
    if not raw_root.is_dir():
        raise ValueError(f"Raw root is not a directory: {raw_root}")
    by_task: dict[str, RawArmEvidence] = {}
    by_group: dict[str, dict[str, RawArmEvidence]] = {}
    for record_path in sorted(raw_root.glob("*/mcp_*/record.json")):
        record = _load_raw_arm(record_path)
        group = by_group.setdefault(record.run_group_id, {})
        if record.arm in group:
            raise ValueError(f"Duplicate raw {record.arm} record for run group {record.run_group_id}")
        group[record.arm] = record
        if record.arm == "mcp_on":
            if record.task_id in by_task:
                raise ValueError(f"Duplicate mcp_on raw record for task_id: {record.task_id}")
            by_task[record.task_id] = record

    for run_group_id, arms in by_group.items():
        if "mcp_on" in arms and "mcp_off" in arms and arms["mcp_on"].task_id != arms["mcp_off"].task_id:
            raise ValueError(
                "Mismatched task_id in run group "
                f"{run_group_id}: mcp_on={arms['mcp_on'].task_id}, mcp_off={arms['mcp_off'].task_id}"
            )
    return by_task


def _load_raw_arm(path: Path) -> RawArmEvidence:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Raw record must be an object: {path}")
    task_id = _require_clean_string(data.get("task_id"), f"{path}.task_id")
    run_group_id = _require_clean_string(data.get("run_group_id"), f"{path}.run_group_id")
    arm = _require_clean_string(data.get("arm"), f"{path}.arm")
    if arm not in {"mcp_on", "mcp_off"}:
        raise ValueError(f"{path}.arm unsupported value: {arm!r}")
    mcp_tools = _require_string_list(data.get("mcp_tools_called"), f"{path}.mcp_tools_called")
    non_mcp_tools = _require_string_list(data.get("non_mcp_tools_called"), f"{path}.non_mcp_tools_called")
    messages_path = path.with_name("messages.jsonl")
    return RawArmEvidence(
        task_id=task_id,
        run_group_id=run_group_id,
        arm=arm,
        path=path,
        messages_path=messages_path if messages_path.is_file() else None,
        mcp_tools_called=tuple(mcp_tools),
        non_mcp_tools_called=tuple(non_mcp_tools),
        mcp_tool_attempt_count=_require_int(data.get("mcp_tool_attempt_count"), f"{path}.mcp_tool_attempt_count"),
        non_mcp_tool_attempt_count=_require_int(
            data.get("non_mcp_tool_attempt_count"), f"{path}.non_mcp_tool_attempt_count"
        ),
    )


def _load_caveats(path: Path) -> dict[str, CaveatEvidence]:
    if not path.is_file():
        raise ValueError(f"Report Markdown path is not a file: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    caveats: dict[str, CaveatEvidence] = {}
    in_table = False
    for line in lines:
        if _is_caveat_header(line):
            in_table = True
            continue
        if not in_table:
            continue
        if _is_markdown_separator_row(line):
            continue
        if not line.startswith("|"):
            if caveats:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            raise ValueError(f"Malformed caveat table row in {path}: {line}")
        task_id = _strip_markdown_code(cells[0])
        _require_clean_string(task_id, f"{path}.caveat.task_id")
        if task_id in caveats:
            raise ValueError(f"Duplicate caveat task_id: {task_id}")
        caveats[task_id] = CaveatEvidence(
            task_id=task_id,
            result=_strip_markdown_code(cells[1]),
            classification=cells[2],
            summary=cells[3],
        )
    if not caveats:
        raise ValueError(f"No caveat table rows found in {path}")
    return caveats


def _load_post_pr119(paths: list[Path]) -> dict[str, FocusedRerunEvidence]:
    evidence: dict[str, FocusedRerunEvidence] = {}
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Post-pr119 path is not a file: {path}")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} must be an object")
            task_id = _require_clean_string(row.get("task_id"), f"{path}:{line_number}.task_id")
            winner = row.get("judge_winner")
            if winner not in VALID_WINNERS:
                raise ValueError(f"{path}:{line_number}.judge_winner unsupported value: {winner!r}")
            confidence = _require_number(row.get("judge_confidence"), f"{path}:{line_number}.judge_confidence")
            on = row.get("on")
            on_record = on if isinstance(on, dict) else {}
            mcp_tools = on_record.get("mcp_tools_called")
            mcp_attempts = on_record.get("mcp_tool_attempt_count")
            if mcp_tools is not None:
                _require_string_list(mcp_tools, f"{path}:{line_number}.on.mcp_tools_called")
            if mcp_attempts is not None:
                _require_int(mcp_attempts, f"{path}:{line_number}.on.mcp_tool_attempt_count")
            if task_id in evidence:
                raise ValueError(f"Duplicate post-pr119 task_id: {task_id}")
            evidence[task_id] = FocusedRerunEvidence(
                task_id=task_id,
                judge_winner=winner,
                judge_confidence=confidence,
                path=path,
                mcp_tools_called=tuple(mcp_tools) if mcp_tools is not None else None,
                mcp_tool_attempt_count=mcp_attempts if mcp_attempts is not None else None,
            )
    return evidence


def _row_evidence_lines(row: ClassifiedRow) -> list[str]:
    lines = [
        f"### {row.task_id}",
        "",
        f"- Result: `{row.judge_winner}` with confidence {_format_number(row.judge_confidence)}.",
        f"- Report classification: {row.report_classification or 'n/a'}.",
        f"- Report summary: {row.report_summary or 'n/a'}",
        f"- Raw evidence status: `{row.raw_evidence_status}`.",
    ]
    if row.raw_record_path is not None:
        lines.append(f"- Raw record: `{row.raw_record_path}`.")
    if row.raw_messages_path is not None:
        lines.append(f"- Raw messages: `{row.raw_messages_path}`.")
    lines.append(f"- MCP tools called: {_format_list(row.mcp_tools_called)}.")
    lines.append(f"- Non-MCP tools called: {_format_list(row.non_mcp_tools_called)}.")
    if row.post_pr119_evidence:
        lines.append(f"- Post-pr119 evidence: {row.post_pr119_evidence}.")
    lines.append("")
    return lines


def _derive_post_pr119_evidence(
    historical_winner: str, focused_rerun: FocusedRerunEvidence | None
) -> PostPr119Evidence | None:
    if focused_rerun is None:
        return None
    status = _post_pr119_status(historical_winner, focused_rerun.judge_winner)
    summary_parts = [
        f"{focused_rerun.path}: judge_winner={focused_rerun.judge_winner}",
        f"judge_confidence={focused_rerun.judge_confidence}",
    ]
    if focused_rerun.mcp_tools_called is not None:
        summary_parts.append(f"on.mcp_tools_called={list(focused_rerun.mcp_tools_called)}")
    if focused_rerun.mcp_tool_attempt_count is not None:
        summary_parts.append(f"on.mcp_tool_attempt_count={focused_rerun.mcp_tool_attempt_count}")
    return PostPr119Evidence(status=status, evidence="; ".join(summary_parts))


def _post_pr119_status(historical_winner: str, focused_winner: str) -> str:
    if historical_winner == "mcp_off" and focused_winner == "mcp_on":
        return "fixed_win"
    if historical_winner == "mcp_off" and focused_winner == "tie":
        return "fixed_tie"
    if historical_winner == "tie" and focused_winner == "mcp_on":
        return "promoted_win"
    return f"focused_{focused_winner}"


def _is_caveat_header(line: str) -> bool:
    if not line.startswith("|"):
        return False
    cells = [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
    return cells[:4] == ["task", "result", "classification", "what happened"]


def _is_markdown_separator_row(line: str) -> bool:
    if not line.startswith("|"):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":"} and "-" in cell for cell in cells)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _infer_run_id(report_json_path: Path) -> str:
    if report_json_path.name == "ab-report.json" and report_json_path.parent.name:
        return report_json_path.parent.name
    return report_json_path.stem


def _strip_markdown_code(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2:
        return stripped[1:-1]
    return stripped


def _require_clean_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if not value:
        raise ValueError(f"{label} must be non-empty")
    if value != value.strip():
        raise ValueError(f"{label} must not have padded whitespace")
    return value


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_require_clean_string(item, f"{label}[{index}]"))
    return result


def _require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if value < 0:
        raise ValueError(f"{label} must be non-negative")
    return value


def _require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _format_number(value: float) -> str:
    return f"{value:g}"


def _format_list(values: tuple[str, ...]) -> str:
    if not values:
        return "none"
    return ", ".join(f"`{value}`" for value in values)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|")
