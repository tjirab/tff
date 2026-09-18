# Adapters API Reference

tff uses the `PipelineAdapter` interface to abstract underlying transformation engines (such as SQLMesh, dbt, and Google Cloud Dataform) or proprietary orchestration engines.

For a step-by-step tutorial on implementing a custom adapter, see the [Extending tff Guide](../extending_tff.md#4-authoring-custom-pipeline-adapters).

---

## Adapter Lifecycle

Every `PipelineAdapter` handles four distinct responsibilities during a tff run:

1. **Auto-Detection (`is_applicable`)**: Evaluates whether a given directory is managed by this transformation engine by looking for signature files (e.g. `dbt_project.yml`).
2. **Model Ingestion (`load_models`)**: Parses the project's models and maps them into standardized [`ModelRepresentation`][tff.core.model.ModelRepresentation] instances.
3. **Execution & Checking (`run_checks`)**: Invokes enabled fitness rules and architectural checks, typically delegating to [`CheckRegistry`][tff.core.registry.CheckRegistry].
4. **Diagnostics (`get_diagnostic_files`)**: Reports status of key project files for the `tff info` command.

---

## Core Adapter Interface

::: tff.core.adapter.PipelineAdapter
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2

---

## Adapter Discovery & Registry Functions

::: tff.core.adapter.detect_provider
    options:
      show_root_heading: true
      heading_level: 2

::: tff.core.adapter.get_adapter
    options:
      show_root_heading: true
      heading_level: 2

::: tff.core.adapter.register_adapter
    options:
      show_root_heading: true
      heading_level: 2

::: tff.core.adapter.get_available_providers
    options:
      show_root_heading: true
      heading_level: 2
