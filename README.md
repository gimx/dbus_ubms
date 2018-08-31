# dbus_ubms
CANBUS to dbus bridge for a Valence U-BMS to provide battery service on Victronenergy Venus OS

Preparation
sudo apt-get install libgtk2.0-dev  libdbus-1-dev libgirepository1.0-dev python-gobject python-can
sudo pip install dbus-python can pygobject

sudo vi /etc/dbus-1/system.d/com.victronenergy.dbus_ubms.conf
sudo systemctl reload dbus

cd ext
git clone https://github.com/victronenergy/velib_python.git



Developed using information from
https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus
https://github.com/victronenergy/velib_python

https://groups.google.com/forum/#!msg/victron-dev-venus/nCrpONiWYs0/-Z4wnkEJAAAJ;context-place=forum/victron-dev-venus

/opt/victronenergy/vrmlogger/datalist.py

