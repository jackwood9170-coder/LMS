"""
run_pipeline.py
---------------
Runs the full data/model pipeline sequentially.

Order:
  1) fetch_fpl_fixtures.py
  2) fetch_historic_odds.py
  3) fetch_odds.py
  4) calibrate_elo.py
  5) compare_elo_vs_market.py

Usage:
  python scripts/run_pipeline.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_step(repo_root: Path, script_name: str) -> subprocess.CompletedProcess[str]:
    script_path = repo_root / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    print(f"\n=== Running {script_name} ===")
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.stdout:
        print(completed.stdout.strip())
    if completed.stderr:
        print(completed.stderr.strip(), file=sys.stderr)

    print(f"=== {script_name} exited with code {completed.returncode} ===")
    return completed


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    pipeline = [
        "fetch_fpl_fixtures.py",
        "fetch_historic_odds.py",
        "fetch_odds.py",
        "calibrate_elo.py",
        "compare_elo_vs_market.py",
    ]

    print("Starting full pipeline...")

    for script in pipeline:
        result = run_step(repo_root, script)
        if result.returncode != 0:
            print(f"Pipeline failed at step: {script}", file=sys.stderr)
            return result.returncode

    print("\nPipeline completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
