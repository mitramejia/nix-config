"""Run against the selected RTK binary, never against the user's home."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

module_path, content_path, executable = sys.argv[1:]
sys.argv = sys.argv[:1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("reconcile", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
content = Path(content_path).read_text()


class Integration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name).resolve()
        self.codex = self.home / "custom-codex"
        self.claude = self.home / ".claude"
        self.opencode = self.home / "config/opencode"

    def run_reconciler(self):
        module.reconcile(
            self.home, self.codex, self.claude, self.opencode, executable, content
        )

    def put(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def snapshot(self):
        return {
            str(p): p.read_bytes()
            for p in self.home.rglob("*")
            if p.is_file()
        }

    def test_fresh_repeat_and_real_hook_contracts(self):
        self.run_reconciler()
        before = self.snapshot()
        self.run_reconciler()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.home / ".codex").exists())
        self.assertIn("1.2.1", subprocess.check_output(
            [executable, "--version"], text=True
        ))
        env = {**os.environ, "HOME": str(self.home),
               "CODEX_HOME": str(self.codex),
               "CLAUDE_CONFIG_DIR": str(self.claude),
               "XDG_CONFIG_HOME": str(self.home / "config"),
               "XDG_DATA_HOME": str(self.home / "data")}
        result = subprocess.run(
            [executable, "rewrite", "git status"],
            env=env, text=True, capture_output=True, check=False,
        )
        self.assertIn(result.returncode, (0, 3))
        self.assertEqual(result.stdout.strip(), "rtk git status")
        for agent, path in (
            ("claude", self.claude / "settings.json"),
            ("codex", self.codex / "hooks.json"),
        ):
            handler = json.loads(path.read_text())["hooks"]["PreToolUse"][0]
            self.assertEqual(handler["matcher"], "Bash")
            command = handler["hooks"][0]["command"]
            self.assertIn(executable, command)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
                "cwd": str(self.home),
                "session_id": "fixture",
                "permission_mode": "default",
            }
            result = subprocess.run(
                command, shell=True, input=json.dumps(payload), env=env,
                text=True, capture_output=True, check=True, cwd=self.home,
            )
            output = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "PreToolUse")
            self.assertEqual(output["updatedInput"]["command"], "rtk git status")
            if agent == "codex":
                self.assertEqual(output["permissionDecision"], "allow")
                for mode in ("bypassPermissions", "future-unknown-mode"):
                    payload["permission_mode"] = mode
                    result = subprocess.run(
                        command, shell=True, input=json.dumps(payload), env=env,
                        text=True, capture_output=True, check=True, cwd=self.home,
                    )
                    if mode == "future-unknown-mode":
                        self.assertEqual(result.stdout, "")
                    else:
                        self.assertEqual(
                            json.loads(result.stdout)["hookSpecificOutput"]["updatedInput"]["command"],
                            "rtk git status",
                        )

    def test_existing_hooks_settings_instructions_and_migration(self):
        keep = {"type": "command", "command": "custom-policy"}
        self.put(self.claude / "settings.json", json.dumps({
            "permissions": {"deny": ["Bash(rm:*)"]},
            "env": {"KEEP": "value"},
            "hooks": {
                "Stop": [{"hooks": [keep]}],
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [
                        keep,
                        {"type": "command", "command": "rtk hook claude"},
                        {"type": "command",
                         "command": 'bash "$HOME/.claude/hooks/rtk-rewrite.sh"'},
                    ]},
                    {"matcher": "Read", "hooks": [keep]},
                ],
            },
        }))
        self.put(self.codex / "hooks.json", json.dumps({
            "description": "keep",
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command",
                 "command": "/nix/store/old-rtk/bin/rtk hook codex"}, keep,
            ]}]},
        }))
        self.put(self.codex / "config.toml",
                 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n')
        self.put(self.codex / "AGENTS.md", "# Keep\n\nPR reviewer routing\n@RTK.md\n")
        self.put(self.opencode / "AGENTS.md",
                 "# CodeGraph\n\n## RTK\n\n" + module.LEGACY_RULE + "\n")
        config_before = (self.codex / "config.toml").read_bytes()
        self.run_reconciler()
        root = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(root["permissions"], {"deny": ["Bash(rm:*)"]})
        self.assertEqual(root["env"], {"KEEP": "value"})
        self.assertEqual(root["hooks"]["Stop"], [{"hooks": [keep]}])
        self.assertEqual(root["hooks"]["PreToolUse"][:2], [
            {"matcher": "Bash", "hooks": [keep]},
            {"matcher": "Read", "hooks": [keep]},
        ])
        self.assertEqual(len(root["hooks"]["PreToolUse"]), 3)
        self.assertEqual(config_before, (self.codex / "config.toml").read_bytes())
        self.assertIn("PR reviewer routing", (self.codex / "AGENTS.md").read_text())
        self.assertNotIn("@RTK.md", (self.codex / "AGENTS.md").read_text())
        self.assertIn("# CodeGraph", (self.opencode / "AGENTS.md").read_text())
        self.assertEqual((self.opencode / "AGENTS.md").read_text().count("## RTK"), 1)
        before = self.snapshot()
        self.run_reconciler()
        self.assertEqual(before, self.snapshot())

    def test_native_claude_hook_respects_existing_deny(self):
        self.put(self.claude / "settings.json", json.dumps({
            "permissions": {"deny": ["Bash(git status)"]},
        }))
        self.run_reconciler()
        result = subprocess.run(
            [executable, "hook", "claude"],
            input=json.dumps({
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
                "cwd": str(self.home),
                "permission_mode": "default",
            }),
            env={**os.environ, "HOME": str(self.home),
                 "XDG_CONFIG_HOME": str(self.home / "config"),
                 "CLAUDE_CONFIG_DIR": str(self.claude)},
            text=True, capture_output=True, check=True, cwd=self.home,
        )
        self.assertEqual(result.stdout, "")

    def test_malformed_files_are_unchanged(self):
        files = {
            self.claude / "settings.json": "{bad json",
            self.codex / "hooks.json": '{"hooks":{"PreToolUse":{}}}',
            self.codex / "AGENTS.md": module.START + "\nuser text",
        }
        for path, text in files.items():
            self.put(path, text)
        self.run_reconciler()
        for path, text in files.items():
            self.assertEqual(path.read_text(), text)
        self.assertTrue((self.opencode / "AGENTS.md").exists())

    def test_duplicate_json_keys_and_invalid_shapes_are_unchanged(self):
        path = self.claude / "settings.json"
        for text in (
            '{"env":{"KEY":"one","KEY":"two"}}',
            '[]',
            '{"hooks":[]}',
            '{"hooks":{"PreToolUse":[{"hooks":[null]}]}}',
        ):
            with self.subTest(text=text):
                self.put(path, text)
                self.run_reconciler()
                self.assertEqual(path.read_text(), text)

    def test_symlinks_and_directory_symlinks_are_untouched(self):
        outside = self.home / "outside"
        self.put(outside / "settings.json", '{"keep":true}')
        self.claude.symlink_to(outside, target_is_directory=True)
        self.codex.mkdir()
        (self.codex / "AGENTS.md").symlink_to(self.home / "missing")
        (self.codex / "hooks.json").symlink_to(outside / "settings.json")
        self.run_reconciler()
        self.assertEqual((outside / "settings.json").read_text(), '{"keep":true}')
        self.assertFalse((outside / "CLAUDE.md").exists())
        self.assertTrue((self.codex / "AGENTS.md").is_symlink())
        self.assertFalse((self.home / "missing").exists())

    def test_instruction_update_preserves_surrounding_text_and_mode(self):
        path = self.codex / "AGENTS.md"
        self.put(path, f"before\n\n{module.START}\nold\n{module.END}\n\nafter\n")
        path.chmod(0o640)
        self.run_reconciler()
        self.assertTrue(path.read_text().startswith("before\n\nafter\n\n"))
        self.assertIn(content.strip(), path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)


unittest.main()
