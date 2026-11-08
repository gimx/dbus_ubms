#!/usr/bin/env python3

"""
A class to put a battery service on the dbus, according to victron standards, with constantly updating
paths.

"""
from gi.repository import GLib
import platform
import logging
import signal
import sys
import os
import dbus
import itertools
import math

from time import time
from datetime import datetime
from argparse import ArgumentParser

# bundled packages (python-can, see ext/VENDORED.md) and velib, must come before
# importing ubmsbattery; ext first so the bundled python-can is used, not a system one
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext/velib_python"))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext"))

from ubmsbattery import UbmsBattery  # noqa: E402
from vedbus import VeDbusService  # noqa: E402
from settingsdevice import SettingsDevice  # noqa: E402

VERSION = "1.2.0"


def handle_changed_setting(setting, oldvalue, newvalue):
    logging.debug(
        "setting changed, setting: %s, old: %s, new: %s" % (setting, oldvalue, newvalue)
    )


class DbusBatteryService:
    def __init__(
        self,
        servicename,
        deviceinstance,
        voltage,
        capacity,
        productname="Valence U-BMS",
        connection="can0",
        startup_delay=10,
        max_voltage_delta=1.0,
    ):
        self.minUpdateDone = 0
        self.dailyResetDone = 0
        self._bat = UbmsBattery(
            capacity=capacity,
            voltage=voltage,
            connection=connection,
            start_mode=0,  # always start in standby, i.e. contactor open
        )
        self._maxVoltageDelta = max_voltage_delta
        self._startupCheckPending = True

        try:
            self._dbusservice = VeDbusService(
                servicename + ".socketcan_" + connection + "_di" + str(deviceinstance),
                register=False
            )
        except Exception:
            logging.exception("Failed to create dbus service")
            self._bat.shutdown()
            raise

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            VERSION + " running on Python " + platform.python_version(),
        )
        self._dbusservice.add_path("/Mgmt/Connection", connection)

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/Manufacturer", "Valence")
        self._dbusservice.add_path("/FirmwareVersion", self._bat.firmwareVersion)
        self._dbusservice.add_path("/HardwareVersion", "type: " + str(self._bat.bms_type) + " rev. "+ hex(self._bat.hw_rev))
        self._dbusservice.add_path("/Connected", 0)
        # Create battery specific objects
        self._dbusservice.add_path("/State", 14, writeable=True)
        self._dbusservice.add_path(
            "/Mode",
            self._bat.modeGuiKey[0],
            writeable=True,
            onchangecallback=self._transmit_mode,
        )
        # serialbattery compatible control, e.g. for dbus-bms-switcher. The U-BMS has one
        # contactor for both directions: it is only opened when both are forced off,
        # a single direction is blocked by reporting its current limit as 0.
        # Both start at 1, matching standby, so writing 0 always triggers a change.
        self._dbusservice.add_path("/Settings/HasSettings", 1)
        self._dbusservice.add_path(
            "/Settings/ForceChargingOff",
            1,
            writeable=True,
            onchangecallback=self._force_off_changed,
        )
        self._dbusservice.add_path(
            "/Settings/ForceDischargingOff",
            1,
            writeable=True,
            onchangecallback=self._force_off_changed,
        )
        self._dbusservice.add_path("/Io/AllowToCharge", 0)
        self._dbusservice.add_path("/Io/AllowToDischarge", 0)
        self._dbusservice.add_path("/Soh", 100)
        self._dbusservice.add_path("/Capacity", int(capacity))
        self._dbusservice.add_path("/InstalledCapacity", int(capacity))
        self._dbusservice.add_path("/Dc/0/Temperature", 25)
        self._dbusservice.add_path("/Info/MaxChargeCurrent", 0)
        self._dbusservice.add_path("/Info/MaxDischargeCurrent", 0)
        self._dbusservice.add_path("/Info/MaxChargeVoltage", float(voltage))
        self._dbusservice.add_path("/Info/BatteryLowVoltage", 44.8)
        self._dbusservice.add_path("/Alarms/CellImbalance", 0)
        self._dbusservice.add_path("/Alarms/LowVoltage", 0)
        self._dbusservice.add_path("/Alarms/HighVoltage", 0)
        self._dbusservice.add_path("/Alarms/HighDischargeCurrent", 0)
        self._dbusservice.add_path("/Alarms/HighChargeCurrent", 0)
        self._dbusservice.add_path("/Alarms/LowSoc", 0)
        self._dbusservice.add_path("/Alarms/LowTemperature", 0)
        self._dbusservice.add_path("/Alarms/HighTemperature", 0)
        self._dbusservice.add_path("/Balancing", 0)
        self._dbusservice.add_path("/Settings/HasTemperature", 1)
        self._dbusservice.add_path("/System/NrOfBatteries", self._bat.numberOfModules)
        self._dbusservice.add_path(
            "/System/NrOfModulesOnline", self._bat.numberOfModules
        )
        self._dbusservice.add_path("/System/NrOfModulesOffline", 0)
        self._dbusservice.add_path("/System/NrOfModulesBlockingDischarge", 0)
        self._dbusservice.add_path("/System/NrOfModulesBlockingCharge", 0)
        self._dbusservice.add_path("/System/NrOfBatteriesBalancing", 0)
        self._dbusservice.add_path(
            "/System/BatteriesParallel", self._bat.numberOfStrings
        )
        self._dbusservice.add_path("/System/BatteriesSeries", self._bat.modulesInSeries)
        self._dbusservice.add_path(
            "/System/NrOfCellsPerBattery", self._bat.cellsPerModule
        )
        self._dbusservice.add_path("/System/MinVoltageCellId", "M_C_")
        self._dbusservice.add_path("/System/MaxVoltageCellId", "M_C_")
        self._dbusservice.add_path("/System/MinCellTemperature", 10.0)
        self._dbusservice.add_path("/System/MaxCellTemperature", 10.0)
        self._dbusservice.add_path("/System/MaxPcbTemperature", 10.0)

        BATTERY_CELL_DATA_FORMAT = 1

        if BATTERY_CELL_DATA_FORMAT > 0:
            for i in range(1, self._bat.cellsPerModule * self._bat.numberOfModules + 1):
                cellpath = (
                    "/Cell/%s/Volts"
                    if (BATTERY_CELL_DATA_FORMAT & 2)
                    else "/Voltages/Cell%s"
                )
                self._dbusservice.add_path(
                    cellpath % (str(i)),
                    None,
                    writeable=True,
                    gettextcallback=lambda p, v: "{:0.3f}V".format(v),
                )
                # serialbattery compatible /Balances/Cell<n>: 1 = cell is balancing, 0 = not.
                # Not published: the U-BMS only reports balancing per pack (/Balancing) and
                # the number of modules balancing, not per cell.
                # if BATTERY_CELL_DATA_FORMAT & 1:
                #     self._dbusservice.add_path(
                #         "/Balances/Cell%s" % (str(i)), None, writeable=True
                #     )
            pathbase = "Cell" if (BATTERY_CELL_DATA_FORMAT & 2) else "Voltages"
            self._dbusservice.add_path(
                "/%s/Sum" % pathbase,
                None,
                writeable=True,
                gettextcallback=lambda p, v: "{:2.2f}V".format(v),
            )
            self._dbusservice.add_path(
                "/%s/Diff" % pathbase,
                None,
                writeable=True,
                gettextcallback=lambda p, v: "{:0.3f}V".format(v),
            )

        self._settings = SettingsDevice(
            bus=(
                dbus.SystemBus()
                if (platform.machine() == "armv7l")
                else dbus.SessionBus()
            ),
            supportedSettings={
                "AvgDischarge": ["/Settings/Ubms/AvgerageDischarge", 0.0, 0, 0],
                "TotalAhDrawn": ["/Settings/Ubms/TotalAhDrawn", 0.0, 0, 0],
                "TimeLastFull": ["/Settings/Ubms/TimeLastFull", 0.0, 0, 0],
                "MinCellVoltage": ["/Settings/Ubms/MinCellVoltage", 4.0, 2.0, 4.2],
                "MaxCellVoltage": ["/Settings/Ubms/MaxCellVoltage", 2.0, 2.0, 4.2],
                "interval": ["/Settings/Ubms/Interval", 50, 50, 200],
            },
            eventCallback=handle_changed_setting,
        )

        self._summeditems = {
            "/System/MaxCellVoltage": {"gettext": "%.2F V"},
            "/System/MinCellVoltage": {"gettext": "%.2F V"},
            "/Dc/0/Voltage": {"gettext": "%.2F V"},
            "/Dc/0/Current": {"gettext": "%.1F A"},
            "/Dc/0/Power": {"gettext": "%.0F W"},
            "/Soc": {"gettext": "%.0F %%"},
            "/History/TotalAhDrawn": {"gettext": "%.0F Ah"},
            "/History/DischargedEnergy": {"gettext": "%.2F kWh"},
            "/History/ChargedEnergy": {"gettext": "%.2F kWh"},
            "/History/AverageDischarge": {"gettext": "%.2F kWh"},
            "/TimeToGo": {"gettext": "%.0F s"},
            "/ConsumedAmphours": {"gettext": "%.1F Ah"},
        }
        for path in self._summeditems.keys():
            self._dbusservice.add_path(path, value=None, gettextcallback=self._gettext)

        self._dbusservice["/History/AverageDischarge"] = self._settings["AvgDischarge"]
        self._dbusservice["/History/TotalAhDrawn"] = self._settings["TotalAhDrawn"]
        self._dbusservice.add_path("/History/TimeSinceLastFullCharge", 0)
        self._dbusservice.add_path(
            "/History/MinimumCellVoltage", self._settings["MinCellVoltage"]
        )
        self._dbusservice.add_path(
            "/History/MaximumCellVoltage", self._settings["MaxCellVoltage"]
        )
        self._dbusservice["/ConsumedAmphours"] = 0

        logging.info(
            "History cell voltage min: %.3f, max: %.3f, totalAhDrawn: %d",
            self._settings["MinCellVoltage"],
            self._settings["MaxCellVoltage"],
            self._settings["TotalAhDrawn"],
        )

        self._dbusservice["/History/ChargedEnergy"] = 0
        self._dbusservice["/History/DischargedEnergy"] = 0

        self._dbusservice.register()
        GLib.timeout_add(self._settings["interval"], self._safe_update)
        logging.info(
            "Starting in standby, checking in %ds whether the contactor can be closed",
            startup_delay,
        )
        GLib.timeout_add_seconds(startup_delay, self._safe_startup_check)

    def _gettext(self, path, value):
        item = self._summeditems.get(path)
        if item is not None:
            return item["gettext"] % value
        return str(value)

    def _transmit_mode(self, path, value):
        # translate values coming from GUI/dbus to U-BMS values
        # returning True accepts the new value on dbus, False rejects it
        mode = self._bat.guiModeKey.get(value)
        if mode is None:
            logging.warning(
                "Unsupported /Mode value %s, use 3 (on/drive) or 252 (standby)", value
            )
            return False

        self._cancel_startup_check(path)
        if not self._bat.set_mode(mode):
            return False
        # /Mode itself is set by velib after returning True
        self._set_force_off_flags(mode)
        return True

    def _force_off_changed(self, path, value):
        if value not in (0, 1):
            return False

        self._cancel_startup_check(path)
        flags = {
            p: self._dbusservice[p]
            for p in ("/Settings/ForceChargingOff", "/Settings/ForceDischargingOff")
        }
        flags[path] = value
        # contactor only opens when both directions are forced off
        mode = 0 if all(flags.values()) else 2
        if not self._bat.set_mode(mode):
            return False

        self._dbusservice["/Mode"] = self._bat.modeGuiKey[mode]
        logging.info(
            "%s set to %d, U-BMS %s mode", path, value, self._bat.opModes[mode]
        )
        return True

    def _set_force_off_flags(self, mode):
        flag = 1 if mode == 0 else 0
        self._dbusservice["/Settings/ForceChargingOff"] = flag
        self._dbusservice["/Settings/ForceDischargingOff"] = flag

    def _cancel_startup_check(self, path):
        # an explicit request (e.g. by a BMS switcher) overrides the startup check
        if self._startupCheckPending:
            logging.info("%s set via dbus, cancelling startup check", path)
            self._startupCheckPending = False

    # --- startup check: close the contactor only if that is safe ---

    # service types that report the voltage of the DC bus on /Dc/0/Voltage
    DC_SOURCE_TYPES = (
        "battery",
        "vebus",
        "multi",
        "inverter",
        "solarcharger",
        "charger",
        "dcdc",
        "alternator",
        "dcsource",
    )
    DC_ENERGIZED_MIN = 5.0  # V, below this the DC bus is considered dead
    # range of DC voltages (relative to the configured max charge voltage) this pack can operate at
    DC_RANGE = (0.65, 1.05)

    def _get_value(self, service, path):
        try:
            value = self._dbusservice.dbusconn.call_blocking(
                service, path, "com.victronenergy.BusItem", "GetValue", "", [],
                timeout=2,
            )
        except dbus.exceptions.DBusException:
            return None
        if isinstance(value, dbus.Array) and len(value) == 0:
            return None  # invalid value
        return value

    def _other_services(self):
        return [
            str(n)
            for n in self._dbusservice.dbusconn.list_names()
            if n.startswith("com.victronenergy.") and n != self._dbusservice.name
        ]

    def _in_standby(self, service):
        return self._get_value(service, "/State") == 14 or self._get_value(
            service, "/Mode"
        ) == 252

    def _other_active_bms(self):
        candidates = [
            n for n in self._other_services() if n.split(".")[2] == "battery"
        ]
        bms = self._get_value("com.victronenergy.system", "/ActiveBmsService")
        if bms and str(bms) != self._dbusservice.name and str(bms) not in candidates:
            candidates.append(str(bms))

        active = []
        for name in candidates:
            # a battery service without charge voltage limit is a monitor (e.g. shunt), not a BMS
            if self._get_value(name, "/Info/MaxChargeVoltage") is None:
                continue
            if self._get_value(name, "/Connected") == 0 or self._in_standby(name):
                continue
            active.append(name)
        return active

    def _dc_bus_voltages(self):
        readings = {}
        for name in self._other_services():
            stype = name.split(".")[2]
            if stype not in self.DC_SOURCE_TYPES:
                continue
            # a pack in standby is disconnected, its voltage is not the bus voltage
            if stype == "battery" and self._in_standby(name):
                continue
            v = self._get_value(name, "/Dc/0/Voltage")
            if v is not None:
                readings[name] = float(v)
        return readings

    def _safe_startup_check(self):
        try:
            return self._startup_check()
        except Exception:
            logging.exception("Startup check failed, staying in standby")
            self._startupCheckPending = False
            return False

    def _startup_check(self):
        if not self._startupCheckPending:
            return False

        packVoltage = self._bat.voltage
        if self._dbusservice["/Connected"] != 1 or packVoltage <= 0:
            logging.info(
                "Startup check: waiting for U-BMS data (connected %s, pack voltage %.2fV)",
                self._dbusservice["/Connected"],
                packVoltage,
            )
            return True  # retry after another startup delay

        vMax = self._bat.maxChargeVoltage
        vLow, vHigh = self.DC_RANGE[0] * vMax, self.DC_RANGE[1] * vMax
        reasons = []

        if not vLow <= packVoltage <= vHigh:
            reasons.append(
                "pack voltage %.2fV does not fit configured max charge voltage %.1fV"
                % (packVoltage, vMax)
            )

        others = self._other_active_bms()
        if others:
            reasons.append("other BMS active: %s" % ", ".join(others))

        for name, v in self._dc_bus_voltages().items():
            if v < self.DC_ENERGIZED_MIN:
                continue
            if not vLow <= v <= vHigh:
                reasons.append(
                    "DC voltage %.2fV of %s outside %.1f-%.1fV range of this pack"
                    % (v, name, vLow, vHigh)
                )
            elif abs(v - packVoltage) > self._maxVoltageDelta:
                reasons.append(
                    "DC voltage %.2fV of %s differs from pack voltage %.2fV by more than %.1fV"
                    % (v, name, packVoltage, self._maxVoltageDelta)
                )

        self._startupCheckPending = False
        if reasons:
            for r in reasons:
                logging.warning("Staying in standby: %s", r)
            return False

        logging.info(
            "Startup check passed at pack voltage %.2fV, closing contactor", packVoltage
        )
        if self._bat.set_mode(2):
            self._dbusservice["/Mode"] = self._bat.modeGuiKey[2]
            self._set_force_off_flags(2)
        return False

    def _safe_update(self):
        # replaces velib's exit_on_error, which exits via os._exit() without any cleanup
        try:
            return self._update()
        except:  # noqa: E722
            logging.exception("Exception in update loop, exiting")
            self.shutdown()
            os._exit(1)

    def shutdown(self):
        try:
            self._safe_history()
        except Exception:
            logging.exception("Failed to save history")
        self._bat.shutdown()

    def __del__(self):
        self._safe_history()
        logging.info("Stopping dbus_ubms")

    def _safe_history(self):
        logging.debug("Saving history to localsettings")
        self._settings["AvgDischarge"] = self._dbusservice["/History/AverageDischarge"]
        self._settings["TotalAhDrawn"] = self._dbusservice["/History/TotalAhDrawn"]
        self._settings["MinCellVoltage"] = self._dbusservice["/History/MinimumCellVoltage"]
        self._settings["MaxCellVoltage"] = self._dbusservice["/History/MaximumCellVoltage"]

    def _daily_stats(self):
        if self._dbusservice["/History/DischargedEnergy"] == 0:
            return
        logging.info(
            "Updating stats, SOC: %d, Discharged: %.2f, Charged: %.2f ",
            self._bat.soc,
            self._dbusservice["/History/DischargedEnergy"],
            self._dbusservice["/History/ChargedEnergy"],
        )
        self._dbusservice["/History/AverageDischarge"] = (
            6 * self._dbusservice["/History/AverageDischarge"]
            + self._dbusservice["/History/DischargedEnergy"]
        ) / 7  # rolling week
        self._dbusservice["/History/ChargedEnergy"] = 0
        self._dbusservice["/History/DischargedEnergy"] = 0
        dt = datetime.now() - datetime.fromtimestamp(
            float(self._settings["TimeLastFull"])
        )
      
        # estimate SOH by BMS calculated SOC difference to 100% vs consumed amphours to full capacity
        # only do this if the last full charge was less than 24h ago and SOC < 70%
        if dt.total_seconds() < 24 * 3600 and self._bat.soc < 70:
         
            self._dbusservice["/Soh"] = int(
                -self._dbusservice["/ConsumedAmphours"] / (100 - self._bat.soc)
                * self._dbusservice["/InstalledCapacity"]
            )
            logging.info(
                "SOH: %d, Capacity: %d ",
                self._dbusservice["/Soh"],
                self._dbusservice["/Capacity"],
            )
        self.dailyResetDone = datetime.now().day

    def _update(self):
        # connected while U-BMS status messages are less than 10s old
        lastStatus = self._bat.lastStatusTime
        self._dbusservice["/Connected"] = (
            1 if lastStatus > 0 and time() - lastStatus < 10 else 0
        )

        #       self._dbusservice['/Alarms/CellImbalance'] = (self._bat.internalErrors & 0x20)>>5
        deltaCellVoltage = self._bat.maxCellVoltage - self._bat.minCellVoltage

        # flag cell imbalance, only log first occurence
        if deltaCellVoltage > 0.25:
            self._dbusservice["/Alarms/CellImbalance"] = 2
            if self._bat.balanced:
                #                       logging.error("Cell voltage imbalance: %.2fV, SOC: %d, @Module: %d ", deltaCellVoltage, self._bat.soc, self._bat.moduleSoc.index(min(self.moduleSoc)))
                logging.error(
                    "Cell voltage imbalance: %.2fV, SOC: %d ",
                    deltaCellVoltage,
                    self._bat.soc,
                )
                logging.info("SOC: %d ", self._bat.soc)
            self._bat.balanced = False
        elif deltaCellVoltage >= 0.18:
            # warn only if not already balancing (UBMS threshold is 0.15V)
            if self._bat.numberOfModulesBalancing == 0:
                self._dbusservice["/Alarms/CellImbalance"] = 1
            if self._bat.balanced:
                chain = itertools.chain(*self._bat.cellVoltages)
                flatVList = list(chain)
                iMax = flatVList.index(max(flatVList))
                iMin = flatVList.index(min(flatVList))
                logging.info(
                    "Cell voltage imbalance: %.2fV, iMin: %d, iMax %d, SOC: %d ",
                    deltaCellVoltage,
                    iMin,
                    iMax,
                    self._bat.soc,
                )
            self._bat.balanced = False
        else:
            self._dbusservice["/Alarms/CellImbalance"] = 0
            self._bat.balanced = True

        self._dbusservice["/Alarms/LowVoltage"] = (
            self._bat.voltageAndCellTAlarms & 0x10
        ) >> 3
        self._dbusservice["/Alarms/HighVoltage"] = (
            self._bat.voltageAndCellTAlarms & 0x20
        ) >> 4
        self._dbusservice["/Alarms/LowSoc"] = (
            self._bat.voltageAndCellTAlarms & 0x08
        ) >> 3
        self._dbusservice["/Alarms/HighDischargeCurrent"] = (
            self._bat.currentAndPcbTAlarms & 0x3
        )

        #       flag high cell temperature alarm and high pcb temperature alarm
        self._dbusservice["/Alarms/HighTemperature"] = (
            self._bat.voltageAndCellTAlarms & 0x6
        ) >> 1 | (self._bat.currentAndPcbTAlarms & 0x18) >> 3
        self._dbusservice["/Alarms/LowTemperature"] = (self._bat.mode & 0x60) >> 5

        self._dbusservice["/Soc"] = self._bat.soc
        dt = datetime.now() - datetime.fromtimestamp(
            float(self._settings["TimeLastFull"])
        )
        self._dbusservice["/History/TimeSinceLastFullCharge"] = (
            dt.seconds + dt.days * 24 * 3600
        )

        if self._bat.soc == 100 or self._bat.chargeComplete:
            # reset used Amphours to zero
            self._dbusservice["/ConsumedAmphours"] = 0
            if (
                datetime.fromtimestamp(time()).day
                != datetime.fromtimestamp(float(self._settings["TimeLastFull"])).day
            ):
                # and if it is the first time that day also create log entry
                logging.info(
                    "Fully charged, Discharged: %.2f, Charged: %.2f ",
                    self._dbusservice["/History/DischargedEnergy"],
                    self._dbusservice["/History/ChargedEnergy"],
                )
                self._settings["TimeLastFull"] = time()

        self._dbusservice["/State"] = self._bat.state
        #self._dbusservice["/Mode"] = self._bat.guiModeKey.get(
        #    (self._bat.mode & 0x3), 252
        #)
        self._dbusservice["/Balancing"] = (self._bat.mode & 0x10) >> 4
        self._dbusservice["/Dc/0/Current"] = self._bat.current
        self._dbusservice["/Dc/0/Voltage"] = self._bat.voltage
        power = self._bat.voltage * self._bat.current
        self._dbusservice["/Dc/0/Power"] = power
        self._dbusservice["/Dc/0/Temperature"] = self._bat.maxCellTemperature

        # in standby the contactor is open, so the battery can neither be charged nor
        # discharged, otherwise a direction may be blocked by its force off flag
        bmsMode = self._bat.mode & 0x3
        allowCharge = bmsMode != 0 and not self._dbusservice["/Settings/ForceChargingOff"]
        allowDischarge = (
            bmsMode == 2 and not self._dbusservice["/Settings/ForceDischargingOff"]
        )
        self._dbusservice["/Io/AllowToCharge"] = 1 if allowCharge else 0
        self._dbusservice["/Io/AllowToDischarge"] = 1 if allowDischarge else 0
        self._dbusservice["/Info/MaxChargeCurrent"] = (
            self._bat.maxChargeCurrent if allowCharge else 0
        )
        self._dbusservice["/Info/MaxDischargeCurrent"] = (
            self._bat.maxDischargeCurrent if allowDischarge else 0
        )

        # only update the below every 20s to reduce load
        if datetime.now().second not in [0, 20, 40]:
            return True

        # estimate available capacity from SOC and installed capacity
        self._dbusservice["/Capacity"] = int(
                self._dbusservice["/InstalledCapacity"]
                * self._bat.soc * 0.01
        )

        chain = itertools.chain(*self._bat.cellVoltages)
        flatVList = list(chain)

        index = flatVList.index(max(flatVList))
        m = math.floor(index / 4)
        c = index % 4
        self._dbusservice["/System/MaxVoltageCellId"] = (
            "M" + str(m + 1) + "C" + str(c + 1)
        )
        self._dbusservice["/System/MaxCellVoltage"] = self._bat.maxCellVoltage

        index = flatVList.index(min(flatVList))
        m = math.floor(index / 4)
        c = index % 4
        self._dbusservice["/System/MinVoltageCellId"] = (
            "M" + str(m + 1) + "C" + str(c + 1)
        )
        self._dbusservice["/System/MinCellVoltage"] = self._bat.minCellVoltage

        # cell voltages
        try:
            voltageSum = 0
            for i in range(len(flatVList)):
                voltage = flatVList[i] / 1000.0
                cellpath = "/Voltages/Cell%s"
                self._dbusservice[cellpath % (str(i + 1))] = voltage
                if voltage and i < self._bat.cellsPerModule * self._bat.modulesInSeries:
                    voltageSum += voltage
            self._dbusservice["/Voltages/Sum"] = voltageSum
            self._dbusservice["/Voltages/Diff"] = (
                self._bat.maxCellVoltage - self._bat.minCellVoltage
            )
        except Exception:
            pass

        if self._bat.maxCellVoltage > self._dbusservice["/History/MaximumCellVoltage"]:
            self._dbusservice["/History/MaximumCellVoltage"] = self._bat.maxCellVoltage
            logging.debug("New maximum cell voltage: %f", self._bat.maxCellVoltage)

        if 0 < self._bat.minCellVoltage < self._dbusservice["/History/MinimumCellVoltage"]:
            self._dbusservice["/History/MinimumCellVoltage"] = self._bat.minCellVoltage
            logging.debug("New minimum cell voltage: %f", self._bat.minCellVoltage)
        self._dbusservice["/System/MinCellTemperature"] = self._bat.minCellTemperature
        self._dbusservice["/System/MaxCellTemperature"] = self._bat.maxCellTemperature
        self._dbusservice["/System/MaxPcbTemperature"] = self._bat.maxPcbTemperature
        self._dbusservice["/Info/MaxChargeVoltage"] = self._bat.maxChargeVoltage
        self._dbusservice["/System/NrOfModulesOnline"] = (
            self._bat.numberOfModulesCommunicating
        )
        self._dbusservice["/System/NrOfModulesOffline"] = (
            self._bat.numberOfModules - self._bat.numberOfModulesCommunicating
        )
        self._dbusservice["/System/NrOfBatteriesBalancing"] = (
            self._bat.numberOfModulesBalancing
        )

        # update energy statistics daily at 6:00,
        if (
            datetime.now().hour == 6
            and datetime.now().minute == 0
            and datetime.now().day != self.dailyResetDone
        ):
            self._daily_stats()

        now = datetime.now().time()
        if now.minute != self.minUpdateDone:
            self.minUpdateDone = now.minute
            if self._bat.current > 0:
                # charging
                self._dbusservice["/History/ChargedEnergy"] += (
                    power * 1.666667e-5
                )  # kWh
                # calculate time to full, in the absense of a mutex accessing bat.current value might have changed
                # to 0 after check above, so try to catch a div0
                try:
                    self._dbusservice["/TimeToGo"] = (
                        (100 - self._bat.soc)
                        * self._bat.capacity
                        * 36
                        / self._bat.current
                    )
                except:
                    self._dbusservice["/TimeToGo"] = (
                        self._bat.soc * self._bat.capacity * 36
                    )
            else:
                # discharging
                self._dbusservice["/ConsumedAmphours"] += (
                    self._bat.current * 0.016667
                )  # Ah
                self._dbusservice["/History/TotalAhDrawn"] += (
                    self._bat.current * 0.016667
                )  # Ah
                self._dbusservice["/History/DischargedEnergy"] += (
                    -power * 1.666667e-5
                )  # kWh

                # calculate time to empty
                try:
                    self._dbusservice["/TimeToGo"] = (
                        self._bat.soc * self._bat.capacity * 36 / (-self._bat.current)
                    )
                except:
                    self._dbusservice["/TimeToGo"] = (
                        self._bat.soc * self._bat.capacity * 36
                    )

            self._safe_history()

        return True


# === All code below is to simply run it from the commandline for debugging purposes ===

# It will create a dbus service called com.victronenergy.battery
# To try this on commandline, start this program in one terminal, and try these commands
# from another terminal:
# dbus -y com.victronenergy.battery /Soc GetValue


def main():
    parser = ArgumentParser(description="dbus_ubms", add_help=True)
    parser.add_argument(
        "-d", "--debug", help="enable debug logging", action="store_true"
    )
    parser.add_argument("-i", "--interface", help="CAN interface")
    parser.add_argument("-c", "--capacity", help="capacity in Ah")
    parser.add_argument("-v", "--voltage", help="maximum charge voltage V")
    parser.add_argument("-p", "--print", help="print only")
    parser.add_argument(
        "--startup-delay",
        help="seconds in standby before checking whether the contactor can be closed "
        "(default 10), use different values for several U-BMS in one system",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--max-voltage-delta",
        help="maximum difference between DC bus and pack voltage to close the "
        "contactor on startup in V (default 1.0)",
        type=float,
        default=1.0,
    )

    args = parser.parse_args()

    logging.basicConfig(
        format="%(levelname)-8s %(message)s",
        level=(logging.DEBUG if args.debug else logging.INFO),
    )

    if not args.interface:
        logging.info("No CAN interface specified, using default can0")
        args.interface = "can0"

    if not args.capacity:
        logging.warning("Battery capacity not specified, using default (130Ah)")
        args.capacity = 130

    if not args.voltage:
        logging.error("Maximum charge voltage not specified. Exiting.")
        return

    os.system("ip link set can0 type can bitrate 250000")
    os.system("ifconfig can0 up")

    logging.info("Starting dbus_ubms %s on %s " % (VERSION, args.interface))

    from dbus.mainloop.glib import DBusGMainLoop

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    if sys.version_info.major == 2:
        gobject.threads_init()
    DBusGMainLoop(set_as_default=True)

    # Until the main loop runs, turn termination signals into a regular exit,
    # so the atexit handler of UbmsBattery puts the U-BMS into standby.
    # SIGINT already raises KeyboardInterrupt.
    def _raise_exit(signum, frame):
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _raise_exit)

    service = DbusBatteryService(
        servicename="com.victronenergy.battery",
        connection=args.interface,
        deviceinstance=0,
        capacity=int(args.capacity),
        voltage=float(args.voltage),
        startup_delay=args.startup_delay,
        max_voltage_delta=args.max_voltage_delta,
    )

    logging.debug(
        "Connected to dbus, and switching over to GLib.MainLoop() (= event based)"
    )
    mainloop = GLib.MainLoop()

    def _quit(signame):
        logging.info("Received %s, stopping", signame)
        mainloop.quit()
        return GLib.SOURCE_REMOVE

    for sig, name in (
        (signal.SIGTERM, "SIGTERM"),
        (signal.SIGINT, "SIGINT"),
        (signal.SIGHUP, "SIGHUP"),
    ):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, _quit, name)

    try:
        mainloop.run()
    finally:
        # leave the U-BMS in standby, i.e. contactor open
        service.shutdown()
        logging.info("Stopped dbus_ubms")


if __name__ == "__main__":
    main()
