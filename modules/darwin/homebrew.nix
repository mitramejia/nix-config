{
  config,
  host,
  inputs,
  ...
}: {
  nix-homebrew = {
    enable = true;
    user = host.username;
    autoMigrate = true;
    mutableTaps = false;
    taps = {
      "homebrew/homebrew-core" = inputs.homebrew-core;
      "homebrew/homebrew-cask" = inputs.homebrew-cask;
      "homebrew/homebrew-bundle" = inputs.homebrew-bundle;
      "peteonrails/homebrew-voxtype" = inputs.homebrew-voxtype;
    };
  };

  homebrew = {
    enable = true;
    taps = builtins.attrNames config.nix-homebrew.taps;
    casks = import ./casks.nix;
    onActivation.cleanup = "uninstall";
  };
}
