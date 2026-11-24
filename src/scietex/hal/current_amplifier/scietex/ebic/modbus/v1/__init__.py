"""EBIC v1.0 preamp Modbus RTU subpackage.

Modules:
    client: Implements the `EBICModbusV1Preamp` relay driver.
    constants: Wire register, coil and identity constants.
    identity: Decodes the device identity from input registers.

Exports:
    EBICModbusV1Preamp: The EBIC v1.0 Modbus RTU driver.
    DeviceIdentity: The vendor, product, version and serial number.
    BaudRate: Baud rates the firmware selects by index.
"""

from .client import EBICModbusV1Preamp
from .constants import BaudRate
from .identity import DeviceIdentity

__all__ = ["BaudRate", "DeviceIdentity", "EBICModbusV1Preamp"]
