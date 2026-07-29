#!/usr/bin/env bash
# Dich .ui -> .py. Chi chay lai khi sua file .ui trong Designer.
#   pyside6-designer laptop/ui/main_window.ui
set -e
cd "$(dirname "$0")/.."
for f in laptop/ui/*.ui; do
    pyside6-uic "$f" -o "${f%.ui}_ui.py"
    echo "uic  $f -> ${f%.ui}_ui.py"
done
