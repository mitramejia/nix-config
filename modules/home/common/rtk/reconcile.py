"""Merge global RTK integration without taking ownership of agent settings."""

import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile

START = "<!-- NIX-RTK-START -->"
END = "<!-- NIX-RTK-END -->"
LEGACY_RULE = (
    "Across all projects, use `rtk` for supported shell commands to reduce output "
    "noise. Pass this requirement to delegated workers. Use native commands when "
    "RTK does not support them or when verbatim output is required. Keep dedicated "
    "tools and CodeGraph preferred over shell equivalents."
)


def regular_path(path):
    """Skip file and directory symlinks, including dangling links."""
    if not path.is_absolute():
        raise ValueError(f"agent configuration path must be absolute: {path}")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"user-managed symlink: {component}")
    if path.exists() and not path.is_file():
        raise ValueError(f"not a regular file: {path}")


def write(path, text):
    regular_path(path)
    if path.exists() and path.read_text() == text:
        return
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".nix-rtk-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def owned_hook(handler, agent):
    command = handler.get("command")
    if handler.get("type") != "command" or not isinstance(command, str):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    # Exact native invocations (including previous store paths) or the known
    # upstream legacy shell hook. Never match arbitrary commands containing rtk.
    if len(argv) == 3 and Path(argv[0]).name == "rtk":
        return argv[1:] == ["hook", agent]
    return (
        agent == "claude"
        and len(argv) in (1, 2)
        and (len(argv) == 1 or argv[0] in ("bash", "sh"))
        and Path(argv[-1]).name == "rtk-rewrite.sh"
    )


def hooks(path, agent, executable):
    regular_path(path)
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    root = json.loads(path.read_text(), object_pairs_hook=unique_keys) if path.exists() else {}
    if not isinstance(root, dict):
        raise ValueError("settings must be a JSON object")
    events = root.setdefault("hooks", {})
    if not isinstance(events, dict):
        raise ValueError("hooks must be an object")
    entries = events.setdefault("PreToolUse", [])
    if not isinstance(entries, list):
        raise ValueError("PreToolUse must be an array")
    kept = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            raise ValueError("invalid PreToolUse matcher group")
        handlers = entry["hooks"]
        if not all(isinstance(handler, dict) for handler in handlers):
            raise ValueError("invalid PreToolUse handler")
        remaining = [h for h in handlers if not owned_hook(h, agent)]
        if remaining or not handlers:
            kept.append({**entry, "hooks": remaining})
    kept.append({
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": f"{shlex.quote(executable)} hook {agent}"}],
    })
    events["PreToolUse"] = kept
    write(path, json.dumps(root, indent=2, ensure_ascii=False) + "\n")


def instructions(path, content):
    regular_path(path)
    text = path.read_text() if path.exists() else ""
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise ValueError("ambiguous RTK instruction markers")
    if START in text:
        before, remainder = text.split(START)
        _, after = remainder.split(END)
        text = before.rstrip() + after
    # Migrate only the exact known manually installed rule, not arbitrary notes.
    text = text.replace("## RTK\n\n" + LEGACY_RULE, "")
    text = re.sub(r"(?m)^@RTK\.md\r?\n?", "", text)
    block = f"{START}\n{content.strip()}\n{END}\n"
    write(path, text.rstrip() + ("\n\n" if text.strip() else "") + block)


def reconcile(home, codex, claude, opencode, executable, content):
    del home  # Explicit roots allow CODEX_HOME and XDG_CONFIG_HOME overrides.
    operations = [
        (hooks, Path(claude) / "settings.json", ("claude", executable)),
        (hooks, Path(codex) / "hooks.json", ("codex", executable)),
        (instructions, Path(claude) / "CLAUDE.md", (content,)),
        (instructions, Path(codex) / "AGENTS.md", (content,)),
        (instructions, Path(opencode) / "AGENTS.md", (content,)),
    ]
    for operation, path, args in operations:
        try:
            operation(path, *args)
        except (OSError, ValueError) as error:
            # Fail this file closed, leave it byte-for-byte intact, and let the
            # other integrations activate. Make skipped integration visible.
            print(f"RTK: leaving {path} unchanged: {error}", file=sys.stderr)


if __name__ == "__main__":
    home, codex, claude, opencode, executable, content_path = sys.argv[1:]
    reconcile(home, codex, claude, opencode, executable, Path(content_path).read_text())
