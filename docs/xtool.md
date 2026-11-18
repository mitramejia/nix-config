# iOS development with xtool (NixOS)

The NixOS configuration installs xtool 1.24.0 from its hash-pinned upstream
AppImage (x86_64 Linux only), plus libimobiledevice tools, and enables usbmuxd.
The common Home Manager package list selects Swift **6.4.0** from the existing
unstable input on Linux to meet xtool's Swift **6.4** requirement, replacing the
stable Swift **5.10.1** entry rather than adding a second toolchain. macOS keeps
its existing stable Swift selection.
Linux also installs the matching unstable SwiftPM package, which provides
`swift package`, `swift sdk`, and `swift build` separately from the compiler.
Neither pinned nixpkgs set currently includes xtool.

After applying the configuration yourself, check:

```sh
xtool --help
swift --version
systemctl status usbmuxd
```

## One-time manual setup

1. Download **Xcode 27.1** in your browser from
   <https://developer.apple.com/download/all/?q=Xcode>. Apple requires login and
   license acceptance. Keep the `.xip` outside this repository and the Nix store.
2. Run `xtool setup`. Choose API-key authentication for a paid developer account
   (a Team Key with the App Manager role), or Apple ID/password authentication.
   Enter credentials interactively; do not put them in Nix or this repository.
3. When prompted, provide the path to the downloaded Xcode `.xip`. xtool extracts
   and installs the iOS Swift SDK. Confirm `swift sdk list` includes `darwin`.
4. Connect and unlock your iPhone/iPad via USB, accept **Trust This Computer**,
   and enable **Developer Mode** under Settings → Privacy & Security if prompted.
   Use `ideviceinfo` to check that the device is reachable.

## First app

In a development directory outside this configuration repository:

```sh
xtool new Hello
cd Hello
xtool dev
```

Follow any on-device developer trust prompts before launching the app. Building,
signing, SDK extraction, and device installation require the manual setup above;
they are not performed by Nix activation.

References: [Linux setup](https://xtool.sh/documentation/xtool/installation-linux/)
and [first app tutorial](https://xtool.sh/tutorials/xtool/first-app/).
