#!/bin/bash
# Rebuild the native macOS .app launcher for CSB Spot Bot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="CSB Spot Bot"
APP_DIR="${SCRIPT_DIR}/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
EXE="${MACOS}/${APP_NAME}"

echo "Building ${APP_DIR} ..."

rm -rf "${APP_DIR}"
mkdir -p "${MACOS}" "${RESOURCES}"

cat > "${CONTENTS}/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleExecutable</key>
	<string>CSB Spot Bot</string>
	<key>CFBundleIdentifier</key>
	<string>com.csb.spotbot.launcher</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>CSB Spot Bot</string>
	<key>CFBundleDisplayName</key>
	<string>CSB Spot Bot</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>12.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>LSApplicationCategoryType</key>
	<string>public.app-category.finance</string>
	<key>NSDesktopFolderUsageDescription</key>
	<string>CSB Spot Bot needs access to the project folder to start the trading application.</string>
	<key>NSDocumentsFolderUsageDescription</key>
	<string>CSB Spot Bot needs access to the project folder to start the trading application.</string>
	<key>NSDownloadsFolderUsageDescription</key>
	<string>CSB Spot Bot needs access to the project folder to start the trading application.</string>
</dict>
</plist>
PLIST

printf 'APPL????' > "${CONTENTS}/PkgInfo"

# Copy the checked-in executable template into the bundle.
cp "${SCRIPT_DIR}/macos_app_executable.sh" "${EXE}"
chmod +x "${EXE}"
xattr -dr com.apple.quarantine "${APP_DIR}" 2>/dev/null || true

echo "Built: ${APP_DIR}"
echo
echo "Desktop tip: do NOT copy/move the .app alone (relative project paths break)."
echo "  Create an alias or symlink instead, e.g.:"
echo "  ln -sf \"${APP_DIR}\" \"${HOME}/Desktop/CSB Spot Bot.app\""
echo
echo "Logs: ~/Library/Logs/CSBSpotBot/launcher.log"
echo "No project logo/icns found — using the default macOS app icon."
