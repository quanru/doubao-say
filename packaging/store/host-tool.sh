#!/bin/sh
# Desktop integration intentionally runs the corresponding host tool.
exec flatpak-spawn --host "$(basename "$0")" "$@"
