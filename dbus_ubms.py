#!/usr/bin/env python3

"""
A class to put a battery service on the dbus, according to victron standards, with constantly updating
paths.

"""
from gi.repository import GLib
import platform
import argparse
import logging
import sys
import os
import dbus
import itertools
import math

from time import time
from datetime import datetime
import struct
from argparse import ArgumentParser

from ubmsbattery import *


# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext/velib_python'))
from vedbus import VeDbusService
from ve_utils import exit_on_error
from settingsdevice import SettingsDevice

VERSION = '1.0'

def handle_changed_setting(setting, oldvalue, newvalue):
    logging.debug('setting changed, setting: %s, old: %s, new: %s' % (setting, oldvalue, newvalue))


class DbusBatteryService:
    def __init__(self, servicename, deviceinstance, voltage, capacity, productname='Valence U-BMS', connection='can0'):
        self.minUpdateDone = 0
        self.dailyResetDone = 0
        self.lastUpdated = 0
        self._bat = UbmsBattery(capacity=capacity, voltage=voltage, connection=connection)

        try:
             self._dbusservice = VeDbusService(servicename+'.socketcan_'+connection+'_di'+str(deviceinstance))
        except:
             exit

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
        self._dbusservice.add_path('/Connected', 0)
        # Create battery specific objects
        self._dbusservice.add_path('/State', 0)
        self._dbusservice.add_path('/Mode', 1, writeable=True, onchangecallback=self._transmit_mode)
        self._dbusservice.add_path('/Soh', 100)
        self._dbusservice.add_path('/Capacity', int(capacity))
        self._dbusservice.add_path('/InstalledCapacity', int(capacity))
        self._dbusservice.add_path('/Dc/0/Temperature', 25)
        self._dbusservice.add_path('/Info/MaxChargeCurrent', 0)
        self._dbusservice.add_path('/Info/MaxDischargeCurrent', int(capacity/2))
        self._dbusservice.add_path('/Info/MaxChargeVoltage', float(voltage))
        self._dbusservice.add_path('/Info/BatteryLowVoltage', 44.8)
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
        self._dbusservice.add_path('/System/NrOfBatteries', self._bat.numberOfModules)
        self._dbusservice.add_path('/System/NrOfModulesOnline', self._bat.numberOfModules)
        self._dbusservice.add_path('/System/NrOfModulesOffline', 0)
        self._dbusservice.add_path('/System/NrOfModulesBlockingDischarge', 0)
        self._dbusservice.add_path('/System/NrOfModulesBlockingCharge', 0)
        self._dbusservice.add_path('/System/NrOfBatteriesBalancing', 0)
        self._dbusservice.add_path('/System/BatteriesParallel', self._bat.numberOfStrings)
        self._dbusservice.add_path('/System/BatteriesSeries', self._bat.modulesInSeries)
        self._dbusservice.add_path('/System/NrOfCellsPerBattery', self._bat.cellsPerModule)
        self._dbusservice.add_path('/System/MinVoltageCellId', 'M_C_')
        self._dbusservice.add_path('/System/MaxVoltageCellId', 'M_C_')
        self._dbusservice.add_path('/System/MinCellTemperature', 10.0)
        self._dbusservice.add_path('/System/MaxCellTemperature', 10.0)
        self._dbusservice.add_path('/System/MaxPcbTemperature', 10.0)

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
                if BATTERY_CELL_DATA_FORMAT & 1:                                       
                    self._dbusservice.add_path(                                              
                        "/Balances/Cell%s" % (str(i)), None, writeable=True                  
                    )                                                                        
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
                bus=dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus(),
                supportedSettings={
                        'AvgDischarge': ['/Settings/Ubms/AvgerageDischarge', 0.0,0,0],
                        'TotalAhDrawn': ['/Settings/Ubms/TotalAhDrawn', 0.0,0,0],
                        'TimeLastFull': ['/Settings/Ubms/TimeLastFull', 0.0 ,0,0],
                        'MinCellVoltage': ['/Settings/Ubms/MinCellVoltage', 4.0,2.0,4.2],
                        'MaxCellVoltage': ['/Settings/Ubms/MaxCellVoltage', 2.0,2.0,4.2],
                        'interval': ['/Settings/Ubms/Interval', 50, 50, 200]
                },
                eventCallback=handle_changed_setting)


        self._summeditems = {
                        '/System/MaxCellVoltage': {'gettext': '%.2F V'},
                        '/System/MinCellVoltage': {'gettext': '%.2F V'},
                        '/Dc/0/Voltage': {'gettext': '%.2F V'},
                        '/Dc/0/Current': {'gettext': '%.1F A'},
                        '/Dc/0/Power': {'gettext': '%.0F W'},
                        '/Soc': {'gettext': '%.0F %%'},
                        '/History/TotalAhDrawn': {'gettext': '%.0F Ah'},
                        '/History/DischargedEnergy': {'gettext': '%.2F kWh'},
                        '/History/ChargedEnergy': {'gettext': '%.2F kWh'},
                        '/History/AverageDischarge': {'gettext': '%.2F kWh'},
                        '/TimeToGo': {'gettext': '%.0F s'},
                        '/ConsumedAmphours': {'gettext': '%.1F Ah'}
        }
        for path in self._summeditems.keys():
            self._dbusservice.add_path(path, value=None, gettextcallback=self._gettext)

        self._dbusservice['/History/AverageDischarge'] = self._settings['AvgDischarge']
        self._dbusservice['/History/TotalAhDrawn'] = self._settings['TotalAhDrawn']
        self._dbusservice.add_path('/History/TimeSinceLastFullCharge', 0)
        self._dbusservice.add_path('/History/MinCellVoltage', self._settings['MinCellVoltage'])
        self._dbusservice.add_path('/History/MaxCellVoltage', self._settings['MaxCellVoltage'])
        self._dbusservice['/ConsumedAmphours'] = 0


        logging.info("History cell voltage min: %.3f, max: %.3f, totalAhDrawn: %d",
                self._settings['MinCellVoltage'], self._settings['MaxCellVoltage'], self._settings['TotalAhDrawn'])

        self._dbusservice['/History/ChargedEnergy'] = 0
        self._dbusservice['/History/DischargedEnergy'] = 0

        GLib.timeout_add( self._settings['interval'], exit_on_error, self._update)

    def _gettext(self, path, value):
        item = self._summeditems.get(path)
        if item is not None:
            return item['gettext'] % value
        return str(value)

    def _transmit_mode(self, path, value):
        if self._bat.set_mode(value) == True:
            self._dbusservice[path] = value


    def __del__(self):
        self._safe_history()
        logging.info('Stopping dbus_ubms')


    def _safe_history(self):
        logging.debug('Saving history to localsettings')
        self._settings['AvgDischarge'] = self._dbusservice['/History/AverageDischarge']
        self._settings['TotalAhDrawn'] = self._dbusservice['/History/TotalAhDrawn']
        self._settings['MinCellVoltage'] = self._dbusservice['/History/MinCellVoltage']
        #self._settings['MaxCellVoltage'] = self._dbusservice['/History/MaxCellVoltage']


    def _daily_stats(self):
        if (self._dbusservice['/History/DischargedEnergy'] == 0): return
        logging.info("Updating stats, SOC: %d, Discharged: %.2f, Charged: %.2f ",self._bat.soc,  self._dbusservice['/History/DischargedEnergy'],  self._dbusservice['/History/ChargedEnergy'])
        self._dbusservice['/History/AverageDischarge'] = (6*self._dbusservice['/History/AverageDischarge'] + self._dbusservice['/History/DischargedEnergy'])/7 #rolling week
        self._dbusservice['/History/ChargedEnergy'] = 0
        self._dbusservice['/History/DischargedEnergy'] = 0
        dt = datetime.now() - datetime.fromtimestamp( float(self._settings['TimeLastFull']) )
        #if full within the last 24h and more than *0% consumed, estimate actual capacity and SOH based on consumed amphours from full and SOC reported
        if dt.total_seconds() < 24*3600 and self._bat.soc < 70:
            self._dbusservice['/Capacity'] = int(-self._dbusservice['/ConsumedAmphours'] * 100 / (100-self._bat.soc))
            self._dbusservice['/Soh'] = int(self._dbusservice['/Capacity']*100 / self._dbusservice['/InstalledCapacity'])
            logging.info("SOH: %d, Capacity: %d ", self._dbusservice['/Soh'],  self._dbusservice['/Capacity'])
        self.dailyResetDone = datetime.now().day


    def _update(self):
        if (self._bat.updated != -1 and  self.lastUpdated == 0) or  ((self._bat.updated - self.lastUpdated) < 1000):
            self.lastUpdated = self._bat.updated
            self._dbusservice['/Connected'] = 1
        else:
            self._dbusservice['/Connected'] = 0

#       self._dbusservice['/Alarms/CellImbalance'] = (self._bat.internalErrors & 0x20)>>5
        deltaCellVoltage = self._bat.maxCellVoltage - self._bat.minCellVoltage

        # flag cell imbalance, only log first occurence
        if (deltaCellVoltage > 0.25) :
            self._dbusservice['/Alarms/CellImbalance'] = 2
            if self._bat.balanced:
#                       logging.error("Cell voltage imbalance: %.2fV, SOC: %d, @Module: %d ", deltaCellVoltage, self._bat.soc, self._bat.moduleSoc.index(min(self.moduleSoc)))
                logging.error("Cell voltage imbalance: %.2fV, SOC: %d ", deltaCellVoltage, self._bat.soc)
                logging.info("SOC: %d ",self._bat.soc )
            self._bat.balanced = False
        elif (deltaCellVoltage >= 0.18):
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
        self._dbusservice['/Alarms/HighTemperature'] =  (self._bat.voltageAndCellTAlarms &0x6)>>1 | (self._bat.currentAndPcbTAlarms & 0x18)>>3
        self._dbusservice['/Alarms/LowTemperature'] = (self._bat.mode & 0x60)>>5

        self._dbusservice['/Soc'] = self._bat.soc
        dt = datetime.now() - datetime.fromtimestamp( float(self._settings['TimeLastFull']) )
        self._dbusservice['/History/TimeSinceLastFullCharge'] = (dt.seconds + dt.days * 24 * 3600)

        if self._bat.soc == 100 or self._bat.chargeComplete :
            #reset used Amphours to zero
            self._dbusservice['/ConsumedAmphours'] = 0
            if datetime.fromtimestamp(time()).day != datetime.fromtimestamp(float(self._settings['TimeLastFull'])).day:
            #and if it is the first time that day also create log entry
                logging.info("Fully charged, Discharged: %.2f, Charged: %.2f ", self._dbusservice['/History/DischargedEnergy'],  self._dbusservice['/History/ChargedEnergy'])
                self._settings['TimeLastFull'] = time()

        self._dbusservice['/State'] = self._bat.state
        self._dbusservice['/Mode'] = self._bat.guiModeKey.get((self._bat.mode & 0x3), 252)
        self._dbusservice['/Balancing'] = (self._bat.mode &0x10)>>4
        self._dbusservice['/Dc/0/Current'] = self._bat.current
        self._dbusservice['/Dc/0/Voltage'] = self._bat.voltage
        power = self._bat.voltage * self._bat.current
        self._dbusservice['/Dc/0/Power'] = power
        self._dbusservice['/Dc/0/Temperature'] = self._bat.maxCellTemperature

        #only update the below every 10s to reduce load
        if datetime.now().second not in [0, 20, 40]:
               return True

        chain = itertools.chain(*self._bat.cellVoltages)
        flatVList = list(chain)

        index = flatVList.index(max(flatVList))
        m = math.floor(index / 4)
        c = index % 4
        self._dbusservice['/System/MaxVoltageCellId'] = 'M'+str(m+1)+'C'+str(c+1)
        self._dbusservice['/System/MaxCellVoltage'] = self._bat.maxCellVoltage

        index = flatVList.index(min(flatVList))
        m = math.floor(index / 4)
        c = index % 4
        self._dbusservice['/System/MinVoltageCellId'] = 'M'+str(m+1)+'C'+str(c+1)
        self._dbusservice['/System/MinCellVoltage'] = self._bat.minCellVoltage

# cell voltages
        try:
            voltageSum = 0
            for i in range(len(flatVList)):
                voltage = flatVList[i]/1000.0
                cellpath = (
                    "/Voltages/Cell%s"
                )
                self._dbusservice[cellpath % (str(i+1))] = voltage
                self._dbusservice[
                    "/Balances/Cell%s" % (str(i+1))
                ] = voltage 
                if voltage and i < self._bat.cellsPerModule * self._bat.modulesInSeries:
                    voltageSum += voltage
            self._dbusservice["/Voltages/Sum"] = voltageSum
            self._dbusservice["/Voltages/Diff"] = (
                self._bat.maxCellVoltage - self._bat.minCellVoltage
            )
        except Exception:
            pass


        
        if (self._bat.maxCellVoltage > self._dbusservice['/History/MaxCellVoltage'] ):
            self._dbusservice['/History/MaxCellVoltage'] = self._bat.maxCellVoltage
            logging.info("New maximum cell voltage: %f", self._bat.maxCellVoltage)

        if (0 < self._bat.minCellVoltage < self._dbusservice['/History/MinCellVoltage'] ):
            self._dbusservice['/History/MinCellVoltage'] = self._bat.minCellVoltage
            logging.info("New minimum cell voltage: %f", self._bat.minCellVoltage)
        self._dbusservice['/System/MinCellTemperature'] = self._bat.minCellTemperature
        self._dbusservice['/System/MaxCellTemperature'] = self._bat.maxCellTemperature
        self._dbusservice['/System/MaxPcbTemperature'] = self._bat.maxPcbTemperature
        self._dbusservice['/Info/MaxChargeCurrent'] = self._bat.maxChargeCurrent
        self._dbusservice['/Info/MaxDischargeCurrent'] = self._bat.maxDischargeCurrent
        self._dbusservice['/Info/MaxChargeVoltage'] = self._bat.maxChargeVoltage
        self._dbusservice['/System/NrOfModulesOnline'] =  self._bat.numberOfModulesCommunicating
        self._dbusservice['/System/NrOfModulesOffline'] =  self._bat.numberOfModules - self._bat.numberOfModulesCommunicating
        self._dbusservice['/System/NrOfBatteriesBalancing'] = self._bat.numberOfModulesBalancing

        #update energy statistics daily at 6:00,
        if datetime.now().hour == 6 and datetime.now().minute == 0 and datetime.now().day != self.dailyResetDone :
            self._daily_stats()

        now = datetime.now().time()
        if now.minute != self.minUpdateDone:
            self.minUpdateDone = now.minute
            if self._bat.current > 0:
            #charging
                self._dbusservice['/History/ChargedEnergy'] += power * 1.666667e-5 #kWh
                #calculate time to full, in the absense of a mutex accessing bat.current value might have changed
                #to 0 after check above, so try to catch a div0
                try:
                    self._dbusservice['/TimeToGo'] = (100 - self._bat.soc)*self._bat.capacity * 36 / self._bat.current
                except:
                    self._dbusservice['/TimeToGo'] = self._bat.soc*self._bat.capacity*36
            else :
                #discharging
                self._dbusservice['/ConsumedAmphours'] += self._bat.current * 0.016667 #Ah
                self._dbusservice['/History/TotalAhDrawn'] += self._bat.current * 0.016667 #Ah
                self._dbusservice['/History/DischargedEnergy'] += -power * 1.666667e-5 #kWh

                #calculate time to empty
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
        logging.error('Maximum charge voltage not specified. Exiting.')
        return

    logging.info('Starting dbus_ubms %s on %s ' %
             (VERSION, args.interface))

    from dbus.mainloop.glib import DBusGMainLoop
    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    if sys.version_info.major == 2:
        gobject.threads_init()
    DBusGMainLoop(set_as_default=True)

    battery_output = DbusBatteryService(
        servicename='com.victronenergy.battery',
        connection = args.interface,
        deviceinstance=0,
        capacity = int(args.capacity),
        voltage = float(args.voltage)
        )

    logging.debug('Connected to dbus, and switching over to GLib.MainLoop() (= event based)')
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
