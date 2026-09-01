#!/bin/bash
# Builds "Lab Hub.app" with PyInstaller into dist.noindex/.
# Pass --install to also copy it into /Applications.
#
# The output folder is named ".noindex" deliberately. It lives under
# ~/Documents, which Spotlight indexes, and a built .app sitting there shows up
# as a second "Lab Hub" next to the installed one — re-registered on every
# build, because each rebuild re-signs the bundle with a new ad-hoc identity.
# Spotlight skips any directory whose name ends in .noindex.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Lab Hub"
BUNDLE_ID="com.netrunner3000.labhub"
DIST="dist.noindex"

source .venv/bin/activate
uv pip install -q pyinstaller

# Regenerate the icon so the bundle never ships a stale one.
python assets/make_icon.py

rm -rf build dist "$DIST"

pyinstaller --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --icon assets/icon.icns \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --distpath "$DIST" \
  --add-data "assets/icon.icns:assets" \
  --add-data "assets/tray.png:assets" \
  --add-data "assets/tray@2x.png:assets" \
  --hidden-import lab_hub.tools.narrator.converter \
  --exclude-module PySide6.QtWebEngineCore \
  --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.Qt3DCore \
  --exclude-module PySide6.QtCharts \
  --exclude-module PySide6.QtDataVisualization \
  --exclude-module PySide6.QtMultimedia \
  --exclude-module PySide6.QtQuick3D \
  --exclude-module tkinter \
  main.py

# Start life as a menu bar accessory: no Dock icon, no ⌘-Tab entry. The app
# promotes itself to a regular Dock app whenever it actually shows a window,
# and drops back when the window closes. Setting this at runtime alone is not
# enough — LaunchServices pins a bundled app's type from Info.plist at launch,
# so the runtime call was being ignored in the .app while working from source.
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" \
  "$DIST/$APP_NAME.app/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" \
     "$DIST/$APP_NAME.app/Contents/Info.plist"

# Re-sign: editing Info.plist invalidates the ad-hoc signature PyInstaller made.
codesign --force --deep -s - "$DIST/$APP_NAME.app" 2>/dev/null || true

# Confirm the bundle actually works before it is installed: Pillow ships a
# binary extension, and a missing icon or a config path inside the bundle are
# both invisible until someone runs it.
echo
echo "Self-testing the build…"
"$DIST/$APP_NAME.app/Contents/MacOS/$APP_NAME" --selftest

echo
echo "Built: $DIST/$APP_NAME.app ($(du -sh "$DIST/$APP_NAME.app" | cut -f1))"

if [[ "${1:-}" == "--install" ]]; then
  rm -rf "/Applications/$APP_NAME.app"
  cp -R "$DIST/$APP_NAME.app" /Applications/
  touch "/Applications/$APP_NAME.app"  # nudge Finder/Dock to refresh the cached icon
  echo "Installed: /Applications/$APP_NAME.app"

  # Nothing left behind to be indexed or backed up.
  rm -rf build "$DIST"
  echo "Cleaned: build/ and $DIST/"
else
  echo "Run '$0 --install' to copy it into /Applications."
  echo "$DIST/ is skipped by Spotlight; --install removes it entirely."
fi
