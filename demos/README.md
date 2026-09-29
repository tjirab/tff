# Terminal Demos (VHS Recording Suite)

Automated terminal session scripts (`.tape` definitions) powered by [VHS](https://github.com/charmbracelet/vhs) for generating deterministic documentation assets.

## Specifications & Artifacts

| Tape Definition | Target Asset | Functional Scope |
| :--- | :--- | :--- |
| [`demo-check-dbt.tape`](demo-check-dbt.tape) | [`docs/assets/demo.gif`](../docs/assets/demo.gif) | Primary demo: executing `tff check` on `examples/minimal-dbt-project` under default layer conventions. |
| [`demo-sqlmesh.tape`](demo-sqlmesh.tape) | [`docs/assets/demo-sqlmesh.gif`](../docs/assets/demo-sqlmesh.gif) | Demonstrates duplicate CTE identification (Connascence of Algorithm) and layer integrity enforcement. |
| [`demo-health.tape`](demo-health.tape) | [`docs/assets/demo-health.gif`](../docs/assets/demo-health.gif) | Visualizes project health index calculations, penalty driver distributions, and category progress bars. |

## Prerequisites

Install the VHS recording toolchain:

```bash
brew install vhs ffmpeg ttyd
```

## Execution

Demo compilation is decoupled from CI pipelines to preserve build determinism and execution speed.

### Generate All Demo Assets

```bash
make demos
# or direct script invocation:
./scripts/generate-demos.sh
```

### Generate Targeted Assets

```bash
./scripts/generate-demos.sh dbt
./scripts/generate-demos.sh sqlmesh
./scripts/generate-demos.sh health
```

### Single Tape Compilation

```bash
vhs demos/demo-check-dbt.tape
```
