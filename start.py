"""Run BRD generation, requirement parsing, and FRD publication for a Jira Epic."""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BRD_CLIENT = PROJECT_ROOT / "brd_generation" / "mcp_clients&llms" / "brd_client.py"
REQUIREMENTS_CLIENT = PROJECT_ROOT / "brd_retri_parse" / "mcp_clients&llms" / "brd_retri_client.py"
FRD_CLIENT = PROJECT_ROOT / "frd_generation" / "mcp_clients&llms" / "frd_client.py"


def run_step(name: str, command: list[str]) -> int:
    print(f"\n=== {name} ===", flush=True)
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode:
        print(f"{name} failed with exit code {result.returncode}; stopping workflow.")
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Jira BRD, create requirement Tasks, then create the FRD and FRD story Tasks."
    )
    parser.add_argument("jira_key", help="Business Vision Jira issue key, for example KAN-4")
    parser.add_argument(
        "--provider",
        choices=("gemini", "local"),
        default="gemini",
        help="BRD generation provider (default: %(default)s)",
    )
    args = parser.parse_args()

    generation_command = [
        sys.executable,
        str(BRD_CLIENT),
        args.jira_key,
        "--provider",
        args.provider,
    ]
    result = run_step("BRD generation and upload", generation_command)
    if result:
        raise SystemExit(result)

    requirements_command = [
        sys.executable,
        str(REQUIREMENTS_CLIENT),
        args.jira_key,
    ]
    result = run_step("BRD requirement parsing and Jira task creation", requirements_command)
    if result:
        raise SystemExit(result)

    frd_command = [
        sys.executable,
        str(FRD_CLIENT),
        args.jira_key,
        "--provider",
        args.provider,
    ]
    result = run_step("FRD generation and Jira publication", frd_command)
    if result:
        raise SystemExit(result)

    print("\nEnd-to-end BRD-to-FRD workflow completed.")


if __name__ == "__main__":
    main()
