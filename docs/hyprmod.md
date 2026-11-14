# HyprMod: temporary previews, declarative settings

HyprMod is installed through Home Manager, without setup or a managed config
include. Nix remains the source of truth for Hyprland settings.

Launch `hyprmod` and choose **Not Now** in the welcome dialog. This dismisses
setup without disabling the live controls; the prompt can return next launch.
Do **not** choose **Get Started**: it adds an include by atomically rewriting
the entrypoint, which can replace Home Manager's generated symlink.

- Use live setting previews only. Do not save (`Ctrl+S`), create/apply profiles,
  change the managed config path, or run migration/config-fixer actions against
  Home Manager files. Do not use HyprMod's install script or `--install`.
- Close HyprMod without saving, then run `hyprctl reload` to reload the
  declarative config. Prefer this over its in-app reload, which can reapply
  unsaved previews. Not all runtime effects are reversible by a reload (for
  example, launched processes); limit experiments to ordinary setting controls.
- Record desired values in `modules/home/nixos/hyprland/settings.nix`, then
  rebuild normally. There is no supported GUI-to-Nix save path here.

The pinned unstable package is 0.4.0, so this uses the upstream flake instead.
The locked revision packages 0.5.0 plus unreleased Hyprland 0.57 fixes: the 0.57
option catalog, Lua input-key handling, and updated IPC/parser dependencies.
This is compatibility evidence, not a guarantee that every control works with
the pinned Hyprland build. File-only controls (for example, environment and
autostart settings) are not useful as temporary previews. No mutable override
file is sourced by this configuration.
