# Minimal dbt Project (Zero Configuration)

Reference implementation demonstrating zero-configuration DAG auditing with `tff`.

This directory omits `fitness_functions.yaml` to demonstrate default convention inference (`staging` → `intermediate` → `core` → `marts`).

## Execution

Execute the architectural checks directly from this directory:

```bash
# Local invocation
tff check

# Zero-installation invocation via uvx
uvx --from "tff-core[dbt]" tff check --project .
```

### Output Protocol

1. An informational notice is emitted to standard error indicating automatic layer hierarchy inference:
   ```text
   Notice: No fitness_functions.yaml found. Running with default layer conventions (staging -> intermediate -> core -> marts).
   Run 'tff init' to generate a project configuration file.
   ```
2. Structural rules evaluate model DAG relationships across `staging`, `intermediate`, and `marts`.

## Configuration Scaffolding

To transition from zero-configuration defaults to explicit policy constraints:

```bash
# Initialize a project configuration file
tff init
```

Or copy the provided sample template:

```bash
cp fitness_functions.yaml.example fitness_functions.yaml
```
