#!/usr/bin/env bash
# Abre el generador de reportes en macOS / Linux.
cd "$(dirname "$0")" || exit 1
exec python3 app.py
