from pathlib import Path
import pytest

from conftest import _make_model
from tff.core.config import FitnessFunctionsConfig
from tff.core.rules.ban_select_star import BanSelectStar


@pytest.mark.parametrize(
    ("path", "query", "is_symbolic", "expect_violation"),
    [
        ("models/marts/my_model.sql", "SELECT * FROM table", False, True),
        ("models/core/my_model.sql", "SELECT a.*, b.id FROM a JOIN b", False, True),
        ("models/sources/my_model.sql", "SELECT * FROM table", False, False),
        ("models/marts/compliant_model.sql", "SELECT col1, col2 FROM table", False, False),
        ("models/marts/symbolic_model.sql", "SELECT * FROM table", True, False),
        ("models/marts/count_model.sql", "SELECT COUNT(*), COUNT(DISTINCT *) FROM table GROUP BY col1", False, False),
        ("models/marts/sub_star_model.sql", "SELECT COUNT((SELECT * FROM table))", False, True),
    ],
)
def test_ban_select_star_rule(path: str, query: str, is_symbolic: bool, expect_violation: bool) -> None:
    config = FitnessFunctionsConfig()
    config.rules.ban_select_star.enabled = True
    config.rules.ban_select_star.skip_layers = ["sources"]
    rule = BanSelectStar(config=config)

    model = _make_model(name=Path(path).stem, path=path, query=query, is_symbolic=is_symbolic, dialect="bigquery")
    violation = rule.check_model(model)
    if expect_violation:
        assert violation is not None
        assert "SELECT * is prohibited" in violation.violation_msg[0]
    else:
        assert violation is None


def test_ban_select_star_disk_read(tmp_path: Path) -> None:
    config = FitnessFunctionsConfig()
    config.rules.ban_select_star.enabled = True
    rule = BanSelectStar(config=config)

    sql_file = tmp_path / "models" / "marts" / "model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM table", encoding="utf-8")
    model = _make_model(name="marts.disk_model", path=str(sql_file), query=None, dialect="bigquery")
    assert rule.check_model(model) is not None


@pytest.mark.parametrize(
    "model_kwargs",
    [
        {"path": "non_existent_file.sql", "query": None},
        {"query": "SELECT * FROM (invalid syntax"},
    ],
)
def test_ban_select_star_error_paths(model_kwargs: dict) -> None:
    config = FitnessFunctionsConfig()
    config.rules.ban_select_star.enabled = True
    rule = BanSelectStar(config=config)

    model = _make_model(name="marts.err_model", dialect="bigquery", **model_kwargs)
    assert rule.check_model(model) is None
