# tff Terminal Demos (VHS by Charm)

This directory contains automated terminal recording scripts (.tape files) powered by [VHS by Charm](https://github.com/charmbracelet/vhs) to generate high-fidelity, Catppuccin Mocha-themed animated demo GIFs for `README.md` and documentation.

## Demo Tapes

| Tape File | Output Asset | Description |
| :--- | :--- | :--- |
| [`demo-check-dbt.tape`](demo-check-dbt.tape) | [`docs/assets/demo.gif`](../docs/assets/demo.gif) | Hero demo: running `tff check` on `examples/minimal-dbt-project` with zero-config default conventions. |
| [`demo-sqlmesh.tape`](demo-sqlmesh.tape) | [`docs/assets/demo-sqlmesh.gif`](../docs/assets/demo-sqlmesh.gif) | Demonstrates duplicate CTE detection (Connascence of Algorithm), layer integrity enforcement, and anti-pattern bans on `examples/minimal-sqlmesh-project`. |
| [`demo-health.tape`](demo-health.tape) | [`docs/assets/demo-health.gif`](../docs/assets/demo-health.gif) | Demonstrates project health scoring and category breakdowns with visual progress bars. |

## Prerequisites

Install VHS and its recording dependencies:

```bash
brew install vhs ffmpeg ttyd
```

## Generating Demos (Ad-hoc)

Demo generation is maintained as an ad-hoc script rather than automated in CI/CD pipelines to keep CI/CD runs fast, lightweight, and deterministic.

To re-record and compile all demo GIFs locally:

```bash
make demos
# or via scripts:
./scripts/generate-demos.sh
# or directly:
./demos/generate_demos.sh
```

To run a specific demo target:

```bash
./scripts/generate-demos.sh dbt
./scripts/generate-demos.sh sqlmesh
./scripts/generate-demos.sh health
```

Or run an individual tape file directly with VHS:

```bash
vhs demos/demo-check-dbt.tape
```

