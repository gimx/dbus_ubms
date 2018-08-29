#!/usr/bin/env python

"""
derived from dbusexample.py part of velib-python
A class to put a battery service on the dbus, according to victron standards, with constantly updating
paths. The data acquisition is done on CAN bus and decodes Valence U-BMS messages, in particular
arbitration ID 0x0c4

"""
import gobject
import platform
import argparse
import logging
import sys
import os

import can

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext/velib_python'))
from vedbus import VeDbusService

class CanbusDataAcquisition:
    def __init__(self,interface):
        self._bus = can.interface.Bus(channel=interface, bustype='socketcan')
        self.soc = 0;
        self.packvolatage = 0;
        self.dischargecurrent = 0;
        self.disschargecurrent = 0;
        self.temperature = 0;



class DbusBatteryService:
    def __init__(self, servicename, deviceinstance, paths, productname='V*lence U-BMS', connection='CAN bus'):
        self._dbusservice = VeDbusService(servicename)
        self._paths = paths

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 0)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/FirmwareVersion', 0)
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Connected', 1)
        #Create battery specific objects
        self._dbusservice.add_path('/Dc/Voltage', 24)
        self._dbusservice.add_path('/Dc/Current', 4)
        self._dbusservice.add_path('/Dc/Power', 100)
        self._dbusservice.add_path('/Dc/Temperature', 25)
        self._dbusservice.add_path('/Dc/Soc', 50)
        #self._dbusservice.add_path('/Dc/TimeToGo', 10)A

        for path, settings in self._paths.iteritems():
            self._dbusservice.add_path(
                path, settings['initial'], writeable=True, onchangecallback=self._handlechangedvalue)

        self._ci = can.interface.Bus(channel='slcan0', bustype='socketcan')

        gobject.timeout_add(1000, self._update)

    def _update(self):
        for message in self._ci:
                print(message)

        for path, settings in self._paths.iteritems():
            if 'update' in settings:
                self._dbusservice[path] = self._dbusservice[path] + settings['update']
                logging.debug("%s: %s" % (path, self._dbusservice[path]))
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True # accept the change


# === All code below is to simply run it from the commandline for debugging purposes ===

# It will created a dbus service called com.victronenergy.battery.ubms.0
# To try this on commandline, start this program in one terminal, and try these commands
# from another terminal:
# dbus com.victronenergy.battery.ubms
# dbus com.victronenergy.battery.ubms /Dc/Soc GetValue
#

def main():
    logging.basicConfig(level=logging.DEBUG)

    from dbus.mainloop.glib import DBusGMainLoop
    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    battery_output = DbusBatteryService(
        servicename='com.victronenergy.battery',
        deviceinstance=0,
        paths={
            '/Dc/Battery/Soc': {'initial': 50, 'update': 1},
            '/Dc/Battery/Voltage': {'initial': 24, 'update': 1},
            '/Dc/Battery/Current': {'initial': 4, 'update': 1},
            '/Dc/Battery/Power': {'initial': 100, 'update': 1},
        })

    logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
    mainloop = gobject.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()


