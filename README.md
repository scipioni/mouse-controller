# mouse controller


```
python3.12 -mvenv .venv
source .venv/bin/activate
pip install uv

uv sync --active --extra dev
```

```
sudo apt-get install python3-dbus python3-gi bluez libbluetooth-dev
pip install pybluez python-uinput dbus-python
sudo modprobe uinput

```


```
bluetoothctl
[bluetooth]# power on
[bluetooth]# discoverable on
[bluetooth]# pairable on
```
