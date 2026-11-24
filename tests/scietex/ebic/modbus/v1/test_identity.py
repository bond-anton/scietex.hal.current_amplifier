"""Tests for the EBIC v1.0 identity decoder."""

from dataclasses import FrozenInstanceError

import pytest

try:
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        INPUT_REGISTERS,
        PRODUCT_NAME,
        SERIAL_NUMBER_DEFAULT,
        VENDOR_NAME,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.identity import (
        IDENTITY_REGISTER_COUNT,
        DeviceIdentity,
        decode_identity,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        INPUT_REGISTERS,
        PRODUCT_NAME,
        SERIAL_NUMBER_DEFAULT,
        VENDOR_NAME,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.identity import (
        IDENTITY_REGISTER_COUNT,
        DeviceIdentity,
        decode_identity,
    )


def _identity_block(
    vendor: str = VENDOR_NAME,
    product: str = PRODUCT_NAME,
    version: tuple[int, int, int] = (1, 0, 0),
    serial_number: int = SERIAL_NUMBER_DEFAULT,
) -> list[int]:
    """Build the input-register block the firmware reports at addresses 0-34."""
    block = [0] * IDENTITY_REGISTER_COUNT
    for offset, character in enumerate(vendor):
        block[INPUT_REGISTERS.VENDOR_START + offset] = ord(character)
    for offset, character in enumerate(product):
        block[INPUT_REGISTERS.PRODUCT_START + offset] = ord(character)
    block[INPUT_REGISTERS.VERSION_START : INPUT_REGISTERS.SERIAL_NUMBER_START] = list(
        version
    )
    block[INPUT_REGISTERS.SERIAL_NUMBER_START] = serial_number >> 16
    block[INPUT_REGISTERS.SERIAL_NUMBER_START + 1] = serial_number & 0xFFFF
    return block


def test_decodes_the_factory_identity():
    """Vendor, product, version and serial number come from their words."""
    identity = decode_identity(_identity_block())

    assert identity == DeviceIdentity(
        vendor="SCIETEX.RU",
        product="EBIC_Preamp",
        version=(1, 0, 0),
        serial_number=0x12345678,
    )


def test_decodes_a_non_factory_identity():
    """A different version and serial number decode without special cases."""
    identity = decode_identity(
        _identity_block(version=(2, 3, 4), serial_number=0x00A1B2C3)
    )

    assert identity.version == (2, 3, 4)
    assert identity.serial_number == 0x00A1B2C3


def test_strips_the_product_padding():
    """The firmware pads the product name to twenty spaces."""
    block = _identity_block(product="X" * 20)
    block[INPUT_REGISTERS.PRODUCT_START] = ord("X")
    for offset in range(1, 20):
        block[INPUT_REGISTERS.PRODUCT_START + offset] = ord(" ")

    assert decode_identity(block).product == "X"


def test_identity_register_count_covers_the_serial_number():
    """The block ends with the low serial-number word at address 34."""
    assert IDENTITY_REGISTER_COUNT == 35
    assert INPUT_REGISTERS.SERIAL_NUMBER_START + 2 == IDENTITY_REGISTER_COUNT


def test_short_block_is_rejected():
    """A block missing the serial number cannot be decoded."""
    with pytest.raises(ValueError, match="identity needs 35 input registers"):
        decode_identity(_identity_block()[:-1])


def test_identity_is_frozen():
    """The decoded identity cannot be mutated after it leaves the decoder."""
    identity = decode_identity(_identity_block())

    with pytest.raises(FrozenInstanceError):
        identity.serial_number = 0
