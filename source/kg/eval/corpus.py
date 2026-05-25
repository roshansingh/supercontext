from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
import re
from typing import Iterable

import yaml


DEFAULT_QUERY_SET = Path("docs/evaluation/PRODUCT-QUERY-SET.md")
SUPPORTED_DIFFICULTIES = {"Low", "Medium", "Hard"}
SUPPORTED_PHASES = {"planning", "coding", "review"}
FIXTURE_VARIABLE_PATTERN = re.compile(r"\$[A-Z][A-Z0-9_]*")


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
    fixture_input: str = ""
    fixture_bindings: tuple[tuple[str, str], ...] = ()

    @property
    def task_id(self) -> str:
        return self.row.task_id

    @property
    def difficulty(self) -> str:
        return self.row.difficulty

    @property
    def prompt(self) -> str:
        return _bind_text(self.row.user_question, self.fixture_bindings)

    @property
    def fixture(self) -> str:
        return _bind_text(self.row.fixture, self.fixture_bindings)

    @property
    def expected_answer_shape(self) -> str:
        return _bind_text(self.row.expected_answer_shape, self.fixture_bindings)


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
    fixture_overrides_path: str | Path | None = None,
    seed: int = 0,
) -> list[EvalTask]:
    del seed
    query_set = Path(query_set_path)
    rows_by_id = {row.task_id: row for row in parse_query_set(query_set)}
    fixture_defaults = fixture_defaults_from_query_set(query_set)
    manifest_rows = _load_default_manifest(manifest_path)
    fixture_overrides = _load_fixture_overrides(fixture_overrides_path)
    tasks: list[EvalTask] = []
    seen: set[str] = set()
    for index, manifest_row in enumerate(manifest_rows, start=1):
        task_id = _required_string(manifest_row, "id", row_number=index)
        phase = _required_string(manifest_row, "phase", row_number=index)
        note = _optional_string(manifest_row, "note", row_number=index)
        override_row = fixture_overrides.get(task_id, {})
        fixture_input = (
            _optional_string(override_row, "fixture_input", row_number=index)
            or _optional_string(manifest_row, "fixture_input", row_number=index)
        )
        manifest_fixture_bindings = _optional_fixture_bindings(manifest_row, row_number=index)
        override_fixture_bindings = _optional_fixture_bindings(override_row, row_number=index)
        if not _is_task_id(task_id):
            raise ValueError(f"default-v1 row {index} has invalid task ID: {task_id!r}")
        if task_id in seen:
            raise ValueError(f"default-v1 manifest has duplicate task ID: {task_id}")
        if phase not in SUPPORTED_PHASES:
            raise ValueError(f"default-v1 row {index} has unsupported phase: {phase!r}")
        if task_id not in rows_by_id:
            raise ValueError(f"default-v1 task {task_id} does not exist in query set")
        seen.add(task_id)
        row = rows_by_id[task_id]
        fixture_bindings = _fixture_bindings(row, fixture_defaults | manifest_fixture_bindings | override_fixture_bindings)
        tasks.append(
            EvalTask(
                row=row,
                phase=phase,
                note=note,
                fixture_input=fixture_input,
                fixture_bindings=fixture_bindings,
            )
        )

    unused_overrides = sorted(set(fixture_overrides) - seen)
    if unused_overrides:
        raise ValueError(f"default-v1 fixture override task(s) are not in the manifest: {', '.join(unused_overrides)}")
    _validate_default_distribution(tasks)
    return tasks


def task_distribution(tasks: Iterable[EvalTask | CorpusRow]) -> dict[str, int]:
    return dict(Counter(task.difficulty for task in tasks))


def fixture_defaults_from_query_set(path: str | Path = DEFAULT_QUERY_SET) -> dict[str, str]:
    query_set = Path(path)
    if not query_set.is_file():
        raise ValueError(f"Query set file does not exist: {query_set}")
    defaults: dict[str, str] = {}
    header: list[str] | None = None
    for raw_line in query_set.read_text(encoding="utf-8").splitlines():
        cells = _markdown_cells(raw_line)
        if not cells:
            header = None
            continue
        normalized = [_normalize_header(cell) for cell in cells]
        if "variable" in normalized and "mercury v0 value" in normalized:
            header = normalized
            continue
        if header is None or len(cells) != len(header):
            continue
        row = dict(zip(header, cells, strict=True))
        variable = _clean(row.get("variable", ""))
        concrete_value = _concrete_fixture_value(row.get("mercury v0 value", ""))
        if _is_fixture_variable(variable) and concrete_value is not None:
            defaults[variable] = concrete_value
    return defaults


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


def _load_fixture_overrides(path: str | Path | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    override_path = Path(path)
    if not override_path.is_file():
        raise ValueError(f"default-v1 fixture overrides file does not exist: {override_path}")
    loaded = yaml.safe_load(override_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("default-v1 fixture overrides must be a mapping")
    rows = loaded.get("tasks")
    if not isinstance(rows, list):
        raise ValueError("default-v1 fixture overrides require a list field: tasks")
    overrides: dict[str, dict[str, object]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"default-v1 fixture override row {index} must be a mapping")
        task_id = _required_string(row, "id", row_number=index)
        if not _is_task_id(task_id):
            raise ValueError(f"default-v1 fixture override row {index} has invalid task ID: {task_id!r}")
        if task_id in overrides:
            raise ValueError(f"default-v1 fixture overrides have duplicate task ID: {task_id}")
        overrides[task_id] = {
            "id": task_id,
            "fixture_input": _optional_string(row, "fixture_input", row_number=index),
            "fixture_bindings": _optional_fixture_bindings(row, row_number=index),
        }
    return overrides


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
    if text.count("`") == 2 and len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        text = text[1:-1].strip()
    elif "," in text:
        parts = [part.strip() for part in text.split(",")]
        if all(part.count("`") == 2 and part.startswith("`") and part.endswith("`") for part in parts):
            text = ", ".join(part[1:-1].strip() for part in parts)
    return text


def _normalize_header(value: str) -> str:
    return " ".join(_clean(value).casefold().split())


def _is_fixture_variable(value: str) -> bool:
    return bool(FIXTURE_VARIABLE_PATTERN.fullmatch(value))


def _concrete_fixture_value(value: object) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    if text.count("`") == 2 and text[0] == "`" and text[-1] == "`":
        cleaned = _clean(text)
        return cleaned if cleaned else None
    if "`" in text:
        return None
    cleaned = _clean(text)
    return cleaned if cleaned else None


def _fixture_bindings(row: CorpusRow, fixture_defaults: dict[str, str]) -> tuple[tuple[str, str], ...]:
    bindings = dict(fixture_defaults)
    for text in (row.fixture, row.user_question, row.expected_answer_shape, row.capabilities):
        for assignment in _fixture_assignments(text):
            bindings.update(assignment)
    used_variables = sorted(
        set(
            variable
            for text in (row.fixture, row.user_question, row.expected_answer_shape, row.capabilities)
            for variable in FIXTURE_VARIABLE_PATTERN.findall(text)
        )
    )
    return tuple((variable, bindings[variable]) for variable in used_variables if variable in bindings)


def _fixture_assignments(text: str) -> list[dict[str, str]]:
    assignments: list[dict[str, str]] = []
    for token in _fixture_tokens(text):
        if "=" not in token:
            continue
        name, value = token.split("=", 1)
        name = _clean(name)
        value = _clean(value)
        if _is_fixture_variable(name) and value:
            assignments.append({name: value})
    return assignments


def _fixture_tokens(text: str) -> list[str]:
    tokens = []
    previous_assignment: str | None = None
    for part in text.split(","):
        cleaned = _clean(part)
        if cleaned.startswith("$"):
            tokens.append(cleaned)
            previous_assignment = cleaned if "=" in cleaned else None
        elif previous_assignment is not None and cleaned:
            raise ValueError(
                f"fixture assignment {previous_assignment!r} contains a comma; "
                "put comma-containing values in fixture_bindings instead"
            )
        else:
            previous_assignment = None
    return tokens


def _bind_text(text: str, bindings: tuple[tuple[str, str], ...]) -> str:
    bound = text
    for variable, value in bindings:
        bound = bound.replace(variable, value)
    return bound


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


def _optional_fixture_bindings(row: dict[str, object], *, row_number: int) -> dict[str, str]:
    value = row.get("fixture_bindings", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"default-v1 row {row_number} field fixture_bindings must be a mapping")
    bindings: dict[str, str] = {}
    for raw_variable, raw_bound_value in value.items():
        if not isinstance(raw_variable, str) or not _is_fixture_variable(raw_variable):
            raise ValueError(f"default-v1 row {row_number} fixture binding key must be a fixture variable")
        if not isinstance(raw_bound_value, str) or not raw_bound_value.strip():
            raise ValueError(f"default-v1 row {row_number} fixture binding {raw_variable} must be a non-empty string")
        bindings[raw_variable] = raw_bound_value.strip()
    return bindings
