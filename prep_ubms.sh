/opt/victronenergy/swupdate-scripts/set-feed.sh candidate
opkg update
opkg install python-misc python-distutils python-ctypes python-pkgutil
opkg install python-xmlrpc python-unixadmin
#opkg install python-unittest python-difflib python-compile gcc binutils python-dev 
python get-pip.py
pip install python-can
