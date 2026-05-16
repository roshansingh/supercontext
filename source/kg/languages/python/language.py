from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.adapters.legacy import LEGACY_PYTHON_AST_ADAPTER
from source.kg.extraction.adapters.python_boto3_transport import PYTHON_BOTO3_TRANSPORT_ADAPTER
from source.kg.extraction.framework.adapter import Adapter, ExtractionContext
from source.kg.languages.known_stacks import load_known_stacks
from source.kg.languages.python.files import LANGUAGE_FILES, PythonLanguageFiles


@dataclass(frozen=True)
class PythonLanguageSupport:
    files: PythonLanguageFiles = LANGUAGE_FILES

    @property
    def name(self) -> str:
        return self.files.name

    @property
    def aliases(self) -> tuple[str, ...]:
        return self.files.aliases

    @property
    def file_extensions(self) -> frozenset[str]:
        return self.files.file_extensions

    @property
    def manifest_files(self) -> frozenset[str]:
        return self.files.manifest_files

    def matches_file(self, path: Path) -> bool:
        return self.files.matches_file(path)

    def source_roots(self, repo: RepoSnapshot, ctx: ExtractionContext) -> dict[str, set[str]]:
        return {"python": ctx.python_import_roots}

    def adapters(self) -> tuple[Adapter, ...]:
        return (LEGACY_PYTHON_AST_ADAPTER, PYTHON_BOTO3_TRANSPORT_ADAPTER)

    def known_stacks(self) -> dict[str, dict[str, str]]:
        return {"python": dict(_known_stack_imports())}


LANGUAGE_SUPPORT = PythonLanguageSupport()


@cache
def _known_stack_imports() -> dict[str, str]:
    # Static package metadata: read once per process and return copies above.
    return load_known_stacks(Path(__file__).with_name("known_stacks.yaml"))
