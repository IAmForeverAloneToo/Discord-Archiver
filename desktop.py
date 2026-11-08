"""Launch the window by default; preserve command-line access in packaged builds."""

import sys

from discord_archiver.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["gui"]))
