{
  inputs,
  pkgs,
  lib,
  config,
  ...
}: let
  # Use the host's existing allowUnfree policy (Readwise is proprietary),
  # rather than the flake's unconfigured legacyPackages output.
  firefox-addons = (pkgs.extend inputs.firefox-addons.overlays.default).firefox-addons;
  cfg = config.programs.zen-browser;
  profileGuard = pkgs.writeShellApplication {
    name = "zen-profile-guard";
    runtimeInputs = [pkgs.coreutils];
    text = builtins.readFile ./zen-browser/profile-guard.sh;
  };
  extensionIds = map (extension: extension.addonId) cfg.profiles.default.extensions.packages;
  expectedIds = [
    "@react-devtools"
    "extension@redux.devtools"
    "uBlock0@raymondhill.net"
    "{d7742d87-e61d-4b78-b8a1-b469842139fa}"
    "clipper@obsidian.md"
    "team@readwise.io"
    "{d634138d-c276-4fc8-924b-40a0ea21d284}"
  ];
  configCheck = assert cfg.enable;
  assert !cfg.setAsDefaultBrowser;
  assert cfg.package.version == inputs.zen-browser.packages.${pkgs.stdenv.hostPlatform.system}.beta-unwrapped.version;
  assert lib.sort builtins.lessThan extensionIds == lib.sort builtins.lessThan expectedIds;
  assert cfg.profiles.default.path == "default";
  assert !(builtins.hasAttr "{d634138d-c276-4fc8-924b-40a0ea21d284}" (cfg.policies.ExtensionSettings or {}));
  assert if pkgs.stdenv.hostPlatform.isDarwin
  then
    cfg.darwin.packageMode
    == "signed"
    && config.targets.darwin.linkApps.enable
    && cfg.package.drvPath == inputs.zen-browser.packages.${pkgs.stdenv.hostPlatform.system}.beta-unwrapped.drvPath
    && cfg.finalPackage.drvPath == cfg.package.drvPath
    && config.targets.darwin.defaults."app.zen-browser.zen".EnterprisePoliciesEnabled
  else
    lib.all (mime: config.xdg.mimeApps.defaultApplications.${mime} == ["zen-beta.desktop"]) [
      "x-scheme-handler/http"
      "x-scheme-handler/https"
      "text/html"
      "application/xhtml+xml"
    ];
    pkgs.runCommand "zen-browser-config" {
      nativeBuildInputs = [profileGuard pkgs.coreutils];
    } ''
      mkdir -p fresh/default
      zen-profile-guard "$PWD/fresh" "$PWD/fresh/default"
      test ! -e fresh/profiles.ini

      mkdir -p unmanaged/default
      echo 'existing profile index' > unmanaged/profiles.ini
      if zen-profile-guard "$PWD/unmanaged" "$PWD/unmanaged/default"; then
        echo 'Expected unmanaged profiles.ini to block activation' >&2
        exit 1
      fi
      rm unmanaged/profiles.ini
      echo 'private data' > unmanaged/default/prefs.js
      if zen-profile-guard "$PWD/unmanaged" "$PWD/unmanaged/default"; then
        echo 'Expected unmanaged profile contents to block activation' >&2
        exit 1
      fi
      test "$(cat unmanaged/default/prefs.js)" = 'private data'

      mkdir -p managed/default
      ln -s ${pkgs.writeText "zen-profile-fixture" "managed"} managed/profiles.ini
      ln -s ${pkgs.writeText "zen-profile-keep-fixture" ""} managed/default/.keep
      echo 'preserve across rebuilds' > managed/default/prefs.js
      zen-profile-guard "$PWD/managed" "$PWD/managed/default"
      zen-profile-guard "$PWD/managed" "$PWD/managed/default"
      test "$(cat managed/default/prefs.js)" = 'preserve across rebuilds'
      mkdir "$out"
      cp ${pkgs.writeText "zen-config.json" (builtins.toJSON {
        version = cfg.package.version;
        inherit extensionIds;
        profile = cfg.profiles.default.path;
      })} "$out/config.json"
    '';
in {
  imports = [
    inputs.zen-browser.homeModules.beta
  ];

  options.private.zenBrowserCheck = lib.mkOption {
    type = lib.types.package;
    internal = true;
    readOnly = true;
    description = "Zen cross-host configuration and read-only profile preflight regression check.";
  };

  config = {
    private.zenBrowserCheck = configCheck;

    home.activation.checkZenProfileOwnership = lib.hm.dag.entryBefore ["checkLinkTargets"] ''
      ${lib.getExe profileGuard} ${lib.escapeShellArg cfg.configPath} ${lib.escapeShellArg "${cfg.profilesPath}/${cfg.profiles.default.path}"}
    '';

    programs.zen-browser = {
      enable = true;
      # Keep the Linux MIME list narrow; Darwin uses LaunchServices separately.
      setAsDefaultBrowser = false;

      profiles.default = {
        extensions.packages = with firefox-addons; [
          react-devtools
          reduxdevtools
          ublock-origin
          vimium
          web-clipper-obsidian
          readwise-highlighter
          onepassword-password-manager
        ];
      };
    };
  };
}
