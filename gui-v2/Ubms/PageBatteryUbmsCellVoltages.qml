/*
** dbus-ubms - Cell Voltages, gui-v2 UI plugin page (device list integration for ProductId 0xBA75)
** Layout adapted from mr-manuel/venus-os_dbus-serialbattery
** (PageBatteryDbusSerialbatteryCellVoltages.qml, Copyright (C) 2025 Victron Energy B.V.)
**
** Written against the gui-v2 v1.3.x list item API (ListSetting with a custom contentItem).
** One row per U-BMS module. Shows only values dbus-ubms already publishes:
** /Voltages/Cell<n>, /Voltages/Sum, /Voltages/Diff, /System/Min|MaxCellVoltage,
** /System/Min|MaxVoltageCellId, /System/NrOfBatteries, /System/NrOfCellsPerBattery.
** Note: dbus-ubms updates the cell values every 20s.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	title: "U-BMS - Cell Voltages"

	// set by gui-v2 when opened from the battery's device page (device list integration)
	property var device
	readonly property string bindPrefix: device ? device.serviceUid : ""

	readonly property int cellsPerModule: nrOfCellsPerBattery.valid ? nrOfCellsPerBattery.value : 4
	readonly property int moduleCount: nrOfBatteries.valid ? nrOfBatteries.value : 0
	readonly property int cellCount: cellsPerModule * moduleCount

	property real cellVoltagesMean: NaN
	readonly property real cellVoltageDiffThreshold: isNaN(cellVoltagesMean) ? NaN : cellVoltagesMean * 0.05 // 5% of mean voltage

	// 1-based cell numbers of min/max cell, parsed from "M<module>C<cell>"
	readonly property int minCell: cellIdToNumber(minVoltageCellId.value)
	readonly property int maxCell: cellIdToNumber(maxVoltageCellId.value)

	property var cellVoltageItems: []

	function cellIdToNumber(id) {
		var match = /^M(\d+)C(\d+)$/.exec(id || "")
		return match ? (parseInt(match[1]) - 1) * cellsPerModule + parseInt(match[2]) : -1
	}

	function cellValid(item) {
		return item && item.valid && item.value > 0
	}

	// mean over all cells of all modules, the pack voltage is not accurate enough
	function updateCellVoltagesMean() {
		var sum = 0
		var count = 0
		for (var i = 0; i < cellCount; i++) {
			var item = cellVoltageItems[i]
			if (cellValid(item)) {
				sum += item.value
				count += 1
			}
		}
		cellVoltagesMean = count > 0 ? sum / count : NaN
	}

	function cellTextColor(cell) {
		return cell === minCell ? Theme.color_blue
			: cell === maxCell ? Theme.color_red
			: Theme.color_font_primary
	}

	VeQuickItem { id: nrOfCellsPerBattery; uid: root.bindPrefix + "/System/NrOfCellsPerBattery" }
	VeQuickItem { id: nrOfBatteries; uid: root.bindPrefix + "/System/NrOfBatteries" }
	VeQuickItem { id: cellVoltageSum; uid: root.bindPrefix + "/Voltages/Sum" }
	VeQuickItem { id: cellVoltageDiff; uid: root.bindPrefix + "/Voltages/Diff" }
	VeQuickItem { id: cellVoltageMin; uid: root.bindPrefix + "/System/MinCellVoltage" }
	VeQuickItem { id: cellVoltageMax; uid: root.bindPrefix + "/System/MaxCellVoltage" }
	VeQuickItem { id: minVoltageCellId; uid: root.bindPrefix + "/System/MinVoltageCellId" }
	VeQuickItem { id: maxVoltageCellId; uid: root.bindPrefix + "/System/MaxVoltageCellId" }

	Instantiator {
		model: root.cellCount
		delegate: VeQuickItem {
			required property int index
			uid: root.bindPrefix + "/Voltages/Cell" + (index + 1)
			onValidChanged: root.updateCellVoltagesMean()
			onValueChanged: root.updateCellVoltagesMean()
		}
		onObjectAdded: (index, object) => {
			var items = root.cellVoltageItems.slice(0)
			items[index] = object
			root.cellVoltageItems = items
			root.updateCellVoltagesMean()
		}
	}

	// A list item with the title on the left and a row of values on the right.
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
				width: parent.width * 0.18
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

	// One voltage with a caption below, to be placed in a ValueRow.
	component VoltageValue: Column {
		property alias value: valueLabel.value
		property alias decimals: valueLabel.decimals
		property alias valueColor: valueLabel.valueColor
		property alias caption: captionLabel.text
		property alias captionColor: captionLabel.color
		// number of values sharing the row
		property int columns: 1

		width: parent ? (parent.width - parent.spacing * (columns - 1)) / columns : 0

		QuantityLabel {
			id: valueLabel
			width: parent.width
			unit: VenusOS.Units_Volt_DC
			decimals: 3
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

	GradientListView {
		model: VisibleItemModel {

			ValueRow {
				text: "Overview"

				VoltageValue {
					columns: 5
					value: cellVoltageSum.value ?? NaN
					decimals: 2
					caption: "Sum"
				}
				VoltageValue {
					columns: 5
					value: root.cellVoltagesMean
					caption: "Ø Mean"
				}
				VoltageValue {
					columns: 5
					value: cellVoltageMin.value ?? NaN
					caption: "Min" + (minVoltageCellId.valid ? " " + minVoltageCellId.value : "")
				}
				VoltageValue {
					columns: 5
					value: cellVoltageMax.value ?? NaN
					caption: "Max" + (maxVoltageCellId.valid ? " " + maxVoltageCellId.value : "")
				}
				VoltageValue {
					columns: 5
					value: cellVoltageDiff.value ?? NaN
					caption: "Diff"
				}
			}

			Column {
				width: parent ? parent.width : 0

				Repeater {
					model: root.moduleCount
					delegate: ValueRow {
						id: moduleRow

						required property int index
						readonly property int firstCell: index * root.cellsPerModule

						text: "Module " + (index + 1)

						Repeater {
							model: root.cellsPerModule
							delegate: VoltageValue {
								required property int index
								readonly property int cell: moduleRow.firstCell + index + 1
								readonly property var cellVoltageRef: root.cellVoltageItems[cell - 1]
								readonly property bool cellValid: root.cellValid(cellVoltageRef)
								readonly property real cellVoltageMeanDiff: cellValid ? (cellVoltageRef.value - root.cellVoltagesMean) : NaN

								columns: root.cellsPerModule
								value: cellValid ? cellVoltageRef.value : NaN
								valueColor: root.cellTextColor(cell)
								caption: "C" + (index + 1) + (isNaN(cellVoltageMeanDiff) ? ""
									: "  Ø " + (cellVoltageMeanDiff > 0 ? "+" : "") + cellVoltageMeanDiff.toFixed(3) + " V")
								captionColor: isNaN(cellVoltageMeanDiff)
									? Theme.color_font_secondary
									: (cellVoltageMeanDiff > root.cellVoltageDiffThreshold ? Theme.color_red
										: cellVoltageMeanDiff < -root.cellVoltageDiffThreshold ? Theme.color_blue
										: Theme.color_font_secondary)
							}
						}
					}
				}
			}
		}
	}
}
