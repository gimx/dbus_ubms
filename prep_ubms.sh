#/opt/victronenergy/swupdate-scripts/set-feed.sh candidate
/opt/victronenergy/swupdate-scripts/set-feed.sh release
opkg update
opkg install python3-misc python3-distutils python3-ctypes python3-pkgutil
opkg install python3-xmlrpc python3-unixadmin
#opkg install python3-unittest python3-difflib python3-compile gcc binutils python3-dev 
python get-pip.py
pip install python-can
