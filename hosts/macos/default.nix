{
  config,
  host,
  ...
}: let
  home = config.home-manager.users.${host.username};
in {
  networking.hostName = host.hostname;
  system.stateVersion = host.systemStateVersion;
  homebrew.casks = ["1password" "peteonrails/voxtype/voxtype"];

  local.dock.entries = [
    {path = "/Applications/Slack.app/";}
    {
      path = "/Applications/1Password.app/";
      optional = true;
    }
    {path = "/System/Applications/Messages.app/";}
    {path = "/System/Applications/FaceTime.app/";}
    {path = "${home.home.homeDirectory}/${home.targets.darwin.linkApps.directory}/kitty.app";}
    {path = "/System/Applications/Notes.app/";}
    {
      path = "/Applications/WhatsApp.app/";
      optional = true;
    }
    {path = "/Applications/Obsidian.app/";}
    {
      path = "/Applications/Notion.app/";
      optional = true;
    }
    {path = "/Applications/Notion Calendar.app/";}
    {
      path = "${host.homeDirectory}/Applications/WebStorm.app";
      optional = true;
    }
    {
      path = "${host.homeDirectory}/Applications/Android Studio.app/";
      optional = true;
    }
    {path = "/System/Applications/Music.app/";}
    {path = "/Applications/Linear.app/";}
    {path = "${home.home.homeDirectory}/${home.targets.darwin.linkApps.directory}/${home.programs.zen-browser.package.applicationName}.app";}
    {
      path = "/System/Applications/iPhone Mirroring.app/";
      optional = true;
    }
    {
      path = "/Applications/";
      section = "others";
      options = ["--sort" "name" "--view" "grid" "--display" "folder"];
    }
    {
      path = "${host.homeDirectory}/Downloads/";
      section = "others";
      options = ["--sort" "name" "--view" "grid" "--display" "folder"];
    }
    {
      path = "${host.homeDirectory}/Desktop/";
      section = "others";
      options = ["--sort" "name" "--view" "grid" "--display" "folder"];
    }
  ];
}
