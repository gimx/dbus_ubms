#!/usr/bin/env python3

"""
Data acquisition and decoding of Valence U-BMS messages on CAN bus
To evercome the low resolution of the pack voltage(>=1V) the cell voltages are summed up.
In order for this to work the first x modules of a xSyP pack should have assigned module IDs 1 to x
The BMS should be operated in slave mode, VMU packages are being sent

"""
import logging
import itertools

from time import time
from datetime import datetime
import can
import struct
from argparse import ArgumentParser

VERSION = '0.9'

class UbmsBattery(can.Listener):
    opModes = {
        0:"Standby",
        1:"Charge",
        2:"Drive"
        }
    opState = {
        0:"? [0]",
        0x4:"Equalize",
        0x8:"Float",
        0xc:"Equalize & Float"
        }

    def __init__(self, voltage, capacity, connection):
        self.capacity = capacity
        self.maxChargeVoltage = voltage
        self.numberOfModules = 10
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
        self.maxPcbTemperature = 0
        self.maxCellTemperature = 0
        self.minCellTemperature = 0
        self.cellVoltages =[(0,0,0,0) for i in range(self.numberOfModules)]
        self.moduleVoltage = [0 for i in range(self.numberOfModules)]
        self.moduleCurrent = [0 for i in range(self.numberOfModules)]
        self.moduleSoc = [0 for i in range(self.numberOfModules)]
        self.maxCellVoltage = 3.2
        self.minCellVoltage = 3.2
        self.maxChargeCurrent = self.capacity * 0.25
        self.maxDischargeCurrent = self.capacity * 0.4
        self.partnr = 0
        self.firmwareVersion = 'unknown'
        self.numberOfModulesBalancing = 0
        self.numberOfModulesCommunicating = 0
        self.updated = -1
        self.cyclicModeTask = None

        self._ci = can.interface.Bus(channel=connection, bustype='socketcan',
                   can_filters=[{"can_id": 0x0cf, "can_mask": 0xff0},
                                {"can_id": 0x350, "can_mask": 0xff0},
                                {"can_id": 0x360, "can_mask": 0xff0},
                                {"can_id": 0x46a, "can_mask": 0xff0},
                                {"can_id": 0x06a, "can_mask": 0xff0},
                        ])

        # check connection and that reported system voltage roughly matches configuration
        found = False
        msg = None

        while True:
            try:
                msg = self._ci.recv(timeout=10)
            except can.CanError:
                logging.error("Canbus error")

            if msg == None:
            #timeout no system connected
                logging.error("No messages on canbus %s received. Check connection and speed." % connection)
                break;

            elif msg.arbitration_id == 0xc1:
            # status message received, check voltage
                if abs(msg.data[0] - self.maxChargeVoltage) > 0.15* msg.data[0]:
                    logging.error("Pack voltage read (%dV) differs significantly from configure max charge voltage." % msg.data[0])
                    break;
                else:
                    logging.info("Found Valence U-BMS on %s" % connection)
                    found = True
                    break;

        if found:
        # create a cyclic mode command message simulating a VMU master
        # a U-BMS in slave mode according to manual section 6.4.1 switches to standby
        # after 20 seconds of not receiving it
            msg = can.Message(arbitration_id=0x440,
                  data=[0, 2, 0, 0], is_extended_id=False) #default: drive mode
            
            self.cyclicModeTask = self._ci.send_periodic(msg, 1)
            notifier = can.Notifier(self._ci, [self])


    def on_message_received(self, msg):
        self.updated = msg.timestamp
        if msg.arbitration_id == 0xc0:
            self.soc = msg.data[0]
            self.mode = msg.data[1]
            self.state = self.opState[self.mode & 0xc]
            self.firmwareVersion = self.state #FIXME where to put state such that it is visible in GUI
            self.voltageAndCellTAlarms = msg.data[2]
            self.internalErrors = msg.data[3]
            self.currentAndPcbTAlarms = msg.data[4]

            self.numberOfModulesCommunicating = msg.data[5]

            #if no module flagged missing and not too many on the bus, then this is the number the U-BMS was configured for
            if (msg.data[2] & 1 == 0) and (msg.data[3] & 2 == 0):
                self.numberOfModules = self.numberOfModulesCommunicating

            self.numberOfModulesBalancing = msg.data[6]

        elif msg.arbitration_id == 0xc1:
#                self.voltage = msg.data[0] * 1 # voltage scale factor depends on BMS configuration!
            self.current = struct.unpack('Bb',msg.data[0:2])[1]

            if (self.mode & 0x2) != 0 : #provided in drive mode only
                self.maxDischargeCurrent =  int((struct.unpack('<h', msg.data[3:5])[0])/10)
                self.maxChargeCurrent =  int((struct.unpack('<h', bytearray([msg.data[5],msg.data[7]]))[0])/10)
                logging.debug("Icmax %dA Idmax %dA", self.maxChargeCurrent, self.maxDischargeCurrent)

            logging.debug("I: %dA U: %dV",self.current, self.voltage)

        elif msg.arbitration_id == 0xc2:
            #charge mode only
            if (self.mode & 0x1) != 0:
                self.chargeComplete = (msg.data[3] & 0x4) >> 2
                self.maxChargeVoltage2 = struct.unpack('<h', msg.data[1:3])[0]

                #only apply lower charge current when equalizing
                if (self.mode & 0x18) == 0x18 :
                    self.maxChargeCurrent = msg.data[0]
                else:
                #allow charge with 0.1C
                    self.maxChargeCurrent = self.capacity * 0.1


        elif msg.arbitration_id == 0xc4:
            self.maxCellTemperature =  msg.data[0]-40
            self.minCellTemperature =  msg.data[1]-40
            self.maxPcbTemperature =  msg.data[3]-40
            self.maxCellVoltage =  struct.unpack('<h', msg.data[4:6])[0]*0.001
            self.minCellVoltage =  struct.unpack('<h', msg.data[6:8])[0]*0.001
            logging.debug("Umin %1.3fV Umax %1.3fV", self.minCellVoltage, self.maxCellVoltage)

        elif msg.arbitration_id in [0x350, 0x352, 0x354, 0x356, 0x358, 0x35A, 0x35C, 0x35E, 0x360, 0x362, 0x364]:
            module = (msg.arbitration_id - 0x350) >> 1
            self.cellVoltages[module] = struct.unpack('>hhh', msg.data[2:msg.dlc])

        elif msg.arbitration_id in [0x351, 0x353, 0x355, 0x357, 0x359, 0x35B, 0x35D, 0x35F, 0x361, 0x363, 0x365]:
            module = (msg.arbitration_id - 0x351) >> 1
            self.cellVoltages[module] = self.cellVoltages[module]+ tuple(struct.unpack('>h', msg.data[2:msg.dlc]))
            self.moduleVoltage[module] = sum(self.cellVoltages[module])
            logging.debug("Umodule %d: %fmV", module, self.moduleVoltage[module])

            #update pack voltage at each arrival of the last modules cell voltages
            if module == self.numberOfModules-1:
                self.voltage = sum(self.moduleVoltage[0:2])/1000.0 #adjust slice to number of modules in series

        elif msg.arbitration_id in [0x46a, 0x46b, 0x46c, 0x46d]:
            iStart = (msg.arbitration_id - 0x46a) * 3
            fmt = '>' +'h' * int((msg.dlc - 2)/2)
            mCurrent = struct.unpack(fmt, msg.data[2:msg.dlc])
            self.moduleCurrent[iStart:] = mCurrent
            logging.debug("Imodule %s", ",".join(str(x) for x in self.moduleCurrent))

        elif msg.arbitration_id in [0x6a, 0x6b]:
            iStart = (msg.arbitration_id - 0x6a) * 7
            fmt = 'B' * (msg.dlc - 1)
            mSoc = struct.unpack(fmt, msg.data[1:msg.dlc])
            self.moduleSoc[iStart:] = tuple((m * 100)>>8 for m in mSoc)
            logging.debug("SOCmodule %s", ",".join(str(x) for x in self.moduleSoc))

    def prnt(self):
        print(self.mode)
        #print(self.opModes[self.mode & 0xc])
        print("SOC: %2d, I: %3dA, U: %2.2fV, T:%2.1fC" % (self.soc, self.current, self.voltage, self.maxCellTemperature))
        print("Umin: %1.2f, Umax: %1.2f Udelta: %1.2f" % (self.minCellVoltage, self.maxCellVoltage, self.maxCellVoltage-self.minCellVoltage))
        print("CCL: %4.0f A CVL: %2.2f V" % (self.maxChargeCurrent, self.maxChargeVoltage))
        chain = itertools.chain(*self.cellVoltages)
        flatVList = list(chain)
        iMax = flatVList.index(max(flatVList))
        iMin = flatVList.index(min(flatVList))
        print("iMin: %s, iMax %s" % ('M'+str(iMin/4+1)+'C'+str(iMin%4+1), 'M'+str(iMax/4+1)+'C'+str(iMax%4+1)))
        print(self.moduleSoc)
        print(self.moduleVoltage)
        print(self.moduleCurrent)
        #print(self.cellVoltages)


    #change operational mode of the BMS, valid values see opModes (accepting strings and numbers)
    #transition between charge and drive only via standby(1-0-2)
    def set_mode(self, value):
        if not isinstance(self.cyclicModeTask, can.ModifiableCyclicTaskABC):
            logging.error("No support for modification of a cyclic message. Cannot change mode.")
            return

        if value in self.opModes.values():
            value = list(opModes.keys())[list(opModes.values()).index(value)]

        elif value not in self.opModes.keys():
            logging.error('Invalid mode value %d' % value)
            return

        logging.info('Changing mode to %s'% self.opModes[value])

        msg = can.Message(arbitration_id=0x440,
                      data=[0, int(value), 0, 0],
                      extended_id=False)
        self.cyclicModeTask.modify_data(msg)


# === All code below is to simply run it from the commandline for debugging purposes ===
def main():

#       logger = can.Logger('logfile.asc')

    bat = UbmsBattery(capacity=650, voltage=29.0, connection='can0')

    listeners = [
    #               logger,          # Regular Listener object
            bat
    ]

    notifier = can.Notifier(bat._ci, listeners)
    for msg in bat._ci:
        if msg.arbitration_id == 0x6b:
            bat.prnt()

    # Clean-up
    notifier.stop()
    bat._ci.shutdown()


    logging.basicConfig(format='%(levelname)-8s %(message)s',
            level=(logging.DEBUG))


if __name__ == "__main__":
    main()
