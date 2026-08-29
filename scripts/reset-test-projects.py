#!/usr/bin/env python3
import subprocess
from pathlib import Path

PROJECTS = [
    Path("~/git/dbt-ff-testing").expanduser().resolve(),
    Path("~/git/sqlmesh-ff-testing").expanduser().resolve(),
]

def run_cmd(cmd, cwd=None, check=True):
    print(f"Running: {' '.join(cmd)} in {cwd or '.'}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)

def main():
    for proj in PROJECTS:
        if not proj.exists():
            print(f"Skipping {proj} (does not exist)")
            continue
            
        print(f"\nProcessing {proj}...")
        git_dir = proj / ".git"
        if not git_dir.exists():
            run_cmd(["git", "init"], cwd=proj)
            
        # Check if baseline commit exists
        try:
            run_cmd(["git", "log", "-1"], cwd=proj)
            has_commit = True
        except subprocess.CalledProcessError:
            has_commit = False
            
        if not has_commit:
            print("Creating baseline commit...")
            run_cmd(["git", "add", "."], cwd=proj)
            # Configure git name/email locally if not configured
            try:
                run_cmd(["git", "config", "user.name"], cwd=proj)
            except subprocess.CalledProcessError:
                run_cmd(["git", "config", "user.name", "TFF Test Automator"], cwd=proj)
                run_cmd(["git", "config", "user.email", "test@tff.local"], cwd=proj)
            run_cmd(["git", "commit", "-m", "baseline"], cwd=proj)
            print("Baseline commit created successfully.")
        else:
            print("Resetting project to baseline...")
            run_cmd(["git", "reset", "--hard", "HEAD"], cwd=proj)
            run_cmd(["git", "clean", "-fd"], cwd=proj)
            print("Project successfully reset.")
            
        # For dbt project, compile to regenerate target/manifest.json with original violating state
        if proj.name == "dbt-ff-testing":
            print("Compiling dbt project to update manifest...")
            try:
                run_cmd(["uv", "run", "dbt", "compile"], cwd=proj)
                print("dbt compile successful.")
            except Exception:
                # Fall back to standard dbt if uv is not configured
                try:
                    run_cmd(["dbt", "compile"], cwd=proj)
                    print("dbt compile successful.")
                except Exception as ex:
                    print(f"Warning: Could not compile dbt project: {ex}")

if __name__ == "__main__":
    main()
