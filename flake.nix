{
  description = "Inplace-Unpack — extract huge ZIPs on a nearly full disk via fallocate hole punching";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "i686-linux" "riscv64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      mkPackage = pkgs:
        let
          pythonEnv = pkgs.python3.withPackages (ps: [ ps.tkinter ]);
        in
        pkgs.stdenv.mkDerivation {
          pname = "inplace-unpack";
          version = "0.5.0";
          src = self;

          nativeBuildInputs = [ pkgs.makeWrapper ];
          buildInputs = [ pythonEnv ];

          dontBuild = true;

          installPhase = ''
            runHook preInstall

            mkdir -p $out/share/inplace-unpack $out/bin \
                     $out/share/applications \
                     $out/share/icons/hicolor/512x512/apps

            cp -r inplace_unpack assets $out/share/inplace-unpack/
            find $out/share/inplace-unpack -name "__pycache__" -type d -exec rm -rf {} +

            cp assets/icon.png $out/share/icons/hicolor/512x512/apps/inplace-unpack.png
            cp packaging/inplace-unpack.desktop $out/share/applications/inplace-unpack.desktop
            substituteInPlace $out/share/applications/inplace-unpack.desktop \
              --replace-fail "Exec=inplace-unpack %f" "Exec=$out/bin/inplace-unpack %f"

            makeWrapper ${pythonEnv}/bin/python3 $out/bin/inplace-unpack \
              --set PYTHONPATH "$out/share/inplace-unpack" \
              --add-flags "-m inplace_unpack.gui"

            makeWrapper ${pythonEnv}/bin/python3 $out/bin/inplace-unpack-cli \
              --set PYTHONPATH "$out/share/inplace-unpack" \
              --add-flags "-m inplace_unpack.cli"

            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "Unzip huge ZIP files on a nearly full disk by punching holes as you extract";
            homepage = "https://github.com/HaswellHD/InPlace_UnPack";
            license = licenses.mit;
            platforms = platforms.linux;
            mainProgram = "inplace-unpack";
          };
        };
    in
    {
      packages = forAllSystems (pkgs: rec {
        inplace-unpack = mkPackage pkgs;
        default = inplace-unpack;
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/inplace-unpack";
        };
        cli = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/inplace-unpack-cli";
        };
      });

      overlays.default = final: prev: {
        inplace-unpack = mkPackage final;
      };
    };
}
