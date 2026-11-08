#!/usr/bin/env python3

"""
Data acquisition and decoding of Valence U-BMS messages on CAN bus
To evercome the low resolution of the pack voltage(>=1V) the cell voltages are summed up.
In order for this to work the first x modules of a xSyP pack should have assigned module IDs 1 to x
The BMS should be operated in slave mode, VMU packages are being sent

"""
import atexit
import logging
import time
import can
import struct


class UbmsBattery(can.Listener):
    opModes = {0: "Standby", 1: "Charge", 2: "Drive"}

    # Victron /Mode values (252 = standby, 3 = on) to U-BMS mode and back
    guiModeKey = {252: 0, 3: 2}
    modeGuiKey = {0: 252, 2: 3}

    opState = {0: 14, 1: 9, 2: 9}
    # Victron BMS states
    # 0-8 init
    #   9 running
    #  10 error
    #  12 shutdown
    #  13 updating
    #  14 standby
    #  15 going to run
    #  16 pre-charge
    #  17 contactor check

    def __init__(self, voltage, capacity, connection, start_mode=2):
        """start_mode: U-BMS mode commanded from the very first VMU message,
        2 = drive (contactor closed), 0 = standby (hot standby, contactor open)"""
        if start_mode not in self.opModes:
            raise ValueError("Invalid start mode %r" % start_mode)

        self.capacity = capacity
        self.maxChargeVoltage = voltage
        self.numberOfModules = 8
        self.numberOfStrings = 2
        self.modulesInSeries = int(self.numberOfModules / self.numberOfStrings)
        self.cellsPerModule = 4
        self.chargeComplete = 0
        self.soc = 0
        self.mode = 0
        self.state = ""
        self.voltage = 0
        self.current = 0
        self.temperature = 0
        self.balanced = True

        self.voltageAndCellTAlarms = 0
        self.internalErrors = 0
        self.currentAndPcbTAlarms = 0
        self.shutdownReason = 0

        self.maxPcbTemperature = 0
        self.maxCellTemperature = 0
        self.minCellTemperature = 0
        self.cellVoltages = [(0, 0, 0, 0) for i in range(self.numberOfModules)]
        self.moduleVoltage = [0 for i in range(self.numberOfModules)]
        self.moduleCurrent = [0 for i in range(self.numberOfModules)]
        self.moduleSoc = [0 for i in range(self.numberOfModules)]
        self.moduleTemp = [0 for i in range(self.numberOfModules)]
        self.maxCellVoltage = 3.2
        self.minCellVoltage = 3.2
        self.maxChargeCurrent = 5.0
        self.maxDischargeCurrent = 5.0
        self.partnr = 0
        self.firmwareVersion = 0
        self.bms_type = 0
        self.hw_rev = 0
        self.numberOfModulesBalancing = 0
        self.numberOfModulesCommunicating = 0
        self.updated = -1
        self.lastStatusTime = 0
        self.cyclicModeTask = None
        self.commandedMode = None
        self._notifier = None
        self._shutdownDone = False

        self._ci = can.interface.Bus(
            channel=connection,
            bustype="socketcan",
            can_filters=[
                {"can_id": 0x0CF, "can_mask": 0xFF0},  # BMS status
                {"can_id": 0x180, "can_mask": 0xFFF},  # Firmware version and BMS type
            ],
        )

        if self._connect_and_verify(connection):
            # Now that we've confirmed connection, update filters for normal operation
            self._set_operational_filters()

            # create a cyclic mode command message simulating a VMU master
            # a U-BMS in slave mode according to manual section 6.4.1 switches to standby
            # after 20 seconds of not receiving it
            self.commandedMode = start_mode
            self.cyclicModeTask = self._ci.send_periodic(
                self._mode_message(start_mode), 1
            )
            # leave the BMS in standby on any regular interpreter exit,
            # including uncaught exceptions and sys.exit()
            atexit.register(self.shutdown)
            logging.info("Commanding U-BMS %s mode", self.opModes[start_mode])

            # Set up the notifier for message callbacks
            self._notifier = can.Notifier(self._ci, [self])

        else:
            logging.error("Failed to connect to a supported Valence U-BMS")

    @staticmethod
    def _mode_message(mode):
        return can.Message(
            arbitration_id=0x440, data=[0, mode, 0, 0], is_extended_id=False
        )
    
    def _connect_and_verify(self, connection):
        # check connection, BMS type and that reported system voltage roughly matches configuration
        found = 0
        msg = None

        while found != 7:
            try:
                msg = self._ci.recv(timeout=10)
            except can.CanError:
                logging.error("Canbus error")

            if msg is None:
                # timeout no system connected
                logging.error(
                    "No messages on canbus %s received. Check connection and speed setting."
                    % connection
                )
                break

            elif msg.arbitration_id == 0xC0 and found & 2 == 0:
                # status message received
                logging.info(
                    "Found Valence U-BMS on %s in mode %x with %i modules communicating.",
                    connection,
                    msg.data[1],
                    msg.data[5],
                )
                if msg.data[2] & 1 != 0:
                    logging.info(
                        "The number of modules communicating is less than configured."
                    )
                if msg.data[3] & 2 != 0:
                    logging.info(
                        "The number of modules communicating is higher than configured."
                    )

                found = found | 2

            elif msg.arbitration_id == 0xC1 and found & 1 == 0:
                # check pack voltage
                if (
                    abs(2 * msg.data[0] - self.maxChargeVoltage)
                    > 0.15 * self.maxChargeVoltage
                ):
                    logging.error(
                        "Pack voltage of %dV differs significantly from configured max charge voltage %dV.",
                        msg.data[0],
                        self.maxChargeVoltage,
                    )
                found = found | 1

            elif msg.arbitration_id == 0x180 and found & 4 == 0:
                self.firmwareVersion = msg.data[0]
                # self.cust_rel_rev = msg.data[1]
                # self.boot_load_rev = msg.data[2]
                self.bms_type = msg.data[3]
                self.hw_rev = msg.data[4]

                logging.info(
                    "U-BMS type %d with firmware version %d",
                    self.bms_type,
                    self.firmwareVersion,
                )

                found = found | 4

        return found == 7

    def _set_operational_filters(self):
        # Set up filters for the messages we want to receive
        filters = [
            {"can_id": 0x0CF, "can_mask": 0xFF0},  
            {"can_id": 0x350, "can_mask": 0xFF0},
            {"can_id": 0x360, "can_mask": 0xFF0},
            {"can_id": 0x46A, "can_mask": 0xFF0},
            {"can_id": 0x06A, "can_mask": 0xFF0},
            {"can_id": 0x76A, "can_mask": 0xFF0},  
        ]
        self._ci.set_filters(filters)

    def on_message_received(self, msg):
        self.updated = msg.timestamp
        if msg.arbitration_id == 0xC0:
            self.soc = msg.data[0]
            self.mode = msg.data[1]
            self.state = self.opState[self.mode & 0x3]
            self.voltageAndCellTAlarms = msg.data[2]
            self.internalErrors = msg.data[3]
            self.currentAndPcbTAlarms = msg.data[4]

            self.numberOfModulesCommunicating = msg.data[5]

            # if no module flagged missing and not too many on the bus, then this is the number the U-BMS was configured for
            if (msg.data[2] & 1 == 0) and (msg.data[3] & 2 == 0):
                self.numberOfModules = self.numberOfModulesCommunicating

            self.numberOfModulesBalancing = msg.data[6]
            # set last, shutdown() relies on mode being current when this changes
            self.lastStatusTime = time.time()

            if (self.shutdownReason == 0 and msg.data[7] != 0) or self.shutdownReason != msg.data[7]:
                logging.warning("Shutdown reason 0x%x", msg.data[7])
            
                logging.debug(
                    "SOC %d%% mode %d state %s alarms 0x%x 0x%x 0x%x",
                    self.soc,
                    self.mode,
                    self.state,
                    self.voltageAndCellTAlarms,
                    self.internalErrors,
                    self.currentAndPcbTAlarms,
                )

            self.shutdownReason = msg.data[7]

        elif msg.arbitration_id == 0xC1:
            #            self.voltage = msg.data[0] * 1 # voltage scale factor depends on BMS configuration!
            self.current = struct.unpack("Bb", msg.data[0:2])[1]

            if (self.mode & 0x2) != 0:  # provided in drive mode only
                self.maxDischargeCurrent = int(
                    (struct.unpack("<h", msg.data[3:5])[0]) / 10
                )
                self.maxChargeCurrent = int(
                    (struct.unpack("<h", bytearray([msg.data[5], msg.data[7]]))[0]) / 10
                )
                logging.debug(
                    "Icmax %dA Idmax %dA",
                    self.maxChargeCurrent,
                    self.maxDischargeCurrent,
                )

            logging.debug("I: %dA U: %dV", self.current, msg.data[0])

        elif msg.arbitration_id == 0xC2:
            # charge mode only
            if (self.mode & 0x1) != 0:
                self.chargeComplete = (msg.data[3] & 0x4) >> 2
                self.maxChargeVoltage2 = struct.unpack("<h", msg.data[1:3])[0]

                # only apply lower charge current when equalizing
                if (self.mode & 0x18) == 0x18:
                    self.maxChargeCurrent = msg.data[0]
                else:
                    # allow charge with 0.1C
                    self.maxChargeCurrent = self.capacity * 0.1

        elif msg.arbitration_id == 0xC4:
            self.maxCellTemperature = msg.data[0] - 40
            self.minCellTemperature = msg.data[1] - 40
            self.maxPcbTemperature = msg.data[3] - 40
            self.maxCellVoltage = struct.unpack("<h", msg.data[4:6])[0] * 0.001
            self.minCellVoltage = struct.unpack("<h", msg.data[6:8])[0] * 0.001
            logging.debug(
                "Umin %1.3fV Umax %1.3fV", self.minCellVoltage, self.maxCellVoltage
            )

        elif msg.arbitration_id in [
            0x350,
            0x352,
            0x354,
            0x356,
            0x358,
            0x35A,
            0x35C,
            0x35E,
            0x360,
            0x362,
            0x364,
        ]:
            module = (msg.arbitration_id - 0x350) >> 1
            self.cellVoltages[module] = struct.unpack(">hhh", msg.data[2 : msg.dlc])

        elif msg.arbitration_id in [
            0x351,
            0x353,
            0x355,
            0x357,
            0x359,
            0x35B,
            0x35D,
            0x35F,
            0x361,
            0x363,
            0x365,
        ]:
            module = (msg.arbitration_id - 0x351) >> 1
            self.cellVoltages[module] = self.cellVoltages[module] + tuple(
                struct.unpack(">h", msg.data[2 : msg.dlc])
            )
            self.moduleVoltage[module] = sum(self.cellVoltages[module])
            logging.debug("Umodule %d: %fmV", module, self.moduleVoltage[module])

            # update pack voltage at each arrival of the last modules cell voltages
            if module == self.numberOfModules - 1:
                self.voltage = (
                    sum(self.moduleVoltage[0 : self.modulesInSeries]) / 1000.0
                )

        elif msg.arbitration_id in [0x46A, 0x46B, 0x46C, 0x46D]:
            iStart = (msg.arbitration_id - 0x46A) * 3
            fmt = ">" + "h" * int((msg.dlc - 2) / 2)
            mCurrent = struct.unpack(fmt, msg.data[2 : msg.dlc])
            self.moduleCurrent[iStart:] = mCurrent
            # logging.debug("Imodule %s", ",".join(str(x) for x in self.moduleCurrent))

        elif msg.arbitration_id in [0x6A, 0x6B]:
            iStart = (msg.arbitration_id - 0x6A) * 7
            fmt = "B" * (msg.dlc - 1)
            mSoc = struct.unpack(fmt, msg.data[1 : msg.dlc])
            self.moduleSoc[iStart:] = tuple((m * 100) >> 8 for m in mSoc)
            # logging.debug("SOCmodule %s", ",".join(str(x) for x in self.moduleSoc))

        elif msg.arbitration_id in [0x76A, 0x76B, 0x76C, 0x76D]:
            iStart = (msg.arbitration_id - 0x76A) * 3
            self.moduleTemp[iStart] = ((msg.data[2] * 256) + msg.data[3]) * 0.01
            if msg.dlc > 5: 
                self.moduleTemp[iStart + 1] = ((msg.data[4] * 256) + msg.data[5]) * 0.01
            if msg.dlc > 7: 
                self.moduleTemp[iStart + 2] = ((msg.data[6] * 256) + msg.data[7]) * 0.01
            # logging.debug("Tmodule %s", ",".join(str(x) for x in self.moduleTemp))   

    # change operational mode of the BMS, valid values see opModes
    # transition between charge and drive only via standby(1-0-2)
    def set_mode(self, mode):
        if mode not in self.opModes:
            logging.warning("Invalid mode requested: %s", mode)
            return False

        if self.cyclicModeTask is None or self._shutdownDone:
            logging.warning(
                "Cannot change to %s mode, U-BMS not connected", self.opModes[mode]
            )
            return False

        if mode == self.commandedMode:
            return True

        if mode != 0 and self.commandedMode != 0:
            logging.warning(
                "Change from %s to %s mode has to go via standby",
                self.opModes[self.commandedMode],
                self.opModes[mode],
            )
            return False

        msg = self._mode_message(mode)
        if isinstance(self.cyclicModeTask, can.ModifiableCyclicTaskABC):
            self.cyclicModeTask.modify_data(msg)
        else:
            self.cyclicModeTask.stop()
            self.cyclicModeTask = self._ci.send_periodic(msg, 1)
        # apply right away instead of waiting up to one period
        self._ci.send(msg)

        self.commandedMode = mode
        logging.info("Changed mode to %s", self.opModes[mode])
        return True

    def shutdown(self, timeout=3.0):
        """Leave the U-BMS in standby (contactor open) and release the CAN bus.

        Sends the standby command repeatedly until a status message confirms it
        or the timeout expires. Safe to call more than once. If the process dies
        without getting here (SIGKILL, power loss) the U-BMS falls back to
        standby by itself about 20s after the last mode command.
        """
        if self._shutdownDone:
            return
        self._shutdownDone = True

        try:
            if self.cyclicModeTask is not None:
                self.cyclicModeTask.stop()
                self.commandedMode = 0
                msg = self._mode_message(0)
                requested = time.time()
                confirmed = False
                while time.time() - requested < timeout:
                    try:
                        self._ci.send(msg)
                    except can.CanError as e:
                        logging.error("Failed to send standby command: %s", e)
                    time.sleep(0.2)
                    if self.lastStatusTime > requested and self.mode & 0x3 == 0:
                        confirmed = True
                        break

                if confirmed:
                    logging.info("U-BMS confirmed standby mode, contactor open")
                else:
                    logging.error(
                        "U-BMS did not confirm standby within %.0fs, it will fall back "
                        "to standby about 20s after the last mode command",
                        timeout,
                    )
        finally:
            if self._notifier is not None:
                self._notifier.stop()
            self._ci.shutdown()


# === All code below is to simply run it from the commandline for debugging purposes ===
def main():
    logging.basicConfig(format="%(levelname)-8s %(message)s", level=(logging.DEBUG))

    # start in standby, this is only for reading data
    bat = UbmsBattery(capacity=650, voltage=29.0, connection="can0", start_mode=0)
    try:
        time.sleep(3)

        # print out some info about the BMS
        logging.info("BMS type: %d", bat.bms_type)
        logging.info("Firmware version: %d", bat.firmwareVersion)
        logging.info("Hardware version: %d", bat.hw_rev)

        logging.info("Number of modules: %d", bat.numberOfModules)
        logging.info("Module SOCs: %s", bat.moduleSoc)
        logging.info("Max cell voltage: %1.3fV", bat.maxCellVoltage)
        logging.info("Min cell voltage: %1.3fV", bat.minCellVoltage)
        logging.info("Cell voltages:")
        for i in range(bat.numberOfModules):
            logging.info("Module %d: %s", i, bat.cellVoltages[i])
    finally:
        bat.shutdown()


if __name__ == "__main__":
    main()
