{
  pkgs,
  unstablePkgs,
  inputs,
  ...
}: {
  home.packages = with pkgs; [
    zapzap
    slack
    inputs.claude-desktop.packages.${pkgs.stdenv.hostPlatform.system}.claude-desktop
    zoom-us
    thunderbird
    # Aerion is not available in the pinned stable package set.
    unstablePkgs.aerion
    localsend
    virtualbox
    trimage

    obsidian
    gimp
    pinta
    # Disktree is not available in the pinned stable package set.
    unstablePkgs.disktree
    libreoffice
    vlc
    trash-cli
    alpine
    code-cursor
    jetbrains-toolbox
    (callPackage ./xtool.nix {})
    # Swift 6.4 packages SwiftPM separately; xtool needs swift sdk/build.
    unstablePkgs.swiftpm
    libimobiledevice
    chromedriver
    amdgpu_top

    wireplumber
    libgtop
    bluez
    networkmanager
    dart-sass
    wl-clipboard
    upower
    gvfs
    obs-studio
    gpu-screen-recorder
    satty
    hyprpicker
    hyprsunset
    inputs.hyprmod.packages.${pkgs.stdenv.hostPlatform.system}.default
    yubikey-manager
    yubioath-flutter
  ];
}
