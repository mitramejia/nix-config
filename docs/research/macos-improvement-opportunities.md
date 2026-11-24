# macOS improvement opportunities

Scope: ranked recommendations from configuration review and primary documentation, not macOS runtime testing. No configuration was changed or activated. Permissions, installed app paths, display behavior, and backup status still need checking on the Mac.

## 1. Get more from existing Raycast

Use **Switch Windows** as the macOS counterpart to the Noctalia window switcher. Add three quicklinks with memorable aliases: Linear, Slack, and the active repo/emulator workflow. This needs no additional apps.

Evidence: existing [Raycast declaration](../../modules/darwin/casks.nix#L12), [navigation](https://manual.raycast.com/navigation), and [quicklinks](https://manual.raycast.com/quicklinks). Verify keyboard access and destination handling on the Mac before settling on aliases.

## 2. Enable Touch ID sudo, including detached terminals

Consider `security.pam.services.sudo_local.touchIdAuth` together with `security.pam.services.sudo_local.reattach`; the latter matters for terminal multiplexers. These exact options are present in the pinned [nix-darwin PAM module](https://github.com/nix-darwin/nix-darwin/blob/d31953cf55f9027a56e9be938daf5db8c5655663/modules/security/pam.nix).

Relevant workflow: [`fr`/`fu` in Darwin shell:43–45](../../modules/home/darwin/shell.nix#L43-L45) and the [shared Herdr module](../../modules/home/common/herdr.nix). Test sudo both inside and outside Herdr, including after detaching and reattaching and with password fallback; source review does not establish that biometric prompts work in either context.

## 3. Make Dock activation resilient; keep Finder tweaks small

The [host Dock pins:12–28](../../hosts/macos/default.nix#L12-L28) include `/Applications`, Toolbox/manual apps, and a Kitty `/nix/store` path. [Dock validation:55–76](../../modules/darwin/dock/default.nix#L55-L76) aborts its activation block when a path is missing.

Distinguish required pins from optional apps: retain failure for required paths, but warn and skip absent optional apps. Prefer a stable Home Manager application link for Kitty, following the existing [Zen browser module](../../modules/home/darwin/zen-browser.nix), rather than a generation-specific store path. Validate installed paths and rebuild behavior on macOS before changing this logic.

Optional Finder refinements: `FXDefaultSearchScope = "SCcf"` (search current folder) and `_FXSortFoldersFirst = true`. Both are supported by the pinned [Finder module](https://github.com/nix-darwin/nix-darwin/blob/d31953cf55f9027a56e9be938daf5db8c5655663/modules/system/defaults/finder.nix); these are preference choices, not required fixes.

## 4. Confirm encrypted backups and prove restoration

If Time Machine is not already configured, enable encrypted backups for mutable data Nix does not reproduce: local documents, app state, and uncommitted work. Store the recovery password safely and restore a sample file before relying on the backup.

Primary guidance: Apple’s [backup disk and encryption options](https://support.apple.com/guide/mac-help/choose-a-backup-disk-set-encryption-options-mh11421/mac) and [file restoration](https://support.apple.com/guide/mac-help/restore-files-mh11422/mac). Backup configuration and successful restoration were not inspected or tested.
