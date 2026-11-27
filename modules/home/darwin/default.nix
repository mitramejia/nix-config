{host, ...}: {
  imports = [
    ./codex.nix
    ./git.nix
    ./opencode.nix
    ./packages.nix
    ./shell.nix
    ./ssh.nix
    ./zen-browser.nix
  ];

  # Voxtype is installed by the Homebrew cask in hosts/macos.
  services.voxtype.settings.hotkey = {
    key = "D";
    modifiers = ["LEFTMETA"];
  };

  home = {
    enableNixpkgsReleaseCheck = false;
    inherit (host) username homeDirectory;
    stateVersion = host.homeStateVersion;
  };
}
