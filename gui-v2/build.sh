#!/bin/bash
# Compiles the gui-v2 UI plugin into gui-v2/Ubms/Ubms.json.
# Run on a development machine (needs python3 plus Qt's lupdate, lrelease and rcc), then commit the JSON.
# The device only needs the compiled JSON; gui-v2-install.sh deploys it to /data/apps/enabled/.
#
# The pages are added to the device page of every battery with /ProductId 0xBA75 (set by dbus_ubms.py,
# provisional, self-chosen). They use the gui-v2 v1.3.x plugin API (Victron.VenusOS Page, Venus OS v3.8x).

set -e

GUI_V2_TAG="${GUI_V2_TAG:-v1.3.27}"
MIN_REQUIRED_VERSION="v1.3.6"
PRODUCT_ID="0xBA75"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PLUGIN_DIR="$SCRIPT_DIR/Ubms"
COMPILER="${GUI_V2_COMPILER:-$SCRIPT_DIR/.gui-v2-plugin-compiler-$GUI_V2_TAG.py}"

if [ ! -f "$COMPILER" ]; then
    echo "Fetching gui-v2 plugin compiler ($GUI_V2_TAG)..."
    curl -fsSL -o "$COMPILER" \
        "https://raw.githubusercontent.com/victronenergy/gui-v2/$GUI_V2_TAG/tools/gui-v2-plugin-compiler.py"
fi

cd "$PLUGIN_DIR"
python3 "$COMPILER" \
    --name Ubms \
    --min-required-version "$MIN_REQUIRED_VERSION" \
    --devicelist "$PRODUCT_ID" PageBatteryUbms.qml "U-BMS - General" \
    --devicelist "$PRODUCT_ID" PageBatteryUbmsCellVoltages.qml "U-BMS - Cell Voltages"

# Remove build intermediates; only the .json is deployed.
rm -f Ubms.qrc Ubms.rcc ./*.qm ./*.ts

echo "Built $PLUGIN_DIR/Ubms.json"
