#!/usr/bin/env bash
# bushfire_atlas — SessionStart hook. Installs the dev packages the suite needs
# (requirements-dev.txt) when one is missing, so a missing package never reads as a
# regression [F8]. Import-check first: a warm container is a no-op. Never fails the
# session: no network is a legitimate state, and it says so.
cd "$(dirname "$0")/../.." || exit 0
missing=""
for mod in flask pyarrow pytest pandas playwright; do
  python3 -c "import $mod" 2>/dev/null || missing="$missing $mod"
done
if [ -z "$missing" ]; then
  echo "bootstrap: dev packages present"
  exit 0
fi
echo "bootstrap: missing:$missing; installing requirements-dev.txt"
if ! python3 -m pip install -q -r requirements-dev.txt 2>&1 | tail -5; then
  echo "bootstrap: pip failed (no network?); the suite will name what is missing"
fi
exit 0
