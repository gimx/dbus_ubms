/*
** dbus-ubms - General
** Layout adapted from mr-manuel/venus-os_dbus-serialbattery
** (PageBatteryDbusSerialbattery.qml / ...Settings.qml, Copyright (C) Victron Energy B.V.)
**
** Shows only values dbus-ubms already publishes.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	title: "U-BMS - General"

	property string bindPrefix

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

	component OverviewValue: Column {
		property alias value: valueLabel.value
		property alias unit: valueLabel.unit
		property alias precision: valueLabel.precision
		property alias valueText: valueLabel.valueText
		property alias valueColor: valueLabel.valueColor
		property alias caption: captionLabel.text

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
		}
	}

	component YesNoValue: OverviewValue {
		property VeQuickItem item
		valueText: item && item.valid ? CommonWords.yesOrNo(item.value) : "--"
		valueColor: item && item.value === 0 ? "#BF4845" : Theme.color_font_primary
	}

	GradientListView {
		model: VisibleItemModel {

			ListItem {
				id: overviewItem
				text: "Overview"
				content.children: [
					Row {
						id: overviewRow

						readonly property real itemWidth: (width - (spacing * 3)) / 4

						width: overviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						OverviewValue {
							width: overviewRow.itemWidth
							value: voltageItem.value ?? NaN
							unit: VenusOS.Units_Volt_DC
							precision: 2
							caption: CommonWords.voltage
						}
						OverviewValue {
							width: overviewRow.itemWidth
							value: currentItem.value ?? NaN
							unit: VenusOS.Units_Amp
							precision: 1
							caption: CommonWords.current_amps
						}
						OverviewValue {
							width: overviewRow.itemWidth
							value: powerItem.value ?? NaN
							unit: VenusOS.Units_Watt
							precision: 0
							caption: CommonWords.power_watts
						}
						OverviewValue {
							width: overviewRow.itemWidth
							value: socItem.value ?? NaN
							unit: VenusOS.Units_Percentage
							precision: 0
							caption: CommonWords.state_of_charge
						}
					}
				]
			}

			ListItem {
				id: temperaturesItem
				text: "Temperatures"
				preferredVisible: minCellTemperatureItem.valid || maxCellTemperatureItem.valid || maxPcbTemperatureItem.valid
				content.children: [
					Row {
						id: temperaturesRow

						readonly property real itemWidth: (width - (spacing * 2)) / 3

						width: temperaturesItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						OverviewValue {
							width: temperaturesRow.itemWidth
							value: minCellTemperatureItem.value ?? NaN
							unit: Global.systemSettings.temperatureUnit
							precision: 1
							caption: "Cell min"
						}
						OverviewValue {
							width: temperaturesRow.itemWidth
							value: maxCellTemperatureItem.value ?? NaN
							unit: Global.systemSettings.temperatureUnit
							precision: 1
							caption: "Cell max"
						}
						OverviewValue {
							width: temperaturesRow.itemWidth
							value: maxPcbTemperatureItem.value ?? NaN
							unit: Global.systemSettings.temperatureUnit
							precision: 1
							caption: "PCB max"
						}
					}
				]
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

			ListItem {
				id: allowToItem
				text: "Allow to"
				preferredVisible: allowToChargeItem.valid || allowToDischargeItem.valid
				content.children: [
					Row {
						id: allowToRow

						readonly property real itemWidth: (width - spacing) / 2

						width: allowToItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						YesNoValue {
							width: allowToRow.itemWidth
							item: allowToChargeItem
							caption: "Charge"
						}
						YesNoValue {
							width: allowToRow.itemWidth
							item: allowToDischargeItem
							caption: "Discharge"
						}
					}
				]
			}

			ListItem {
				id: modulesItem
				text: "Modules"
				preferredVisible: modulesOnlineItem.valid
				content.children: [
					Row {
						id: modulesRow

						readonly property real itemWidth: (width - (spacing * 3)) / 4

						width: modulesItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						OverviewValue {
							width: modulesRow.itemWidth
							valueText: modulesOnlineItem.valid ? modulesOnlineItem.value : "--"
							caption: "Online"
						}
						OverviewValue {
							width: modulesRow.itemWidth
							valueText: modulesOfflineItem.valid ? modulesOfflineItem.value : "--"
							valueColor: modulesOfflineItem.value > 0 ? "#BF4845" : Theme.color_font_primary
							caption: "Offline"
						}
						OverviewValue {
							width: modulesRow.itemWidth
							valueText: modulesBalancingItem.valid ? modulesBalancingItem.value : "--"
							caption: "Balancing"
						}
						YesNoValue {
							width: modulesRow.itemWidth
							item: balancingItem
							valueColor: Theme.color_font_primary
							caption: "BMS balancing"
						}
					}
				]
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
