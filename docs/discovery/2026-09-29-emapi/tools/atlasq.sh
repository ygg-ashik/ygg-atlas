#!/usr/bin/env bash
# Laptop-side wrapper: forwards to the read-only query tool on the atlas EC2 box.
# SQL on stdin.  Usage:  atlasq.sh <database> [max_rows] <<'SQL' ... SQL
#                        atlasq.sh --list
set -euo pipefail
ssh -o LogLevel=ERROR atlas "\$HOME/atlas-analysis/atlasq $*"
