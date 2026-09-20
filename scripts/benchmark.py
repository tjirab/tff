#!/usr/bin/env python3
"""Performance benchmarking and regression budget verification for tff."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from tff.core.cli import _detect_provider
from tff.core.adapter import get_adapter
from tff.core.config import FitnessFunctionsConfig


def run_benchmark(max_seconds: float = 15.0) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    examples_dir = repo_root / "examples"
    
    benchmark_projects = [
        "minimal-dbt-project",
        "minimal-sqlmesh-project",
        "minimal-dataform-project",
    ]

    print("=" * 60)
    print("🚀 Running tff Performance Benchmark Suite")
    print(f"SLA Budget Ceiling: {max_seconds:.2f}s")
    print("=" * 60)

    total_models = 0
    total_violations = 0
    start_total = time.perf_counter()

    for proj_name in benchmark_projects:
        proj_path = examples_dir / proj_name
        if not proj_path.exists():
            print(f"⚠️  Skipping missing project: {proj_name}")
            continue

        t0 = time.perf_counter()
        provider = _detect_provider(proj_path)
        adapter = get_adapter(provider)
        config = FitnessFunctionsConfig()

        findings, count, executed = adapter.run_checks(
            project_root=proj_path,
            config=config,
        )
        elapsed = time.perf_counter() - t0
        total_models += count
        total_violations += len(findings)

        print(
            f"  • {proj_name:<26} [{provider:<8}] "
            f"models={count:<2} findings={len(findings):<2} checks={len(executed):<2} "
            f"time={elapsed:.3f}s"
        )

    total_duration = time.perf_counter() - start_total
    models_per_sec = (total_models / total_duration) if total_duration > 0 else 0.0

    print("-" * 60)
    print(
        f"Benchmark Complete: {total_models} models, {total_violations} findings "
        f"evaluated across {len(benchmark_projects)} projects in {total_duration:.3f}s "
        f"({models_per_sec:.1f} models/s)"
    )

    if total_duration > max_seconds:
        print(
            f"❌ Performance Regression: Total duration {total_duration:.3f}s exceeded budget {max_seconds:.2f}s!"
        )
        return 1

    print(f"✅ Performance Budget Met ({total_duration:.3f}s <= {max_seconds:.2f}s)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run tff performance benchmarks.")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=15.0,
        help="Maximum allowed duration in seconds before failing (default: 15.0s)",
    )
    args = parser.parse_args()
    sys.exit(run_benchmark(max_seconds=args.max_seconds))


if __name__ == "__main__":
    main()
