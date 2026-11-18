# Noctalia settings

This setup is intentionally hybrid: Home Manager provides a declarative baseline, while Noctalia still writes settings changed through its UI to mutable state.

## What Nix owns

The Home Manager module is `modules/home/nixos/noctalia.nix`.

It enables `programs.noctalia`, uses the Noctalia flake package, and points the declarative baseline at:

```text
modules/home/nixos/noctalia-settings.toml
```

Home Manager also owns `~/.config/noctalia/config.toml`. That file is a symlink into the Nix store, so do not edit it directly.

## What Noctalia owns at runtime

Noctalia UI changes are written to:

```text
~/.local/state/noctalia/settings.toml
```

Other files under `~/.local/state/noctalia/` are runtime state such as notification history, recently used items, plugin state, and usage counters. They are not treated as repo source of truth.

## Activation behavior

Home Manager activation updates the immutable config baseline, not the runtime settings file. Noctalia's mutable settings take precedence over that baseline and survive rebuilds; activation must not seed or overwrite them.

## Persisting UI changes

To make the effective settings (baseline plus UI overrides) reproducible, export them back into the repo:

```bash
persist-noctalia-settings modules/home/nixos/noctalia-settings.toml
```

Then review the diff:

```bash
git diff -- modules/home/nixos/noctalia-settings.toml
```

If the diff looks right, rebuild or switch as usual. Exporting is optional for retaining local UI changes, but required to capture them in the repo baseline.

## Resetting to the repo baseline

To discard UI overrides, stop Noctalia, back up and remove `~/.local/state/noctalia/settings.toml`, then start Noctalia again. It will use the activated baseline. If the repo baseline has changed, switch first to activate it; rebuilding alone does not reset UI overrides.
