# dbus_ubms
CANBUS to dbus bridge for a Valence U-BMS to provide battery service on Victronenergy Venus OS

Preparation on Raspi
sudo apt-get install libgtk2.0-dev  libdbus-1-dev libgirepository1.0-dev python-gobject python-can
sudo pip install dbus-python can pygobject

#sudo vi /etc/dbus-1/system.d/com.victronenergy.dbus_ubms.conf
#sudo systemctl reload dbus

Preparation on CCGX
wget https://bootstrap.pypa.io/ez_setup.py
pythonn ez_setup.py
easy_install python-can


git clone https://github.com/gimx/dbus_ubms.git
cd dbus_ubms/ext
git clone https://github.com/victronenergy/velib_python.git
cd ..
python dbus_ubms.py

Developed using information from
https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus
https://github.com/victronenergy/velib_python

https://groups.google.com/forum/#!msg/victron-dev-venus/nCrpONiWYs0/-Z4wnkEJAAAJ;context-place=forum/victron-dev-venus

/opt/victronenergy/vrmlogger/datalist.py

