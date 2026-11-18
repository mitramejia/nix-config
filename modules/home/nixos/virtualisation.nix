{pkgs, ...}: let
  tools = with pkgs; [acl coreutils kmod systemd util-linux];
  guard = pkgs.writeShellScript "xbox-firmware-usb-guard" ''
    export PATH=${pkgs.lib.makeBinPath tools}
    exec ${pkgs.python3}/bin/python3 -I ${./scripts/xbox-firmware-vm/usb_guard.py} "$@"
  '';
  resolver = pkgs.writeShellScript "xbox-firmware-iso-resolver" ''
    export XBOX_CHROMIUM=${pkgs.chromium}/bin/chromium
    export XBOX_CHROMEDRIVER=${pkgs.chromedriver}/bin/chromedriver
    exec ${(pkgs.python3.withPackages (ps: [ps.selenium ps.websocket-client]))}/bin/python3 -I ${./scripts/xbox-firmware-vm/iso_metadata.py} "$@"
  '';
  guestTools = pkgs.runCommand "xbox-firmware-guest-tools.iso" {nativeBuildInputs = [pkgs.xorriso];} ''
    mkdir tools
    cp ${./scripts/xbox-firmware-vm/guest-awake.ps1} tools/guest-awake.ps1
    cp ${./scripts/xbox-firmware-vm/guest-tools.cmd} tools/guest-tools.cmd
    printf '%s\n' 'Read and run guest-tools.cmd yourself in Windows. No autorun or security bypass.' > tools/README.txt
    xorriso -as mkisofs -quiet -J -r -V XBOX_TOOLS -o "$out" tools
  '';
  backend = pkgs.writeShellScript "xbox-firmware-vm-backend" ''
    export XBOX_USB_GUARD=${guard}
    export XBOX_OVMF=${pkgs.OVMFFull.fd}/FV
    export XBOX_QEMU=${pkgs.qemu}/bin/qemu-system-x86_64
    export XBOX_ISO_RESOLVER=${resolver}
    export XBOX_GUEST_TOOLS=${guestTools}
    exec ${pkgs.python3}/bin/python3 -I ${./scripts/xbox-firmware-vm/vm.py} "$@"
  '';
in {
  home.packages = [
    (pkgs.writeShellApplication {
      name = "xbox-firmware-vm";
      runtimeInputs = with pkgs; [
        coreutils
        util-linux
        libvirt
        qemu
        swtpm
        virt-viewer
        xdg-utils
        libnotify
        python3
      ];
      # Preserve the shared wizard library verbatim: SC1087 is its literal
      # Readline prompt '[Enter...]'; SC2329 covers unused/indirect helpers.
      excludeShellChecks = ["SC1087" "SC2329"];
      text = ''
        export XBOX_FIRMWARE_BACKEND=${backend}
        export XBOX_GUEST_AWAKE=${./scripts/xbox-firmware-vm/guest-awake.ps1}
        ${builtins.readFile ./scripts/xbox-firmware-vm/wizard.sh}
      '';
    })
  ];
}
