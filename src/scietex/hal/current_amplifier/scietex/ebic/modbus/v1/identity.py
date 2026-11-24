"""Device identity decoded from the EBIC v1.0 input registers.

The firmware reports the identity as one block of read-only input registers:
ten vendor characters, twenty product characters, three version words and two
serial-number words. This module decodes that block without touching the bus.

Classes:
    DeviceIdentity: The vendor, product, version and serial number of a device.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .constants import INPUT_REGISTERS

IDENTITY_REGISTER_COUNT = INPUT_REGISTERS.SERIAL_NUMBER_START + 2
"""Number of input registers covered by the identity block, addresses 0-34."""


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """The identity the firmware reports through input registers 0-34.

    Attributes:
        vendor: Vendor string, ``SCIETEX.RU`` on a factory device.
        product: Product string, ``EBIC_Preamp`` on a factory device.
        version: Firmware version as ``(major, minor, patch)``.
        serial_number: 32-bit serial number built from the high and low words.
    """

    vendor: str
    product: str
    version: tuple[int, int, int]
    serial_number: int


def decode_identity(registers: Sequence[int]) -> DeviceIdentity:
    """
    Decode the input-register block into a :class:`DeviceIdentity`.

    Args:
        registers: Input-register words starting at address 0. At least
            ``IDENTITY_REGISTER_COUNT`` words are required.

    Returns:
        DeviceIdentity: The decoded identity. Trailing spaces the firmware pads
        the strings with are removed.

    Raises:
        ValueError: If fewer than ``IDENTITY_REGISTER_COUNT`` words are given.
    """
    if len(registers) < IDENTITY_REGISTER_COUNT:
        raise ValueError(
            f"identity needs {IDENTITY_REGISTER_COUNT} input registers, "
            f"got {len(registers)}"
        )

    vendor = _decode_string(
        registers[INPUT_REGISTERS.VENDOR_START : INPUT_REGISTERS.PRODUCT_START]
    )
    product = _decode_string(
        registers[INPUT_REGISTERS.PRODUCT_START : INPUT_REGISTERS.VERSION_START]
    )
    major, minor, patch = registers[
        INPUT_REGISTERS.VERSION_START : INPUT_REGISTERS.SERIAL_NUMBER_START
    ]
    serial_hi, serial_lo = registers[
        INPUT_REGISTERS.SERIAL_NUMBER_START : IDENTITY_REGISTER_COUNT
    ]
    return DeviceIdentity(
        vendor=vendor,
        product=product,
        version=(major, minor, patch),
        serial_number=(serial_hi << 16) | serial_lo,
    )


def _decode_string(registers: Sequence[int]) -> str:
    """Decode one character per register and strip the firmware's padding."""
    return "".join(chr(word) for word in registers).rstrip(" \x00")
