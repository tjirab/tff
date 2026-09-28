import os
import sys
import pytest

os.environ.setdefault("MAX_FORK_WORKERS", "1")


@pytest.fixture(autouse=True)
def clean_sys_path():
    orig_path = list(sys.path)
    orig_meta_path = list(sys.meta_path)
    orig_path_importer_cache = dict(sys.path_importer_cache)
    yield
    sys.path[:] = orig_path
    sys.meta_path[:] = orig_meta_path
    sys.path_importer_cache.clear()
    sys.path_importer_cache.update(orig_path_importer_cache)


try:
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding, Severity

    def _make_finding(
        check: str = "banselectstar",
        severity: Severity = "error",
        message: str = "Rule violation",
        model: str | None = None,
        path: str | None = None,
        line: int | None = None,
        col: int | None = None,
        end_line: int | None = None,
        end_col: int | None = None,
        msg: str | None = None,
        **kwargs,
    ) -> LintFinding:
        if msg is not None:
            message = msg
        return LintFinding(
            check=check,
            severity=severity,
            message=message,
            model=model,
            path=path,
            line=line,
            col=col,
            end_line=end_line,
            end_col=end_col,
            **kwargs,
        )

    def _make_model(
        name: str = "test_model",
        path: str = "models/test_model.sql",
        dialect: str = "duckdb",
        is_symbolic: bool = False,
        is_external: bool = False,
        **kwargs,
    ) -> ModelRepresentation:
        return ModelRepresentation(
            name=name,
            path=path,
            dialect=dialect,
            is_symbolic=is_symbolic,
            is_external=is_external,
            **kwargs,
        )
except ImportError:
    pass
