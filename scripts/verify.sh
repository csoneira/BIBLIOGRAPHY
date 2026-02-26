#!/usr/bin/env bash
set -euo pipefail

python3 CODE/bib.py verify
python3 CODE/bib.py validate
python3 -m unittest discover -s tests
