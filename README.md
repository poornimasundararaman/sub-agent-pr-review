# PR Review — 3 Specialist Sub-Agents

A working demo of the **orchestrator/sub-agent pattern** from the Claude Code Sub-Agents Enablement Kit. Three specialist agents run **in parallel** using Claude Code's Task tool, then an orchestrator synthesizes their findings into a single structured report.

```
                ┌─────────────────────────────┐
                │         Orchestrator        │
                │       (Claude Code)         │
                └───────────┬─────────────────┘
          spawns in parallel │  (Task tool)
        ┌──────────┬─────────┴──────────┐
        ▼          ▼                    ▼
  Logic         Test              Security
  Reviewer      Writer            Auditor
  (correctness, (coverage         (injection,
   edge cases)   gaps)             secrets, auth)
        └──────────┴────────────────────┘
                        │ synthesize
                        ▼
              Structured Review Report
```

**Why this pattern?** A single reviewer asked to hold logic, tests, and security in their head simultaneously misses things. Specialists stay focused. Parallel execution means 3× the coverage in roughly the same wall-clock time. The `CLAUDE.md` at the repo root locks in the workflow and output format so every engineer gets consistent reviews.

---

## Quickstart — no API key needed

```bash
# 1. Clone
git clone https://github.com/<your-handle>/pr-review-agents.git
cd pr-review-agents

# 2. Start Claude Code
claude

# 3. Run the review slash command
/review
```

Claude Code reads `CLAUDE.md`, spawns the three specialists in parallel via the Task tool, and prints a synthesized report. The bundled `sample_pr.diff` is used by default.

> **Requires:** [Claude Code](https://claude.ai/code) installed and authenticated.

---

## Usage

### Review a specific diff file

```
/review path/to/changes.diff
```

### Review a GitHub PR

```bash
# Outside Claude Code — fetch the diff first
gh pr diff 42 --repo owner/repo > pr42.diff

# Then inside Claude Code
/review pr42.diff
```

### Wire into CI (with API key)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python orchestrator.py --pr owner/repo 42 --output report.md
gh pr comment 42 --body-file report.md
```

---

## What the sample diff contains

`sample_pr.diff` is a realistic Python payments service (Flask + Stripe) with **intentional bugs** planted across all three specialist domains:

| Domain | Issues planted |
|--------|----------------|
| Logic | Stripe amount unit mismatch; refund endpoint doesn't verify caller owns the charge; two DB connections opened and one leaked; `limit` param cast never applied |
| Tests | No test for `/refund`; `test_history` hits a real DB; `test_charge_missing_fields` tests a removed code path |
| Security | Live Stripe key hardcoded in source (`sk_live_...`); SQL injection in two endpoints; shell command injection via `subprocess.run(shell=True)` with user input; no auth on any endpoint |

---

## How it works

`CLAUDE.md` is automatically read by Claude Code on every run. It defines:
- The orchestrator's instructions (spawn 3 agents in parallel, synthesize)
- Each specialist's focused system prompt
- The output report format and guardrails

`.claude/commands/review.md` defines the `/review` slash command. When you type `/review`, Claude Code reads the command, picks up the diff, and executes the full workflow using its built-in Task tool — no subprocess management, no API key plumbing.

---

## Adapting to your team

1. **Edit `CLAUDE.md`** to adjust specialist roles, output format, or P0 criteria for your stack.
2. **Add specialists**: copy one of the role prompts in `CLAUDE.md` and add a new Task spawn in `.claude/commands/review.md`.
3. **Wire into CI**: use `orchestrator.py` (Anthropic SDK, requires API key) for automated pipeline runs.

---

## File layout

```
pr-review-agents/
├── CLAUDE.md                     ← Orchestrator instructions + specialist prompts (auto-loaded)
├── .claude/
│   └── commands/
│       └── review.md             ← /review slash command
├── orchestrator.py               ← SDK version for CI (requires ANTHROPIC_API_KEY)
├── sample_pr.diff                ← Realistic payments service with intentional bugs
├── requirements.txt              ← anthropic SDK (only needed for orchestrator.py)
└── README.md
```

---

## Limitations

- Specialists share no context with each other — all coordination flows through the orchestrator (by design).
- Very large diffs (>100KB) may approach context limits; consider splitting by file.
- The `/review` slash command runs interactively inside Claude Code; use `orchestrator.py` for non-interactive CI runs.
