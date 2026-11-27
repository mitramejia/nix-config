# nix-config

One flake configures an Apple Silicon Mac and an x86_64 NixOS PC. Start with
the matching fresh-machine instructions below; neither requires `nh`.

## Fresh-machine setup

Run only the branch for the local machine, one step at a time. Stop on unexpected
failures. Do not update `flake.lock`, erase disks or overwrite conflicting files
to work around an error.

### Before you start

- **Human approval required:** confirm the target, back up data and existing
  configuration, and approve any OS installation or disk changes. Agents must
  stop for disk selection, formatting, passwords, GUI installers and permission
  prompts. Never collect passwords in logs.
- Use a local console, reliable power/network and enough disk space for large
  builds (`df -h`). Keep an installer or recovery path and existing generations.
- These are personal profiles. The `hosts` records in `flake.nix` expect
  `/Users/mitramejia/nix-config` on Mac and `/home/mitra/nix-config` on Linux.
  For another user or path, change `username`, `homeDirectory` and `nixConfig`
  before building. Preserve state versions: they are compatibility settings,
  not OS releases.
- On retries, reuse the checkout. Inspect `git status --short` and `git diff`,
  preserve local changes and fix the failure before repeating the step.
  Do not reset, clean or autoformat the repository.

### Apple Silicon Mac (`macos`)

1. **Human gate:** finish macOS Setup Assistant with an administrator account
   named `mitramejia`. Install Apple's Command Line Tools and complete the
   dialog; skip installation if they are already installed:

   ```sh
   xcode-select --install
   ```

   Verify before continuing:

   ```sh
   xcode-select -p
   test "$(uname -m)" = arm64
   test "$(id -un)" = mitramejia
   test "$HOME" = /Users/mitramejia
   df -h /
   ```

2. **Human gate:** install [Determinate Nix](https://docs.determinate.systems/getting-started/)
   with its macOS GUI installer, then open a new terminal. This profile was
   tested with Determinate Nix 3.17.1 (Nix 2.33.3).
   `modules/darwin/default.nix` sets `nix.enable = false` because Determinate
   owns the installation and daemon. Do not install another Nix distribution
   alongside it.

   ```sh
   nix --version
   git clone https://github.com/mitramejia/nixos-config.git "$HOME/nix-config"
   cd "$HOME/nix-config"
   git status --short
   ```

3. Review `modules/darwin/casks.nix`, `modules/darwin/homebrew.nix` and
   `hosts/macos/default.nix`. nix-homebrew bootstraps Homebrew and can migrate
   an existing installation; do not install Homebrew separately on a fresh Mac.
   **Human approval required:** activation changes the shell, Dock and
   preferences, installs casks and may request permissions. The current
   `homebrew.onActivation.cleanup = "uninstall"` removes undeclared packages.
   Back up conflicting home or `/etc` files before moving only paths named
   in an activation error.

4. Run repository validation, then build the native system closure:

   ```sh
   nix run --no-update-lock-file .#validate
   nix build --no-update-lock-file .#darwinConfigurations.macos.system
   ```

   **Validation gate:** pre-existing formatting differences currently fail
   `validate`. Inspect its output: only confirmed pre-existing formatting
   failures may be recorded as a hygiene exception. Stop for evaluation,
   native-check or unclassified failures; do not autoformat unrelated files.
   Both host evaluations and Linux native checks have been verified separately,
   but macOS native checks have not. The native closure build must succeed
   before activation, even with a hygiene exception.

5. Bootstrap nix-darwin from the locked `darwin` input:

   ```sh
   sudo nix run --no-update-lock-file --inputs-from . darwin#darwin-rebuild -- switch --flake .#macos
   ```

   Home Manager is integrated; do not run a separate `home-manager switch`.
   If activation fails, inspect the error before retrying.

6. **Human gate:** reboot when ready, log back in and open a new terminal:

   ```sh
   scutil --get HostName # expected: MitraMacBook
   nix --version
   command -v darwin-rebuild nh
   /opt/homebrew/bin/brew --prefix # expected: /opt/homebrew
   test -e "$HOME/.zshrc"
   ```

   Check the Dock, apps and fresh shell. Restore credentials securely:
   `modules/home/darwin/ssh.nix` expects `~/.ssh/github_id`,
   `~/.ssh/comun_github_id` and, optionally, `~/.ssh/config_external`.
   Optional Dock entries such as WebStorm and Android Studio do not mean those
   apps are installed. Setup is incomplete if GUI checks fail.

### x86_64 NixOS PC (`nixos`)

1. **Human gate:** follow the
   [NixOS installation manual](https://nixos.org/manual/nixos/stable/#sec-installation).
   Boot the installer in UEFI mode and obtain explicit disk/partition approval
   before destructive work. Never reuse this repository's disk UUIDs.
   Finish a working base installation with an EFI system partition at `/boot`,
   networking, Git and a password-protected `mitra` account in `wheel`.
   Reboot into it and verify local login and `sudo`.

2. As `mitra`, not root:

   ```sh
   test "$(uname -m)" = x86_64
   test "$(id -un)" = mitra
   test "$HOME" = /home/mitra
   test -d /sys/firmware/efi
   sudo -v
   df -h / /boot
   git clone https://github.com/mitramejia/nixos-config.git "$HOME/nix-config"
   cd "$HOME/nix-config"
   git status --short
   ```

   This profile uses mutable users and sets no password. Retain the working
   base-install account and password.

3. **Hardware gate: do not rebuild with the checked-in disk UUIDs.**
   Generate a reference from the installed system:

   ```sh
   sudo nixos-generate-config --show-hardware-config > /tmp/new-hardware.nix
   lsblk -f
   findmnt /
   findmnt /boot
   ```

   Merge the generated filesystem, swap, platform and required module settings
   into `hosts/nixos/hardware.nix`, replacing the old root/EFI UUIDs. Do not
   replace the file blindly: it also contains AMD graphics, microcode and
   device rules. Review `modules/nixos/boot.nix`: `amdgpu`, `kvm-amd`, the
   MediaTek workaround, systemd-boot and writable EFI variables assume the
   original hardware.

   Different GPU PCI addresses, Intel/NVIDIA hardware, encryption, BIOS boot
   or another EFI mount require deliberate changes. Remove conflicting
   filesystem definitions and compare mounts with `lsblk` and `findmnt`.
   Stop if uncertain.

4. **Human approval required:** review network exposure.
   `modules/nixos/default.nix` disables the firewall and enables SSH.
   Use a trusted network and adapt the policy before proceeding if needed.
   Track newly added Nix modules with `git add <path>` so Git flakes include
   them; no commit is required. Edits to tracked files are already included.

5. Enable flakes in this shell, validate and build the native system closure:

   ```sh
   export NIX_CONFIG='experimental-features = nix-command flakes'
   nix run --no-update-lock-file .#validate
   nix build --no-update-lock-file .#nixosConfigurations.nixos.config.system.build.toplevel
   ```

   **Validation gate:** only confirmed pre-existing formatting failures may
   be recorded as a hygiene exception. Both host evaluations and Linux native
   checks have been verified separately; inspect your own output after hardware
   edits. Stop for other failures. The native closure build must succeed before
   deployment, but a successful build does not prove bootability.

6. Review `git diff`, then prepare the next boot without switching the live
   session:

   ```sh
   sudo env NIX_CONFIG='experimental-features = nix-command flakes' nixos-rebuild boot --flake .#nixos
   ```

   Stop if this fails. **Human gate:** approve the reboot, then run:

   ```sh
   sudo reboot
   ```

7. Log back in and verify:

   ```sh
   hostname # expected: nixos
   findmnt /
   findmnt /boot
   readlink -f /run/current-system
   readlink -f /nix/var/nix/profiles/system
   systemctl --failed
   systemctl status home-manager-mitra.service
   command -v nh
   ```

   The two system paths should match. Check mounts, failed units, a fresh
   desktop login, networking, graphics, audio and Bluetooth. Keep the previous
   generation and installer until these checks pass. If boot or login fails,
   select the previous systemd-boot generation; see
   [recovery](#cleanup-and-recovery-nixos). Fix the source, validate and build
   before retrying. Do not clean generations during recovery.

After either setup, use the deployment commands below. `fr` and `fu` depend on
the host record's `nixConfig` path. Application sign-ins, secrets and GUI
approvals remain manual; a build alone does not establish completion.

## Hosts and deployment

| Configuration key | System | Hostname | User | System state | Home Manager state |
| --- | --- | --- | --- | --- | --- |
| `nixos` | `x86_64-linux` | `nixos` | `mitra` | `24.11` | `23.11` |
| `macos` | `aarch64-darwin` | `MitraMacBook` | `mitramejia` | `4` | `23.11` |

The configuration key selects a host in the flake and `nh`; it need not match
the hostname. From the repository root, run only the local machine's command:

```sh
# NixOS
nh os switch . -H nixos
```

```sh
# macOS
nh darwin switch . -H macos
```

The former macOS repository at `/home/mitra/WebstormProjects/macos-nix-config`
is retained as an archive. Its snapshot at
`5b255acfb221938ac7d86525cfc5ec1d2311183a` supplied the imported Darwin configuration.

### OpenCode V2 updates with `fu`

Both hosts use `unstablePkgs.opencode` from `nixpkgs-unstable`, currently V2
`2.3.0`. There is no separate OpenCode development input, release updater,
archive pin or local dependency-hash override.

`fu` refreshes `nixpkgs-unstable` and the other inputs in `flake.lock`; review
and commit the lock changes. `fr` uses the existing lock without updating it.
The aliases run:

- Linux: `nh os boot --ask --hostname nixos --update` for `fu`; reboot to
  activate the prepared generation.
- macOS: `nh darwin switch --hostname macos --update` for `fu`.

If an installed alias still invokes the removed release updater, activate this
configuration once with `fr`, then open a new shell when ready to deploy.
The opt-in local-plugin check uses the package's source and `node_modules`,
with Bun from the same unstable package set. Mutable-configuration checks remain
available on both hosts; validation deploys neither.

## Repository validation

From the repository root on either supported platform:

```sh
nix run --no-update-lock-file .#validate
```

Locked stable Nixpkgs supplies Alejandra, Bash, coreutils, findutils and the
wrapper's Nix CLI; the initial `nix run` uses your installed Nix.
The `formatter` output exposes the same Alejandra on both platforms.

Validation checks all repository `.nix` files without changing them. It excludes
`.git`, `.scratch`, `.codegraph`, `generated`, `vendor` and `node_modules`
directories and does not follow directory symlinks, including build results.
File enumeration failure stops validation. Otherwise, it attempts every check:

- Nix formatting, including pre-existing differences.
- `nixosConfigurations.nixos.config.system.build.toplevel.drvPath` evaluation.
- `darwinConfigurations.macos.system.drvPath` evaluation.
- Native `nix flake check`.

Any failure produces a nonzero exit. No stage implicitly updates the lock, uses
`--impure` or activates a configuration.

Evaluation is not a full closure build or boot/activation test. It may fetch
inputs or build import-from-derivation dependencies. Native checks build only
the current platform's check derivations; run validation on both machines for
both sets. Full closure builds need compatible local or remote builders:

```sh
# Linux builder
nix build --no-link --no-update-lock-file .#nixosConfigurations.nixos.config.system.build.toplevel
```

```sh
# Darwin builder
nix build --no-link --no-update-lock-file .#darwinConfigurations.macos.system
```

## Claude Code agents and skills

After host activation, start the coordinating agent with `claude --agent planner`.
`/agents` lists the user-scoped definitions under `~/.claude/agents`: `planner`,
`worker`, `scout`, `triage`, `pr-reviewer`, `mobile-reviewer` and `commit-staged`.
Their prompts are generated from the existing OpenCode Markdown and Codex TOML
sources, not maintained as separate copies.

All agents inherit Claude's model and ordinary permission approvals. Only
`worker` retains file-editing tools; read-only roles can request shell checks,
and reviewers can publish when authorized. Use `planner` to coordinate work.

Claude receives the same selected skills as Codex and OpenCode. Claude Code
2.1.310 ignores nested skill directories, so deployment uses flat basenames,
such as `/check-compiler-errors` and `/expo-upgrade`. Source IDs and other targets
are unchanged; basename collisions fail evaluation. The reviewer explicitly
reads `~/.claude/skills/pr-review-style/SKILL.md`.

Run the focused generation and skill-parity check without activation:

```sh
# macOS
nix build --no-link --no-update-lock-file .#darwinConfigurations.macos.config.home-manager.users.mitramejia.private.claudeAgentsCheck
```

```sh
# Linux
nix build --no-link --no-update-lock-file .#nixosConfigurations.nixos.config.home-manager.users.mitra.private.claudeAgentsCheck
```

## Xbox controller firmware (NixOS)

Run `xbox-firmware-vm wizard` for an isolated Windows maintenance VM and guarded,
dedicated-port USB handoff to the official Xbox Accessories app. Windows setup,
physical reconnect tests and update confirmation remain manual. See
[setup, safety boundaries and recovery](docs/xbox-firmware-vm.md).

## Cleanup and recovery (NixOS)

`ncg` removes user and sudo/root profile generations older than 15 days,
preserving each profile's current generation, then collects unreferenced store
paths. The retention window does not guarantee a previous generation: an old,
non-current generation can be deleted even if it is the only rollback.
After both collections succeed, it runs the current system's
`switch-to-configuration boot` to synchronize boot entries without switching
the live session. `fu` still updates and prepares a boot-only deployment.

To recover, reboot and select a retained older NixOS generation. To make the
previous system profile generation the next boot default, the installed
`nixos-rebuild` supports:

```sh
sudo nixos-rebuild boot --rollback
```

This changes the boot default, not the running session; reboot to use it.
Rollback needs a retained generation and does not restore mutable application
data. A Git revert restores source, **not** an installed generation; validate,
build and deploy separately when recovering by reverting source.
