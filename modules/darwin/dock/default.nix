#
# Fully declarative dock using dockutil
# Original source: https://gist.github.com/antifuchs/10138c4d838a63c0a05e725ccd7bccdd
{
  config,
  pkgs,
  lib,
  ...
}: let
  cfg = config.local.dock;
  inherit (lib) concatMapStrings concatStringsSep escapeShellArg escapeURL hasSuffix mkAfter mkIf mkOption optionalString splitString types;
  inherit (pkgs) dockutil stdenv;
in {
  options.local.dock = {
    enable = mkOption {
      description = "Enable dock";
      default = stdenv.isDarwin;
      example = false;
    };

    entries = mkOption {
      description = "Entries on the Dock";
      type = with types;
        listOf (submodule {
          options = {
            path = lib.mkOption {type = str;};
            optional = lib.mkOption {
              type = bool;
              default = false;
              description = "Warn and skip this entry when its path does not exist.";
            };
            section = lib.mkOption {
              type = str;
              default = "apps";
            };
            options = lib.mkOption {
              type = listOf str;
              default = [];
            };
          };
        });
      readOnly = true;
    };
    username = mkOption {
      description = "Username to apply the dock settings to";
      default = config.system.primaryUser;
      type = types.str;
    };
  };

  config = mkIf cfg.enable (
    let
      normalize = path:
        if hasSuffix ".app" path
        then path + "/"
        else path;
      entryURI = path:
        "file://"
        + concatStringsSep "/" (map escapeURL (splitString "/" (normalize path)));
      validateEntries = concatMapStrings (entry: let
        path = normalize entry.path;
      in
        optionalString (!entry.optional) ''
          if [ ! -e ${escapeShellArg path} ]; then
            printf '%s\n' ${escapeShellArg "Dock entry does not exist: ${path}"} >&2
            exit 1
          fi
        '')
      cfg.entries;
      writeExpectedURIs = concatMapStrings (entry: let
        path = normalize entry.path;
        writeURI = "printf '%s\\n' ${escapeShellArg (entryURI path)} >> \"$dock_state/want-uris\"";
      in
        if entry.optional
        then ''
          if [ -e ${escapeShellArg path} ]; then
            ${writeURI}
          else
            printf '%s\n' ${escapeShellArg "Optional Dock entry does not exist; skipping: ${path}"} >&2
          fi
        ''
        else "${writeURI}\n")
      cfg.entries;
      createEntries =
        concatMapStrings (
          entry: let
            path = normalize entry.path;
            addEntry = "${dockutil}/bin/dockutil --no-restart --add ${escapeShellArg path} --section ${escapeShellArg entry.section}${concatMapStrings (option: " ${escapeShellArg option}") entry.options}";
          in
            if entry.optional
            then ''
              if [ -e ${escapeShellArg path} ]; then
                ${addEntry}
              fi
            ''
            else "${addEntry}\n"
        )
        cfg.entries;
    in {
      # Home Manager creates the stable app links in its postActivation script.
      system.activationScripts.postActivation.text = mkAfter ''
          echo >&2 "Setting up the Dock for ${cfg.username}..."
          su ${escapeShellArg cfg.username} -s /bin/sh <<'USERBLOCK'
        set -eu
        ${validateEntries}
        dock_state="$(${pkgs.coreutils}/bin/mktemp -d -t dock-state.XXXXXX)"
        dock_was_running=false
        trap '
          if [ "$dock_was_running" = true ]; then
            /usr/bin/killall -CONT Dock >/dev/null 2>&1 || true
          fi
          ${pkgs.coreutils}/bin/rm -rf "$dock_state"
        ' EXIT

        : > "$dock_state/want-uris"
        ${writeExpectedURIs}

        if ! ${dockutil}/bin/dockutil --list > "$dock_state/list"; then
          echo >&2 "Cannot read the Dock; leaving it unchanged."
          exit 1
        fi

        ${pkgs.gawk}/bin/awk -F '\t' '$3 != "recentApps" {print $2}' "$dock_state/list" > "$dock_state/uris"
        if ${pkgs.diffutils}/bin/diff -wu "$dock_state/uris" "$dock_state/want-uris" >&2; then
          echo >&2 "Dock setup complete."
        else
          diff_status=$?
          if [ "$diff_status" -ne 1 ]; then
            echo >&2 "Cannot compare the current Dock; leaving it unchanged."
            exit "$diff_status"
          fi

          echo >&2 "Resetting Dock."
          if /usr/bin/pgrep -x Dock >/dev/null; then
            dock_was_running=true
            /usr/bin/killall -STOP Dock || true
          fi
          ${dockutil}/bin/dockutil --no-restart --remove all
          ${createEntries}
          if [ "$dock_was_running" = true ]; then
            /usr/bin/killall -KILL Dock || true
          else
            echo >&2 "Dock was not running; skipping restart."
          fi
        fi
        USERBLOCK
      '';
    }
  );
}
