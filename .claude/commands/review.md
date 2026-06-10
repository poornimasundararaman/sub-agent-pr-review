Review the pull request diff at $ARGUMENTS (default: sample_pr.diff) using the 3-specialist sub-agent workflow defined in CLAUDE.md.

Steps:
1. Read the diff file. If no argument given, use sample_pr.diff.
2. Spawn three sub-agents in parallel using the Task tool, one per specialist role defined in CLAUDE.md: Logic Reviewer, Test Writer, Security Auditor. Give each agent the full diff and their role-specific system prompt from CLAUDE.md.
3. Wait for all three tasks to complete.
4. Synthesize the results into the structured report format defined in CLAUDE.md.
