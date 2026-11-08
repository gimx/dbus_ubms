#!/bin/bash
#
# Install (or with "uninstall" remove) the dbus-ubms gui-v2 UI plugin.
#
# The plugin adds "U-BMS - General" and "U-BMS - Cell Voltages" to the device page of every battery
# with /ProductId 0xBA75 (published by dbus_ubms.py). No Victron files are modified.
# Requires gui-v2 with UI plugin support (Venus OS v3.70~45 or later).

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
PLUGIN_JSON="$SCRIPT_DIR/gui-v2/Ubms/Ubms.json"
# the app directory must be named like the plugin
APP_AVAILABLE_DIR="/data/apps/available/Ubms"
APP_ENABLED_LINK="/data/apps/enabled/Ubms"

action=${1:-install}

restart_gui() {
    if [ -d /service/gui ]; then guiService=/service/gui; else guiService=/service/start-gui; fi
    if [ -d "$guiService" ]; then
        echo "Restarting GUI to load the plugin..."
        svc -t "$guiService"
    fi
}

case "$action" in
install)
    if [ ! -f "$PLUGIN_JSON" ]; then
        echo "ERROR: $PLUGIN_JSON not found, build it with gui-v2/build.sh"
        exit 1
    fi
    changed=0
    mkdir -p "$APP_AVAILABLE_DIR/gui-v2" /data/apps/enabled
    if ! cmp -s "$PLUGIN_JSON" "$APP_AVAILABLE_DIR/gui-v2/Ubms.json"; then
        echo "Installing gui-v2 UI plugin..."
        cp -f "$PLUGIN_JSON" "$APP_AVAILABLE_DIR/gui-v2/Ubms.json"
        changed=1
    fi
    if [ ! -e "$APP_ENABLED_LINK" ]; then
        ln -s "$APP_AVAILABLE_DIR" "$APP_ENABLED_LINK"
        changed=1
    fi
    if [ $changed -eq 1 ]; then
        restart_gui
    else
        echo "gui-v2 UI plugin already up to date"
    fi
    ;;
uninstall)
    if [ -e "$APP_ENABLED_LINK" ] || [ -L "$APP_ENABLED_LINK" ] || [ -d "$APP_AVAILABLE_DIR" ]; then
        echo "Removing gui-v2 UI plugin..."
        rm -f "$APP_ENABLED_LINK"
        rm -rf "$APP_AVAILABLE_DIR"
        restart_gui
    else
        echo "gui-v2 UI plugin is not installed"
    fi
    ;;
*)
    echo "Usage: $0 [install|uninstall]"
    exit 1
    ;;
esac
