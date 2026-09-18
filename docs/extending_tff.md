# Extending tff: Custom Rules, Checks & Adapters

tff provides an extensible, plugin-based architecture that enables teams to enforce internal coding standards, build project-wide architectural checks, and integrate proprietary or unsupported transformation engines without modifying `tff-core`.

---

## 1. Concepts & Terminology

Before writing extensions, it is helpful to understand how tff organizes fitness functions and engine integrations:

| Concept | Scope | Implementation | Configuration |
| :--- | :--- | :--- | :--- |
| **Model Rule** (Linter Rule) | Single Model | Subclass `tff.core.rules.base.Rule` | Under `rules.<name>` in `fitness_functions.yaml` |
| **Architectural Check** (DAG Check) | Entire Project / Multi-Model | Collector function registered via `tff.core.registry.CheckDefinition` (`scope="dag"`) | Under `checks.<name>` in `fitness_functions.yaml` |
| **Transformation Engine** | Pipeline Tool | Underlying framework (e.g. dbt, SQLMesh, Dataform, custom internal CLI) | Project files (e.g. `dbt_project.yml`) |
| **Pipeline Adapter** | Engine Abstraction | Subclass `tff.core.adapter.PipelineAdapter` | Registered in entry points or loaded via plugins |
| **Provider Identifier** | CLI & Config Key | Short string ID (e.g. `dbt`, `sqlmesh`, `dataform`, `custom_engine`) | CLI option `--provider <id>` |

### Model Rules vs. Architectural Checks

* **Model Rules** (`scope="model"`): Evaluate one model file in isolation. They receive a single `ModelRepresentation` object and return a `RuleViolation` if invalid. Model rules run concurrently across thread pools and automatically benefit from `skip_layers` and `only_layers` filtering.
* **Architectural Checks** (`scope="dag"`): Evaluate the entire DAG or cross-model patterns (e.g., dependency cycles, connascence of value, CTE duplication, schema contracts). They receive the dictionary of all loaded models (`dict[str, ModelRepresentation]`) and return a list of `LintFinding` objects.

---

## 2. Authoring Custom Model Rules

To create a custom rule that checks individual SQL models, subclass `Rule` and implement `check_model`.

### Minimal Example: Enforce Model Naming

```python
# rules/company_naming.py
from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation

class CompanyNamingRule(Rule):
    """Enforce that models start with an approved company prefix."""
    name = "company_naming_convention"
    category = "Internal Standards"
    default_severity = "error"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        # Read custom configuration options
        cfg = self.get_rule_config() or {}
        prefix = cfg.get("prefix", "corp_") if isinstance(cfg, dict) else getattr(cfg, "prefix", "corp_")

        # Flag violation if model name does not start with prefix
        if not model.name.startswith(prefix):
            return self.violation(f"Model '{model.name}' must start with required prefix '{prefix}'.")
        return None
```

### Advanced Example: Inspecting the SQL AST

tff parses SQL using [SQLGlot](https://github.com/tobymao/sqlglot) and exposes the parsed Abstract Syntax Tree (AST) via `model.ast`. You can query and traverse the AST using SQLGlot's expression API:

```python
# rules/ban_distinct_in_joins.py
import sqlglot.expressions as exp
from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation

class BanDistinctInJoins(Rule):
    """Disallow SELECT DISTINCT directly inside JOIN subqueries."""
    name = "ban_distinct_in_joins"
    category = "Query Performance"
    default_severity = "warning"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        ast = model.ast
        if ast is None:
            return None

        # Traverse all JOIN expressions in the model
        for join in ast.find_all(exp.Join):
            subquery = join.this
            if isinstance(subquery, exp.Select) and subquery.args.get("distinct"):
                return self.violation("Avoid using SELECT DISTINCT inside JOIN subqueries; deduplicate upstream.")

        return None
```

### Available `ModelRepresentation` Properties

When writing model rules, the `model` object provides access to both parsed metadata and SQL content:

* `model.name` (`str`): The resolved model identifier (e.g. `dim_users`).
* `model.path` (`str`): Path to the source file on disk.
* `model.dialect` (`str`): Target SQL dialect (e.g. `snowflake`, `duckdb`, `bigquery`).
* `model.ast` (`sqlglot.expressions.Expression | None`): Parsed and cached SQLGlot AST.
* `model.get_sql()` (`str | None`): Full SQL or Jinja query text.
* `model.columns_to_types` (`dict[str, str]`): Known column types (if resolved by adapter or manifest).
* `model.depends_on` (`set[str]`): Set of upstream model dependencies.
* `model.tags` (`list[str]`): Tags declared on the model.
* `model.meta` (`dict[str, Any]`): Engine-specific metadata dictionary.
* `model.owner` (`str | None`): Designated owner string.
* `model.description` (`str | None`): Model description/documentation.
* `model.audits` (`list[tuple[str, dict]]`): Declared tests/audits (e.g., `[("not_null", {"columns": ["id"]})]`).
* `model.materialized` (`str | None`): Materialization strategy (`view`, `table`, `incremental`, etc.).

---

## 3. Authoring Custom Architectural (DAG) Checks

Architectural checks evaluate the entire project DAG or relationships across multiple models.

### Step 1: Write the Collector Function

A DAG collector function takes the dictionary of loaded models and the active `FitnessFunctionsConfig`, and returns a list of `LintFinding` objects:

```python
# checks/max_upstream_check.py
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.report import LintFinding

def collect_max_upstream_findings(
    models: dict[str, ModelRepresentation],
    config: FitnessFunctionsConfig,
) -> list[LintFinding]:
    """Flag models that depend on more than 10 upstream sources."""
    findings: list[LintFinding] = []
    
    # Retrieve configuration options under checks.max_upstream
    check_cfg = getattr(config.checks, "max_upstream", None) if hasattr(config, "checks") else None
    max_allowed = getattr(check_cfg, "limit", 10) if check_cfg else 10

    for model_name, model in models.items():
        if len(model.depends_on) > max_allowed:
            findings.append(
                LintFinding(
                    check="max_upstream",
                    severity="warning",
                    message=f"Model '{model_name}' has {len(model.depends_on)} dependencies (max allowed: {max_allowed}).",
                    model=model_name,
                    path=model.path,
                )
            )
    return findings
```

### Step 2: Register the DAG Check via Module Hook

To register a DAG check, define a `register` function in your plugin module that registers a `CheckDefinition`:

```python
# checks/max_upstream_check.py
from tff.core.registry import CheckDefinition, CheckRegistry

def register(registry: CheckRegistry) -> list[CheckDefinition]:
    return [
        CheckDefinition(
            id="max_upstream",
            label="Maximum Upstream Dependencies",
            category="Dynamic Coupling & DAG Structure",
            scope="dag",
            default_severity="warning",
            collector_fn=collect_max_upstream_findings,
        )
    ]
```

### Configuring in `fitness_functions.yaml`

Once registered, users can configure your DAG check just like built-in checks:

```yaml
checks:
  max_upstream:
    enabled: true
    limit: 8
    severity: warning

health:
  weights:
    max_upstream: 2.0  # Weight for health score calculation
```

---

## 4. Authoring Custom Pipeline Adapters

If your team uses an internal orchestration engine or an unsupported data transformation framework, you can implement a custom `PipelineAdapter`.

### Adapter Interface

Subclass `tff.core.adapter.PipelineAdapter` and implement its abstract methods:

```python
# adapters/in_house_adapter.py
from pathlib import Path
from typing import Sequence
from tff.core.adapter import PipelineAdapter
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.registry import registry
from tff.core.report import LintFinding

class InHouseEngineAdapter(PipelineAdapter):
    @property
    def provider_name(self) -> str:
        """The identifier string passed to --provider (e.g. --provider inhouse)."""
        return "inhouse"

    def is_applicable(self, project_root: Path) -> bool:
        """Return True if project_root contains this engine's project definition."""
        return (project_root / "pipeline_manifest.yaml").is_file()

    def load_models(
        self,
        project_root: Path | Sequence[Path],
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        """Parse engine models and return a dictionary of ModelRepresentation objects."""
        root = Path(project_root if isinstance(project_root, Path) else project_root[0])
        models: dict[str, ModelRepresentation] = {}

        # Scan and construct ModelRepresentation instances
        sql_dir = root / "models"
        if sql_dir.is_dir():
            for sql_file in sql_dir.glob("**/*.sql"):
                model_name = sql_file.stem
                models[model_name] = ModelRepresentation(
                    name=model_name,
                    path=str(sql_file.relative_to(root)),
                    dialect=dialect or "duckdb",
                    provider=self.provider_name,
                )
        return models

    def run_checks(
        self,
        project_root: Path | Sequence[Path],
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
        models: dict[str, ModelRepresentation] | None = None,
    ) -> tuple[list[LintFinding], int, list[str]]:
        """Run all enabled fitness checks and return (findings, model_count, executed_checks)."""
        if models is None:
            models = self.load_models(project_root, dialect=dialect, manifest_path=manifest_path)

        findings, executed_checks = registry.run_checks(
            models=models,
            config=config,
            checks=checks,
            provider=self.provider_name,
        )
        return findings, len(models), executed_checks

    def get_diagnostic_files(self, project_root: Path | Sequence[Path]) -> list[tuple[str, str]]:
        """Optional: return signature file statuses for 'tff info'."""
        root = Path(project_root if isinstance(project_root, Path) else project_root[0])
        manifest = root / "pipeline_manifest.yaml"
        status = "found" if manifest.is_file() else "missing"
        return [("pipeline_manifest.yaml", f"{manifest} ({status})")]
```

---

## 5. Plugin Registration & Packaging

tff supports two methods to register rules, checks, and adapters:

### Method A: Local Configuration File (`plugins:`)

For project-specific rules, declare the Python file paths directly under `plugins:` in `fitness_functions.yaml`:

```yaml
# fitness_functions.yaml
plugins:
  - rules/company_naming.py
  - checks/max_upstream_check.py
  - adapters/in_house_adapter.py

rules:
  company_naming_convention:
    enabled: true
    prefix: "corp_"

checks:
  max_upstream:
    enabled: true
    limit: 12
```

When loading plugins, tff:
1. Automatically discovers any `Rule` subclasses and registers them.
2. Calls `register(registry)` or `register_rules(registry)` hooks if defined.
3. Automatically discovers any `PipelineAdapter` subclasses and registers them.

### Method B: Distributed Python Package (Entry Points)

For organizations sharing custom rules and adapters across multiple data repositories, distribute them as a Python wheel and configure standard entry points in `pyproject.toml`:

```toml
# pyproject.toml
[project.entry-points."tff.rules"]
company_naming = "corp_tff.rules:CompanyNamingRule"
max_upstream = "corp_tff.checks:register"

[project.entry-points."tff.adapters"]
inhouse = "corp_tff.adapters:InHouseEngineAdapter"
```

Once installed into the Python virtual environment (`pip install corp-tff-plugin`), tff discovers and activates all rules and adapters automatically—no `plugins:` list in `fitness_functions.yaml` required.

---

## 6. Verifying Extensions via CLI

Verify that your custom rules, checks, and adapters are discovered using the `tff info` command:

```bash
tff info
```

Output will show the detected provider, active adapter versions, and discovered signature files:

```text
● tff Info
  Project root:  /path/to/project
  Provider:      inhouse
  Config file:   fitness_functions.yaml (found)

● Adapter Versions
  tff-core              0.19.0
  inhouse integration   1.0.0 (custom plugin)

● Provider Files
  pipeline_manifest.yaml  /path/to/project/pipeline_manifest.yaml (found)
```

Run your custom rules directly:

```bash
# Run all checks including custom rules
tff lint

# Run your custom rule exclusively
tff lint --checks company_naming_convention,max_upstream
```
