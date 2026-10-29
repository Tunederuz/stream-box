#!/usr/bin/env bash
# Stream Box: relay. Boxes whose image is 0.5.0 or older start the session from here (stream-box-session,
# stream-box.desktop): the script is now scripts/start.sh. To remove once no box runs those images.
exec "$(dirname "$(readlink -f "$0")")/scripts/start.sh" "$@"
