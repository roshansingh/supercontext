from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable

import yaml


DEFAULT_QUERY_SET = Path("docs/evaluation/PRODUCT-QUERY-SET.md")
SUPPORTED_DIFFICULTIES = {"Low", "Medium", "Hard"}
SUPPORTED_PHASES = {"planning", "coding", "review"}


@dataclass(frozen=True)
class CorpusRow:
    task_id: str
    difficulty: str
    tool_surface: str
    persona: str
    fixture: str
    user_question: str
    expected_answer_shape: str
    capabilities: str
    golden: str | None = None


@dataclass(frozen=True)
class EvalTask:
    row: CorpusRow
    phase: str
    note: str = ""

    @property
    def task_id(self) -> str:
        return self.row.task_id

    @property
    def difficulty(self) -> str:
        return self.row.difficulty

    @property
    def prompt(self) -> str:
        return self.row.user_question

    @property
    def fixture(self) -> str:
        return self.row.fixture


def parse_query_set(path: str | Path = DEFAULT_QUERY_SET) -> list[CorpusRow]:
    query_set = Path(path)
    if not query_set.is_file():
        raise ValueError(f"Query set file does not exist: {query_set}")

    lines = query_set.read_text(encoding="utf-8").splitlines()
    low_goldens = _parse_low_goldens(lines)
    rows: list[CorpusRow] = []
    seen: set[str] = set()
    for line in lines:
        cells = _markdown_cells(line)
        if len(cells) < 8:
            continue
        task_id = _clean(cells[0])
        difficulty = _clean(cells[1])
        if not _is_task_id(task_id) or difficulty not in SUPPORTED_DIFFICULTIES:
            continue
        if task_id in seen:
            raise ValueError(f"Duplicate product-query task ID: {task_id}")
        seen.add(task_id)

        golden = low_goldens.get(task_id)
        if len(cells) >= 10 and _clean(cells[8]).casefold() == "yes":
            golden = _clean(cells[9]) or golden

        rows.append(
            CorpusRow(
                task_id=task_id,
                difficulty=difficulty,
                tool_surface=_clean(cells[2]),
                persona=_clean(cells[3]),
                fixture=_clean(cells[4]),
                user_question=_clean(cells[5]),
                expected_answer_shape=_clean(cells[6]),
                capabilities=_clean(cells[7]),
                golden=golden,
            )
        )

    if not rows:
        raise ValueError(f"No product-query rows found in {query_set}")
    return rows


def default_v1_tasks(
    *,
    query_set_path: str | Path = DEFAULT_QUERY_SET,
    manifest_path: str | Path | None = None,
    seed: int = 0,
) -> list[EvalTask]:
    del seed
    rows_by_id = {row.task_id: row for row in parse_query_set(query_set_path)}
    manifest_rows = _load_default_manifest(manifest_path)
    tasks: list[EvalTask] = []
    seen: set[str] = set()
    for index, manifest_row in enumerate(manifest_rows, start=1):
        task_id = _required_string(manifest_row, "id", row_number=index)
        phase = _required_string(manifest_row, "phase", row_number=index)
        note = _optional_string(manifest_row, "note", row_number=index)
        if not _is_task_id(task_id):
            raise ValueError(f"default-v1 row {index} has invalid task ID: {task_id!r}")
        if task_id in seen:
            raise ValueError(f"default-v1 manifest has duplicate task ID: {task_id}")
        if phase not in SUPPORTED_PHASES:
            raise ValueError(f"default-v1 row {index} has unsupported phase: {phase!r}")
        if task_id not in rows_by_id:
            raise ValueError(f"default-v1 task {task_id} does not exist in query set")
        seen.add(task_id)
        tasks.append(EvalTask(row=rows_by_id[task_id], phase=phase, note=note))

    _validate_default_distribution(tasks)
    return tasks


def task_distribution(tasks: Iterable[EvalTask | CorpusRow]) -> dict[str, int]:
    return dict(Counter(task.difficulty for task in tasks))


def _load_default_manifest(path: str | Path | None) -> list[dict[str, object]]:
    if path is None:
        data = resources.files("source.kg.eval").joinpath("default_v1_tasks.yaml").read_text(encoding="utf-8")
    else:
        manifest_path = Path(path)
        if not manifest_path.is_file():
            raise ValueError(f"default-v1 manifest does not exist: {manifest_path}")
        data = manifest_path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(data)
    if not isinstance(loaded, dict):
        raise ValueError("default-v1 manifest must be a mapping")
    rows = loaded.get("tasks")
    if not isinstance(rows, list):
        raise ValueError("default-v1 manifest requires a list field: tasks")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"default-v1 row {index} must be a mapping")
    return rows


def _validate_default_distribution(tasks: list[EvalTask]) -> None:
    if len(tasks) != 18:
        raise ValueError(f"default-v1 requires exactly 18 tasks, found {len(tasks)}")
    expected = {"Low": 4, "Medium": 6, "Hard": 8}
    actual = task_distribution(tasks)
    if actual != expected:
        raise ValueError(f"default-v1 distribution must be {expected}, found {actual}")


def _parse_low_goldens(lines: list[str]) -> dict[str, str]:
    goldens: dict[str, str] = {}
    for line in lines:
        cells = _markdown_cells(line)
        if len(cells) != 2:
            continue
        task_id = _clean(cells[0])
        if _is_task_id(task_id):
            goldens[task_id] = _clean(cells[1])
    return goldens


def _markdown_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _clean(value: object) -> str:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        text = text[1:-1].strip()
    return text.replace("`", "")


def _is_task_id(value: str) -> bool:
    return len(value) == 4 and value[0] == "Q" and value[1:].isdigit()


def _required_string(row: dict[str, object], field: str, *, row_number: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"default-v1 row {row_number} requires non-empty string field: {field}")
    return value.strip()


def _optional_string(row: dict[str, object], field: str, *, row_number: int) -> str:
    value = row.get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"default-v1 row {row_number} field {field} must be a string")
    return value.strip()
