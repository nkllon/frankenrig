#!/usr/bin/env bash
# Ontology-backed operator path: bind Aux2 to the authoritative lower-left feed, then apply layout.
set -e
cd "$(dirname "$0")"
PY=".venv_obsws/bin/python3"
$PY obs_bind_aux2_by_url.py || exit 1
$PY obs_apply_pip_layout.py --no-preview
echo "done. ontology-backed proof bundle written under evidence/proof/ and latest JSON exports refreshed."
