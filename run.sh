#!/bin/bash
# usage: ./run.sh anim 480 270 24 CYCLES
BL=${BL:-blender}
DIR=$(cd "$(dirname "$0")" && pwd)
exec "$BL" -b --factory-startup -noaudio --python "$DIR/scene.py" -- "$@"
