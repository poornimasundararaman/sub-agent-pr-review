#!/usr/bin/env python3
"""
PR Review Orchestrator — spawns 3 specialist sub-agents in parallel.

This script demonstrates the orchestrator/sub-agent pattern: three specialist
agents (Logic, Tests, Security) run concurrently against a PR diff, then an
orchestrator synthesizes their findings into a single structured report.

Usage:
    python orchestrator.py --demo
    python orchestrator.py <diff_file>
    python orchestrator.py --pr <owner/repo> <pr_number>
"""

import argparse
import concurrent.futures
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed.\nRun: pip install anthropic", file=sys.stderr)
    sys.exit(1)


SPECIALISTS = {
    "logic": {
        "role": "Logic Reviewer",
        "focus": textwrap.dedent("""\
            You are a Logic Reviewer performing a focused code review.
            Your job: find correctness bugs, unhandled edge cases, off-by-one errors,
            incorrect assumptions about inputs, and gaps in business logic.

            Rules:
            - Be specific: quote the exact diff lines you're citing.
            - Rate each finding: P0 (blocks merge), P1 (should fix soon), P2 (nit).
            - Do NOT comment on test coverage or security — those are other agents' jobs.
            - If you find nothing, say "No logic issues found."
        """),
    },
    "tests": {
        "role": "Test Writer",
        "focus": textwrap.dedent("""\
            You are a Test Writer performing a focused code review.
            Your job: find coverage gaps — untested branches, missing assertions,
            happy-path-only tests, and cases where the test name doesn't match what it tests.

            For each gap, write the specific test case that should exist (pseudocode is fine).
            Rate each finding: P0 (no tests for a critical path), P1 (missing branch), P2 (nit).
            Do NOT comment on logic bugs or security — those are other agents' jobs.
            If you find nothing, say "No test gaps found."
        """),
    },
    "security": {
        "role": "Security Auditor",
        "focus": textwrap.dedent("""\
            You are a Security Auditor performing a focused code review.
            Your job: find:
            - Injection vulnerabilities (SQL, shell command, path traversal)
            - Authentication and authorization gaps
            - Secrets or credentials committed to code
            - Insecure defaults (no rate limiting, no input validation, open CORS, etc.)

            Rate each finding: P0 (exploitable, blocks merge), P1 (should fix), P2 (harden).
            Do NOT comment on logic correctness or test coverage — those are other agents' jobs.
            If you find nothing, say "No security issues found."
        """),
    },
}


def load_diff_from_file(path: str) -> str:
    return Path(path).read_text()


def load_diff_from_github(repo: str, pr_number: int) -> str:
    result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR fetching PR diff:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def load_demo_diff() -> str:
    demo_path = Path(__file__).parent / "sample_pr.diff"
    if not demo_path.exists():
        print("sample_pr.diff not found. Run from the repo root.", file=sys.stderr)
        sys.exit(1)
    return demo_path.read_text()


def call_specialist(client: anthropic.Anthropic, role_key: str, diff: str) -> tuple[str, str]:
    """Call one specialist agent. Returns (role_key, findings_text)."""
    spec = SPECIALISTS[role_key]
    prompt = textwrap.dedent(f"""\
        {spec['focus']}

        ---
        PR DIFF TO REVIEW:
        ---
        {diff}
        ---

        Provide your findings as the {spec['role']}. Use this structure:

        ## {spec['role']} Findings

        ### P0 — Blocks Merge
        (list or "None")

        ### P1 — Should Fix
        (list or "None")

        ### P2 — Nits / Hardening
        (list or "None")
    """)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return role_key, message.content[0].text


def synthesize(client: anthropic.Anthropic, role_outputs: dict[str, str]) -> str:
    """Call the orchestrator to synthesize three specialist reports into one."""
    reports_block = "\n\n".join(
        f"=== {SPECIALISTS[k]['role'].upper()} ===\n{v}"
        for k, v in role_outputs.items()
    )
    synthesis_prompt = textwrap.dedent(f"""\
        You are the PR Review Orchestrator. You received reports from three specialist agents
        who reviewed the same PR diff independently and in parallel.

        Synthesize them into a single structured report. Follow this format exactly:

        ## PR Review Report

        ### P0 — Must Fix Before Merge
        (list any P0 items from any specialist, with attribution, or "None")

        ### Logic
        (Logic Reviewer findings, summarized with file/line citations)

        ### Tests
        (Test Writer findings)

        ### Security
        (Security Auditor findings)

        ### Summary
        (2-3 sentence verdict: is this safe to merge? what is the overall risk level?)

        ---
        SPECIALIST REPORTS:
        ---
        {reports_block}
    """)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": synthesis_prompt}],
    )
    return message.content[0].text


def main():
    parser = argparse.ArgumentParser(
        description="PR Review via parallel Claude sub-agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python orchestrator.py --demo
              python orchestrator.py path/to/changes.diff
              python orchestrator.py --pr myorg/myrepo 42 --output report.md
        """),
    )
    parser.add_argument("diff_file", nargs="?", help="Path to a .diff or patch file")
    parser.add_argument(
        "--pr", nargs=2, metavar=("REPO", "NUMBER"),
        help="Fetch diff from GitHub: --pr owner/repo 42 (requires gh CLI)",
    )
    parser.add_argument("--demo", action="store_true", help="Run with the bundled sample diff")
    parser.add_argument("--output", "-o", help="Write final report to this file")
    args = parser.parse_args()

    # Load the diff
    if args.demo:
        diff = load_demo_diff()
        print("Running demo with sample_pr.diff ...")
    elif args.pr:
        repo, pr_number = args.pr
        diff = load_diff_from_github(repo, int(pr_number))
        print(f"Fetched diff for PR #{pr_number} in {repo}")
    elif args.diff_file:
        diff = load_diff_from_file(args.diff_file)
        print(f"Loaded diff from {args.diff_file}")
    else:
        parser.print_help()
        sys.exit(1)

    if not diff.strip():
        print("Diff is empty — nothing to review.", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY not set.\n"
            "Export it: export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("\nSpawning 3 specialist agents in parallel...")
    print("  • Logic Reviewer")
    print("  • Test Writer")
    print("  • Security Auditor")
    print()

    start = time.time()

    # Run all three specialists concurrently
    role_outputs: dict[str, str] = {}
    errors: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(call_specialist, client, role_key, diff): role_key
            for role_key in SPECIALISTS
        }
        for future in concurrent.futures.as_completed(futures):
            role_key = futures[future]
            try:
                _, findings = future.result()
                role_outputs[role_key] = findings
                print(f"  [done] {SPECIALISTS[role_key]['role']}")
            except Exception as exc:
                errors.append(f"{role_key}: {exc}")
                print(f"  [error] {SPECIALISTS[role_key]['role']}: {exc}")

    elapsed = time.time() - start
    print(f"\nAll specialists finished in {elapsed:.1f}s")

    if errors:
        print(f"\nWarning: {len(errors)} agent(s) failed. Synthesizing partial results.")

    if not role_outputs:
        print("All agents failed. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Fill in any missing specialists
    for k in SPECIALISTS:
        if k not in role_outputs:
            role_outputs[k] = f"[{SPECIALISTS[k]['role']} did not complete]"

    print("\nSynthesizing results...")
    report = synthesize(client, role_outputs)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    if args.output:
        Path(args.output).write_text(report)
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
