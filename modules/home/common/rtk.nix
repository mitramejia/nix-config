{
  config,
  lib,
  pkgs,
  unstablePkgs,
  ...
}: let
  # Stable has 0.41.0. The existing unstable lock already pins upstream v1.2.1
  # (2026-11-19), including source and Cargo hashes; no second package set.
  package = assert lib.assertMsg (unstablePkgs.rtk.version == "1.2.1") "Review RTK hooks and tests before updating the pinned release.";
    unstablePkgs.rtk;
  check =
    pkgs.runCommand "rtk-global-integration" {
      nativeBuildInputs = [pkgs.python3 package];
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME"
      python ${./rtk/test_reconcile.py} ${./rtk/reconcile.py} ${./rtk/instructions.md} ${lib.getExe package}
      touch "$out"
    '';
in {
  options.private = {
    rtkPackage = lib.mkOption {
      type = lib.types.package;
      internal = true;
      readOnly = true;
      description = "One RTK release for runtime and OpenCode plugin tests.";
    };
    rtkCheck = lib.mkOption {
      type = lib.types.package;
      internal = true;
      readOnly = true;
      description = "RTK reconciliation and native hook smoke tests.";
    };
  };

  config = {
    private = {
      rtkPackage = package;
      rtkCheck = check;
    };
    home.packages = [package];

    # These files are shared with the agents and external integrations. Merge
    # only RTK-owned entries after Codex's existing mutable-file activations.
    home.activation.ensureGlobalRtk =
      lib.hm.dag.entryAfter [
        "writeBoundary"
        "ensureMutableCodexConfig"
        "ensurePrReviewerRouting"
        "ensureMutableOpenCodeConfig"
      ] ''
        run ${pkgs.python3}/bin/python ${./rtk/reconcile.py} \
          ${lib.escapeShellArg config.home.homeDirectory} \
          "''${CODEX_HOME:-${config.home.sessionVariables.CODEX_HOME or "${config.home.homeDirectory}/.codex"}}" \
          "''${CLAUDE_CONFIG_DIR:-${config.home.homeDirectory}/.claude}" \
          ${lib.escapeShellArg "${config.xdg.configHome}/opencode"} \
          ${lib.escapeShellArg (lib.getExe package)} ${./rtk/instructions.md}
      '';
  };
}
