# Bundled third-party packages

Pure-Python packages bundled with dbus-ubms, so that the driver works without
`opkg install python3-can`, which is lost on every Venus OS firmware update.
`dbus_ubms.py` puts this folder first on `sys.path`.

| Package | Version | Source | License |
|---|---|---|---|
| python-can (`can/`) | 4.6.1 | PyPI wheel python_can-4.6.1-py3-none-any.whl | LGPL-3.0, `licenses/python-can-LICENSE.txt` |
| wrapt (`wrapt/`) | 1.17.3 | PyPI sdist, Python sources only (no C extension, wrapt falls back to its pure-Python implementation) | BSD-2-Clause, `licenses/wrapt-LICENSE` |
| typing_extensions (`typing_extensions.py`) | 4.15.0 | PyPI wheel | PSF-2.0, `licenses/typing_extensions-LICENSE` |

python-can's `packaging` dependency is not bundled, it is only used by the PCAN interface.

To update, download the new versions with pip into an empty folder and replace the files above.
