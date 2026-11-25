"""
Current amplifier protocol.

This module defines the transport-agnostic contract every current amplifier
driver implements, plus the capability conveniences that tell a caller which
optional control operations a given amplifier supports. The contract is
deliberately minimal: a driver must be able to connect, disconnect and read the
state snapshot. Every control operation beyond that is advertised through
:attr:`CurrentAmplifierProtocol.capabilities`, so a caller can reject an
unsupported command before dispatching it instead of catching an exception
after the fact.

Every driver I/O call is a coroutine, because the shared transport is
asynchronous: callers must ``await`` :meth:`connect`, :meth:`close`,
:meth:`read_data` and every optional accessor, and an unimplemented optional
accessor raises ``NotImplementedError`` when awaited. The ``supports_*`` and
``can_*`` properties are pure capability checks over :attr:`capabilities` and
stay synchronous.

Two failure signals carry different meanings and must not be confused. A
``NotImplementedError`` raised by an optional method means "this driver does not
implement that capability": the feature is absent, so the caller should consult
the capability set and take a different path. A ``None`` field in the snapshot
returned by :meth:`CurrentAmplifierProtocol.read_data` means "this driver cannot
report that value": the feature may well exist and be controllable, but the
current reading is unknown, so the caller must not substitute zero or ``False``.

Status indications are an exception to the method-based surface: input
overcurrent and output overload are read only through ``read_data()`` and have
no dedicated accessors. :class:`IndicationCapabilities` separates whether the
signal exists from whether the firmware can read it; ``supports_input_overcurrent``
and ``supports_output_overload`` answer observability, while the snapshot says
what the flag currently is.

Filter kinds are read from ``capabilities.filters.types``; there is no
per-kind ``supports_*`` property, so adding a :class:`FilterType` never changes
this class.

The output voltage range is static geometry rather than a controllable feature,
so it has no ``supports_*`` property either: a caller reads
``capabilities.output_voltage`` directly. The only adjustable gain in this
device is the boost stage; the preamp selects one feedback resistor, which fixes
the transimpedance; the input-current range is derived from that resistor, the
boost gain and the static clip limits.

A fixed, non-selectable bandwidth is read from
``capabilities.bandwidth.fixed_hz``. It has no ``supports_*`` truth because
there is nothing to select.

Classes:
    CurrentAmplifierProtocol: The runtime-checkable protocol every current
        amplifier driver satisfies.
"""

from typing import ClassVar, Protocol, runtime_checkable

from .capabilities import CurrentAmplifierCapabilities, FilterType
from .data import AmplifierState, FilterSetting


@runtime_checkable
class CurrentAmplifierProtocol(Protocol):
    """
    Contract implemented by every current amplifier driver.

    The three core methods are mandatory. Every optional method raises
    ``NotImplementedError`` by default and is advertised through
    :attr:`capabilities`; callers must consult the capability set before
    invoking one. Every I/O method is a coroutine; the convenience properties
    are synchronous.

    Attributes:
        capabilities: What this amplifier can do, grouped by function. A driver
            declares it as a class attribute, so the whole capability set is
            known before an instance connects to hardware.
    """

    capabilities: ClassVar[CurrentAmplifierCapabilities]

    @property
    def supports_preamp(self) -> bool:
        """Whether the preamp exposes feedback-resistor selection."""
        return bool(self.capabilities.preamp.feedback_resistor)

    @property
    def supports_boost(self) -> bool:
        """Whether the amplifier exposes boost stage gain selection."""
        return bool(self.capabilities.boost.gain)

    @property
    def supports_dc_bias(self) -> bool:
        """Whether the amplifier exposes DC bias injection or its level."""
        return bool(self.capabilities.dc_bias.enabled) or bool(
            self.capabilities.dc_bias.level
        )

    @property
    def supports_bandwidth(self) -> bool:
        """Whether the amplifier exposes selectable bandwidth."""
        return bool(self.capabilities.bandwidth)

    @property
    def supports_filters(self) -> bool:
        """Whether the amplifier exposes any signal filter control."""
        filters = self.capabilities.filters
        return bool(filters.types) or bool(filters.enabled) or bool(filters.cutoff)

    @property
    def supports_input_overcurrent(self) -> bool:
        """Whether the driver can observe the input-overcurrent signal."""
        return self.capabilities.input_overcurrent.read

    @property
    def supports_output_overload(self) -> bool:
        """Whether the driver can observe the output-overload signal."""
        return self.capabilities.output_overload.read

    @property
    def supports_input_compensation(self) -> bool:
        """Whether the amplifier exposes input-capacitance compensation."""
        compensation = self.capabilities.input_compensation
        return bool(compensation.enabled) or bool(compensation.level)

    @property
    def supports_invert_output(self) -> bool:
        """Whether the amplifier exposes output-polarity inversion."""
        return bool(self.capabilities.invert_output)

    @property
    def can_select_preamp(self) -> bool:
        """Whether the preamp feedback resistance can be written."""
        return self.capabilities.preamp.feedback_resistor.access.write

    @property
    def can_set_boost(self) -> bool:
        """Whether the boost stage gain can be written."""
        return self.capabilities.boost.gain.access.write

    @property
    def can_set_dc_bias(self) -> bool:
        """Whether DC bias injection or its level can be written."""
        return (
            self.capabilities.dc_bias.enabled.write
            or self.capabilities.dc_bias.level.write
        )

    @property
    def can_set_bandwidth(self) -> bool:
        """Whether selectable bandwidth can be written."""
        return self.capabilities.bandwidth.access.write

    @property
    def can_set_filter(self) -> bool:
        """Whether a filter can be switched or its cutoff written."""
        return (
            self.capabilities.filters.enabled.write
            or self.capabilities.filters.cutoff.write
        )

    @property
    def can_set_input_compensation(self) -> bool:
        """Whether input compensation or its level can be written."""
        return (
            self.capabilities.input_compensation.enabled.write
            or self.capabilities.input_compensation.level.write
        )

    @property
    def can_set_invert_output(self) -> bool:
        """Whether output-polarity inversion can be written."""
        return self.capabilities.invert_output.write

    async def connect(self) -> bool | None:
        """Open the transport to the amplifier.

        Returns:
            bool | None: ``True`` when a transport that reports its own success
                opened a connection, ``None`` when the implementation has
                nothing to open. A failure raises instead of returning
                ``False``.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement connect()")

    async def close(self) -> None:
        """Close the transport to the amplifier."""
        raise NotImplementedError(f"{type(self).__name__} must implement close()")

    async def read_data(self) -> AmplifierState:
        """
        Read a snapshot of the amplifier's current values.

        Returns:
            AmplifierState: The current snapshot. A field is ``None`` when the
                driver cannot report it.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement read_data()")

    async def get_boost_gain(self) -> float:
        """
        Read the boost stage gain.

        Returns:
            float: The dimensionless boost gain.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_boost_gain(); "
            "capability: boost.gain"
        )

    async def set_boost_gain(self, gain: float) -> None:
        """
        Set the boost stage gain.

        Args:
            gain: The dimensionless boost gain, normally one of
                ``capabilities.boost.gain.options``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_boost_gain(); "
            "capability: boost.gain"
        )

    async def get_feedback_resistor(self) -> float:
        """
        Read the feedback resistor.

        Returns:
            float: Resistance in ohm.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_feedback_resistor(); "
            "capability: preamp.feedback_resistor"
        )

    async def select_feedback_resistor(self, resistance_ohm: float) -> None:
        """
        Select the feedback resistor.

        Args:
            resistance_ohm: Resistance in ohm.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement select_feedback_resistor(); "
            "capability: preamp.feedback_resistor"
        )

    async def get_dc_bias(self) -> bool:
        """
        Read the DC bias injection state.

        Returns:
            bool: Whether bias injection is on.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_dc_bias(); "
            "capability: dc_bias.enabled"
        )

    async def set_dc_bias(self, enabled: bool) -> None:
        """
        Switch DC bias injection on or off.

        Args:
            enabled: Whether to turn bias injection on.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_dc_bias(); "
            "capability: dc_bias.enabled"
        )

    async def get_dc_bias_level(self) -> float:
        """
        Read the DC bias level.

        Returns:
            float: Bias level in device-native units.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_dc_bias_level(); "
            "capability: dc_bias.level"
        )

    async def set_dc_bias_level(self, level: float) -> None:
        """
        Set the DC bias level.

        Args:
            level: Bias level in device-native units.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_dc_bias_level(); "
            "capability: dc_bias.level"
        )

    async def get_bandwidth(self) -> float:
        """
        Read the bandwidth.

        Returns:
            float: Bandwidth in Hz.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_bandwidth(); "
            "capability: bandwidth"
        )

    async def set_bandwidth(self, bandwidth_hz: float) -> None:
        """
        Set the bandwidth.

        Args:
            bandwidth_hz: Bandwidth in Hz.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_bandwidth(); "
            "capability: bandwidth"
        )

    async def get_filter(self, filter_type: FilterType) -> FilterSetting:
        """
        Read one filter's settings.

        Args:
            filter_type: The filter response to read.

        Returns:
            FilterSetting: The filter entry, with its cutoff corners in Hz.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_filter(); "
            "capability: filters"
        )

    async def set_filter(self, setting: FilterSetting) -> None:
        """
        Write one filter's settings.

        Args:
            setting: The filter entry to apply. ``setting.type`` selects the
                filter, ``enabled`` switches it and the cutoff corners set its
                frequency.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_filter(); "
            "capability: filters"
        )

    async def get_input_compensation(self) -> bool:
        """
        Read the input-capacitance compensation state.

        Returns:
            bool: Whether compensation is on.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_input_compensation(); "
            "capability: input_compensation.enabled"
        )

    async def set_input_compensation(self, enabled: bool) -> None:
        """
        Switch input-capacitance compensation on or off.

        Args:
            enabled: Whether to turn compensation on.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_input_compensation(); "
            "capability: input_compensation.enabled"
        )

    async def get_input_compensation_level(self) -> float:
        """
        Read the input-compensation level.

        Returns:
            float: Compensation level in device-native units.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement "
            "get_input_compensation_level(); capability: input_compensation.level"
        )

    async def set_input_compensation_level(self, level: float) -> None:
        """
        Set the input-compensation level.

        Args:
            level: Compensation level in device-native units.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement "
            "set_input_compensation_level(); capability: input_compensation.level"
        )

    async def get_inverted(self) -> bool:
        """
        Read the output-polarity inversion state.

        Returns:
            bool: Whether the output is inverted.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_inverted(); "
            "capability: invert_output"
        )

    async def set_inverted(self, inverted: bool) -> None:
        """
        Set the output-polarity inversion state.

        Args:
            inverted: Whether to invert the output.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_inverted(); "
            "capability: invert_output"
        )
