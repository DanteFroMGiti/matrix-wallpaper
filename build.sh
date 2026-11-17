#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
cc -O2 -Wall -Wextra renderer.c -o renderer.new $(pkg-config --cflags --libs x11 xext xcomposite cairo pangocairo epoxy) -lm
mv renderer.new renderer
