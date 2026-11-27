{
  config,
  lib,
  pkgs,
  ...
}: let
  inherit (lib) mkDefault mkIf mkMerge mkOption;
  inherit (pkgs.stdenv) isDarwin;
  toml = pkgs.formats.toml {};
  configFile = toml.generate "voxtype-config.toml" config.services.voxtype.settings;
in {
  options.services.voxtype.settings = mkOption {
    inherit (toml) type;
    default = {};
    description = ''
      Voxtype configuration. Platform layers set the hotkey; how the daemon
      runs is platform-specific.
    '';
  };

  config = mkMerge [
    {
      services.voxtype.settings = {
        # Voxtype rejects a config file missing any of these sections.
        hotkey = {};
        audio = {
          device = mkDefault "default";
          sample_rate = mkDefault 16000;
          max_duration_secs = mkDefault 60;
        };
        output = {
          mode = mkDefault "type";
          fallback_to_clipboard = mkDefault true;
        };
        whisper = {
          model = "large-v3-turbo";
          language = ["en" "es"];
        };
      };
    }

    # Voxtype reads its config from the platform's native config directory.
    (mkIf isDarwin {
      home.file."Library/Application Support/voxtype/config.toml".source = configFile;
    })
    (mkIf (!isDarwin) {
      xdg.configFile."voxtype/config.toml".source = configFile;
    })
  ];
}
