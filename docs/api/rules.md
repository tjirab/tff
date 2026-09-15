# Rules API Reference

This section documents the base classes and registry used to define and register custom fitness function rules in TFF.

## Custom Rules Overview

To implement a custom rule:
1. Subclass [`Rule`][tff.core.rules.base.Rule].
2. Define a unique `name`.
3. Implement `check_model(self, model)`. Return `self.violation(...)` if the model violates the rule, or `None` if it passes.
4. Register the rule with [`CheckRegistry`][tff.core.registry.CheckRegistry] or configure it via standard Python entry points (`tff.rules`).

---

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

::: tff.core.registry.CheckRegistry
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2

::: tff.core.registry.CheckDefinition
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2
