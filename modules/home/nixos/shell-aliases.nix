{host, ...}: {
  sv = "sudo nvim";
  open = "xdg-open";
  fr = "nh os switch --hostname ${host.key} ${host.nixConfig}";
  # A full flake update can replace systemd and re-exec the user manager.
  # Activate it at the next boot instead of interrupting Hyprland live.
  # gh supplies a GitHub token so updating every input stays under the API rate limit.
  fu = "NIX_CONFIG=\"access-tokens = github.com=$(gh auth token)\" nh os boot --ask --hostname ${host.key} --update ${host.nixConfig}";
  ncg = "nix-collect-garbage --delete-older-than 15d && sudo nix-collect-garbage --delete-older-than 15d && sudo /run/current-system/bin/switch-to-configuration boot";
  top = "btop";
  copy = "wl-copy";
}
