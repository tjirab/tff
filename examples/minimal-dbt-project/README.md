# Minimal dbt Example Project (Zero-Config)

This example project demonstrates **Zero-Config Default Execution** with TFF (Transformation Fitness Functions).

Notice that this project **intentionally does not include a `fitness_functions.yaml` file**.

## Testing Zero-Config Execution

When you run `tff` without an existing configuration file, it automatically falls back to standard modern data stack layer conventions (`staging -> intermediate -> core -> marts`) with all core rules enabled:

```bash
# Run lint checks (from this directory)
tff lint

# Or run via uvx without cloning/installing:
uvx tff-core lint --project examples/minimal-dbt-project
```

### Expected Output

1. An informational notice is printed to stderr indicating that default layer conventions are being used:
   ```text
   Notice: No fitness_functions.yaml found. Running with default layer conventions (staging -> intermediate -> core -> marts).
   Run 'tff init' to generate a project configuration file.
   ```
2. The lint checks execute and evaluate models across `staging`, `intermediate`, and `marts`.

## Scaffolding a Configuration File

To generate an annotated `fitness_functions.yaml` starter file in this directory, run:

```bash
tff init
```

Once generated, you can customize layer hierarchies, rules, thresholds, and contracts specifically for your project.
