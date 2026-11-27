{
  inputs,
  pkgs,
  unstablePkgs,
  ...
}: let
  claudeCode = inputs.claude-code.packages.${pkgs.stdenv.hostPlatform.system}.claude-code;
  scmpuff070 = pkgs.scmpuff.overrideAttrs (old: rec {
    version = "0.7.0";

    src = pkgs.fetchFromGitHub {
      owner = "mroth";
      repo = "scmpuff";
      rev = "v${version}";
      hash = "sha256-PrnZYk0moWH46AT5njQPk7kVOQaktwVbOGMAX307tyY=";
    };

    vendorHash = "sha256-Uu3tZhIoYPq4QWc63Y5cPNa+MZtFklwuZyUc0CJLlXc=";

    nativeCheckInputs =
      (old.nativeCheckInputs or [])
      ++ (with pkgs; [
        coreutils
        fish
        git
        which
        zsh
      ]);

    postPatch =
      (old.postPatch or "")
      + ''
        substituteInPlace internal/cmd/inits/data/status_shortcuts.sh internal/cmd/inits/data/status_shortcuts.fish \
          --replace-fail /usr/bin/env ${pkgs.coreutils}/bin/env
      ''
      + pkgs.lib.optionalString pkgs.stdenv.hostPlatform.isDarwin ''
        # Keep nix-darwin's global zshenv from replacing the test sandbox PATH.
        for testFile in internal/cmd/testdata/script/*.txtar; do
          if grep -q "exec zsh -c" "$testFile"; then
            substituteInPlace "$testFile" \
              --replace-fail "exec zsh -c" "exec zsh -f -c"
          fi
        done
      '';
  });
in {
  home.packages = with pkgs;
    [
      cargo
      rustc
      ruby
      jdk17
      jq
      glab
      # Follow recent Multica CLI releases from unstable.
      unstablePkgs.multica-cli
      uv
      # Stable 2.34 lacks Agent Toolkit (introduced in 2.35).
      unstablePkgs.awscli2

      claudeCode
      alejandra
      statix
      lazydocker
      scmpuff070
      act
      actionlint
      just
      docker-compose
      lmstudio
      detekt
      gradle
      just-lsp
      kotlin
      kotlin-language-server
      ktlint
      # xtool on Linux requires Swift 6.4; stable still provides Swift 5.10.
      (
        if stdenv.hostPlatform.isLinux
        then unstablePkgs.swift
        else swift
      )
      swift-format
      swiftlint
      watchman

      doppler
    ]
    # Linux Swift already includes its matching sourcekit-lsp.
    ++ lib.optionals stdenv.hostPlatform.isDarwin [sourcekit-lsp];
}
