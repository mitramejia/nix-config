{
  config,
  pkgs,
  ...
}: {
  imports = [
    ./hyprland
    ./clipboard.nix
    ./terminal-shortcuts.nix
    ./neovim.nix
    ./neomutt.nix
    ./android.nix
    ./packages.nix
    ./noctalia.nix
    ./noctalia-clipboard.nix
    ./zen-browser.nix
    ./virtualisation.nix
    ./stylix.nix
    ./qt.nix
    ./swapy.nix
    ./btop.nix
    ./xdg.nix
    ./yazi.nix
    ./fzf.nix
    ./lazygit.nix
    ./zsh.nix
    ./voxtype.nix
  ];

  home.file."Pictures/Wallpapers" = {
    source = ../../../assets/wallpapers;
    recursive = true;
  };

  services.espanso.enable = true;

  services.voxtype = {
    enable = true;
    package = pkgs.voxtype.override {vulkanSupport = true;};
    loadModels = [config.services.voxtype.settings.whisper.model];
    wayland.display = "wayland-1";
    # Hyprland's Super+D binds drive recording via `voxtype record`.
    settings.hotkey.enabled = false;
  };
}
