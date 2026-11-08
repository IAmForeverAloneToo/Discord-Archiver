#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ "$#" -eq 0 ]; then
    set -- gui
fi
exec python3 -m discord_archiver "$@"
