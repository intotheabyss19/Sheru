#!/bin/bash
# Install Sheru as a LaunchAgent: auto-start at login, survive restarts, crash-recover, and (crucially) show its
# menu-bar icon. The /Applications/Sheru.app shim exec's a python OUTSIDE its bundle, so macOS treats it as a
# faceless process and the menu-bar status item collapses to zero height; a LaunchAgent runs in the Aqua GUI
# session and lays the item out correctly. Run once:  bash packaging/install-autostart.sh
set -e
PLIST="$HOME/Library/LaunchAgents/com.sheru.assistant.plist"
cp "$(dirname "$0")/com.sheru.assistant.plist" "$PLIST"
launchctl bootout "gui/$(id -u)/com.sheru.assistant" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Sheru LaunchAgent installed + started. Manage: launchctl {bootout,kickstart -k} gui/$(id -u)/com.sheru.assistant"
