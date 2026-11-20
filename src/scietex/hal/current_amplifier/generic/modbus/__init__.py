"""Generic Modbus driver for the current amplifier.

The driver is reachable by direct import until the device is identified and the
register map is transcribed; it is deliberately not advertised through the
driver entry points yet.

Exports:
    GenericModbusCurrentAmplifier: The vendor-neutral Modbus driver.
    RegisterMapIncomplete: A register the operation needs is not mapped.
    UnexpectedResponse: A response cannot belong to the register it answers.
    Register: The registers the driver needs.
    RegisterSpec: One register's wire address, function code and scaling.
    DEVICE_MAP: The specification of every register.
    STATUS_BITS: Status-word bit masks.
    FILTER_TYPE_CODES: Filter type enumeration codes.
"""

from .client import GenericModbusCurrentAmplifier
from .errors import RegisterMapIncomplete, UnexpectedResponse
from .registers import (
    DEVICE_MAP,
    FILTER_TYPE_CODES,
    STATUS_BITS,
    Register,
    RegisterSpec,
)

__all__ = [
    "DEVICE_MAP",
    "FILTER_TYPE_CODES",
    "STATUS_BITS",
    "GenericModbusCurrentAmplifier",
    "Register",
    "RegisterMapIncomplete",
    "RegisterSpec",
    "UnexpectedResponse",
]
