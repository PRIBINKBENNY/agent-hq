#!/bin/zsh
# Installs Agent HQ as a macOS launch agent: starts the dashboard (which runs the scheduler)
# at login and restarts it if it crashes. Free, no third-party tools.
#   ./office/launchd/install.sh      install / update
#   ./office/launchd/install.sh off  uninstall
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.pribin.agenthq"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "$1" == "off" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Agent HQ launch agent removed."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/office/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string>
    <string>$ROOT/office/dashboard.py</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$ROOT/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$ROOT/office/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/office/logs/launchd.err.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Agent HQ launch agent installed: starts at login, restarts on crash. Dashboard: http://localhost:8787"
