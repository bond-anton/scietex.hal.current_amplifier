"""Serial Modbus driver skeleton for the current amplifier.

The driver is structurally complete but deliberately inert: the device's
register map has not been transcribed, so every register resolves through
:meth:`GenericModbusCurrentAmplifier._spec` and raises
:class:`RegisterMapIncomplete` before a single frame reaches the bus. Filling
``DEVICE_MAP``, ``FILTER_TYPE_CODES`` and ``STATUS_BITS`` and declaring the
capability set they imply is the only change needed to make the driver operate.

The transport is the shared asynchronous :class:`RS485Client`, which opens the
port once per operation; ``connect`` therefore has nothing to open and every
accessor is a coroutine.

Classes:
    GenericModbusCurrentAmplifier: The vendor-neutral Modbus driver.
"""

from logging import Logger
from typing import Any, ClassVar

from pymodbus.pdu.register_message import (
    ReadHoldingRegistersRequest,
    ReadInputRegistersRequest,
)
from scietex.hal.serial import (
    ModbusSerialConnectionConfig,
    RS485Client,
    SerialConnectionConfig,
)

from ...base import (
    AmplifierState,
    CurrentAmplifierCapabilities,
    CurrentAmplifierProtocol,
    FilterSetting,
    FilterType,
)
from .errors import RegisterMapIncomplete, UnexpectedResponse
from .registers import (
    DEVICE_MAP,
    FILTER_TYPE_CODES,
    STATUS_BITS,
    Register,
    RegisterSpec,
)

# Function code to the register table it reads. The request classes carry the
# Modbus specification's own numbers, so the driver never restates them, and the
# map stays the only place a device-specific code is written down.
_READ_TABLES: dict[int, bool] = {
    ReadHoldingRegistersRequest.function_code: True,
    ReadInputRegistersRequest.function_code: False,
}


class GenericModbusCurrentAmplifier(RS485Client, CurrentAmplifierProtocol):
    """Modbus RTU driver for the current amplifier, pending its register map.

    Every group of the capability set is unsupported until the group's registers
    are transcribed into ``DEVICE_MAP``; this attribute is filled in at the same
    time as the map.

    Attributes:
        capabilities (CurrentAmplifierCapabilities): The amplifier control
            surface, currently empty.
    """

    capabilities: ClassVar[CurrentAmplifierCapabilities] = (
        CurrentAmplifierCapabilities()
    )

    def __init__(
        self,
        con_params: SerialConnectionConfig | ModbusSerialConnectionConfig,
        address: int = 1,
        label: str = "Current amplifier",
        logger: Logger | None = None,
        **kwargs,
    ) -> None:
        """
        Initialize the driver.

        Args:
            con_params: Serial connection configuration.
            address: Modbus unit id of the amplifier.
            label: Human-readable label used in logs.
            logger: Optional logger for diagnostics.
            **kwargs: Forwarded to :class:`RS485Client`, such as ``chunk_size``.
        """
        super().__init__(
            con_params,
            address,
            label=label,
            logger=logger,
            **kwargs,
        )

    async def connect(self) -> None:
        """No-op: the shared client opens the port once per operation."""
        self.logger.debug("%s: Connect (per-operation serial client).", self.label)

    def _spec(self, register: Register) -> RegisterSpec:
        """
        Return the wire specification of one register.

        Args:
            register: The register to resolve.

        Returns:
            RegisterSpec: The mapped specification.

        Raises:
            RegisterMapIncomplete: If the register has no address or function
                code yet.
        """
        spec = DEVICE_MAP[register]
        if not spec.mapped:
            raise RegisterMapIncomplete(register.name)
        return spec

    @staticmethod
    def _group_mapped(*registers: Register) -> bool:
        """Whether every register of a capability group is mapped."""
        return all(DEVICE_MAP[register].mapped for register in registers)

    @staticmethod
    def _reject_multi_word(register: Register, spec: RegisterSpec) -> None:
        """
        Reject a value that spans more than one register.

        Args:
            register: The register being accessed.
            spec: Its specification.

        Raises:
            NotImplementedError: If the value spans several registers, whose
                assembly order the map cannot state yet.
        """
        if spec.word_count != 1:
            raise NotImplementedError(
                f"{register.name} spans {spec.word_count} registers and the map "
                "does not state their order"
            )

    async def _read_register(self, register: Register) -> float:
        """
        Read one register in engineering units.

        Args:
            register: The register to read.

        Returns:
            float: The decoded value, ``raw * scale + offset``.

        Raises:
            RegisterMapIncomplete: If the register is unmapped.
            NotImplementedError: If the map names a function code that does not
                read registers, or the value spans more than one register.
            UnexpectedResponse: If the response has the wrong register count.
        """
        spec = self._spec(register)
        address, function = spec.address, spec.function
        assert address is not None and function is not None  # _spec guarantees both
        holding = _READ_TABLES.get(function)
        if holding is None:
            raise NotImplementedError(
                f"{register.name}: function code {function} does not read registers"
            )
        self._reject_multi_word(register, spec)
        values = await self.read_registers(
            address,
            count=spec.word_count,
            holding=holding,
            signed=spec.signed,
        )
        if values is None or len(values) != spec.word_count:
            raise UnexpectedResponse(
                register.name,
                f"expected {spec.word_count} register(s), got {values}",
            )
        return values[0] * spec.scale + spec.offset

    async def _write_register(self, register: Register, value: float) -> None:
        """
        Write one register from an engineering-unit value.

        Args:
            register: The register to write.
            value: The value in engineering units, inverse-scaled before writing.

        Raises:
            RegisterMapIncomplete: If the register is unmapped.
            NotImplementedError: If the value spans more than one register.
        """
        spec = self._spec(register)
        address = spec.address
        assert address is not None  # _spec guarantees it
        self._reject_multi_word(register, spec)
        raw = round((value - spec.offset) / spec.scale)
        await self.write_register(address, raw, signed=spec.signed)

    @staticmethod
    def _filter_type_for(code: int) -> FilterType | None:
        """Return the filter type a device code names, or ``None`` if unknown."""
        for filter_type, mapped_code in FILTER_TYPE_CODES.items():
            if mapped_code == code:
                return filter_type
        return None

    @staticmethod
    def _status_flag(status: int | None, name: str) -> bool | None:
        """Decode one status flag, or return ``None`` while its mask is unknown."""
        if status is None:
            return None
        mask = STATUS_BITS.get(name)
        if mask is None:
            return None
        return bool(status & mask)

    async def _read_filter(self) -> FilterSetting | None:
        """
        Read the filter entry.

        Returns:
            FilterSetting | None: The decoded entry, or ``None`` when its type
                code is absent from ``FILTER_TYPE_CODES``.
        """
        filter_type = self._filter_type_for(
            int(await self._read_register(Register.FILTER_TYPE))
        )
        if filter_type is None:
            return None
        return FilterSetting(
            type=filter_type,
            enabled=bool(await self._read_register(Register.FILTER_ENABLE)),
            low_cutoff_hz=await self._read_register(Register.FILTER_LOW_CUTOFF),
            high_cutoff_hz=await self._read_register(Register.FILTER_HIGH_CUTOFF),
        )

    async def read_data(self) -> Any:
        """
        Read a snapshot of the amplifier's values.

        The three mandatory registers are resolved before the first read, so a
        partially mapped device fails without partial traffic. Each optional
        group is read only when every register of that group is mapped; fields
        whose group is unmapped stay ``None``.

        Returns:
            AmplifierState: The snapshot.

        Raises:
            RegisterMapIncomplete: If a mandatory register is unmapped.
            UnexpectedResponse: If a read returns the wrong register count.

        The return annotation is ``Any`` because the inherited
        :meth:`RS485Client.read_data` hook declares a ``dict`` payload, while
        this driver returns the typed :class:`AmplifierState` its protocol
        promises. The two annotations are mutually incompatible; ``Any`` is the
        only return type that satisfies both bases, and the concrete snapshot
        is still :class:`AmplifierState`.
        """
        mandatory = (
            Register.OUTPUT_VOLTAGE,
            Register.OUTPUT_CURRENT,
            Register.INPUT_CURRENT,
        )
        for register in mandatory:
            self._spec(register)

        output_voltage = await self._read_register(Register.OUTPUT_VOLTAGE)
        output_current = await self._read_register(Register.OUTPUT_CURRENT)
        input_current = await self._read_register(Register.INPUT_CURRENT)

        preamp_range: float | None = None
        feedback_resistor: float | None = None
        if self._group_mapped(
            Register.PREAMP_RANGE_SELECT,
            Register.PREAMP_RANGE_READBACK,
            Register.FEEDBACK_RESISTOR_SELECT,
            Register.FEEDBACK_RESISTOR_READBACK,
        ):
            preamp_range = await self._read_register(Register.PREAMP_RANGE_READBACK)
            feedback_resistor = await self._read_register(
                Register.FEEDBACK_RESISTOR_READBACK
            )

        boost_gain: float | None = None
        if self._group_mapped(Register.BOOST_GAIN):
            boost_gain = await self._read_register(Register.BOOST_GAIN)

        dc_bias_enabled: bool | None = None
        dc_bias_level: float | None = None
        if self._group_mapped(Register.DC_BIAS_ENABLE, Register.DC_BIAS_LEVEL):
            dc_bias_enabled = bool(await self._read_register(Register.DC_BIAS_ENABLE))
            dc_bias_level = await self._read_register(Register.DC_BIAS_LEVEL)

        bandwidth: float | None = None
        if self._group_mapped(Register.BANDWIDTH):
            bandwidth = await self._read_register(Register.BANDWIDTH)

        filters: tuple[FilterSetting, ...] = ()
        if self._group_mapped(
            Register.FILTER_ENABLE,
            Register.FILTER_TYPE,
            Register.FILTER_LOW_CUTOFF,
            Register.FILTER_HIGH_CUTOFF,
        ):
            filter_setting = await self._read_filter()
            if filter_setting is not None:
                filters = (filter_setting,)

        status: int | None = None
        if self._group_mapped(Register.STATUS):
            status = int(await self._read_register(Register.STATUS))

        input_compensation_enabled: bool | None = None
        input_compensation_level: float | None = None
        if self._group_mapped(
            Register.COMPENSATION_ENABLE, Register.COMPENSATION_LEVEL
        ):
            input_compensation_enabled = bool(
                await self._read_register(Register.COMPENSATION_ENABLE)
            )
            input_compensation_level = await self._read_register(
                Register.COMPENSATION_LEVEL
            )

        inverted: bool | None = None
        if self._group_mapped(Register.INVERT):
            inverted = bool(await self._read_register(Register.INVERT))

        return AmplifierState(
            output_voltage_v=output_voltage,
            output_current_a=output_current,
            input_current_a=input_current,
            preamp_range=preamp_range,
            boost_gain=boost_gain,
            feedback_resistor_ohm=feedback_resistor,
            dc_bias_enabled=dc_bias_enabled,
            dc_bias_level=dc_bias_level,
            bandwidth_hz=bandwidth,
            filters=filters,
            input_overcurrent=self._status_flag(status, "input_overcurrent"),
            output_overload=self._status_flag(status, "output_overload"),
            input_compensation_enabled=input_compensation_enabled,
            input_compensation_level=input_compensation_level,
            inverted=inverted,
        )

    async def get_preamp_range(self) -> float:
        """Read the preamp range designator."""
        return await self._read_register(Register.PREAMP_RANGE_READBACK)

    async def select_preamp_range(self, range_value: float) -> None:
        """Select the preamp range."""
        await self._write_register(Register.PREAMP_RANGE_SELECT, range_value)

    async def get_feedback_resistor(self) -> float:
        """Read the feedback resistor in ohm."""
        return await self._read_register(Register.FEEDBACK_RESISTOR_READBACK)

    async def select_feedback_resistor(self, resistance_ohm: float) -> None:
        """Select the feedback resistor."""
        await self._write_register(Register.FEEDBACK_RESISTOR_SELECT, resistance_ohm)

    async def get_boost_gain(self) -> float:
        """Read the boost stage gain."""
        return await self._read_register(Register.BOOST_GAIN)

    async def set_boost_gain(self, gain: float) -> None:
        """Set the boost stage gain."""
        await self._write_register(Register.BOOST_GAIN, gain)

    async def get_dc_bias(self) -> bool:
        """Read the DC bias injection state."""
        return bool(await self._read_register(Register.DC_BIAS_ENABLE))

    async def set_dc_bias(self, enabled: bool) -> None:
        """Switch DC bias injection on or off."""
        await self._write_register(Register.DC_BIAS_ENABLE, float(enabled))

    async def get_dc_bias_level(self) -> float:
        """Read the DC bias level."""
        return await self._read_register(Register.DC_BIAS_LEVEL)

    async def set_dc_bias_level(self, level: float) -> None:
        """Set the DC bias level."""
        await self._write_register(Register.DC_BIAS_LEVEL, level)

    async def get_bandwidth(self) -> float:
        """Read the bandwidth in Hz."""
        return await self._read_register(Register.BANDWIDTH)

    async def set_bandwidth(self, bandwidth_hz: float) -> None:
        """Set the bandwidth."""
        await self._write_register(Register.BANDWIDTH, bandwidth_hz)

    async def get_filter(self, filter_type: FilterType) -> FilterSetting:
        """
        Read one filter's settings.

        The map has no per-filter addressing yet, so every filter type resolves
        to the same registers and ``filter_type`` is only echoed into the entry.

        Args:
            filter_type: The filter response the entry describes.

        Returns:
            FilterSetting: The entry read from the filter registers.
        """
        for register in (
            Register.FILTER_ENABLE,
            Register.FILTER_LOW_CUTOFF,
            Register.FILTER_HIGH_CUTOFF,
        ):
            self._spec(register)
        return FilterSetting(
            type=filter_type,
            enabled=bool(await self._read_register(Register.FILTER_ENABLE)),
            low_cutoff_hz=await self._read_register(Register.FILTER_LOW_CUTOFF),
            high_cutoff_hz=await self._read_register(Register.FILTER_HIGH_CUTOFF),
        )

    async def set_filter(self, setting: FilterSetting) -> None:
        """
        Write one filter's settings.

        Args:
            setting: The filter entry to apply. A ``None`` cutoff is left
                untouched rather than written as zero.

        Raises:
            RegisterMapIncomplete: If a filter register or the entry's type code
                is missing from the map.
        """
        for register in (
            Register.FILTER_TYPE,
            Register.FILTER_ENABLE,
            Register.FILTER_LOW_CUTOFF,
            Register.FILTER_HIGH_CUTOFF,
        ):
            self._spec(register)
        type_code = FILTER_TYPE_CODES.get(setting.type)
        if type_code is None:
            raise RegisterMapIncomplete(
                Register.FILTER_TYPE.name,
                f"has no code for {setting.type.value}",
            )
        await self._write_register(Register.FILTER_TYPE, float(type_code))
        await self._write_register(Register.FILTER_ENABLE, float(setting.enabled))
        if setting.low_cutoff_hz is not None:
            await self._write_register(
                Register.FILTER_LOW_CUTOFF, setting.low_cutoff_hz
            )
        if setting.high_cutoff_hz is not None:
            await self._write_register(
                Register.FILTER_HIGH_CUTOFF, setting.high_cutoff_hz
            )

    async def get_input_compensation(self) -> bool:
        """Read the input-capacitance compensation state."""
        return bool(await self._read_register(Register.COMPENSATION_ENABLE))

    async def set_input_compensation(self, enabled: bool) -> None:
        """Switch input-capacitance compensation on or off."""
        await self._write_register(Register.COMPENSATION_ENABLE, float(enabled))

    async def get_input_compensation_level(self) -> float:
        """Read the input-compensation level."""
        return await self._read_register(Register.COMPENSATION_LEVEL)

    async def set_input_compensation_level(self, level: float) -> None:
        """Set the input-compensation level."""
        await self._write_register(Register.COMPENSATION_LEVEL, level)

    async def get_inverted(self) -> bool:
        """Read the output-polarity inversion state."""
        return bool(await self._read_register(Register.INVERT))

    async def set_inverted(self, inverted: bool) -> None:
        """Set the output-polarity inversion state."""
        await self._write_register(Register.INVERT, float(inverted))
