#!/usr/bin/env bash
# Deletes generated state/artifacts to ensure a clean rebuild.
set -u
rm -rf "${QDATA_DIR:-.qdata}"
echo "reset: OK"
