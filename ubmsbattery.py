#!/usr/bin/env python

"""
derived from dbusexample.py part of velib-python
A class to put a battery service on the dbus, according to victron standards, with constantly updating
paths. The data acquisition is done on CAN bus and decodes Valence U-BMS messages
To evercome the low resolution of the pack voltage(>=1V) the cell voltages are summed up.
In order for this to work the first x modules of a xSyP pack should have assigned module IDs 1 to x
The BMS should be operated in slave mode, VMU packages are being sent 

"""
import gobject
import platform
import argparse
import logging
import sys
import os
import dbus
import itertools

from time import time
from datetime import datetime
import can
import struct
from argparse import ArgumentParser

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext/velib_python'))
from vedbus import VeDbusService
from ve_utils import exit_on_error
from settingsdevice import SettingsDevice 

VERSION = '0.8'

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
	self.capacity = capacity
	self.maxChargeVoltage = voltage 
	self.numberOfModules = 10
	self.chargeComplete = 0
        self.soc = 0
	self.mode = 0
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
	self.maxDischargeCurrent = self.capacity * 0.5
	self.partnr = 0 
	self.firmwareVersion = 'unknown'
	self.numberOfModulesBalancing = 0


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
#                self.voltage = msg.data[0] * 1 # voltage scale factor depends on BMS configuration! 
                self.current = struct.unpack('b',chr(msg.data[1]))[0]

		if (self.mode & 0x2) == 2: #provided in drive mode only
			self.maxDischargeCurrent =  struct.unpack('<h', msg.data[3:5])[0]
			self.maxChargeCurrent =  struct.unpack('<h', chr(msg.data[5])+chr(msg.data[7]))[0]
			logging.debug("Icmax %dA Idmax %dA", self.maxChargeCurrent, self.maxDischargeCurrent)

		logging.debug("I: %dA U: %dV",self.current, self.voltage)

	elif msg.arbitration_id == 0xc2:
		#charge mode only 
		if (self.mode & 0x1) != 0:
			self.chargeComplete = (msg.data[3] & 0x4) >> 2
#               		self.maxChargeVoltage = struct.unpack('<h', msg.data[1:3])[0]
			
			#only apply lower charge current when equalizing 
			if (self.mode & 0x18) == 0x18 : 
                		self.maxChargeCurrent = msg.data[0]
			else:
			#allow charge with 0.5C
				self.maxChargeCurrent = self.capacity * 0.5 
			
			logging.debug("CCL: %d CVL: %d",self.maxChargeCurrent, self.maxChargeVoltage)

	elif msg.arbitration_id == 0xc4:
		self.maxCellTemperature =  msg.data[0]-40
                self.minCellTemperature =  msg.data[1]-40
                self.maxPcbTemperature =  msg.data[3]-40
		self.maxCellVoltage =  struct.unpack('<h', msg.data[4:6])[0]*0.001
		self.minCellVoltage =  struct.unpack('<h', msg.data[6:8])[0]*0.001
		logging.debug("Umin %.3fV Umax %.3fV", self.minCellVoltage, self.maxCellVoltage)

        elif msg.arbitration_id in [0x350, 0x352, 0x354, 0x356, 0x358, 0x35A, 0x35C, 0x35E, 0x360, 0x362, 0x364]:
		module = (msg.arbitration_id - 0x350) >> 1
                self.cellVoltages[module] = struct.unpack('>hhh', msg.data[2:msg.dlc])

        elif msg.arbitration_id in [0x351, 0x353, 0x355, 0x357, 0x359, 0x35B, 0x35D, 0x35F, 0x361, 0x363, 0x365]:
		module = (msg.arbitration_id - 0x351) >> 1
                self.cellVoltages[module] = self.cellVoltages[module]+ tuple(struct.unpack('>h', msg.data[2:msg.dlc]))
		self.moduleVoltage[module] = sum(self.cellVoltages[module]) 
		logging.debug("Umodule %d: %fmV", module, self.moduleVoltage[module])
		if module == self.numberOfModules-1:
			self.voltage = sum(self.moduleVoltage[0:2])/1000.0 #adjust slice to number of modules in series

        elif msg.arbitration_id in [0x46a, 0x46b, 0x46c, 0x46d]:
		iStart = (msg.arbitration_id - 0x46a) * 3 
		fmt = '>hhh' * (msg.dlc - 2)/2
                mCurrent = struct.unpack(fmt, ''.join(chr(i) for i in msg.data[2:msg.dlc]))
		self.moduleCurrent[iStart:] = mCurrent		
                logging.debug("mCurrents ", self.moduleCurrent)

        elif msg.arbitration_id in [0x6a, 0x6b]:
		iStart = (msg.arbitration_id - 0x6a) * 7 
		fmt = 'B' * (msg.dlc - 1) 
                mSoc = struct.unpack(fmt, msg.data[1:msg.dlc])
		tuple((m * 100)>>8 for m in mSoc)
		self.moduleSoc[iStart:] = mSoc

    def _print(self):
        print("SOC:", self.soc, "%"
        	"I:", self.current, "A", 
		"U:", self.voltage, "V",
		"T:", self.maxCellTemperature, "degC")
	print("Umin:", self.minCellVoltage, "Umax:", self.maxCellVoltage)

        return True


def handle_changed_setting(setting, oldvalue, newvalue):
    logging.debug('setting changed, setting: %s, old: %s, new: %s' % (setting, oldvalue, newvalue))


class DbusBatteryService:
    def __init__(self, servicename, deviceinstance, voltage, capacity, productname='Valence U-BMS', connection='can0'):
	self.minUpdateDone = 0
	self.dailyResetDone = 0
	self._ci = can.interface.Bus(channel=connection, bustype='socketcan',
                   can_filters=[{"can_id": 0x0cf, "can_mask": 0xff0}, 
				{"can_id": 0x350, "can_mask": 0xff0}, 
				{"can_id": 0x360, "can_mask": 0xff0},
#				{"can_id": 0x46a, "can_mask": 0xff0}, # module currents 
				{"can_id": 0x06a, "can_mask": 0xff0}, # module SOC 
			])

        # create a cyclic mode command message simulating a VMU master
        msg = can.Message(arbitration_id=0x440,
                      data=[0, 1, 0, 0], #default: charge mode
                      extended_id=False)
       	self.cyclicModeTask = self._ci.send_periodic(msg, 0.1) #UBMS in slave mode times out after 20s

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
        self._dbusservice.add_path('/Status', 0)
	self._dbusservice.add_path('/Mode', 1, writeable=True, onchangecallback=self._transmit_mode) 
#        self._dbusservice.add_path('/Dc/0/Voltage', 0.0, gettextcallback=get_text_cb)
#        self._dbusservice.add_path('/Dc/0/Power', 0.0)
#        self._dbusservice.add_path('/Dc/0/Current', 0.0)
#        self._dbusservice.add_path('/Soc', 20)
        self._dbusservice.add_path('/Soh', 100)
        self._dbusservice.add_path('/Capacity', int(capacity))
        self._dbusservice.add_path('/InstalledCapacity', int(capacity))
#        self._dbusservice.add_path('/TimeToGo', 600)
        self._dbusservice.add_path('/ConsumedAmphours', 0)
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
        self._dbusservice.add_path('/System/NrOfModulesOnline', 10)
        self._dbusservice.add_path('/System/NrOfBatteriesBalancing', 0)
        self._dbusservice.add_path('/System/BatteriesParallel', 5)
        self._dbusservice.add_path('/System/BatteriesSeries', 2)
        self._dbusservice.add_path('/System/NrOfCellsPerBattery', 4)
#        self._dbusservice.add_path('/System/MinCellVoltage', 3.0)
        self._dbusservice.add_path('/System/MinVoltageCellId', 'M_C_')
#        self._dbusservice.add_path('/System/MaxCellVoltage', 4.2)
        self._dbusservice.add_path('/System/MaxVoltageCellId', 'M_C_')
        self._dbusservice.add_path('/System/MinCellTemperature', 10.0)
        self._dbusservice.add_path('/System/MaxCellTemperature', 10.0)
        self._dbusservice.add_path('/System/MaxPcbTemperature', 10.0)

	self._summeditems = {
                        '/System/MaxCellVoltage': {'gettext': '%.2F V'},
                        '/System/MinCellVoltage': {'gettext': '%.2F V'},
                        '/Dc/0/Voltage': {'gettext': '%.2F V'},
                        '/Dc/0/Current': {'gettext': '%.1F A'},
                        '/Dc/0/Power': {'gettext': '%.0F W'},
                        '/Soc': {'gettext': '%.0F %%'},
                        '/TimeToGo': {'gettext': '%.0F s'}
#                        '/ConsumedAmphours': {'gettext': '%.1F Ah'}
        }
        for path in self._summeditems.keys():
                        self._dbusservice.add_path(path, value=None, gettextcallback=self._gettext)



	self._settings = SettingsDevice(
    		bus=dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus(),
    		supportedSettings={
                	'AvgDischarge': ['/Settings/Ubms/AvgerageDischarge', 0.0,0,0], 
                	'TotalAhDrawn': ['/Settings/Ubms/TotalAhDrawn', 0.0,0,0],
                	'TimeLastFull': ['/Settings/Ubms/TimeLastFull', 0.0 ,0,0],
                	'MinCellVoltage': ['/Settings/Ubms/MinCellVoltage', 4.0,2.0,4.0],
                	'MaxCellVoltage': ['/Settings/Ubms/MaxCellVoltage', 2.0,2.0,4.0],
			'interval': ['/Settings/Ubms/Interval', 50, 50, 200]
        	},
    		eventCallback=handle_changed_setting)

	self._dbusservice.add_path('/History/AverageDischarge', self._settings['AvgDischarge'])
        self._dbusservice.add_path('/History/TotalAhDrawn', self._settings['TotalAhDrawn'])
        self._dbusservice.add_path('/History/DischargedEnergy', 0.0)
        self._dbusservice.add_path('/History/ChargedEnergy', 0.0)
	self._dbusservice.add_path('/History/MinCellVoltage', self._settings['MinCellVoltage'])
        self._dbusservice.add_path('/History/MaxCellVoltage', self._settings['MaxCellVoltage'])
	logging.info("History cell voltage min: %.3f, max: %.3f, totalAhDrawn: %d",  
		self._settings['MinCellVoltage'], self._settings['MaxCellVoltage'], self._settings['TotalAhDrawn'])

	self._bat = UbmsBattery(capacity=capacity, voltage=voltage) 

	notifier = can.Notifier(self._ci, [self._bat])

        gobject.timeout_add( self._settings['interval'], exit_on_error, self._update)


    def _gettext(self, path, value):
	item = self._summeditems.get(path)
	if item is not None:
		return item['gettext'] % value
	return str(value)

    def _transmit_mode(self, path, value):
	if not isinstance(self.cyclicModeTask, can.ModifiableCyclicTaskABC):
        	logging.error("This interface doesn't seem to support modification of cyclic message")
        	return
	logging.info('Changing mode to %d %s', value, type(self.cyclicModeTask))
    	msg = can.Message(arbitration_id=0x440,
                      data=[0, min(max(0,int(value)),2), 0, 0],
                      extended_id=False)
	self.cyclicModeTask.modify_data(msg)


    def __del__(self):
	self._safe_history()
	self._ci.close()
	logging.info('Stopping dbus_ubms')


    def _safe_history(self):
	logging.debug('Saving history to localsettings')
	self._settings['AvgDischarge'] = self._dbusservice['/History/AverageDischarge']
	self._settings['TotalAhDrawn'] = self._dbusservice['/History/TotalAhDrawn']
	self._settings['MinCellVoltage'] = self._dbusservice['/History/MinCellVoltage']
	self._settings['MaxCellVoltage'] = self._dbusservice['/History/MaxCellVoltage']


    def _daily_stats(self):
	if (self._dbusservice['/History/DischargedEnergy'] == 0): return
        logging.info("Updating stats, SOC: %d, Discharged: %.2f, Charged: %.2f ",self._bat.soc,  self._dbusservice['/History/DischargedEnergy'],  self._dbusservice['/History/ChargedEnergy'])
        self._dbusservice['/History/AverageDischarge'] = (6*self._dbusservice['/History/AverageDischarge'] + self._dbusservice['/History/DischargedEnergy'])/7 #rolling week
      	self._dbusservice['/History/ChargedEnergy'] = 0
       	self._dbusservice['/History/DischargedEnergy'] = 0
        self._dbusservice['/ConsumedAmphours'] = 0
        self.dailyResetDone = datetime.now().day 


    def _update(self):
#	self._dbusservice['/Alarms/CellImbalance'] = (self._bat.internalErrors & 0x20)>>5
	deltaCellVoltage = self._bat.maxCellVoltage - self._bat.minCellVoltage

	# flag cell imbalance, only log first occurence 
	if (deltaCellVoltage > 0.25) :
		self._dbusservice['/Alarms/CellImbalance'] = 2
		if self._bat.balanced: 
			logging.error("Cell voltage imbalance: %.2fV, SOC: %d, @Module: %d ", deltaCellVoltage, self._bat.soc, self.moduleSoc.index(min(self.moduleSoc)))
		        logging.info("SOC: %d ",self._bat.soc )
		self._bat.balanced = False
	elif (deltaCellVoltage > 0.18):
		# warn only if not already balancing (UBMS threshold is 0.15V) 
		if self._bat.numberOfModulesBalancing == 0 :
			self._dbusservice['/Alarms/CellImbalance'] = 1
		if self._bat.balanced: 
			chain = itertools.chain(*self._bat.cellVoltages)
        		flatVList = list(chain)
        		iMax = flatVList.index(max(flatVList))
        		iMin = flatVList.index(min(flatVList))
			logging.info("Cell voltage imbalance: %.2fV, iMin: %d, iMax %d, SOC: %d ", deltaCellVoltage, iMin, iMax, self._bat.soc)
		self._bat.balanced = False
	else:
		self._dbusservice['/Alarms/CellImbalance'] = 0
		self._bat.balanced = True

	self._dbusservice['/Alarms/LowVoltage'] =  (self._bat.voltageAndCellTAlarms & 0x10)>>3 
        self._dbusservice['/Alarms/HighVoltage'] =  (self._bat.voltageAndCellTAlarms & 0x20)>>4 
	self._dbusservice['/Alarms/LowSoc'] = (self._bat.voltageAndCellTAlarms & 0x08)>>3 
        self._dbusservice['/Alarms/HighDischargeCurrent'] = (self._bat.currentAndPcbTAlarms & 0x3) 

#       flag high cell temperature alarm and high pcb temperature alarm  
	self._dbusservice['/Alarms/HighTemperature'] =	(self._bat.voltageAndCellTAlarms &0x6)>>1 | (self._bat.currentAndPcbTAlarms & 0x18)>>3
        self._dbusservice['/Alarms/LowTemperature'] = (self._bat.mode & 0x60)>>5 

        self._dbusservice['/Soc'] = self._bat.soc 
	if self._bat.soc == 100 or self._bat.chargeComplete :  
		if datetime.fromtimestamp(time()).day != datetime.fromtimestamp(float(self._settings['TimeLastFull'])).day: 
			logging.info("Fully charged, SOC(min/max/avg): %d/%d/%d, Discharged: %.2f, Charged: %.2f ",min(self._bat.moduleSoc), max(self._bat.moduleSoc), self._bat.soc,  self._dbusservice['/History/DischargedEnergy'],  self._dbusservice['/History/ChargedEnergy'])  
			self._settings['TimeLastFull'] = time() 

        self._dbusservice['/Status'] = (self._bat.mode &0xC)
        self._dbusservice['/Mode'] = (self._bat.mode &0x3)
        self._dbusservice['/Balancing'] = (self._bat.mode &0x10)>>4
        self._dbusservice['/Dc/0/Current'] = self._bat.current
        self._dbusservice['/Dc/0/Voltage'] = self._bat.voltage
        power = self._bat.voltage * self._bat.current
        self._dbusservice['/Dc/0/Power'] = power 
        self._dbusservice['/Dc/0/Temperature'] = self._bat.maxCellTemperature
	chain = itertools.chain(*self._bat.cellVoltages)
	flatVList = list(chain)
	index = flatVList.index(max(flatVList))	
	m = index / 4 
	c = index % 4 
        self._dbusservice['/System/MaxVoltageCellId'] = 'M'+str(m+1)+'C'+str(c+1)
 	index = flatVList.index(min(flatVList))
        m = index / 4
        c = index % 4 
        self._dbusservice['/System/MinVoltageCellId'] = 'M'+str(m+1)+'C'+str(c+1) 
        self._dbusservice['/System/MaxCellVoltage'] = self._bat.maxCellVoltage
	if (self._bat.maxCellVoltage > self._dbusservice['/History/MaxCellVoltage'] ):
        	self._dbusservice['/History/MaxCellVoltage'] = self._bat.maxCellVoltage
		logging.info("New maximum cell voltage: %f", self._bat.maxCellVoltage)
        self._dbusservice['/System/MinCellVoltage'] = self._bat.minCellVoltage
	if (0 < self._bat.minCellVoltage < self._dbusservice['/History/MinCellVoltage'] ):
	        self._dbusservice['/History/MinCellVoltage'] = self._bat.minCellVoltage
		logging.info("New minimum cell voltage: %f", self._bat.minCellVoltage)
        self._dbusservice['/System/MinCellTemperature'] = self._bat.minCellTemperature
        self._dbusservice['/System/MaxCellTemperature'] = self._bat.maxCellTemperature
        self._dbusservice['/System/MaxPcbTemperature'] = self._bat.maxPcbTemperature
        self._dbusservice['/Info/MaxChargeCurrent'] = self._bat.maxChargeCurrent
        self._dbusservice['/Info/MaxDischargeCurrent'] = self._bat.maxDischargeCurrent
        self._dbusservice['/Info/MaxChargeVoltage'] = self._bat.maxChargeVoltage
        self._dbusservice['/System/NrOfModulesOnline'] =  self._bat.numberOfModules
        self._dbusservice['/System/NrOfBatteriesBalancing'] = self._bat.numberOfModulesBalancing
	
	if self._bat.current > 0  and datetime.now().day != self.dailyResetDone : #on first occurence of a positive bat current 
		self._daily_stats()

	now = datetime.now().time()
	if now.minute != self.minUpdateDone: 
	    self.minUpdateDone = now.minute	
	    if self._bat.current > 0:
		#charging 
	      	#calculate time to full
		self._dbusservice['/TimeToGo'] = (100 - self._bat.soc)*self._bat.capacity * 36 / self._bat.current 
                self._dbusservice['/History/ChargedEnergy'] += power * 1.666667e-5 #kWh
            else:
		#discharging
		self._dbusservice['/ConsumedAmphours'] += self._bat.current * 0.016667 #Ah
		self._dbusservice['/History/TotalAhDrawn'] += self._bat.current * 0.016667 #Ah
                self._dbusservice['/History/DischargedEnergy'] += power * 1.666667e-5 #kWh
		#calculate time to empty/full
		try:
			self._dbusservice['/TimeToGo'] = self._bat.soc*self._bat.capacity*36/(-self._bat.current)
		except:
		      	self._dbusservice['/TimeToGo'] = self._bat.soc*self._bat.capacity*36

	    self._safe_history()

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
        logging.warning('Battery capacity not specified, using default (130Ah)')
	args.capacity = 130 

    if not args.voltage:
        logging.warning('Maximum charge voltage not specified, using default 14.5V')
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

    logging.debug('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
    mainloop = gobject.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()

