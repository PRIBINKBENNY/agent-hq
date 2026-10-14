#!/bin/zsh
# Installs Agent HQ as a macOS launch agent: starts the dashboard (which runs the scheduler)
# at login and restarts it if it crashes. Free, no third-party tools.
#   ./office/launchd/install.sh      install / update
#   ./office/launchd/install.sh off  uninstall
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.pribin.agenthq"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "$1" == "tunnel" ]]; then
  # Free Cloudflare quick tunnel as a launch agent: public HTTPS URL for the phone app (token-protected).
  # The URL changes each time it starts; read it with: ./office/launchd/install.sh url   (or run.py --doctor)
  TP="$HOME/Library/LaunchAgents/$LABEL.tunnel.plist"
  CF="$(command -v cloudflared || echo /opt/homebrew/bin/cloudflared)"
  cat > "$TP" <<EOF3
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL.tunnel</string>
  <key>ProgramArguments</key><array><string>$CF</string><string>tunnel</string><string>--url</string><string>http://localhost:8787</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$ROOT/office/logs/tunnel.log</string>
  <key>StandardErrorPath</key><string>$ROOT/office/logs/tunnel.log</string>
</dict></plist>
EOF3
  launchctl bootout "gui/$(id -u)/$LABEL.tunnel" 2>/dev/null || true; sleep 2
  : > "$ROOT/office/logs/tunnel.log"
  launchctl bootstrap "gui/$(id -u)" "$TP" || launchctl kickstart -k "gui/$(id -u)/$LABEL.tunnel"
  for i in $(seq 1 40); do U=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$ROOT/office/logs/tunnel.log" | head -1); [[ -n "$U" ]] && break; sleep 1; done
  echo "Tunnel running. Phone app: ${U:-see office/logs/tunnel.log}/m   (token from .env)"
  exit 0
fi
if [[ "$1" == "url" ]]; then
  grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$ROOT/office/logs/tunnel.log" 2>/dev/null | head -1 | sed 's#$#/m#' || echo "no tunnel running"
  exit 0
fi
if [[ "$1" == "off" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL.tunnel" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$LABEL.tunnel.plist"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootout "gui/$(id -u)/$LABEL.awake" 2>/dev/null || true
  rm -f "$PLIST" "$HOME/Library/LaunchAgents/$LABEL.awake.plist"
  echo "Agent HQ launch agents removed."
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
sleep 2                                   # launchd needs a moment between unload and load
launchctl bootstrap "gui/$(id -u)" "$PLIST" || launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Agent HQ launch agent installed: starts at login, restarts on crash. The dashboard keeps the Mac awake on mains power while it runs."
echo "Dashboard: http://localhost:8787   Phone app: http://localhost:8787/m (via a tunnel from outside)"
