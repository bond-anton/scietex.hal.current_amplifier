"""EBIC v1.0 preamp Modbus subpackage.

Modules:
    client: Implements the `EBICModbusV1Preamp` relay driver over RS485.
    client_tcp: Implements the same relay driver over Modbus/TCP.
    constants: Wire register, coil and identity constants.
    exceptions: Transport exceptions specific to this device.
    identity: Decodes the device identity from input registers.
    relaymap: Maps relays to amplifier functions and decodes coil readbacks.
    semantic: Implements the amplifier contracts over the relay map.

Exports:
    EBICModbusV1Preamp: The EBIC v1.0 Modbus RTU driver.
    EBICModbusV1PreampTcp: The EBIC v1.0 Modbus/TCP driver.
    EBICModbusV1Amplifier: The EBIC v1.0 current amplifier contract.
    EBICModbusV1TcpAmplifier: The EBIC v1.0 amplifier contract over Modbus/TCP.
    DeviceIdentity: The vendor, product, version and serial number.
    BaudRate: Baud rates the firmware selects by index.
    GatewayBusy: The gateway or device was busy; the request is retryable.
    GatewayTargetFailed: The gateway could not reach the device.
    RelayAccess: The relay operations the semantic layer needs.
    RelayTransitionError: A relay transition did not reach its target.
    BOOSTER_COILS: Channel to the relay-3 coil that feeds it to the booster.
"""

from .client import EBICModbusV1Preamp
from .client_tcp import EBICModbusV1PreampTcp
from .constants import BaudRate
from .exceptions import GatewayBusy, GatewayTargetFailed
from .identity import DeviceIdentity
from .relaymap import BOOSTER_COILS
from .semantic import (
    EBICModbusV1Amplifier,
    EBICModbusV1TcpAmplifier,
    RelayAccess,
    RelayTransitionError,
)

__all__ = [
    "BOOSTER_COILS",
    "BaudRate",
    "DeviceIdentity",
    "EBICModbusV1Amplifier",
    "EBICModbusV1Preamp",
    "EBICModbusV1PreampTcp",
    "EBICModbusV1TcpAmplifier",
    "GatewayBusy",
    "GatewayTargetFailed",
    "RelayAccess",
    "RelayTransitionError",
]
