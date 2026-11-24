"""Modbus RTU driver for the EBIC v1.0 preamp relay layer.

The firmware in ``ebic_control`` exposes seventeen relay outputs and the
communication settings that reach them. It has no ADC, DAC, measurement, status
or unlock register, so this driver implements the relay layer. It declares only
what the raw coil layer alone can declare: the pre-amp's 5 V clip point, the
booster's +/-10 V linear range, and the physical presence of the Overcurrent
comparator. The relay-to-function map now fixes the selectable controls, but this
driver still addresses raw coils, so the semantic layer built on it
(``semantic.EBICModbusV1Amplifier``) declares them.

The transport is the shared :class:`RS485Client`, which opens the port once per
operation; ``connect`` therefore has nothing to open and every accessor is a
coroutine. All requests carry the address the instance was built with. A slave
address or baud change is acknowledged at the old settings and followed by a
firmware restart after ``REBOOT_DELAY_S``; see the setters for the consequences.

Classes:
    EBICModbusV1Preamp: The EBIC v1.0 relay driver.
"""

from collections.abc import Sequence
from logging import Logger
from typing import ClassVar

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
from scietex.hal.serial import (
    ModbusSerialConnectionConfig,
    RS485Client,
    SerialConnectionConfig,
)

from .....base import (
    AmplifierState,
    CurrentAmplifierCapabilities,
    CurrentAmplifierProtocol,
    IndicationCapabilities,
    OutputVoltageCapabilities,
    PreampCapabilities,
    UnexpectedResponse,
)
from .constants import (
    BAUD_INDEX_TO_RATE,
    COILS,
    DEFAULT_SLAVE_ADDRESS,
    INPUT_REGISTERS,
    RATE_TO_BAUD_INDEX,
    REGISTERS,
    RELAY_COUNT,
    SLAVE_ADDRESS_MAX,
    SLAVE_ADDRESS_MIN,
)
from .identity import IDENTITY_REGISTER_COUNT, DeviceIdentity, decode_identity


class EBICModbusV1Preamp(RS485Client, CurrentAmplifierProtocol):
    """Modbus RTU client for the EBIC v1.0 relay outputs.

    Attributes:
        capabilities: The static analog geometry the board fixes: the pre-amp
            clip point, the booster linear range and the physical Overcurrent
            comparator. No selectable control is declared here, because this
            class drives coils rather than functions; the semantic layer owns the
            relay map and declares the selectable groups.
    """

    # Only geometry is declared on the raw driver: it speaks coil indices, not
    # functions. The pre-amp clips at 5 V, the booster is linear over +/-10 V,
    # and the Overcurrent comparator exists on the board but is unreachable over
    # Modbus. The selectable groups are declared by the semantic layer, which
    # owns the relay-to-function map and the Rf values.
    capabilities: ClassVar[CurrentAmplifierCapabilities] = CurrentAmplifierCapabilities(
        preamp=PreampCapabilities(max_output_v=5.0),
        output_voltage=OutputVoltageCapabilities(min_v=-10.0, max_v=10.0),
        input_overcurrent=IndicationCapabilities(present=True, read=False),
    )

    def __init__(
        self,
        con_params: SerialConnectionConfig | ModbusSerialConnectionConfig,
        address: int = DEFAULT_SLAVE_ADDRESS,
        label: str = "EBIC Preamp",
        logger: Logger | None = None,
    ) -> None:
        """
        Initialize the client.

        Args:
            con_params: Serial port and framing configuration.
            address: Modbus slave address the device answers at.
            label: Human-readable label used in log messages.
            logger: Optional logger for transport diagnostics.
        """
        super().__init__(
            con_params=con_params,
            address=address,
            label=label,
            logger=logger,
        )

    async def connect(self) -> None:
        """Nothing to open: the serial client connects once per operation."""
        self.logger.debug("%s: Connect (per-operation serial client).", self.label)

    async def close(self) -> None:
        """Close the underlying Modbus client and release the serial port."""
        await super().close()

    # `RS485Client.read_data` returns a raw register dictionary; the current
    # amplifier contract replaces it with a typed snapshot, so the override is
    # deliberate and the Liskov warning is expected. Remove the ignore once the
    # serial client's `read_data` matches the contract signature or the contract
    # stops narrowing the return type.
    async def read_data(self) -> AmplifierState:  # ty: ignore[incompatible-method-override]
        """
        Return an empty snapshot.

        The EBIC v1.0 firmware reports no output voltage, current, gain, bias,
        bandwidth, filter or status value. Every field therefore stays
        ``None`` and the filter tuple stays empty. ``None`` is not zero and not
        ``False``: the quantities are unknown, not idle. Relay levels are read
        through :meth:`read_relays` instead.

        Returns:
            AmplifierState: A snapshot with every field unset.
        """
        return AmplifierState()

    # -- relays ------------------------------------------------------------

    async def read_relays(self) -> tuple[bool, ...]:
        """
        Read all seventeen relay output levels.

        The levels are read with FC01 from coils 0-16, the table the firmware
        writes on FC05/FC0F and the one its tester reads. The same levels are
        mirrored in input registers 36-52, but that mirror is only reachable
        through a 53-register input read, so coils are the narrower path for the
        relay layer.

        Returns:
            tuple[bool, ...]: Relay levels in coil order, relay 0 first. The
            firmware zeroes the unused high bits of the last data byte, so they
            are discarded.

        Raises:
            UnexpectedResponse: If the response carries fewer than seventeen
                coils or is not a coil response.
        """
        response = await self.execute(
            ReadCoilsRequest(
                address=COILS.RELAY_START,
                count=RELAY_COUNT,
                dev_id=self.address,
            )
        )
        if not isinstance(response, ReadCoilsResponse) or response.bits is None:
            raise UnexpectedResponse(
                "relays", f"expected {RELAY_COUNT} coils, got {response!r}"
            )
        if len(response.bits) < RELAY_COUNT:
            raise UnexpectedResponse(
                "relays", f"expected {RELAY_COUNT} coils, got {len(response.bits)}"
            )
        return tuple(response.bits[:RELAY_COUNT])

    async def read_relay(self, index: int) -> bool:
        """
        Read one relay output level.

        Args:
            index: Relay index, 0-16.

        Returns:
            bool: The level the firmware drives on that relay.

        Raises:
            IndexError: If ``index`` is outside 0-16.
            UnexpectedResponse: If the response carries no coil value.
        """
        _check_relay_index(index)
        response = await self.execute(
            ReadCoilsRequest(address=index, count=1, dev_id=self.address)
        )
        if not isinstance(response, ReadCoilsResponse) or not response.bits:
            raise UnexpectedResponse(f"relay {index}", f"no coil value in {response!r}")
        return bool(response.bits[0])

    async def set_relay(self, index: int, state: bool) -> None:
        """
        Drive one relay output.

        The firmware writes the level to EEPROM before changing the GPIO, so the
        setting survives a restart. Frequent switching consumes flash write
        cycles; this is a state interface, not a PWM output.

        Args:
            index: Relay index, 0-16.
            state: ``True`` for logic high, ``False`` for logic low. The level
                reaches the GPIO, not the relay contact: the driver board may
                invert it.

        Raises:
            IndexError: If ``index`` is outside 0-16.
            UnexpectedResponse: If the device does not echo the written coil.
        """
        _check_relay_index(index)
        response = await self.execute(
            WriteSingleCoilRequest(
                address=index,
                bits=[bool(state)],
                dev_id=self.address,
            )
        )
        if (
            not isinstance(response, WriteSingleCoilResponse)
            or response.address != index
            or response.bits != [bool(state)]
        ):
            raise UnexpectedResponse(
                f"relay {index}",
                f"expected echo of coil {index} = {bool(state)}, got {response!r}",
            )

    async def set_relays(self, states: Sequence[bool]) -> None:
        """
        Drive all seventeen relay outputs with FC0F.

        The firmware applies the levels one by one and persists each to EEPROM,
        so the group write is not atomic: a flash failure or power loss can
        leave only part of the group applied. Re-read :meth:`read_relays` after
        an error instead of assuming either the old or the new state.

        Args:
            states: Seventeen levels in coil order, relay 0 first.

        Raises:
            ValueError: If fewer or more than seventeen levels are given, before
                any bus traffic.
            UnexpectedResponse: If the device does not echo the written range.
        """
        values = tuple(bool(state) for state in states)
        if len(values) != RELAY_COUNT:
            raise ValueError(f"expected {RELAY_COUNT} relay states, got {len(values)}")
        response = await self.execute(
            WriteMultipleCoilsRequest(
                address=COILS.RELAY_START,
                bits=list(values),
                dev_id=self.address,
            )
        )
        if (
            not isinstance(response, WriteMultipleCoilsResponse)
            or response.address != COILS.RELAY_START
            or response.count != RELAY_COUNT
        ):
            raise UnexpectedResponse(
                "relays",
                f"expected echo of {RELAY_COUNT} coils at {COILS.RELAY_START}, "
                f"got {response!r}",
            )

    # -- identity ----------------------------------------------------------

    async def read_identity(self) -> DeviceIdentity:
        """
        Read the vendor, product, version and serial number.

        One FC04 request reads input registers 0-34, the whole identity block.

        Returns:
            DeviceIdentity: The decoded identity.

        Raises:
            UnexpectedResponse: If the response carries a different number of
                registers or is not an input-register response.
        """
        registers = await self._read_input(
            INPUT_REGISTERS.VENDOR_START,
            IDENTITY_REGISTER_COUNT,
            "identity",
        )
        return decode_identity(registers)

    async def read_firmware_version(self) -> tuple[int, int, int]:
        """
        Read the firmware version.

        Returns:
            tuple[int, int, int]: ``(major, minor, patch)``.

        Raises:
            UnexpectedResponse: If the response does not carry three registers.
        """
        registers = await self._read_input(
            INPUT_REGISTERS.VERSION_START,
            INPUT_REGISTERS.SERIAL_NUMBER_START - INPUT_REGISTERS.VERSION_START,
            "firmware version",
        )
        major, minor, patch = registers
        return (major, minor, patch)

    async def read_serial_number(self) -> int:
        """
        Read the 32-bit serial number.

        Returns:
            int: The serial number built from the high and low words.

        Raises:
            UnexpectedResponse: If the response does not carry two registers.
        """
        registers = await self._read_input(
            INPUT_REGISTERS.SERIAL_NUMBER_START,
            IDENTITY_REGISTER_COUNT - INPUT_REGISTERS.SERIAL_NUMBER_START,
            "serial number",
        )
        serial_hi, serial_lo = registers
        return (serial_hi << 16) | serial_lo

    # -- communication settings -------------------------------------------

    async def get_slave_address(self) -> int:
        """
        Read the persisted Modbus slave address.

        Returns:
            int: The address in holding register 0, normally 1-247.

        Raises:
            UnexpectedResponse: If the response does not carry one in-range
                register.
        """
        value = (await self._read_holding(REGISTERS.SLAVE_ADDRESS, 1, "slave address"))[
            0
        ]
        if not SLAVE_ADDRESS_MIN <= value <= SLAVE_ADDRESS_MAX:
            raise UnexpectedResponse(
                "slave address",
                f"expected {SLAVE_ADDRESS_MIN}-{SLAVE_ADDRESS_MAX}, got {value}",
            )
        return value

    async def set_slave_address(self, address: int) -> None:
        """
        Persist a new Modbus slave address.

        The device writes the address to EEPROM and acknowledges the request at
        the OLD address. It then waits ``REBOOT_DELAY_S`` and restarts, after
        which it answers only at the new address. This client keeps requesting
        the old address, so construct a new instance with the new address after
        the restart. Writing the address already stored still answers at the old
        address but causes no restart.

        Args:
            address: The new slave address, 1-247.

        Raises:
            ValueError: If the address is outside 1-247, before any bus traffic.
            UnexpectedResponse: If the device does not echo the written value.
        """
        if not SLAVE_ADDRESS_MIN <= address <= SLAVE_ADDRESS_MAX:
            raise ValueError(
                f"slave address must be {SLAVE_ADDRESS_MIN}-"
                f"{SLAVE_ADDRESS_MAX}, got {address}"
            )
        await self._write_holding(REGISTERS.SLAVE_ADDRESS, address, "slave address")

    async def get_baud_index(self) -> int:
        """
        Read the persisted baud-rate index.

        Returns:
            int: The index in holding register 1, 0-5. Use
            ``BAUD_INDEX_TO_RATE`` to convert it to a baud rate.

        Raises:
            UnexpectedResponse: If the response does not carry one known index.
        """
        value = (await self._read_holding(REGISTERS.BAUD_INDEX, 1, "baud index"))[0]
        if value not in BAUD_INDEX_TO_RATE:
            raise UnexpectedResponse(
                "baud index", f"expected 0-{len(BAUD_INDEX_TO_RATE) - 1}, got {value}"
            )
        return value

    async def set_baud_rate(self, baud_rate: int) -> None:
        """
        Persist a new baud rate by writing its index.

        The firmware stores the index, never the baud number itself. It writes
        the index to EEPROM and acknowledges the request at the OLD baud rate.
        It then waits ``REBOOT_DELAY_S`` and restarts, after which it answers
        only at the new rate. Keep the port configured for the old rate until
        the restart completes, then reconfigure it. Writing the rate already
        stored still answers at the old rate but causes no restart.

        Args:
            baud_rate: One of 9600, 14400, 19200, 38400, 57600 or 115200.

        Raises:
            ValueError: If the rate is not one the firmware supports, before any
                bus traffic.
            UnexpectedResponse: If the device does not echo the written index.
        """
        index = RATE_TO_BAUD_INDEX.get(baud_rate)
        if index is None:
            supported = ", ".join(str(rate) for rate in RATE_TO_BAUD_INDEX)
            raise ValueError(
                f"unsupported baud rate {baud_rate}; expected one of {supported}"
            )
        await self._write_holding(REGISTERS.BAUD_INDEX, index, "baud index")

    # -- transport helpers -------------------------------------------------

    async def _read_holding(self, address: int, count: int, label: str) -> list[int]:
        """Read holding registers and check the response length."""
        response = await self.execute(
            ReadHoldingRegistersRequest(
                address=address,
                count=count,
                dev_id=self.address,
            )
        )
        return _expect_registers(response, count, label)

    async def _read_input(self, address: int, count: int, label: str) -> list[int]:
        """Read input registers and check the response length."""
        response = await self.execute(
            ReadInputRegistersRequest(
                address=address,
                count=count,
                dev_id=self.address,
            )
        )
        return _expect_registers(response, count, label)

    async def _write_holding(self, address: int, value: int, label: str) -> None:
        """Write one holding register and check that the device echoed it."""
        response = await self.execute(
            WriteSingleRegisterRequest(
                address=address,
                registers=[value],
                dev_id=self.address,
            )
        )
        if (
            not isinstance(response, WriteSingleRegisterResponse)
            or response.address != address
            or response.registers != [value]
        ):
            raise UnexpectedResponse(
                label,
                f"expected echo of register {address} = {value}, got {response!r}",
            )


def _check_relay_index(index: int) -> None:
    """Reject a relay index outside 0-16 before any bus traffic."""
    if not 0 <= index < RELAY_COUNT:
        raise IndexError(f"relay index must be 0-{RELAY_COUNT - 1}, got {index}")


def _expect_registers(
    response: ModbusPDU | None,
    count: int,
    label: str,
) -> list[int]:
    """Return the registers of a response, or raise on a mismatch."""
    if response is None or not isinstance(
        response, (ReadHoldingRegistersResponse, ReadInputRegistersResponse)
    ):
        raise UnexpectedResponse(
            label, f"expected {count} register(s), got {response!r}"
        )
    registers = response.registers
    if registers is None or len(registers) != count:
        raise UnexpectedResponse(
            label, f"expected {count} register(s), got {registers!r}"
        )
    return registers
