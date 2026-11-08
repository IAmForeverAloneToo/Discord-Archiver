#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 -m discord_archiver gui "$@"
