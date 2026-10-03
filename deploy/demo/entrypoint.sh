#!/bin/sh
# Demo container: record the two simulated scenes once, then loop them through the
# whole platform with the public API on port 8000.
set -e
if [ -z "$(ls -A /data/sessions 2>/dev/null)" ]; then
  upchirp sim --scene default --notes "Simulated courtyard: two people, a car, a drone-like target."
  upchirp sim --scene crossing --notes "Simulated: two people cross paths, a drone-like target hovers."
fi
exec upchirp live --session latest --host 0.0.0.0 --port 8000
