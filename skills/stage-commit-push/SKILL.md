---
name: stage-commit-push
description: Stage selected repository changes, create one or several atomic convention-compliant commits, and optionally push them. Use when the user asks to stage files, commit work, push a branch, or complete a stage-commit-push workflow.
---

# Stage, Commit, Push

Spawn exactly one `worker` agent with `fork_turns: "none"`, model
`openai/gpt-6.1-terra`, and reasoning effort `high`. The worker owns all Git changes
for this workflow. Tell it that it is not alone in the codebase and must not
revert others' work.

Give the worker the user request and these requirements:

1. Inspect the current branch, worktree status, staged diff, unstaged diff,
   and the repository's documented commit convention. Read
   `references/commit-conventions.md` before choosing the commit message.
2. Stage only the files or hunks the user identified. If no files were named,
   stage only changes clearly attributable to the current task; ask the user
   when ownership is ambiguous. Use explicit paths or interactive patch
   staging. Do not stage unrelated work.
3. Recheck the staged diff, use `scripts/commit_context.py` to summarize it,
   run focused checks appropriate to the staged files, and create one commit
   using the repository convention. When the user asks for multiple commits,
   group the changes into atomic commits, one logical change each, staging and
   committing each group in turn; done when every selected hunk belongs to
   exactly one commit.
4. Push only when the user requested a push. Push the current branch to its
   configured upstream; if none exists, set an upstream only when the remote
   and target branch are unambiguous. Otherwise, report the blocker.
5. Return each commit's hash, message, and committed files, plus checks run
   and the push result.

The main agent must not stage, unstage, commit, amend, push, or spawn another
agent for this workflow.
