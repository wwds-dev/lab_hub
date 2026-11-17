#!/bin/bash
# Remove Qt modules that Lab Hub never uses and that Qt does not offer under
# the LGPL from a built "Lab Hub.app". Usage: prune_gpl_qt.sh <path/to/App.app>
#
# GPL-3.0-only per the legal audit (docs/audit/legal.md, P1 1): Qt Graphs,
# Qt Quick 3D incl. Physics, Qt Quick Timeline, Qt Virtual Keyboard. Also Qt
# Charts and Qt Data Visualization: unused (build_app.sh already excludes their
# Python bindings) and offered by Qt under GPL-3.0 or commercial terms only.
#
# PySide6's PyInstaller hooks collect these frameworks, QML modules and plugins
# even when their Python bindings are excluded. The patterns name the modules
# exactly, so the LGPL-3.0 Qt Quick, Qt 3D (Qt3D*, qml/Qt3D) and Qt WebEngine
# files stay. Fails if anything matching a looser check survives, if anything
# left still links a removed module, or if a symlink is left dangling.
set -euo pipefail

APP="${1:?usage: $0 <path/to/App.app>}"
[[ -d "$APP/Contents" ]] || { echo "error: $APP is not an app bundle" >&2; exit 1; }

MODULES='Graphs|Quick3D|QuickTimeline|VirtualKeyboard|Charts|DataVisualization'
LOWER='graphs|quick3d|quicktimeline|virtualkeyboard|charts|datavisualization'
PRUNE="(^|/)(Qt($MODULES)[A-Za-z0-9]*\.(framework|abi3\.so|pyi)"
PRUNE+="|qt6($LOWER)[a-z0-9]*_metatypes\.json"
PRUNE+="|qml/Qt(Graphs|Quick3D|Charts|DataVisualization)|qml/QtQuick/(Timeline|VirtualKeyboard)"
PRUNE+="|libqtvirtualkeyboardplugin\.dylib|libqmldbg_quick3dprofiler\.dylib)$"

# List first, then delete: removing a directory while find walks it is noisy.
doomed=()
while IFS= read -r -d '' p; do
  [[ "$p" =~ $PRUNE ]] && doomed+=("$p")
done < <(find "$APP/Contents" -print0)

pruned=0
for path in ${doomed[@]+"${doomed[@]}"}; do
  [[ -e "$path" || -L "$path" ]] || continue  # already gone with its parent
  rm -rf "$path"
  pruned=$((pruned + 1))
done

# PyInstaller also links each framework from Contents/Resources; drop the links
# left pointing at what was just removed (codesign refuses dangling ones).
while IFS= read -r -d '' link; do
  if [[ "$(readlink "$link")" =~ Qt($MODULES)|$PRUNE ]]; then
    rm -f "$link"
    pruned=$((pruned + 1))
  fi
done < <(find "$APP/Contents" -type l ! -exec test -e {} \; -print0)
echo "Pruned $pruned unused GPL-only Qt items from the bundle."

failed=0

# A looser, case-insensitive check than the one that deleted, so a module that
# a PySide6 update renames or moves fails the build instead of shipping.
# Matched at the start of a path component; qml/Qt3D (LGPL Qt 3D, whose
# plugins are named libquick3d*plugin) is left out.
survivors="$(find "$APP/Contents" | grep -iE "(^|/)(lib)?(qt6?|q)?($LOWER)" \
  | grep -v '/qml/Qt3D/' || true)"
if [[ -n "$survivors" ]]; then
  echo "error: unused GPL-only Qt modules are still in the bundle:" >&2
  echo "$survivors" >&2
  failed=1
fi

if [[ "${PRUNE_SKIP_OTOOL:-}" != 1 ]]; then
  if ! otool -L /usr/bin/true >/dev/null 2>&1; then
    echo "error: otool is unavailable (install the Xcode Command Line Tools)" >&2
    exit 1
  fi
  linked="$(find "$APP/Contents" -type f \( -name '*.dylib' -o -name '*.so' -o -perm -u+x \) -print0 \
    | xargs -0 otool -L 2>/dev/null | grep -E "Qt($MODULES)" || true)"
  if [[ -n "$linked" ]]; then
    echo "error: the bundle still links a removed Qt module:" >&2
    echo "$linked" >&2
    failed=1
  fi
fi

dangling="$(find "$APP/Contents" -type l ! -exec test -e {} \; -print)"
if [[ -n "$dangling" ]]; then
  echo "error: dangling symlinks in the bundle (codesign will refuse them):" >&2
  echo "$dangling" >&2
  failed=1
fi

exit "$failed"
