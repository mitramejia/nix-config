{
  lib,
  appimageTools,
  fetchurl,
}:
# Neither pinned nixpkgs set provides xtool yet; use the upstream Linux release.
appimageTools.wrapType2 rec {
  pname = "xtool";
  version = "1.24.0";

  src = fetchurl {
    url = "https://github.com/xtool-org/xtool/releases/download/${version}/xtool-x86_64.AppImage";
    hash = "sha256-2/2dchbwd8hMFxtojEFzw3wjyna/f9GF0amuilPatZ8=";
  };

  meta = {
    description = "Cross-platform Xcode replacement";
    homepage = "https://xtool.sh";
    license = lib.licenses.mit;
    mainProgram = "xtool";
    platforms = ["x86_64-linux"];
  };
}
