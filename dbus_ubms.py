#!/usr/bin/env python

"""
derived from dbusexample.py part of velib-python
A class to put a battery service on the dbus, according to victron standards, with constantly updating
paths. The data acquisition is done on CAN bus and decodes Valence U-BMS messages, in particular
arbitration ID 0x0c0, 0xc1, 0xc4

"""
import gobject
import platform
import argparse
import logging
import sys
import os

import can
import struct
from argparse import ArgumentParser

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext/velib_python'))
from vedbus import VeDbusService

VERSION = '0.1'


class UbmsBattery(can.Listener):
    def __init__(self):
        self.soc = 0
        self.voltage = 0
	self.current = 0
        self.temperature = 0
	self.underVoltageAlarm = 0
	self.overVoltageAlarm = 0
	self.overCurrentAlarm = 0
	self.maxCellVoltage = 3.0
	self.minCellVoltage = 3.0
	self.partnr = 0 
	self.firmwareVersion = 'unknown'
	self.numberOfModules = 0

    def on_message_received(self, msg):
	if msg.arbitration_id == 0xc0:
		self.soc = msg.data[0]
		self.underVoltageAlarm = msg.data[2] & 0x10
		self.overVoltageAlarm = msg.data[2] & 0x20
		self.overCurrentAlarm = msg.data[4] & 0x20
		logging.debug("SOC: %d",self.soc)

	elif msg.arbitration_id == 0xc1:
                self.voltage = msg.data[0] * 1 #TODO make voltage scale factor input parameter
                self.current = struct.unpack('b',chr(msg.data[1]))[0]
		logging.debug("I: %dA U: %dV",self.current, self.voltage)

	elif msg.arbitration_id == 0xc4:
		self.maxCellVOltage =  struct.unpack('<h', chr(msg.data[4])+chr(msg.data[5]))[0]*0.001
		self.minCellVoltage =  struct.unpack('<h', chr(msg.data[6])+chr(msg.data[7]))[0]*0.001
		logging.debug("Umin %.3fV Umax %.3fV", self.minCellVoltage, self.maxCellVOltage)

#        elif msg.arbitration_id in [0x46a, 0x46b]:
#                self.moduleCurrent = struct.unpack('>hhh', ''.join(chr(i) for i in msg.data[2:msg.dlc]))
#                logging.debug("mCurrents ", self.moduleCurrent)

#        elif msg.arbitration_id in [0x6a]:
#                self.moduleSoc = struct.unpack('BBBBBBB', ''.join(chr(i) for i in msg.data[1:msg.dlc]))
#                logging.debug("mSoc ", self.moduleSoc)

#	elif msg.arbitration_id == 0x184:
#		if msg.data[0] != 0xFF:
#			#this is encoded battery information, not BMS 
#			if msg.data[1] == 1: 
#                		self.partnr = msg.data[2:7].decode() 
#			elif msg.data[1] == 2:
#				self.firmwareVersion = msg.data[2:7].decode()
#
#			if  msg.data[0] > self.numberOfModules: 
#				self.numberOfModules = msg.data[0]



class DbusBatteryService:
    def __init__(self, servicename, deviceinstance, productname='V*lence U-BMS', connection='can0'):
        self._dbusservice = VeDbusService(servicename)

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 0)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/FirmwareVersion', 'unknown')
        self._dbusservice.add_path('/HardwareVersion', 'unknown')
        self._dbusservice.add_path('/Connected', 1)
        # Create battery specific objects
        self._dbusservice.add_path('/Dc/0/Voltage', 0)
        self._dbusservice.add_path('/Dc/0/Power', 0)
        self._dbusservice.add_path('/Dc/0/Current', 0)
        self._dbusservice.add_path('/Soc', 10)
        self._dbusservice.add_path('/Dc/Temperature', 25)
        self._dbusservice.add_path('/Info/MaxChargeCurrent', 150)
        self._dbusservice.add_path('/Info/MaxDischargeCurrent', 150)
        self._dbusservice.add_path('/Alarms/LowVoltage', 0)
        self._dbusservice.add_path('/Alarms/HighVoltage', 0)
        self._dbusservice.add_path('/Alarms/LowSoc', 0)
        self._dbusservice.add_path('/Alarms/LowTemperature', 0)
        self._dbusservice.add_path('/Alarms/HighTemperature', 0)
        self._dbusservice.add_path('/Balancing', 0)
        self._dbusservice.add_path('/System/NrOfBatteries', 8)
        self._dbusservice.add_path('/System/MinCellVoltage', 3.0)
        self._dbusservice.add_path('/System/MaxCellVoltage', 4.2)


        self._ci = can.interface.Bus(channel=connection, bustype='socketcan', can_filters=[{"can_id": 0x0cf, "can_mask": 0xff0}])
	self._bat = UbmsBattery() 
	notifier = can.Notifier(self._ci, [self._bat])
        gobject.timeout_add(1000, self._update)

    def _update(self):
#	self._dbusservice['/FirmwareVersion'] = self._bat.firmwareVersion
#	self._dbusservice['/HardwareVersion'] = self._bat.partnr
	
	if self._bat.soc < 5:
		self._dbusservice['/Alarms/LowSoc'] = 2 
	elif self._bat.soc < 10:
		self._dbusservice['/Alarms/LowSoc'] = 1 
	else:
		self._dbusservice['/Alarms/LowSoc'] = 0

	if self._bat.underVoltageAlarm != 0:
	 	self._dbusservice['/Alarms/LowVoltage'] = 2 
	else:
	 	self._dbusservice['/Alarms/LowVoltage'] = 0 

 	if self._bat.overVoltageAlarm:
                self._dbusservice['/Alarms/HighVoltage'] = 2 
        else:
                self._dbusservice['/Alarms/HighVoltage'] = 0

        self._dbusservice['/Soc'] = self._bat.soc 
        self._dbusservice['/Dc/0/Current'] = self._bat.current 
        self._dbusservice['/Dc/0/Voltage'] = self._bat.voltage 
        self._dbusservice['/Dc/0/Power'] = self._bat.voltage * self._bat.current 
	self._dbusservice['/System/MinCellVoltage'] = self._bat.minCellVoltage
        self._dbusservice['/System/MinCellVoltage'] = self._bat.maxCellVoltage
	self._dbusservice['/System/NrOfBatteries'] =  self._bat.numberOfModules
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else tried to update %s to %s" % (path, value))
        return False # reject the change


# === All code below is to simply run it from the commandline for debugging purposes ===

# It will created a dbus service called com.victronenergy.battery
# To try this on commandline, start this program in one terminal, and try these commands
# from another terminal:
# dbus -y com.victronenergy.battery /Dc/Soc GetValue

def main():
    parser = ArgumentParser(description='dbus-modem', add_help=True)
    parser.add_argument('-d', '--debug', help='enable debug logging',
                        action='store_true')
    parser.add_argument('-i', '--interface', help='CAN interface')

    args = parser.parse_args()

    logging.basicConfig(format='%(levelname)-8s %(message)s',
                        level=(logging.DEBUG if args.debug else logging.INFO))

    if not args.interface:
        logging.error('No CAN interface specified, see -h')
        exit(1)
	
    logging.info('Starting dbus_ubms %s on %s ' %
             (VERSION, args.interface))

    from dbus.mainloop.glib import DBusGMainLoop
    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    battery_output = DbusBatteryService(
        servicename='com.victronenergy.battery',
	connection = args.interface, 	
        deviceinstance=0
        )

    logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
    mainloop = gobject.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()


