#!/usr/bin/env python

"""
derived from dbusexample.py part of velib-python
A class to put a battery service on the dbus, according to victron standards, with constantly updating
paths. The data acquisition is done on CAN bus and decodes Valence U-BMS messages, in particular
arbitration ID 0xc0, 0xc2, 0xc1, 0xc4
The BMS should be operated in Charge mode, ie AUX2 connected to +12V

"""
import gobject
import platform
import argparse
import logging
import sys
import os
import dbus

from datetime import datetime
import can
import struct
from argparse import ArgumentParser

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext/velib_python'))
from vedbus import VeDbusService
from ve_utils import exit_on_error
from settingsdevice import SettingsDevice 

VERSION = '0.6'

class UbmsBattery(can.Listener):
    opModes = {
	0:"Standby",
	1:"Charge",
	2:"Drive"	
	}

    state = {
	4:"Equalize",
	8:"Float"
	}

    def __init__(self, voltage, capacity):
	self.capacity = capacity # Ah
	self.maxChargeVoltage = voltage 
        self.soc = 0
	self.mode = 0
        self.voltage = 0
	self.current = 0
        self.temperature = 0
	self.voltageAndCellTAlarms = 0
	self.internalErrors = 0
	self.currentAndPcbTAlarms = 0
	self.maxPcbTemperature = 0
	self.maxCellTemperature = 0
	self.minCellTemperature = 0
	self.maxCellVoltage = 3.2
	self.minCellVoltage = 3.2
        self.maxChargeCurrent = self.capacity * 0.25
	self.maxDischargeCurrent = self.capacity * 0.5
	self.partnr = 0 
	self.firmwareVersion = 'unknown'
	self.numberOfModules = 0
	self.numberOfModulesBalancing = 0
	self.daylyResetDone = 0

	self.history = {
		"lastDischarge":0,
		"avgDischarge":0,
		"totalAhDrawn":0l,
		"numSamples":0,
		"timeSinceLastFullCharge":0,
		"chargedEnergy":0
	}

    def _update_history():
	if self.current < 0:
		self.history.totalAhDrawn += self.current*2.778e-5
		self.history.discharged += self.current*2.778e-5
	else:
		self.history.charged += self.current*2.778e-5	
		
    def on_exit():
	with open("ubms_history.json", "w") as write_file:
                json.dump(self.history, write_file)

    def on_message_received(self, msg):
	if msg.arbitration_id == 0xc0:
		self.soc = msg.data[0]
		self.mode = msg.data[1]
		self.voltageAndCellTAlarms = msg.data[2]
		self.internalErrors = msg.data[3]
		self.currentAndPcbTAlarms = msg.data[4]
		self.numberOfModules = msg.data[5]
		self.numberOfModulesBalancing = msg.data[6]
		logging.debug("SOC: %d Mode: %X",self.soc, self.mode&0x1F)

	elif msg.arbitration_id == 0xc1:
                self.voltage = msg.data[0] * 1 #TODO make voltage scale factor input parameter
                self.current = struct.unpack('b',chr(msg.data[1]))[0]

		if (self.mode & 0x2) == 2: #provided in drive mode only
			self.maxDischargeCurrent =  struct.unpack('<h', chr(msg.data[3])+chr(msg.data[4]))[0]
			self.maxChargeCurrent =  struct.unpack('<h', chr(msg.data[5])+chr(msg.data[7]))[0]
			logging.debug("Icmax %dA Idmax %dA", self.maxChargeCurrent, self.maxDischargeCurrent)

		logging.debug("I: %dA U: %dV",self.current, self.voltage)

	elif msg.arbitration_id == 0xc2:
		#charge mode only 
		if (self.mode & 0x1) != 0:
			self.chargeComplete = (msg.data[3] & 0x4) >> 2
               		self.maxChargeVoltage = struct.unpack('<h', chr(msg.data[1])+chr(msg.data[2]))[0]
			
			#only apply lower charge current when equalizing 
			if (self.mode & 0x18) == 0x18 : 
                		self.maxChargeCurrent = msg.data[0]
			else:
			#allow charge with 0.5C
				self.maxChargeCurrent = self.capacity * 0.5 
			
			logging.debug("CCL: %d CCV: %d",self.maxChargeCurrent, self.maxChargeVoltage)

	elif msg.arbitration_id == 0xc4:
		self.maxCellTemperature =  msg.data[0]-40
                self.minCellTemperature =  msg.data[1]-40
                self.maxPcbTemperature =  msg.data[3]-40
		self.maxCellVoltage =  struct.unpack('<h', chr(msg.data[4])+chr(msg.data[5]))[0]*0.001
		self.minCellVoltage =  struct.unpack('<h', chr(msg.data[6])+chr(msg.data[7]))[0]*0.001
		logging.debug("Umin %.3fV Umax %.3fV", self.minCellVoltage, self.maxCellVoltage)

#        elif msg.arbitration_id in [0x46a, 0x46b]:
#                self.moduleCurrent = struct.unpack('>hhh', ''.join(chr(i) for i in msg.data[2:msg.dlc]))
#                logging.debug("mCurrents ", self.moduleCurrent)

#        elif msg.arbitration_id in [0x6a]:
#                self.moduleSoc = struct.unpack('BBBBBBB', ''.join(chr(i) for i in msg.data[1:msg.dlc]))
#                logging.debug("mSoc ", self.moduleSoc)


    def _print(self):
        print("SOC:", self.soc, "%"
        	"I:", self.current, "A", 
		"U:", self.voltage, "V",
		"T:", self.maxCellTemperature, "degC")
	print("Umin:", self.minCellVoltage, "Umax:", self.maxCellVoltage)

        return True


def handle_changed_setting(setting, oldvalue, newvalue):
    print 'setting changed, setting: %s, old: %s, new: %s' % (setting, oldvalue, newvalue)



class DbusBatteryService:
    def __init__(self, servicename, deviceinstance, voltage, capacity, productname='Valence U-BMS', connection='can0'):

	self._ci = can.interface.Bus(channel=connection, bustype='socketcan',
                                        can_filters=[{"can_id": 0x0cf, "can_mask": 0xff0}])

        self._dbusservice = VeDbusService(servicename+'.socketcan_'+connection+'_di'+str(deviceinstance))

        logging.debug("%s /DeviceInstance = %d" % (servicename+'.socketcan_'+connection+'_di'+str(deviceinstance), deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', VERSION + ' running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 0)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/FirmwareVersion', 'unknown')
        self._dbusservice.add_path('/HardwareVersion', 'unknown')
        self._dbusservice.add_path('/Connected', 1)
        # Create battery specific objects
        self._dbusservice.add_path('/State', 0)
        self._dbusservice.add_path('/Mode', 2, writeable=True, onchangecallback=self._send_mode_request) #default to drive mode
        self._dbusservice.add_path('/Dc/0/Voltage', 0)
        self._dbusservice.add_path('/Dc/0/Power', 0)
        self._dbusservice.add_path('/Dc/0/Current', 0)
        self._dbusservice.add_path('/Soc', 20)
        self._dbusservice.add_path('/Capacity', int(capacity))
        self._dbusservice.add_path('/TimeToGo', 600)
        self._dbusservice.add_path('/Dc/0/Temperature', 25)
        self._dbusservice.add_path('/Info/MaxChargeCurrent', 70)
        self._dbusservice.add_path('/Info/MaxDischargeCurrent', 150)
	self._dbusservice.add_path('/Info/MaxChargeVoltage', float(voltage))
	self._dbusservice.add_path('/Info/BatteryLowVoltage', 24.0)
 	self._dbusservice.add_path('/Alarms/CellImbalance', 0)
        self._dbusservice.add_path('/Alarms/LowVoltage', 0)
        self._dbusservice.add_path('/Alarms/HighVoltage', 0)
 	self._dbusservice.add_path('/Alarms/HighDischargeCurrent', 0)
        self._dbusservice.add_path('/Alarms/HighChargeCurrent', 0)
        self._dbusservice.add_path('/Alarms/LowSoc', 0)
        self._dbusservice.add_path('/Alarms/LowTemperature', 0)
        self._dbusservice.add_path('/Alarms/HighTemperature', 0)
        self._dbusservice.add_path('/Balancing', 0)
        self._dbusservice.add_path('/System/HasTemperature', 1)
        self._dbusservice.add_path('/System/NrOfBatteries', 10)
        self._dbusservice.add_path('/System/NrOfBatteriesBalancing', 0)
        self._dbusservice.add_path('/System/BatteriesParallel', 5)
        self._dbusservice.add_path('/System/BatteriesSeries', 2)
        self._dbusservice.add_path('/System/NrOfCellsPerBattery', 4)
        self._dbusservice.add_path('/System/MinCellVoltage', 3.0)
        self._dbusservice.add_path('/System/MaxCellVoltage', 4.2)
        self._dbusservice.add_path('/System/MinCellTemperature', 10.0)
        self._dbusservice.add_path('/System/MaxCellTemperature', 10.0)
        self._dbusservice.add_path('/System/MaxPcbTemperature', 10.0)

	self._settings = SettingsDevice(
    		bus=dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus(),
    		supportedSettings={
                	'AvgDischarge': ['/Settings/Ubms/AvgerageDischarge', 0,0,0], 
                	'TotalAhDrawn': ['/Settings/Ubms/TotalAhDrawn', 0,0,0],
			'interval': ['/Settings/Ubms/Interval', 50, 50, 200]
        	},
    		eventCallback=handle_changed_setting)

	self._dbusservice.add_path('/History/AverageDischarge', 0)#self._settings['/Settings/Ubms/AvgerageDischarge'])
        self._dbusservice.add_path('/History/TotalAhDrawn', 0)#self._settings['/Settings/Ubms/TotalAhDrawn'])
        self._dbusservice.add_path('/History/DischargedEnergy', 0)
        self._dbusservice.add_path('/History/ChargedEnergy', 0)

	self._bat = UbmsBattery(capacity=capacity, voltage=voltage) 
	notifier = can.Notifier(self._ci, [self._bat])
        gobject.timeout_add(50, exit_on_error, self._update)

    def _send_mode_request(self, path, value):

    	msg = can.Message(arbitration_id=0x440,
                      data=[0, min(max(0,int(value)),255), 0, 0],
                      extended_id=False)

    	try:
        	self._ci.send(msg)
        	logging.debug("Mode request message sent on {}".format(self._ci.channel_info))
    	except can.CanError:
        	logging.error("Mode request message NOT sent")

    def _on_exit(self):
	self._settings['/Settings/Ubms/AvgerageDischarge'] = self._dbusservice['/History/AverageDischarge']
	self._settings['/Settings/Ubms/TotalAhDrawn'] = self._dbusservice['/History/TotalAhDrawn']

    def _update(self):
#	msg = can.Message(arbitration_id=0x440,
#                      data=[0, 1, 0, 0],
#                      extended_id=False)

#        self._ci.send(msg)

#	self._dbusservice['/FirmwareVersion'] = self._bat.firmwareVersion
#	self._dbusservice['/HardwareVersion'] = self._bat.partnr
	
#	self._dbusservice['/Alarms/CellImbalance'] = (self._bat.internalErrors & 0x20)>>5
	deltaCellVoltage = self._bat.maxCellVoltage - self._bat.minCellVoltage
	if (deltaCellVoltage > 0.1):
		self._dbusservice['/Alarms/CellImbalance'] = 1
	elif (deltaCellVoltage > 0.2):
		self._dbusservice['/Alarms/CellImbalance'] = 2
	else:
		self._dbusservice['/Alarms/CellImbalance'] = 0

	self._dbusservice['/Alarms/LowVoltage'] =  (self._bat.voltageAndCellTAlarms & 0x10)>>3 
        self._dbusservice['/Alarms/HighVoltage'] =  (self._bat.voltageAndCellTAlarms & 0x20)>>4 
	self._dbusservice['/Alarms/LowSoc'] = (self._bat.voltageAndCellTAlarms & 0x08)>>3 
        self._dbusservice['/Alarms/HighDischargeCurrent'] = (self._bat.currentAndPcbTAlarms & 0x3) 

#        self._dbusservice['/Alarms/HighTemperature'] = (self._bat.currentAndPcbTAlarms & 0x18)>>3  
	self._dbusservice['/Alarms/HighTemperature'] =	(self._bat.voltageAndCellTAlarms &0x6)>>1
        self._dbusservice['/Alarms/LowTemperature'] = (self._bat.mode & 0x60)>>5 

        self._dbusservice['/Soc'] = self._bat.soc 
	if self._bat.soc == 100 : #and self._dbusservice['/Info/MaxChargeVoltage'] == self._bat.maxChargeVoltage:  #self._bat.mode&0xC == 8 
		logging.info("Reducing CVL to float level, SOC: %d Mode: %X",self._bat.soc, self._bat.mode&0x1F)
		self._dbusservice['/Info/MaxChargeVoltage'] = 27.0	
	
	now = datetime.now().time()
	if now.hour == 0 and now.minute == 0 and not self._bat.daylyResetDone: #at midnight
		logging.info("Increase CVL to absorbtion level, SOC: %d Mode: %X",self._bat.soc, self._bat.mode&0x1F)
		self._dbusservice['/Info/MaxChargeVoltage']=self._bat.maxChargeVoltage
		self._bat.daylyResetDone = 1
 
	if(self._bat.current >= 0):
	      	self._dbusservice['/TimeToGo'] = self._bat.soc*self._bat.capacity*36
        else:
		try:
			self._dbusservice['/TimeToGo'] = self._bat.soc*self._bat.capacity*36/(-self._bat.current)
		except:
		      	self._dbusservice['/TimeToGo'] = self._bat.soc*self._bat.capacity*36

	self._dbusservice['/State'] = (self._bat.mode &0xC) 
	self._dbusservice['/Mode'] = (self._bat.mode &0x3) 
	self._dbusservice['/Balancing'] = (self._bat.mode &0x10)>>4 
        self._dbusservice['/Dc/0/Current'] = self._bat.current 
        self._dbusservice['/Dc/0/Voltage'] = self._bat.voltage 
        self._dbusservice['/Dc/0/Power'] = self._bat.voltage * self._bat.current 
        self._dbusservice['/Dc/0/Temperature'] = self._bat.maxCellTemperature 
        self._dbusservice['/System/MaxCellVoltage'] = self._bat.maxCellVoltage
	self._dbusservice['/System/MinCellVoltage'] = self._bat.minCellVoltage
	self._dbusservice['/System/MinCellTemperature'] = self._bat.minCellTemperature
	self._dbusservice['/System/MaxCellTemperature'] = self._bat.maxCellTemperature
	self._dbusservice['/System/MaxPcbTemperature'] = self._bat.maxPcbTemperature
	self._dbusservice['/Info/MaxChargeCurrent'] = self._bat.maxChargeCurrent
	self._dbusservice['/Info/MaxDischargeCurrent'] = self._bat.maxDischargeCurrent
#	self._dbusservice['/Info/MaxChargeVoltage'] = self._bat.maxChargeVoltage
	self._dbusservice['/System/NrOfBatteries'] =  self._bat.numberOfModules
	self._dbusservice['/System/NrOfBatteriesBalancing'] = self._bat.numberOfModulesBalancing 
        return True


# === All code below is to simply run it from the commandline for debugging purposes ===

# It will create a dbus service called com.victronenergy.battery
# To try this on commandline, start this program in one terminal, and try these commands
# from another terminal:
# dbus -y com.victronenergy.battery /Soc GetValue

def main():
    parser = ArgumentParser(description='dbus_ubms', add_help=True)
    parser.add_argument('-d', '--debug', help='enable debug logging',
                        action='store_true')
    parser.add_argument('-i', '--interface', help='CAN interface')
    parser.add_argument('-c', '--capacity', help='capacity in Ah')
    parser.add_argument('-v', '--voltage', help='maximum charge voltage V')
    parser.add_argument('-p', '--print', help='print only')

    args = parser.parse_args()

    logging.basicConfig(format='%(levelname)-8s %(message)s',
                        level=(logging.DEBUG if args.debug else logging.INFO))

    if not args.interface:
        logging.info('No CAN interface specified, using default can0')
	args.interface = 'can0'

    if not args.capacity:
        logging.info('Battery capacity not specified, using default (550Ah)')
	args.capacity = 550

    if not args.voltage:
        logging.info('Maximum charge voltage not specified, using default 14.5V')
	args.voltage = 14.5
	
    logging.info('Starting dbus_ubms %s on %s ' %
             (VERSION, args.interface))

    from dbus.mainloop.glib import DBusGMainLoop
    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    battery_output = DbusBatteryService(
        servicename='com.victronenergy.battery',
	connection = args.interface, 	
        deviceinstance=0,
	capacity = int(args.capacity),
	voltage = float(args.voltage)
        )

    logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
    mainloop = gobject.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()


