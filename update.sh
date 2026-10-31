#!/usr/bin/env bash
# Inlet: relay. The user unit stream-box-update.service of images 0.5.0 and older starts ~/stream-box/update.sh:
# the script is now scripts/update.sh. To remove once no box runs those images.
exec "$(dirname "$(readlink -f "$0")")/scripts/update.sh" "$@"
