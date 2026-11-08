/*
** dbus-ubms - General, gui-v2 UI plugin page (device list integration for ProductId 0xBA75)
** Layout adapted from mr-manuel/venus-os_dbus-serialbattery
** (PageBatteryDbusSerialbattery.qml / ...Settings.qml, Copyright (C) Victron Energy B.V.)
**
** Written against the gui-v2 v1.3.x list item API (ListSetting with a custom contentItem).
** Shows only values dbus-ubms already publishes.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	title: "U-BMS - General"

	// set by gui-v2 when opened from the battery's device page (device list integration)
	property var device
	readonly property string bindPrefix: device ? device.serviceUid : ""

	VeQuickItem { id: voltageItem; uid: root.bindPrefix + "/Dc/0/Voltage" }
	VeQuickItem { id: currentItem; uid: root.bindPrefix + "/Dc/0/Current" }
	VeQuickItem { id: powerItem; uid: root.bindPrefix + "/Dc/0/Power" }
	VeQuickItem { id: socItem; uid: root.bindPrefix + "/Soc" }
	VeQuickItem {
		id: minCellTemperatureItem
		uid: root.bindPrefix + "/System/MinCellTemperature"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: maxCellTemperatureItem
		uid: root.bindPrefix + "/System/MaxCellTemperature"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: maxPcbTemperatureItem
		uid: root.bindPrefix + "/System/MaxPcbTemperature"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem { id: maxChargeVoltageItem; uid: root.bindPrefix + "/Info/MaxChargeVoltage" }
	VeQuickItem { id: maxChargeCurrentItem; uid: root.bindPrefix + "/Info/MaxChargeCurrent" }
	VeQuickItem { id: maxDischargeCurrentItem; uid: root.bindPrefix + "/Info/MaxDischargeCurrent" }
	VeQuickItem { id: allowToChargeItem; uid: root.bindPrefix + "/Io/AllowToCharge" }
	VeQuickItem { id: allowToDischargeItem; uid: root.bindPrefix + "/Io/AllowToDischarge" }
	VeQuickItem { id: balancingItem; uid: root.bindPrefix + "/Balancing" }
	VeQuickItem { id: modulesOnlineItem; uid: root.bindPrefix + "/System/NrOfModulesOnline" }
	VeQuickItem { id: modulesOfflineItem; uid: root.bindPrefix + "/System/NrOfModulesOffline" }
	VeQuickItem { id: modulesBalancingItem; uid: root.bindPrefix + "/System/NrOfBatteriesBalancing" }
	VeQuickItem { id: hasSettingsItem; uid: root.bindPrefix + "/Settings/HasSettings" }

	// A list item with the title on the left and a row of evenly spaced values on the right.
	component ValueRow: ListSetting {
		id: valueRow

		default property alias cells: cellRow.data

		contentItem: Item {
			implicitWidth: Theme.geometry_listItem_width
			implicitHeight: Math.max(titleLabel.implicitHeight, cellRow.implicitHeight)

			Label {
				id: titleLabel
				anchors {
					left: parent.left
					verticalCenter: parent.verticalCenter
				}
				width: parent.width * 0.22
				text: valueRow.text
				font: valueRow.font
				elide: Text.ElideRight
			}

			Row {
				id: cellRow
				anchors {
					left: titleLabel.right
					leftMargin: Theme.geometry_listItem_content_spacing
					right: parent.right
					verticalCenter: parent.verticalCenter
				}
				spacing: Theme.geometry_listItem_content_spacing
			}
		}
	}

	// One value with a caption below, to be placed in a ValueRow.
	component OverviewValue: Column {
		property alias value: valueLabel.value
		property alias unit: valueLabel.unit
		property alias decimals: valueLabel.decimals
		property alias valueText: valueLabel.valueText
		property alias valueColor: valueLabel.valueColor
		property alias caption: captionLabel.text

		// share the width of the ValueRow's cell row evenly
		width: parent && parent.children.length > 0
			? (parent.width - parent.spacing * (parent.children.length - 1)) / parent.children.length
			: 0

		QuantityLabel {
			id: valueLabel
			width: parent.width
			font.pixelSize: 22
		}

		Label {
			id: captionLabel
			width: parent.width
			horizontalAlignment: Text.AlignHCenter
			color: Theme.color_font_secondary
			font.pixelSize: Theme.font_size_caption
			elide: Text.ElideRight
		}
	}

	component YesNoValue: OverviewValue {
		property VeQuickItem item
		valueText: item && item.valid ? CommonWords.yesOrNo(item.value) : "--"
		valueColor: item && item.value === 0 ? "#BF4845" : Theme.color_font_primary
	}

	GradientListView {
		model: VisibleItemModel {

			ValueRow {
				text: "Overview"

				OverviewValue {
					value: voltageItem.value ?? NaN
					unit: VenusOS.Units_Volt_DC
					decimals: 2
					caption: CommonWords.voltage
				}
				OverviewValue {
					value: currentItem.value ?? NaN
					unit: VenusOS.Units_Amp
					decimals: 1
					caption: CommonWords.current_amps
				}
				OverviewValue {
					value: powerItem.value ?? NaN
					unit: VenusOS.Units_Watt
					decimals: 0
					caption: CommonWords.power_watts
				}
				OverviewValue {
					value: socItem.value ?? NaN
					unit: VenusOS.Units_Percentage
					decimals: 0
					caption: CommonWords.state_of_charge
				}
			}

			ValueRow {
				text: "Temperatures"
				preferredVisible: minCellTemperatureItem.valid || maxCellTemperatureItem.valid || maxPcbTemperatureItem.valid

				OverviewValue {
					value: minCellTemperatureItem.value ?? NaN
					unit: Global.systemSettings.temperatureUnit
					decimals: 1
					caption: "Cell min"
				}
				OverviewValue {
					value: maxCellTemperatureItem.value ?? NaN
					unit: Global.systemSettings.temperatureUnit
					decimals: 1
					caption: "Cell max"
				}
				OverviewValue {
					value: maxPcbTemperatureItem.value ?? NaN
					unit: Global.systemSettings.temperatureUnit
					decimals: 1
					caption: "PCB max"
				}
			}

			ListQuantityGroup {
				text: "Charge Voltage Limit (CVL)"
				preferredVisible: maxChargeVoltageItem.valid
				model: QuantityObjectModel {
					QuantityObject { object: maxChargeVoltageItem; unit: VenusOS.Units_Volt_DC }
				}
			}

			ListQuantityGroup {
				text: "Charge Current Limit (CCL)"
				preferredVisible: maxChargeCurrentItem.valid
				model: QuantityObjectModel {
					QuantityObject { object: maxChargeCurrentItem; unit: VenusOS.Units_Amp }
				}
			}

			ListQuantityGroup {
				text: "Discharge Current Limit (DCL)"
				preferredVisible: maxDischargeCurrentItem.valid
				model: QuantityObjectModel {
					QuantityObject { object: maxDischargeCurrentItem; unit: VenusOS.Units_Amp }
				}
			}

			ValueRow {
				text: "Allow to"
				preferredVisible: allowToChargeItem.valid || allowToDischargeItem.valid

				YesNoValue {
					item: allowToChargeItem
					caption: "Charge"
				}
				YesNoValue {
					item: allowToDischargeItem
					caption: "Discharge"
				}
			}

			ValueRow {
				text: "Modules"
				preferredVisible: modulesOnlineItem.valid

				OverviewValue {
					valueText: modulesOnlineItem.valid ? modulesOnlineItem.value : "--"
					caption: "Online"
				}
				OverviewValue {
					valueText: modulesOfflineItem.valid ? modulesOfflineItem.value : "--"
					valueColor: modulesOfflineItem.value > 0 ? "#BF4845" : Theme.color_font_primary
					caption: "Offline"
				}
				OverviewValue {
					valueText: modulesBalancingItem.valid ? modulesBalancingItem.value : "--"
					caption: "Balancing"
				}
				YesNoValue {
					item: balancingItem
					valueColor: Theme.color_font_primary
					caption: "BMS balancing"
				}
			}

			SettingsListHeader {
				text: "Settings"
				preferredVisible: hasSettingsItem.valid && hasSettingsItem.value === 1
			}

			// The U-BMS has one contactor: it only opens (standby) when both are forced off.
			ListSwitch {
				text: "Force charging off"
				dataItem.uid: root.bindPrefix + "/Settings/ForceChargingOff"
				preferredVisible: dataItem.valid
			}

			ListSwitch {
				text: "Force discharging off"
				dataItem.uid: root.bindPrefix + "/Settings/ForceDischargingOff"
				preferredVisible: dataItem.valid
			}
		}
	}
}
