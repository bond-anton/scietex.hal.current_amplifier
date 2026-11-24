"""EBIC v1.0 preamp Modbus RTU subpackage.

Modules:
    client: Implements the `EBICModbusV1Preamp` relay driver.
    constants: Wire register, coil and identity constants.
    identity: Decodes the device identity from input registers.
    relaymap: Maps relays to amplifier functions and decodes coil readbacks.
    semantic: Implements the `EBICModbusV1Amplifier` contract over the relay map.

Exports:
    EBICModbusV1Preamp: The EBIC v1.0 Modbus RTU driver.
    EBICModbusV1Amplifier: The EBIC v1.0 current amplifier contract.
    DeviceIdentity: The vendor, product, version and serial number.
    BaudRate: Baud rates the firmware selects by index.
    RelayAccess: The relay operations the semantic layer needs.
    RelayMapAssumptions: The board facts the relay map records as inference.
    RelayTransitionError: A relay transition did not reach its target.
"""

from .client import EBICModbusV1Preamp
from .constants import BaudRate
from .identity import DeviceIdentity
from .semantic import (
    EBICModbusV1Amplifier,
    RelayAccess,
    RelayMapAssumptions,
    RelayTransitionError,
)

__all__ = [
    "BaudRate",
    "DeviceIdentity",
    "EBICModbusV1Amplifier",
    "EBICModbusV1Preamp",
    "RelayAccess",
    "RelayMapAssumptions",
    "RelayTransitionError",
]
