{config, ...}: {
  private.openCodeMutableConfigPlatform = {
    opencode = {
      seed.permission = "allow";
    };
    # Retain the private.tui alias; the shared reconciler writes V2 cli.json.
    tui.seed.keybinds.leader = "ctrl+x";
  };

  assertions = [
    # Leave the model unset so OpenCode's default applies; agents pin their own.
    {
      assertion = let
        intent = config.private.openCodeMutableConfigIntent;
      in
        !((builtins.elemAt intent 0).seed ? model)
        && (builtins.elemAt intent 0).seed.permission == "allow"
        && (builtins.elemAt intent 1).seed.keybinds.leader == "ctrl+x";
      message = "Darwin OpenCode policy must leave the model to OpenCode and retain its permission and CLI settings.";
    }
  ];
}
