"""Entry point of the Linux AppImage: one file for the window and the command line.

    ./Inplace-Unpack-x86_64.AppImage                     -> window
    ./Inplace-Unpack-x86_64.AppImage some.zip            -> window with that ZIP
    ./Inplace-Unpack-x86_64.AppImage cli some.zip out/   -> command line
    (also when the AppImage is called through a link named inplace-unpack-cli)
"""
import os
import sys


def _wants_cli() -> bool:
    if len(sys.argv) > 1 and sys.argv[1] in ("cli", "--cli"):
        del sys.argv[1]
        return True
    # AppImage runtimes put the name the AppImage was started with into $ARGV0
    name = os.path.basename(os.environ.get("ARGV0", ""))
    return name.startswith("inplace-unpack-cli")


if __name__ == "__main__":
    if _wants_cli():
        from inplace_unpack.cli import main as cli_main
        sys.exit(cli_main())
    from inplace_unpack.gui import main as gui_main
    gui_main()
