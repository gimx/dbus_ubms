## dbus_ubms
 CANBUS to dbus bridge for a Valence U-BMS to provide battery monitor service on Victronenergy Venus OS

 Use this code at your own risk.
## Installation
```
with git:
 opkg install git
 git clone https://github.com/gimx/dbus_ubms.git
 cd dbus_ubms/ext
 git clone https://github.com/victronenergy/velib_python.git

or download the above projects as archives, copy and unzip to root home
```

## Dependencies
 python-can (with wrapt and typing_extensions) is bundled in ext/, see ext/VENDORED.md, so nothing has to be
 installed on Venus OS and the driver keeps working after firmware updates (packages installed with opkg
 are lost on every update). dbus-python and PyGObject are part of Venus OS.

## Preparation on Raspi (development, not Venus OS)
```
 sudo apt-get install libgtk2.0-dev libdbus-1-dev libgirepository1.0-dev python3-gi
 sudo pip install dbus-python pygobject
```

## Run from command line
```
 python dbus_ubms.py -i can0 -v 29.0 -c 650
 or
 nohup python dbus_ubms.py -i can0 -v 29.0 -c 650 &
```

## Run as a service: 
```
 ln -s /home/root/dbus_ubms/service /service/dbus-ubms.can0
 cp rc.local /data/rc.local
 svc -u /service/dbus-ubms.can0
```

## Standby and startup check
 The driver acts as VMU master and always starts with the U-BMS in standby mode, i.e. the contactor open,
 while all data is read and published on dbus. While in standby /State is 14, /Mode is 252 and
 /Info/MaxChargeCurrent and /Info/MaxDischargeCurrent are reported as 0.

 After --startup-delay seconds (default 10) the driver checks on dbus whether the contactor can be closed.
 It stays in standby and logs the reason if
 - the pack voltage does not fit the configured max charge voltage (-v), or
 - another BMS is active: a battery service with a charge voltage limit (/Info/MaxChargeVoltage) that is
   connected and not in standby (/State 14 or /Mode 252), or the ActiveBmsService of the system, or
 - the DC bus is energized (above 5V, as reported by other batteries not in standby, Multis/inverters,
   chargers, solar chargers, DC-DC converters, ...) with a voltage outside the range of this pack (65-105%
   of -v) or differing from the pack voltage by more than --max-voltage-delta (default 1.0V).
 Otherwise it switches to drive mode and closes the contactor. The check is done once only; writing /Mode
 before it ran (e.g. by a BMS switcher) cancels it.

 Change the mode at any time by writing to /Mode, 3 closes the contactor (drive), 252 opens it (standby):
```
 dbus -y com.victronenergy.battery.socketcan_can0_di0 /Mode SetValue %3
 dbus -y com.victronenergy.battery.socketcan_can0_di0 /Mode SetValue %252
```

 For compatibility with dbus-serialbattery (e.g. dbus-bms-switcher) the driver also provides
 /Settings/ForceChargingOff, /Settings/ForceDischargingOff (writeable, 0/1) and /Io/AllowToCharge,
 /Io/AllowToDischarge. The U-BMS has a single contactor for both directions, so it is opened (standby) only
 when both are forced off. With just one direction forced off the contactor is closed (drive) and that
 direction is blocked by reporting its current limit as 0. In standby both flags are 1, writing /Mode
 sets both flags accordingly. /Io/AllowTo(Dis)Charge is 1 when the U-BMS reports a mode allowing it
 and the direction is not forced off.

 With several U-BMS in one system give each instance a different --startup-delay (at least 10s apart),
 instances in standby do not see each other as active, so the first one closing must be visible on dbus
 before the next one does its check.

 The driver puts the U-BMS into standby (contactor open) whenever it stops: on SIGTERM/SIGINT/SIGHUP
 (e.g. svc -d), on an unhandled exception and on any other regular exit. It waits up to 3s for the U-BMS
 to confirm standby. If the process cannot clean up (SIGKILL, power loss) the U-BMS in VMU slave mode
 falls back to standby by itself 20s after the last mode command.

## Configuration of U-BMS
```
 set SOC calculation to minimum (not average)
 set voltage scaling factor to 1
 set VMU slave mode (error on timeout maybe on or off)
 configure C3 to single discharge/charge contactor, ie no separate charge path, no pre-charge, no on/off charge control
 connect C3 (and route battery + through it)
 connect battery voltage
 connect CAN and CAN 5V supply
 connect +12V for System and Ignition
 in a system with x modules in series and multiple in parallel, module numbers 1 to x have to be assigned to one string, pack voltage calculation depends on this 
``` 
   

## Credits
 - Majority of the protocol reverse engineering work was done by @cogito44 http://cogito44.free.fr
 - This code has been developed using information from the following (re-)sources
   - https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus
   - https://github.com/victronenergy/venus/wiki/dbus#battery
   - https://github.com/victronenergy/velib_python
   - https://groups.google.com/forum/#!msg/victron-dev-venus/nCrpONiWYs0/-Z4wnkEJAAAJ;context-place=forum/victron-dev-venus
   - /opt/victronenergy/vrmlogger/datalist.py
   - https://groups.google.com/forum/#!searchin/victron-dev-venus/link$20to$20service%7Csort:date/victron-dev-venus/-AJzKTxk-3k/fOt707ZeAAAJ

