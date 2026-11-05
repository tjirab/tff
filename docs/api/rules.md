# Rules & Checks API Reference

This section documents the base classes, data structures, and registry used to define and execute custom fitness function rules and architectural checks in tff.

For a comprehensive tutorial on authoring extensions, see the [Extending tff Guide](../extending_tff.md).

---

## Architecture Overview

* **Model Rules** (`scope="model"`): Subclass [`Rule`][tff.core.rules.base.Rule] and implement `check_model(self, model)`. They inspect an individual [`ModelRepresentation`][tff.core.model.ModelRepresentation] and return a [`RuleViolation`][tff.core.rules.base.RuleViolation] if invalid.
* **Architectural Checks** (`scope="dag"`): Implement a collector function `(models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig) -> list[LintFinding]` and register it via [`CheckDefinition`][tff.core.registry.CheckDefinition] in [`CheckRegistry`][tff.core.registry.CheckRegistry].

---

## Documentation URL Resolution

Rules and checks can declare documentation URLs that are surfaced across reports and developer workflows:

1. **Resolution Precedence**: When registering a rule or resolving a check's documentation URL:
   * Explicit argument passed to `CheckRegistry.register_rule(..., docs_url="...")` or `CheckDefinition(..., docs_url="...")`.
   * Rule class attribute `rule_cls.docs_url`.
   * Fallback rule class attribute `rule_cls.help_url`.
2. **Registry Lookup**:
   * `CheckRegistry.get_docs_url(check_id)` resolves the URL by canonical check ID, finding check ID, or configured alias.
   * `CheckRegistry.get_docs_urls()` returns a dictionary mapping of all check IDs to their documentation URLs.
3. **Surfaced Outputs**:
   * **GitHub Actions PR Comments**: Check names in summary violation tables are rendered as Markdown links.
   * **SARIF Format**: Populates `rule.helpUri` for GitHub Code Scanning and IDE SARIF viewers.
   * **HTML Documentation Dashboard**: Generates clickable documentation links for each finding in the dashboard.

---

## Model Rule Classes

::: tff.core.rules.base.Rule
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2

::: tff.core.rules.base.RuleViolation
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2

---

## Model & Finding Data Structures

::: tff.core.model.ModelRepresentation
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2

::: tff.core.report.LintFinding
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2

---

## Registry & Check Definitions

::: tff.core.registry.CheckDefinition
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2

::: tff.core.registry.CheckRegistry
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2
