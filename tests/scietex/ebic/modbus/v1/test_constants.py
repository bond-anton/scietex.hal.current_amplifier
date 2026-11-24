"""Tests for the EBIC v1.0 wire constants.

Every value here is transcribed from the firmware; a test fails if it drifts.
"""

try:
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        BAUD_INDEX_TO_RATE,
        COILS,
        DEFAULT_BAUD_INDEX,
        DEFAULT_SLAVE_ADDRESS,
        INPUT_REGISTERS,
        PRODUCT_NAME,
        RATE_TO_BAUD_INDEX,
        REBOOT_DELAY_S,
        REGISTERS,
        RELAY_COUNT,
        SERIAL_NUMBER_DEFAULT,
        SLAVE_ADDRESS_MAX,
        SLAVE_ADDRESS_MIN,
        VENDOR_NAME,
        BaudRate,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        BAUD_INDEX_TO_RATE,
        COILS,
        DEFAULT_BAUD_INDEX,
        DEFAULT_SLAVE_ADDRESS,
        INPUT_REGISTERS,
        PRODUCT_NAME,
        RATE_TO_BAUD_INDEX,
        REBOOT_DELAY_S,
        REGISTERS,
        RELAY_COUNT,
        SERIAL_NUMBER_DEFAULT,
        SLAVE_ADDRESS_MAX,
        SLAVE_ADDRESS_MIN,
        VENDOR_NAME,
        BaudRate,
    )


def test_baud_rate_members_are_the_six_supported_rates_in_index_order():
    """The firmware enumerates exactly these six rates, index 0 first."""
    assert [int(rate) for rate in BaudRate] == [
        9600,
        14400,
        19200,
        38400,
        57600,
        115200,
    ]


def test_baud_index_to_rate_matches_the_firmware_table():
    """Index 0-5 selects 9600 through 115200 baud."""
    assert BAUD_INDEX_TO_RATE == {
        0: BaudRate.B9600,
        1: BaudRate.B14400,
        2: BaudRate.B19200,
        3: BaudRate.B38400,
        4: BaudRate.B57600,
        5: BaudRate.B115200,
    }


def test_rate_to_baud_index_is_the_inverse():
    """The write path maps a rate back to the index the register stores."""
    assert {
        rate.value: index for index, rate in enumerate(BaudRate)
    } == RATE_TO_BAUD_INDEX


def test_factory_defaults():
    """An empty EEPROM yields address 2, index 2 and serial 0x12345678."""
    assert DEFAULT_SLAVE_ADDRESS == 2
    assert DEFAULT_BAUD_INDEX == 2
    assert SERIAL_NUMBER_DEFAULT == 0x12345678
    assert REBOOT_DELAY_S == 0.5


def test_slave_address_bounds():
    """The firmware accepts slave addresses 1 through 247."""
    assert SLAVE_ADDRESS_MIN == 1
    assert SLAVE_ADDRESS_MAX == 247


def test_relay_count():
    """Seventeen relays map to coils 0-16."""
    assert RELAY_COUNT == 17
    assert COILS.RELAY_START == 0


def test_holding_register_addresses():
    """Only registers 0, 1, 10 and 11 carry data."""
    assert REGISTERS.SLAVE_ADDRESS == 0
    assert REGISTERS.BAUD_INDEX == 1
    assert REGISTERS.SERIAL_NUMBER_HI == 10
    assert REGISTERS.SERIAL_NUMBER_LO == 11


def test_input_register_addresses():
    """The identity block and the relay mirror have fixed offsets."""
    assert INPUT_REGISTERS.VENDOR_START == 0
    assert INPUT_REGISTERS.PRODUCT_START == 10
    assert INPUT_REGISTERS.VERSION_START == 30
    assert INPUT_REGISTERS.SERIAL_NUMBER_START == 33
    assert INPUT_REGISTERS.SERVICE_CONSTANT == 35
    assert INPUT_REGISTERS.RELAY_LEVEL_START == 36


def test_identity_strings():
    """The vendor and product strings are the firmware's own spellings."""
    assert VENDOR_NAME == "SCIETEX.RU"
    assert PRODUCT_NAME == "EBIC_Preamp"
