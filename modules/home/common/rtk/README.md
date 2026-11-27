# Global RTK

The shared Home Manager module selects RTK 1.2.1 from the existing unstable
lock on Linux and Darwin. Stable still provides 0.41.0. Runtime and OpenCode
plugin checks use the same package; no flake input is updated.

Release evidence: [v1.2.1](https://github.com/rtk-ai/rtk/releases/tag/v1.2.1),
published 2026-11-19. Integration contracts were checked against the tagged
`src/hooks/constants.rs`, `src/hooks/init/codex.rs`, `src/hooks/hook_cmd.rs`,
and `docs/guide/getting-started/supported-agents.md`.

Activation merges `PreToolUse`/`Bash` hooks into Claude's `settings.json` and
Codex's `hooks.json`, using immutable RTK executable paths. It reconciles a
small marked instruction block in each agent's global instructions. Existing
settings, permissions, non-RTK hooks, instructions, and Codex config are retained.
Known native RTK hooks and Claude's legacy `rtk-rewrite.sh` registration are
replaced rather than duplicated; obsolete scripts are left on disk but unregistered.
Malformed files and symlinked files/directories are skipped with a warning.
Codex activation runs after PR-reviewer routing.

`CODEX_HOME` and `CLAUDE_CONFIG_DIR` overrides in the activation environment are
respected; OpenCode uses Home Manager's XDG config directory. Re-activate with
the same overrides used to launch the agents.

OpenCode retains the existing V2 `execute.before` plugin rather than installing
upstream's generated plugin. It continues to use RTK's rewrite registry.

## First launch

Restart the agents after activation. [Codex hooks](https://developers.openai.com/codex/hooks)
are enabled by default, but user hooks require review/trust through `/hooks`.
The packaged Codex 0.172.0 reports `hooks stable true` with a fresh temporary home.
This module intentionally does not bypass hook trust or change sandbox/approval
policy. Explicitly disabled hooks or administrator policy remain authoritative.
The shared instructions provide manual RTK usage even before hook trust.
Claude also requires hooks to be enabled in the running client.

The full upstream binary links the BUSL-1.1 engine as well as the Apache-2.0
CLI; see the tagged upstream `Cargo.toml` and `engine/LICENSE`.

## Checks

`checks.<system>.rtk-global-integration` exercises fresh/existing/repeated
activation, migration, malformed-file and symlink safety, and the selected
binary's version, rewrite, and native hook contracts. The OpenCode package's
`localPluginsCheck` tests the V2 plugin against that same binary.
