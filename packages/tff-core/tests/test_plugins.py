"""Unit tests for plugin discovery, entry points, and dynamic loading."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tff.core.adapter import PipelineAdapter, _REGISTERED_ADAPTERS, get_adapter, register_adapter
from tff.core.model import ModelRepresentation
from tff.core.plugins import (
    discover_adapter_entry_points,
    discover_rule_entry_points,
    extract_and_register_from_module,
    load_plugin_module_or_file,
    load_plugins,
)
from tff.core.registry import CheckDefinition, CheckRegistry
from tff.core.rules.base import Rule, RuleViolation


class SampleRule(Rule):
    """Sample rule docstring."""
    name = "sample_rule"
    category = "Custom Category"
    default_severity = "warning"
    aliases = ("sample_alias",)

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        if model.name == "bad":
            return self.violation("bad model")
        return None


class SampleAdapter(PipelineAdapter):
    @property
    def provider_name(self) -> str:
        return "sample_engine"

    def is_applicable(self, project_root: Path) -> bool:
        return (project_root / "sample_engine.yml").exists()

    def load_models(self, project_root: Path, dialect=None, manifest_path=None):
        return {}

    def run_checks(self, project_root: Path, config, checks=None, dialect=None, manifest_path=None, models=None):
        return [], 0, []


def test_discover_rule_entry_points():
    reg = CheckRegistry()

    sample_rule = SampleRule()
    model_mock = MagicMock()
    model_mock.name = "bad"
    assert sample_rule.check_model(model_mock) is not None
    model_mock.name = "good"
    assert sample_rule.check_model(model_mock) is None

    sample_adapter = SampleAdapter()
    assert sample_adapter.provider_name == "sample_engine"
    assert sample_adapter.is_applicable(Path("/nonexistent")) is False
    assert sample_adapter.load_models(Path("/nonexistent")) == {}
    assert sample_adapter.run_checks(Path("/nonexistent"), None) == ([], 0, [])

    ep_rule = MagicMock()
    ep_rule.name = "ep_rule"
    ep_rule.load.return_value = SampleRule

    ep_check_def = MagicMock()
    ep_check_def.name = "ep_check_def"
    chk_def = CheckDefinition(id="ep_check_def", label="EP Check", category="Custom", scope="model")
    ep_check_def.load.return_value = chk_def

    ep_callable_single = MagicMock()
    ep_callable_single.name = "ep_callable_single"
    chk_single = CheckDefinition(id="ep_single", label="Single", category="Custom", scope="dag")
    ep_callable_single.load.return_value = lambda r: chk_single

    ep_callable_multi = MagicMock()
    ep_callable_multi.name = "ep_callable_multi"
    chk_multi = [CheckDefinition(id="ep_multi_1", label="Multi 1", category="Custom", scope="dag")]
    ep_callable_multi.load.return_value = lambda r: chk_multi

    ep_fail = MagicMock()
    ep_fail.name = "ep_fail"
    ep_fail.load.side_effect = RuntimeError("Failed to load")

    with patch("importlib.metadata.entry_points", return_value=[ep_rule, ep_check_def, ep_callable_single, ep_callable_multi, ep_fail]):
        discovered = discover_rule_entry_points(registry=reg, raise_errors=False)
        assert len(discovered) == 4
        assert reg.get("ep_rule") is not None
        assert reg.get("ep_check_def") is not None
        assert reg.get("ep_single") is not None
        assert reg.get("ep_multi_1") is not None

    # Test raise_errors=True
    with patch("importlib.metadata.entry_points", return_value=[ep_fail]):
        with pytest.raises(RuntimeError, match="Failed to load"):
            discover_rule_entry_points(registry=reg, raise_errors=True)

    # Test exception querying entry points
    with patch("importlib.metadata.entry_points", side_effect=Exception("EP Query Error")):
        assert discover_rule_entry_points(registry=reg) == []

    # Test default registry fallback
    with patch("importlib.metadata.entry_points", return_value=[]):
        assert discover_rule_entry_points(registry=None) == []


def test_discover_adapter_entry_points():
    ep_adapter = MagicMock()
    ep_adapter.name = "mock_provider"
    ep_adapter.load.return_value = SampleAdapter

    ep_fail = MagicMock()
    ep_fail.name = "fail_provider"
    ep_fail.load.side_effect = RuntimeError("Broken adapter")

    with patch("importlib.metadata.entry_points", return_value=[ep_adapter, ep_fail]):
        discovered = discover_adapter_entry_points(raise_errors=False)
        assert "mock_provider" in discovered
        assert discovered["mock_provider"] is SampleAdapter
        assert isinstance(get_adapter("mock_provider"), SampleAdapter)

    with patch("importlib.metadata.entry_points", return_value=[ep_fail]):
        with pytest.raises(RuntimeError, match="Broken adapter"):
            discover_adapter_entry_points(raise_errors=True)

    with patch("importlib.metadata.entry_points", side_effect=Exception("Adapter EP error")):
        assert discover_adapter_entry_points() == {}


def test_extract_and_register_from_module():
    reg = CheckRegistry()

    # Create dummy module object
    class DummyModule:
        __name__ = "dummy_module"

        class InternalRule(Rule):
            __module__ = "dummy_module"
            name = "internal_rule"

        class InternalAdapter(PipelineAdapter):
            __module__ = "dummy_module"
            provider_name = "internal_engine"

            def is_applicable(self, project_root: Path) -> bool:
                return False

            def load_models(self, project_root: Path, dialect=None, manifest_path=None):
                return {}

            def run_checks(self, project_root: Path, config, checks=None, dialect=None, manifest_path=None, models=None):
                return [], 0, []

        check_def_instance = CheckDefinition(
            id="standalone_check", label="Standalone", category="Test", scope="dag"
        )

        @staticmethod
        def register(registry):
            return [CheckDefinition(id="hook_check", label="Hook Check", category="Test", scope="dag")]

        @staticmethod
        def register_adapters():
            register_adapter("hook_adapter", SampleAdapter)

    assert len(extract_and_register_from_module(DummyModule, reg)) >= 3
    assert reg.get("internal_rule") is not None
    assert reg.get("standalone_check") is not None
    assert reg.get("hook_check") is not None
    assert isinstance(get_adapter("internal_engine"), DummyModule.InternalAdapter)
    assert isinstance(get_adapter("hook_adapter"), SampleAdapter)

    internal_adapter = DummyModule.InternalAdapter()
    assert internal_adapter.is_applicable(Path("/nonexistent")) is False
    assert internal_adapter.load_models(Path("/nonexistent")) == {}
    assert internal_adapter.run_checks(Path("/nonexistent"), None) == ([], 0, [])

    # Test register_rules hook
    class RegisterRulesModule:
        __name__ = "rules_module"

        @staticmethod
        def register_rules(registry):
            return [CheckDefinition(id="rules_hook_check", label="Rules Hook", category="Test", scope="dag")]

    assert len(extract_and_register_from_module(RegisterRulesModule, reg)) == 1
    assert reg.get("rules_hook_check") is not None

    # Test register hook returning single CheckDefinition
    class RegisterSingleModule:
        __name__ = "single_module"

        @staticmethod
        def register(registry):
            return CheckDefinition(id="single_hook_check", label="Single Hook", category="Test", scope="dag")

    assert len(extract_and_register_from_module(RegisterSingleModule, reg)) == 1
    assert reg.get("single_hook_check") is not None

    # Test adapter with property provider_name
    class PropertyAdapterModule:
        __name__ = "prop_module"

        class PropAdapter(PipelineAdapter):
            __module__ = "prop_module"

            @property
            def provider_name(self) -> str:
                return "prop_engine"

            def is_applicable(self, project_root: Path) -> bool:
                return False

            def load_models(self, project_root: Path, dialect=None, manifest_path=None):
                return {}

            def run_checks(self, project_root: Path, config, checks=None, dialect=None, manifest_path=None, models=None):
                return [], 0, []

    extract_and_register_from_module(PropertyAdapterModule, reg)
    assert isinstance(get_adapter("prop_engine"), PropertyAdapterModule.PropAdapter)
    prop_adapter = PropertyAdapterModule.PropAdapter()
    assert prop_adapter.is_applicable(Path("/nonexistent")) is False
    assert prop_adapter.load_models(Path("/nonexistent")) == {}
    assert prop_adapter.run_checks(Path("/nonexistent"), None) == ([], 0, [])

    # Test adapter constructor failure fallback to class name
    class InitFailModule:
        __name__ = "init_fail_module"

        class FailInitAdapter(PipelineAdapter):
            __module__ = "init_fail_module"

    extract_and_register_from_module(InitFailModule, reg)
    assert _REGISTERED_ADAPTERS["failinit"] is InitFailModule.FailInitAdapter


def test_load_plugin_module_or_file(tmp_path: Path):
    reg = CheckRegistry()

    plugin_file = tmp_path / "custom_company_rules.py"
    plugin_file.write_text(
        """from tff.core.rules.base import Rule, RuleViolation
from tff.core.model import ModelRepresentation
from tff.core.adapter import PipelineAdapter

class CompanyCustomRule(Rule):
    name = "company_custom_rule"
    category = "Internal Governance"

    def check_model(self, model: ModelRepresentation):
        if "forbidden" in model.name:
            return self.violation("Forbidden model name!")
        return None

class CompanyAdapter(PipelineAdapter):
    provider_name = "company_engine"

    def is_applicable(self, project_root):
        return (project_root / "company.yml").exists()

    def load_models(self, project_root, dialect=None, manifest_path=None):
        return {}

    def run_checks(self, project_root, config, checks=None, dialect=None, manifest_path=None, models=None):
        return [], 0, []
""",
        encoding="utf-8",
    )

    # 1. Load by relative path
    loaded = load_plugin_module_or_file("custom_company_rules.py", project_root=tmp_path, registry=reg)
    assert len(loaded) >= 1
    assert reg.get("company_custom_rule") is not None
    assert isinstance(get_adapter("company_engine"), PipelineAdapter)

    # 2. File not found
    with pytest.raises(FileNotFoundError, match="Plugin file not found"):
        load_plugin_module_or_file("nonexistent.py", project_root=tmp_path, registry=reg)

    # 3. Path is directory
    dir_path = tmp_path / "some_dir.py"
    dir_path.mkdir()
    with pytest.raises(ValueError, match="Plugin path is not a file"):
        load_plugin_module_or_file(dir_path, registry=reg)

    # 4. Import failure for module name
    with pytest.raises(ImportError, match="Failed to import plugin module 'nonexistent_package_xyz'"):
        load_plugin_module_or_file("nonexistent_package_xyz", project_root=tmp_path, registry=reg)

    # 5. Local candidate without .py extension
    plugin_file_with_ext = tmp_path / "my_rules.py"
    plugin_file_with_ext.write_text(
        """from tff.core.rules.base import Rule
class CandidateRule(Rule):
    name = "candidate_rule"
    def check_model(self, model):
        return None
""",
        encoding="utf-8",
    )
    loaded_candidate = load_plugin_module_or_file("my_rules", project_root=tmp_path, registry=reg)
    assert len(loaded_candidate) >= 1
    assert reg.get("candidate_rule") is not None

    # 6. Load without passing registry (uses default registry)
    loaded_default = load_plugin_module_or_file("custom_company_rules.py", project_root=tmp_path)
    assert len(loaded_default) >= 1

    # 7. spec_from_file_location returns None
    with patch("importlib.util.spec_from_file_location", return_value=None):
        with pytest.raises(ImportError, match="Could not load module specification"):
            load_plugin_module_or_file("custom_company_rules.py", project_root=tmp_path, registry=reg)


def test_load_plugins_idempotency(tmp_path: Path):
    reg = CheckRegistry()

    plugin_file = tmp_path / "idempotent_plugin.py"
    plugin_file.write_text(
        """from tff.core.rules.base import Rule
class IdempotentRule(Rule):
    name = "idempotent_rule"
    def check_model(self, model):
        return None
""",
        encoding="utf-8",
    )

    # First load
    loaded1 = load_plugins([plugin_file], project_root=tmp_path, registry=reg)
    assert len(loaded1) == 1

    # Second load with same path should be skipped
    loaded2 = load_plugins([plugin_file], project_root=tmp_path, registry=reg)
    assert len(loaded2) == 0
