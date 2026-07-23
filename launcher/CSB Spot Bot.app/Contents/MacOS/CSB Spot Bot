#!/bin/bash
# CSB Spot Bot — macOS .app entry point (no Terminal window).
#
# LaunchServices apps under Desktop cannot read the project/.venv (TCC).
# This entry point registers a per-user LaunchAgent (full user file access)
# that starts the existing Flet app + BotEngine, then exits.

HERE="$(cd "$(dirname "$0")" && pwd)"
# MacOS -> Contents -> .app -> launcher -> <repo root>
PROJECT_ROOT="$(cd "${HERE}/../../../.." && pwd)"

SUPPORT_DIR="${HOME}/Library/Application Support/CSBSpotBot"
LOG_DIR="${HOME}/Library/Logs/CSBSpotBot"
AGENTS_DIR="${HOME}/Library/LaunchAgents"
HELPER="${SUPPORT_DIR}/start_bot.sh"
LOG_FILE="${LOG_DIR}/launcher.log"
LABEL="com.csb.spotbot.gui"
PLIST="${AGENTS_DIR}/${LABEL}.plist"

mkdir -p "${SUPPORT_DIR}" "${LOG_DIR}" "${AGENTS_DIR}"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') entry ====="
  echo "HERE=${HERE}"
  echo "PROJECT_ROOT=${PROJECT_ROOT}"
} >>"${LOG_FILE}" 2>/dev/null || true

alert() {
  /usr/bin/osascript -e "display alert \"CSB Spot Bot\" message \"$1\" as critical" >/dev/null 2>&1 || true
}

Q_PROJECT="$(printf '%q' "${PROJECT_ROOT}")"
Q_LOG="$(printf '%q' "${LOG_FILE}")"

cat > "${HELPER}" << HELPER_EOF
#!/bin/bash
set -e
PROJECT_ROOT=${Q_PROJECT}
LOG_FILE=${Q_LOG}
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:\${PATH:-}"

{
  echo "===== \$(date '+%Y-%m-%d %H:%M:%S %z') agent ====="
  echo "Project: \${PROJECT_ROOT}"
} >> "\${LOG_FILE}" 2>/dev/null || true

cd "\${PROJECT_ROOT}"

if [ ! -f "\${PROJECT_ROOT}/main.py" ]; then
  echo "ERROR: main.py not found in \${PROJECT_ROOT}" >> "\${LOG_FILE}"
  /usr/bin/osascript -e 'display alert "CSB Spot Bot" message "main.py not found. Keep CSB Spot Bot.app inside project/launcher (use a Desktop alias; do not move the .app alone)." as critical' >/dev/null 2>&1 || true
  exit 1
fi

PYTHON3="\$(command -v python3 || true)"
if [ -z "\${PYTHON3}" ]; then
  echo "ERROR: python3 not found" >> "\${LOG_FILE}"
  /usr/bin/osascript -e 'display alert "CSB Spot Bot" message "python3 was not found. Install Python 3 and try again." as critical' >/dev/null 2>&1 || true
  exit 1
fi

if [ ! -d "\${PROJECT_ROOT}/.venv" ]; then
  echo "Creating virtual environment..." >> "\${LOG_FILE}"
  "\${PYTHON3}" -m venv "\${PROJECT_ROOT}/.venv"
  "\${PROJECT_ROOT}/.venv/bin/pip" install --upgrade pip
  if [ -f "\${PROJECT_ROOT}/requirements.txt" ]; then
    "\${PROJECT_ROOT}/.venv/bin/pip" install -r "\${PROJECT_ROOT}/requirements.txt"
  fi
fi

if [ ! -x "\${PROJECT_ROOT}/.venv/bin/python" ]; then
  echo "ERROR: .venv/bin/python missing" >> "\${LOG_FILE}"
  exit 1
fi

echo "Starting main.py ..." >> "\${LOG_FILE}"
exec "\${PROJECT_ROOT}/.venv/bin/python" "\${PROJECT_ROOT}/main.py" >>"\${LOG_FILE}" 2>&1
HELPER_EOF

chmod +x "${HELPER}"

# Escape XML special chars in paths for the plist.
xml_escape() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'
}
X_HELPER="$(xml_escape "${HELPER}")"
X_LOG="$(xml_escape "${LOG_FILE}")"

cat > "${PLIST}" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>${LABEL}</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>${X_HELPER}</string>
	</array>
	<key>RunAtLoad</key>
	<false/>
	<key>KeepAlive</key>
	<false/>
	<key>StandardOutPath</key>
	<string>${X_LOG}</string>
	<key>StandardErrorPath</key>
	<string>${X_LOG}</string>
</dict>
</plist>
PLIST_EOF

UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
SERVICE="${DOMAIN}/${LABEL}"

# Replace any previous registration, then kickstart once.
/bin/launchctl bootout "${SERVICE}" >/dev/null 2>&1 || true
if ! /bin/launchctl bootstrap "${DOMAIN}" "${PLIST}" >>"${LOG_FILE}" 2>&1; then
  # Older macOS fallback
  /bin/launchctl unload "${PLIST}" >/dev/null 2>&1 || true
  if ! /bin/launchctl load "${PLIST}" >>"${LOG_FILE}" 2>&1; then
    alert "Failed to register launcher service. See ~/Library/Logs/CSBSpotBot/launcher.log"
    exit 1
  fi
  /bin/launchctl start "${LABEL}" >>"${LOG_FILE}" 2>&1 || true
else
  if ! /bin/launchctl kickstart -k "${SERVICE}" >>"${LOG_FILE}" 2>&1; then
    alert "Failed to start CSB Spot Bot. See ~/Library/Logs/CSBSpotBot/launcher.log"
    exit 1
  fi
fi

echo "$(date '+%Y-%m-%d %H:%M:%S %z') kickstart OK (${SERVICE})" >>"${LOG_FILE}" 2>/dev/null || true
exit 0
