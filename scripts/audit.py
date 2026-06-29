#!/usr/bin/env python3
import json
import sys
import argparse
import subprocess

def main():
    parser = argparse.ArgumentParser(description="Audit dependencies and enforce severity thresholds.")
    parser.add_argument(
        "--min-severity",
        choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        default="HIGH",
        help="Minimum severity level to trigger failure (default: HIGH)"
    )
    args = parser.parse_args()

    # Define severity ranking to compare levels
    severity_rank = {
        None: 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4
    }

    min_rank = severity_rank.get(args.min_severity.upper(), 3)

    print(f"Running dependency audit (minimum failure severity: {args.min_severity})...")

    # Run pip-audit with json formatting.
    try:
        result = subprocess.run(
            ["uv", "run", "--with", "pip-audit", "pip-audit", "-f", "json"],
            capture_output=True,
            text=True
        )
    except FileNotFoundError:
        # Fallback to direct pip-audit run if uv is not present
        try:
            result = subprocess.run(
                ["pip-audit", "-f", "json"],
                capture_output=True,
                text=True
            )
        except Exception as e:
            print(f"Error: Neither 'uv' nor 'pip-audit' could be run. {e}", file=sys.stderr)
            sys.exit(1)

    # Note: pip-audit returns 1 if vulnerabilities are found.
    stdout = result.stdout
    json_start = stdout.find("{")
    if json_start == -1:
        # If no JSON object is found, let's check returncode.
        if result.returncode == 0:
            print("No vulnerabilities found.")
            sys.exit(0)
        else:
            print(f"Error running pip-audit (exit code {result.returncode}):", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            print(stdout, file=sys.stderr)
            sys.exit(1)

    json_str = stdout[json_start:]
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Failed to parse pip-audit JSON output: {e}", file=sys.stderr)
        print(stdout, file=sys.stderr)
        sys.exit(1)

    failures = []
    total_vulns = 0

    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            total_vulns += 1
            vuln_id = vuln.get("id")
            description = vuln.get("description", "No description")
            severity = vuln.get("severity")
            severity_str = severity.upper() if severity else "LOW"
            rank = severity_rank.get(severity_str, 1)

            if rank >= min_rank:
                failures.append({
                    "dep": dep["name"],
                    "version": dep.get("version"),
                    "id": vuln_id,
                    "severity": severity_str,
                    "desc": description
                })

    if total_vulns > 0:
        print(f"Total vulnerabilities found: {total_vulns}")
    else:
        print("No vulnerabilities found.")

    if failures:
        print(f"\n[FAIL] Found {len(failures)} vulnerabilities at or above severity threshold '{args.min_severity}':", file=sys.stderr)
        for fail in failures:
            print(f" - {fail['dep']} ({fail['version']}): {fail['id']} [{fail['severity']}] - {fail['desc'][:100]}...", file=sys.stderr)
        sys.exit(1)
    elif total_vulns > 0:
        print(f"\n[PASS] Vulnerabilities were found, but all were below the threshold '{args.min_severity}'.")
        sys.exit(0)
    else:
        print("\n[PASS] Dependency audit completed successfully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
