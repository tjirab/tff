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

## Generating Demos

To re-record and compile all demo GIFs:

```bash
./demos/generate_demos.sh
```

Or run an individual tape file:

```bash
vhs demos/demo-check-dbt.tape
```
