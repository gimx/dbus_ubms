/*
** dbus-ubms - Cell Voltages
** Layout adapted from mr-manuel/venus-os_dbus-serialbattery
** (PageBatteryDbusSerialbatteryCellVoltages.qml, Copyright (C) 2025 Victron Energy B.V.)
**
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

	property string bindPrefix

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

	VeQuickItem {
		id: nrOfCellsPerBattery
		uid: root.bindPrefix + "/System/NrOfCellsPerBattery"
	}
	VeQuickItem {
		id: nrOfBatteries
		uid: root.bindPrefix + "/System/NrOfBatteries"
	}
	VeQuickItem {
		id: cellVoltageSum
		uid: root.bindPrefix + "/Voltages/Sum"
	}
	VeQuickItem {
		id: cellVoltageDiff
		uid: root.bindPrefix + "/Voltages/Diff"
	}
	VeQuickItem {
		id: cellVoltageMin
		uid: root.bindPrefix + "/System/MinCellVoltage"
	}
	VeQuickItem {
		id: cellVoltageMax
		uid: root.bindPrefix + "/System/MaxCellVoltage"
	}
	VeQuickItem {
		id: minVoltageCellId
		uid: root.bindPrefix + "/System/MinVoltageCellId"
	}
	VeQuickItem {
		id: maxVoltageCellId
		uid: root.bindPrefix + "/System/MaxVoltageCellId"
	}

	Repeater {
		model: root.cellCount
		delegate: Item {
			required property int index
			VeQuickItem {
				id: voltageItem
				uid: root.bindPrefix + "/Voltages/Cell" + (index + 1)
				onValidChanged: root.updateCellVoltagesMean()
				onValueChanged: root.updateCellVoltagesMean()
				Component.onCompleted: {
					var items = root.cellVoltageItems.slice(0)
					items[index] = voltageItem
					root.cellVoltageItems = items
				}
			}
		}
	}

	component OverviewValue: Column {
		property alias value: valueLabel.value
		property alias precision: valueLabel.precision
		property alias caption: captionLabel.text

		QuantityLabel {
			id: valueLabel
			width: parent.width
			unit: VenusOS.Units_Volt_DC
			precision: 3
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

	GradientListView {
		model: VisibleItemModel {

			ListItem {
				id: cellOverviewItem
				text: "Overview"
				content.children: [
					Row {
						id: contentRowOverview

						readonly property real itemWidth: (width - (spacing * 4)) / 5

						width: cellOverviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						OverviewValue {
							width: contentRowOverview.itemWidth
							value: cellVoltageSum.value ?? NaN
							precision: 2
							caption: "Sum"
						}
						OverviewValue {
							width: contentRowOverview.itemWidth
							value: root.cellVoltagesMean
							caption: "Ø Mean"
						}
						OverviewValue {
							width: contentRowOverview.itemWidth
							value: cellVoltageMin.value ?? NaN
							caption: "Min" + (minVoltageCellId.valid ? " " + minVoltageCellId.value : "")
						}
						OverviewValue {
							width: contentRowOverview.itemWidth
							value: cellVoltageMax.value ?? NaN
							caption: "Max" + (maxVoltageCellId.valid ? " " + maxVoltageCellId.value : "")
						}
						OverviewValue {
							width: contentRowOverview.itemWidth
							value: cellVoltageDiff.value ?? NaN
							caption: "Diff"
						}
					}
				]
			}

			Column {
				width: parent ? parent.width : 0
				spacing: Theme.geometry_gradientList_spacing

				Repeater {
					model: root.moduleCount
					delegate: ListItem {
						id: moduleListItem

						required property int index
						readonly property int firstCell: index * root.cellsPerModule

						text: "Module " + (index + 1)
						content.children: [
							Row {
								id: contentRow

								readonly property real itemWidth: width / root.cellsPerModule

								width: moduleListItem.maximumContentWidth

								Repeater {
									model: root.cellsPerModule
									delegate: Column {
										required property int index
										readonly property int cell: moduleListItem.firstCell + index + 1
										readonly property var cellVoltageRef: root.cellVoltageItems[cell - 1]
										readonly property bool cellValid: root.cellValid(cellVoltageRef)
										readonly property real cellVoltageMeanDiff: cellValid ? (cellVoltageRef.value - root.cellVoltagesMean) : NaN

										width: contentRow.itemWidth

										QuantityLabel {
											width: parent.width
											value: cellValid ? cellVoltageRef.value : NaN
											unit: VenusOS.Units_Volt_DC
											precision: 3
											font.pixelSize: 22
											valueColor: root.cellTextColor(cell)
										}

										Label {
											width: parent.width
											horizontalAlignment: Text.AlignHCenter
											text: "C" + (index + 1) + (isNaN(cellVoltageMeanDiff) ? ""
												: "  Ø " + (cellVoltageMeanDiff > 0 ? "+" : "") + cellVoltageMeanDiff.toFixed(3) + " V")
											color: isNaN(cellVoltageMeanDiff)
												? Theme.color_font_secondary
												: (cellVoltageMeanDiff > root.cellVoltageDiffThreshold ? Theme.color_red
													: cellVoltageMeanDiff < -root.cellVoltageDiffThreshold ? Theme.color_blue
													: Theme.color_font_secondary)
											font.pixelSize: Theme.font_size_caption
										}
									}
								}
							}
						]
					}
				}
			}
		}
	}
}
