#!/bin/bash
#
# Install (or with "uninstall" remove) the dbus-ubms pages for GUI v2 on the local display.
#
# - copies PageBatteryUbms.qml and PageBatteryUbmsCellVoltages.qml into the gui-v2 battery pages
# - inserts two menu entries ("U-BMS - General", "U-BMS - Cell Voltages") into PageBattery.qml,
#   shown only for battery services whose /Mgmt/ProcessName contains "dbus_ubms"
# - if the dbus-serialbattery GUI is installed, hides its "dbus-serialbattery - General" and
#   "dbus-serialbattery - Cell Voltages" entries for those services (they stay for all other batteries)
#
# Works on top of the stock PageBattery.qml as well as on the one installed by dbus-serialbattery.
# Re-run after (re)installing the dbus-serialbattery GUI, which overwrites PageBattery.qml.
#
# The changes are kept in /data using the overlay-fs app (/data/apps/overlay-fs), which is
# installed e.g. by dbus-serialbattery:
#   bash /data/apps/dbus-serialbattery/ext/venus-os_overlay-fs/install.sh
#
# Not covered: the GUI v2 web version (remote console / VRM), it is a compiled WebAssembly build.

set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SRC_DIR="$SCRIPT_DIR/qml/gui-v2"
GUI_DIR="/opt/victronenergy/gui-v2"
PAGE_DIR="$GUI_DIR/Victron/VenusOS/pages/settings/devicelist/battery"
PAGE_BATTERY="$PAGE_DIR/PageBattery.qml"
OVERLAY_APP="dbus-ubms_gui"
PAGES="PageBatteryUbms.qml PageBatteryUbmsCellVoltages.qml"

action=${1:-install}

if [ ! -d "$GUI_DIR" ]; then
    echo "GUI v2 is not installed on this system, nothing to do."
    exit 0
fi

if [ ! -d /data/apps/overlay-fs ]; then
    echo "ERROR: /data/apps/overlay-fs not found, install it first, e.g. with"
    echo "       bash /data/apps/dbus-serialbattery/ext/venus-os_overlay-fs/install.sh"
    exit 1
fi

venusVersion=$(head -n 1 /opt/victronenergy/version)
# the pages use the gui-v2 API of Venus OS v3.60 and later (VisibleItemModel, preferredVisible)
ver=${venusVersion#v}
ver=${ver%%~*}
major=${ver%%.*}
minor=${ver#*.}
minor=${minor%%.*}
if ! (( major > 3 || (major == 3 && 10#$minor >= 60) )); then
    echo "ERROR: Venus OS $venusVersion is not supported, v3.60 or later is required."
    exit 1
fi

HIDE_MARKER='// dbus-ubms-hide'

# remove the menu entries and restore the dbus-serialbattery entries, returns 1 if nothing was there
remove_entries() {
    if [ -f "$PAGE_BATTERY" ] && grep -q "// dbus-ubms BEGIN\|$HIDE_MARKER" "$PAGE_BATTERY"; then
        # unhide first, the hide conditions reference an id inside the inserted block
        sed -i -E 's#preferredVisible: !ubmsGeneralEntry\.isUbms && \((.*)\) // dbus-ubms-hide$#preferredVisible: \1#' "$PAGE_BATTERY"
        sed -i '/\/\/ dbus-ubms BEGIN/,/\/\/ dbus-ubms END/d' "$PAGE_BATTERY"
        return 0
    fi
    return 1
}

# hide the dbus-serialbattery General and Cell Voltages entries for dbus-ubms services by
# prefixing the first preferredVisible after their text with "!ubmsGeneralEntry.isUbms && (...)"
hide_serialbattery_entries() {
    awk '
        /text: "dbus-serialbattery - (General|Cell Voltages)"/ { look = 4 }
        look > 0 && /^[ \t]*preferredVisible:/ {
            if ($0 !~ /dbus-ubms-hide/ && $0 !~ /\/\//) {
                match($0, /^[ \t]*preferredVisible:[ \t]*/)
                $0 = substr($0, 1, RLENGTH) "!ubmsGeneralEntry.isUbms && (" substr($0, RLENGTH + 1) ") // dbus-ubms-hide"
            }
            look = 0
        }
        { if (look > 0) look--; print }
    ' "$PAGE_BATTERY" > "$PAGE_BATTERY.ubms.tmp"
    mv "$PAGE_BATTERY.ubms.tmp" "$PAGE_BATTERY"
}

restart_gui() {
    if [ -d /service/gui ]; then
        servicePath=/service/gui
    else
        servicePath=/service/start-gui
    fi
    svc -d $servicePath
    sleep 1
    svc -u $servicePath
    echo "GUI restarted."
}

if [ "$action" == "uninstall" ]; then
    changed=0
    if [ -d "$PAGE_DIR" ]; then
        remove_entries && changed=1
        for page in $PAGES; do
            if [ -f "$PAGE_DIR/$page" ]; then
                rm -f "$PAGE_DIR/$page"
                changed=1
            fi
        done
    fi
    bash /data/apps/overlay-fs/remove-app.sh "$OVERLAY_APP" || true
    [ $changed -eq 1 ] && restart_gui
    echo "dbus-ubms GUI v2 pages removed."
    exit 0
fi

if [ "$action" != "install" ]; then
    echo "Usage: $0 [install|uninstall]"
    exit 1
fi

# make /opt/victronenergy/gui-v2 writeable, changes are stored in /data
if ! bash /data/apps/overlay-fs/add-app-and-directory.sh "$OVERLAY_APP" "$GUI_DIR"; then
    echo "ERROR: could not add $GUI_DIR to overlay-fs"
    exit 1
fi

changed=0

for page in $PAGES; do
    if ! cmp -s "$SRC_DIR/$page" "$PAGE_DIR/$page"; then
        echo "Copying $page"
        cp "$SRC_DIR/$page" "$PAGE_DIR/"
        changed=1
    fi
done

if ! grep -q "^\s*ListAlarmState {" "$PAGE_BATTERY"; then
    echo "ERROR: insertion point (ListAlarmState) not found in $PAGE_BATTERY, menu entries not added."
    exit 1
fi

# (re)insert the menu entries before the alarm state and (re)hide the serialbattery entries
before=$(md5sum < "$PAGE_BATTERY")
remove_entries || true
awk -v part="$SRC_DIR/PageBattery-ubms-entries.qml.part" '
    !done && /^[ \t]*ListAlarmState \{/ {
        while ((getline line < part) > 0) print line
        done = 1
    }
    { print }
' "$PAGE_BATTERY" > "$PAGE_BATTERY.ubms.tmp"
mv "$PAGE_BATTERY.ubms.tmp" "$PAGE_BATTERY"
hide_serialbattery_entries
hidden=$(grep -c "$HIDE_MARKER" "$PAGE_BATTERY" || true)
[ "$hidden" -gt 0 ] && echo "Hiding $hidden dbus-serialbattery menu entries for dbus-ubms services"
if [ "$before" != "$(md5sum < "$PAGE_BATTERY")" ]; then
    echo "Updated menu entries in PageBattery.qml"
    changed=1
fi

if [ $changed -eq 1 ]; then
    restart_gui
else
    echo "dbus-ubms GUI v2 pages are up to date."
fi
