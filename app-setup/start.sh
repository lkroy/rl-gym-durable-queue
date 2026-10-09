#!/usr/bin/env bash
# Starts the model runtime so the verifier can interact with it.
# `q` is a short-lived CLI (no daemon); starting = ensuring a state dir.
set -u
mkdir -p "${QDATA_DIR:-.qdata}"
echo "READY"
