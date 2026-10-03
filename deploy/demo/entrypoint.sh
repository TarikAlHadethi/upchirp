#!/bin/sh
# Demo container: record the two short simulated scenes once (sessions to ask about),
# then run the whole platform on the live 15-minute courtyard scene, public API on 8000.
set -e
if [ -z "$(ls -A /data/sessions 2>/dev/null)" ]; then
  upchirp sim --scene default --notes "Simulated courtyard: two people, a car, a drone-like target."
  upchirp sim --scene crossing --notes "Simulated: two people cross paths, a drone-like target hovers."
fi
exec upchirp live --scene courtyard --host 0.0.0.0 --port 8000
