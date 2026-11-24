"""Wire constants for the EBIC v1.0 preamp Modbus RTU interface.

The values transcribe the firmware in ``ebic_control`` at commit ``66d3b08``.
Nothing is inferred beyond what that firmware implements: two writeable holding
registers, two read-only holding registers, read-only input registers 0-52 and
seventeen coils. The device exposes no ADC, DAC, measurement, status or unlock
register.

Classes:
    BaudRate: Baud rates the firmware selects by index.
    REGISTERS: Holding-register addresses.
    INPUT_REGISTERS: Input-register addresses.
    COILS: Coil addresses.
"""

from enum import IntEnum


class BaudRate(IntEnum):
    """Baud rates the firmware selects by index, in index order."""

    B9600 = 9600
    B14400 = 14400
    B19200 = 19200
    B38400 = 38400
    B57600 = 57600
    B115200 = 115200


BAUD_INDEX_TO_RATE: dict[int, BaudRate] = dict(enumerate(BaudRate))
"""Map a holding-register 1 value to the baud rate it selects."""

RATE_TO_BAUD_INDEX: dict[int, int] = {
    rate.value: index for index, rate in enumerate(BaudRate)
}
"""Map a baud rate to the index written into holding register 1."""

SLAVE_ADDRESS_MIN = 1
"""Lowest accepted Modbus slave address."""

SLAVE_ADDRESS_MAX = 247
"""Highest accepted Modbus slave address."""

DEFAULT_SLAVE_ADDRESS = 2
"""Slave address the firmware uses on an empty EEPROM."""

DEFAULT_BAUD_INDEX = 2
"""Baud index the firmware uses on an empty EEPROM, selecting 19200 baud."""

RELAY_COUNT = 17
"""Number of relay outputs driven by coils 0-16."""

REBOOT_DELAY_S = 0.5
"""Delay between acknowledging an address or baud change and restarting."""

SERIAL_NUMBER_DEFAULT = 0x12345678
"""Serial number the firmware uses on an empty EEPROM."""

VENDOR_NAME = "SCIETEX.RU"
"""Vendor string in input registers 0-9."""

PRODUCT_NAME = "EBIC_Preamp"
"""Product string in input registers 10-29, space-padded by the firmware."""


class REGISTERS:
    """Holding-register addresses (FC03 read, FC06/FC10 write)."""

    SLAVE_ADDRESS = 0
    """Slave address, 1-247, persisted to EEPROM."""

    BAUD_INDEX = 1
    """Baud index, 0-5, persisted to EEPROM."""

    SERIAL_NUMBER_HI = 10
    """High word of the serial number, read only."""

    SERIAL_NUMBER_LO = 11
    """Low word of the serial number, read only."""


class INPUT_REGISTERS:
    """Input-register addresses (FC04 read only)."""

    VENDOR_START = 0
    """First vendor-string register; ten registers, one character each."""

    PRODUCT_START = 10
    """First product-string register; twenty registers, one character each."""

    VERSION_START = 30
    """First of three version registers: major, minor, patch."""

    SERIAL_NUMBER_START = 33
    """First of two serial-number registers: high word, low word."""

    SERVICE_CONSTANT = 35
    """Service constant, always 7."""

    RELAY_LEVEL_START = 36
    """First of seventeen registers mirroring relay levels 0 and 1."""


class COILS:
    """Coil addresses (FC01 read, FC05/FC0F write)."""

    RELAY_START = 0
    """First relay coil; seventeen coils follow it."""
