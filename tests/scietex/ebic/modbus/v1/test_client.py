"""Tests for the EBIC v1.0 Modbus RTU relay driver.

The transport is replaced by a stub that records each request and returns a
canned PDU, so these cover request construction, response validation and the
register map rather than the serial port. No test opens a port.

The register addresses, counts and coil values asserted here transcribe the
firmware README's frame examples for slave 2 (``02 01 00 00 00 11 FC 35`` to
read all 17 outputs, ``02 05 00 00 FF 00 8C 09`` for PA0 = 1, and
``02 0F 00 00 00 11 03 FF FF 01 DC 7A`` to set all 17 outputs to 1), so a drift
in the request shape fails a test.
"""

import asyncio

import pytest
from pymodbus.pdu import ModbusPDU
from pymodbus.pdu.bit_message import (
    ReadCoilsRequest,
    ReadCoilsResponse,
    WriteMultipleCoilsRequest,
    WriteMultipleCoilsResponse,
    WriteSingleCoilRequest,
    WriteSingleCoilResponse,
)
from pymodbus.pdu.register_message import (
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    ReadInputRegistersRequest,
    ReadInputRegistersResponse,
    WriteSingleRegisterRequest,
    WriteSingleRegisterResponse,
)
from scietex.hal.serial import ModbusSerialConnectionConfig

try:
    from src.scietex.hal.current_amplifier.base import (
        AmplifierState,
        CurrentAmplifierCapabilities,
        CurrentAmplifierProtocol,
        RegisterMapIncomplete,
        UnexpectedResponse,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1Preamp,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        COILS,
        DEFAULT_SLAVE_ADDRESS,
        INPUT_REGISTERS,
        REGISTERS,
        RELAY_COUNT,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.identity import (
        IDENTITY_REGISTER_COUNT,
        DeviceIdentity,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.base import (
        AmplifierState,
        CurrentAmplifierCapabilities,
        CurrentAmplifierProtocol,
        RegisterMapIncomplete,
        UnexpectedResponse,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1Preamp,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        COILS,
        DEFAULT_SLAVE_ADDRESS,
        INPUT_REGISTERS,
        REGISTERS,
        RELAY_COUNT,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.identity import (
        IDENTITY_REGISTER_COUNT,
        DeviceIdentity,
    )

_CAPABILITY_PROPERTIES = [
    "supports_preamp",
    "supports_boost",
    "supports_dc_bias",
    "supports_bandwidth",
    "supports_filters",
    "supports_input_overcurrent",
    "supports_output_overload",
    "supports_input_compensation",
    "supports_invert_output",
]

_WRITE_PROPERTIES = [
    "can_select_preamp",
    "can_set_boost",
    "can_set_dc_bias",
    "can_set_bandwidth",
    "can_set_filter",
    "can_set_input_compensation",
    "can_set_invert_output",
]


def _config() -> ModbusSerialConnectionConfig:
    """A Modbus RTU configuration; the port is never opened in these tests."""
    return ModbusSerialConnectionConfig(port="/dev/ttyUSB0", framer="RTU")


class StubPreamp(EBICModbusV1Preamp):
    """Driver that records each request and returns the next canned response."""

    def __init__(self, responses: tuple[ModbusPDU | None, ...] = ()) -> None:
        super().__init__(_config())
        self.requests: list[ModbusPDU] = []
        self.responses = list(responses)

    async def execute(
        self,
        request: ModbusPDU,
        no_response_expected: bool = False,
        raise_on_error: bool = True,
    ) -> ModbusPDU | None:
        """Record the request and return the next canned response."""
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("stub ran out of canned responses")
        return self.responses.pop(0)


def _run(scenario, *responses) -> None:
    """Run one scenario on a fresh driver inside a live event loop."""

    async def main() -> None:
        driver = StubPreamp(responses)
        try:
            await scenario(driver)
        finally:
            await driver.close()

    asyncio.run(main())


def _identity_block() -> list[int]:
    """The input-register block the firmware reports at addresses 0-34."""
    block = [0] * IDENTITY_REGISTER_COUNT
    for offset, character in enumerate("SCIETEX.RU"):
        block[INPUT_REGISTERS.VENDOR_START + offset] = ord(character)
    for offset, character in enumerate("EBIC_Preamp".ljust(20)):
        block[INPUT_REGISTERS.PRODUCT_START + offset] = ord(character)
    block[INPUT_REGISTERS.VERSION_START : INPUT_REGISTERS.SERIAL_NUMBER_START] = [
        1,
        0,
        0,
    ]
    block[INPUT_REGISTERS.SERIAL_NUMBER_START] = 0x1234
    block[INPUT_REGISTERS.SERIAL_NUMBER_START + 1] = 0x5678
    return block


# -- construction and protocol ---------------------------------------------


def test_constructor_defaults():
    """The device answers at address 2 and the driver labels itself for logs."""

    async def scenario(driver) -> None:
        assert driver.address == DEFAULT_SLAVE_ADDRESS
        assert driver.label == "EBIC Preamp"
        assert driver.con_params.port == "/dev/ttyUSB0"

    _run(scenario)


def test_capabilities_are_empty_class_data():
    """The relay layer advertises nothing the capability model describes."""
    assert "capabilities" in EBICModbusV1Preamp.__dict__
    capabilities = EBICModbusV1Preamp.capabilities
    assert isinstance(capabilities, CurrentAmplifierCapabilities)
    assert not any(
        (
            capabilities.preamp.range,
            capabilities.preamp.feedback_resistor,
            capabilities.boost.gain,
            capabilities.dc_bias.enabled,
            capabilities.dc_bias.level,
            capabilities.bandwidth,
            capabilities.filters.enabled,
            capabilities.filters.cutoff,
            capabilities.input_compensation.enabled,
            capabilities.input_compensation.level,
            capabilities.invert_output,
        )
    )
    assert capabilities.filters.types == ()
    assert capabilities.bandwidth.options == ()

    async def scenario(driver) -> None:
        for name in _CAPABILITY_PROPERTIES + _WRITE_PROPERTIES:
            assert getattr(driver, name) is False

    _run(scenario)


def test_driver_satisfies_the_protocol():
    """The driver is a runtime-checkable :class:`CurrentAmplifierProtocol`."""

    async def scenario(driver) -> None:
        assert isinstance(driver, CurrentAmplifierProtocol)

    _run(scenario)


def test_connect_does_not_touch_the_bus():
    """The serial client opens the port per operation, so connect is a no-op."""

    async def scenario(driver) -> None:
        await driver.connect()
        assert driver.requests == []

    _run(scenario)


def test_read_data_returns_an_empty_snapshot():
    """The firmware reports no amplifier value, so every field stays None."""

    async def scenario(driver) -> None:
        state = await driver.read_data()
        assert state == AmplifierState()
        assert state.filters == ()
        assert driver.requests == []

    _run(scenario)


# -- relays ----------------------------------------------------------------


def test_read_relays_reads_coils_zero_through_sixteen():
    """FC01 is issued once for the whole relay range."""
    levels = [index % 2 == 0 for index in range(RELAY_COUNT)]

    async def scenario(driver) -> None:
        relays = await driver.read_relays()

        assert relays == tuple(levels)
        request = driver.requests[0]
        assert isinstance(request, ReadCoilsRequest)
        assert request.address == COILS.RELAY_START
        assert request.count == RELAY_COUNT
        assert request.dev_id == DEFAULT_SLAVE_ADDRESS

    _run(
        scenario,
        ReadCoilsResponse(bits=[*levels, False, False, False, False, False]),
    )


def test_read_relays_discards_the_unused_padding_bits():
    """The last byte carries padding above bit 16; only seventeen are returned."""

    async def scenario(driver) -> None:
        relays = await driver.read_relays()

        assert relays == (True, False, True) + (False,) * 14

    _run(scenario, ReadCoilsResponse(bits=[True, False, True] + [False] * 21))


def test_read_relays_rejects_a_short_response():
    """A response with fewer than seventeen coils is not a relay snapshot."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse) as excinfo:
            await driver.read_relays()

        assert excinfo.value.register == "relays"

    _run(scenario, ReadCoilsResponse(bits=[True] * (RELAY_COUNT - 1)))


def test_read_relays_rejects_a_missing_response():
    """No response is an unexpected response, not a silent empty tuple."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse):
            await driver.read_relays()

    _run(scenario, None)


@pytest.mark.parametrize("level", [True, False])
def test_read_relay_reads_only_the_requested_coil(level):
    """FC01 is issued for a single coil at the relay index."""

    async def scenario(driver) -> None:
        assert await driver.read_relay(3) is level

        request = driver.requests[0]
        assert isinstance(request, ReadCoilsRequest)
        assert request.address == 3
        assert request.count == 1

    _run(scenario, ReadCoilsResponse(bits=[level] + [False] * 7))


@pytest.mark.parametrize("index", [-1, RELAY_COUNT])
def test_read_relay_rejects_an_index_outside_the_range(index):
    """An invalid relay index fails before any bus traffic."""

    async def scenario(driver) -> None:
        with pytest.raises(IndexError):
            await driver.read_relay(index)

        assert driver.requests == []

    _run(scenario)


@pytest.mark.parametrize("state", [True, False])
def test_set_relay_writes_one_coil(state):
    """FC05 carries 0xFF00 for high and 0x0000 for low."""

    async def scenario(driver) -> None:
        await driver.set_relay(4, state)

        request = driver.requests[0]
        assert isinstance(request, WriteSingleCoilRequest)
        assert request.address == 4
        assert request.bits == [state]
        assert request.dev_id == DEFAULT_SLAVE_ADDRESS

    _run(scenario, WriteSingleCoilResponse(address=4, bits=[state]))


def test_set_relay_rejects_a_mismatched_echo():
    """An echo for another coil is not an acknowledgement."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse):
            await driver.set_relay(4, True)

    _run(scenario, WriteSingleCoilResponse(address=5, bits=[True]))


@pytest.mark.parametrize("index", [-1, RELAY_COUNT])
def test_set_relay_rejects_an_index_outside_the_range(index):
    """An invalid relay index fails before any bus traffic."""

    async def scenario(driver) -> None:
        with pytest.raises(IndexError):
            await driver.set_relay(index, True)

        assert driver.requests == []

    _run(scenario)


def test_set_relays_writes_all_coils_in_one_request():
    """FC0F sends seventeen bits starting at coil 0."""
    states = [index % 2 == 0 for index in range(RELAY_COUNT)]

    async def scenario(driver) -> None:
        await driver.set_relays(states)

        request = driver.requests[0]
        assert isinstance(request, WriteMultipleCoilsRequest)
        assert request.address == COILS.RELAY_START
        assert request.count == RELAY_COUNT
        assert request.bits == states
        assert request.dev_id == DEFAULT_SLAVE_ADDRESS

    _run(
        scenario,
        WriteMultipleCoilsResponse(address=COILS.RELAY_START, count=RELAY_COUNT),
    )


@pytest.mark.parametrize("count", [RELAY_COUNT - 1, RELAY_COUNT + 1])
def test_set_relays_rejects_a_wrong_length_before_io(count):
    """The group write accepts exactly seventeen levels."""

    async def scenario(driver) -> None:
        with pytest.raises(ValueError, match="relay states"):
            await driver.set_relays([True] * count)

        assert driver.requests == []

    _run(scenario)


def test_set_relays_rejects_a_mismatched_echo():
    """An echo for a different quantity is not an acknowledgement."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse):
            await driver.set_relays([True] * RELAY_COUNT)

    _run(scenario, WriteMultipleCoilsResponse(address=COILS.RELAY_START, count=1))


# -- identity --------------------------------------------------------------


def test_read_identity_reads_the_whole_block_once():
    """FC04 reads input registers 0-34 in one request."""

    async def scenario(driver) -> None:
        identity = await driver.read_identity()

        assert identity == DeviceIdentity(
            vendor="SCIETEX.RU",
            product="EBIC_Preamp",
            version=(1, 0, 0),
            serial_number=0x12345678,
        )
        request = driver.requests[0]
        assert isinstance(request, ReadInputRegistersRequest)
        assert request.address == INPUT_REGISTERS.VENDOR_START
        assert request.count == IDENTITY_REGISTER_COUNT
        assert request.dev_id == DEFAULT_SLAVE_ADDRESS

    _run(scenario, ReadInputRegistersResponse(registers=_identity_block()))


def test_read_identity_rejects_a_short_block():
    """A response missing the serial number is not an identity."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse) as excinfo:
            await driver.read_identity()

        assert excinfo.value.register == "identity"

    _run(
        scenario,
        ReadInputRegistersResponse(registers=[0] * (IDENTITY_REGISTER_COUNT - 1)),
    )


def test_read_identity_rejects_a_missing_response():
    """No response is an unexpected response."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse):
            await driver.read_identity()

    _run(scenario, None)


def test_read_firmware_version_reads_three_registers():
    """The version is read from registers 30-32 only."""

    async def scenario(driver) -> None:
        assert await driver.read_firmware_version() == (1, 2, 3)

        request = driver.requests[0]
        assert isinstance(request, ReadInputRegistersRequest)
        assert request.address == INPUT_REGISTERS.VERSION_START
        assert request.count == 3

    _run(scenario, ReadInputRegistersResponse(registers=[1, 2, 3]))


def test_read_serial_number_combines_high_and_low_words():
    """The serial number is read from registers 33-34 only."""

    async def scenario(driver) -> None:
        assert await driver.read_serial_number() == 0x12345678

        request = driver.requests[0]
        assert isinstance(request, ReadInputRegistersRequest)
        assert request.address == INPUT_REGISTERS.SERIAL_NUMBER_START
        assert request.count == 2

    _run(scenario, ReadInputRegistersResponse(registers=[0x1234, 0x5678]))


# -- communication settings ------------------------------------------------


def test_get_slave_address_reads_holding_register_zero():
    """FC03 reads the persisted address from register 0."""

    async def scenario(driver) -> None:
        assert await driver.get_slave_address() == 7

        request = driver.requests[0]
        assert isinstance(request, ReadHoldingRegistersRequest)
        assert request.address == REGISTERS.SLAVE_ADDRESS
        assert request.count == 1

    _run(scenario, ReadHoldingRegistersResponse(registers=[7]))


@pytest.mark.parametrize("address", [0, 248])
def test_get_slave_address_rejects_an_out_of_range_value(address):
    """A register outside 1-247 cannot be a valid slave address."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse):
            await driver.get_slave_address()

    _run(scenario, ReadHoldingRegistersResponse(registers=[address]))


@pytest.mark.parametrize("address", [1, 247])
def test_set_slave_address_writes_the_boundary_value(address):
    """FC06 writes the new address to holding register 0."""

    async def scenario(driver) -> None:
        await driver.set_slave_address(address)

        request = driver.requests[0]
        assert isinstance(request, WriteSingleRegisterRequest)
        assert request.address == REGISTERS.SLAVE_ADDRESS
        assert request.registers == [address]

    _run(
        scenario,
        WriteSingleRegisterResponse(
            address=REGISTERS.SLAVE_ADDRESS,
            registers=[address],
        ),
    )


@pytest.mark.parametrize("address", [0, 248])
def test_set_slave_address_rejects_an_out_of_range_value(address):
    """The address is validated before any bus traffic."""

    async def scenario(driver) -> None:
        with pytest.raises(ValueError, match="slave address"):
            await driver.set_slave_address(address)

        assert driver.requests == []

    _run(scenario)


def test_set_slave_address_rejects_a_mismatched_echo():
    """An echo for another value is not an acknowledgement."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse):
            await driver.set_slave_address(7)

    _run(
        scenario,
        WriteSingleRegisterResponse(address=REGISTERS.SLAVE_ADDRESS, registers=[8]),
    )


def test_get_baud_index_reads_holding_register_one():
    """FC03 reads the persisted index from register 1."""

    async def scenario(driver) -> None:
        assert await driver.get_baud_index() == 2

        request = driver.requests[0]
        assert isinstance(request, ReadHoldingRegistersRequest)
        assert request.address == REGISTERS.BAUD_INDEX
        assert request.count == 1

    _run(scenario, ReadHoldingRegistersResponse(registers=[2]))


def test_get_baud_index_rejects_an_unknown_index():
    """An index above 5 names no baud rate the firmware supports."""

    async def scenario(driver) -> None:
        with pytest.raises(UnexpectedResponse):
            await driver.get_baud_index()

    _run(scenario, ReadHoldingRegistersResponse(registers=[6]))


@pytest.mark.parametrize(("baud_rate", "index"), [(9600, 0), (115200, 5)])
def test_set_baud_rate_writes_the_index_not_the_rate(baud_rate, index):
    """FC06 writes the lookup index to holding register 1."""

    async def scenario(driver) -> None:
        await driver.set_baud_rate(baud_rate)

        request = driver.requests[0]
        assert isinstance(request, WriteSingleRegisterRequest)
        assert request.address == REGISTERS.BAUD_INDEX
        assert request.registers == [index]

    _run(
        scenario,
        WriteSingleRegisterResponse(address=REGISTERS.BAUD_INDEX, registers=[index]),
    )


def test_set_baud_rate_rejects_an_unsupported_rate():
    """An unknown rate is rejected before any bus traffic."""

    async def scenario(driver) -> None:
        with pytest.raises(ValueError, match="unsupported baud rate 12345"):
            await driver.set_baud_rate(12345)

        assert driver.requests == []

    _run(scenario)


# -- shared errors ---------------------------------------------------------


def test_register_map_incomplete_keeps_the_register_name():
    """The moved error still exposes the register it names."""
    error = RegisterMapIncomplete("BOOST_GAIN", "is not mapped")

    assert error.register == "BOOST_GAIN"
    assert str(error) == "BOOST_GAIN is not mapped"


def test_unexpected_response_keeps_the_register_name():
    """The moved error still prefixes the register and explains the mismatch."""
    error = UnexpectedResponse("relays", "expected 17 coils, got 16")

    assert error.register == "relays"
    assert str(error) == "Unexpected response for relays: expected 17 coils, got 16"
