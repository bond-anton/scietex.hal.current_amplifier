"""
Current amplifier capability model.

An amplifier advertises what it can do through a single
:class:`CurrentAmplifierCapabilities` value, grouped by function rather than by
method name. The grouping is semantic: a driver maps its own vocabulary onto
these groups, so a caller can ask "can this amplifier change its preamp range?"
without knowing whether the underlying protocol calls the setting a range, a
code, or a resistor.

Two kinds of surface are modelled separately. A switch is an :class:`Access`,
which distinguishes "readable" from "writeable" because many devices expose a
setting read-only. A switch that also takes a value is a
:class:`SelectableCapabilities`, which adds the domain of accepted values.

A third kind is static geometry: a limit that never changes while the device
runs, such as the output voltage swing, is capability data rather than state.
It is read from the capability set directly instead of through a protocol
method or a ``supports_*`` property.

The groups are frozen dataclasses so a driver declares them once as a class
attribute and callers cannot mutate them.

Classes:
    FilterType: The filter responses an amplifier can apply.
    Access: Whether a setting can be read and whether it can be written.
    SelectableCapabilities: An access plus the values it accepts.
    PreampCapabilities: Preamp range and feedback-resistor selection.
    BoostCapabilities: Boost stage gain selection.
    OutputVoltageCapabilities: Static output voltage swing limits.
    DcBiasCapabilities: DC bias injection surface.
    FilterCapabilities: Signal-filter surface.
    IndicationCapabilities: A read-only status flag.
    CompensationCapabilities: Input-capacitance compensation surface.
    CurrentAmplifierCapabilities: The complete capability set for one amplifier.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar


class FilterType(str, Enum):
    """The filter responses an amplifier can apply.

    The member value is the wire spelling a driver sends; it doubles as the
    serialised form because the class inherits from ``str``.
    """

    LOW_PASS = "low_pass"
    HIGH_PASS = "high_pass"
    BAND_PASS = "band_pass"


@dataclass(frozen=True, slots=True)
class Access:
    """
    Whether a setting can be read and whether it can be written.

    Attributes:
        read (bool): Whether the current value can be read back.
        write (bool): Whether the value can be set.
    """

    read: bool = False
    write: bool = False

    def __bool__(self) -> bool:
        """Return whether the setting is supported in either direction."""
        return self.read or self.write


T = TypeVar("T")


@dataclass(frozen=True, slots=True, eq=False)
class SelectableCapabilities(Generic[T]):
    """
    An access plus the values it accepts.

    Attributes:
        access (Access): Whether the setting is readable and writeable.
        options (tuple[T, ...]): The values the device accepts, in the device's
            own order and native units. An empty tuple means the device does
            not enumerate its domain, which is typical of a continuous setting
            such as a boost gain or a cutoff frequency; it does **not** mean the
            device accepts no value. A caller that needs the legal domain of an
            enumerating device reads the options, and against a device with an
            empty tuple it must rely on the state snapshot instead.
    """

    access: Access = field(default_factory=Access)
    options: tuple[T, ...] = ()

    def __bool__(self) -> bool:
        """Return whether the setting is supported in either direction."""
        return bool(self.access)


@dataclass(frozen=True, slots=True)
class PreampCapabilities:
    """
    Preamp range and transimpedance feedback-resistor selection.

    The two settings describe independent quantities, so a caller must not
    convert one into the other: ``range`` is a designator the device chooses,
    while ``feedback_resistor`` is a physical resistance.

    Attributes:
        range (SelectableCapabilities[float]): The device's preamp range
            designators in device-native units as reported by the device, which
            are not necessarily amperes or volts. An empty tuple means the
            domain is continuous or not enumerated.
        feedback_resistor (SelectableCapabilities[float]): Selectable
            transimpedance feedback-resistor options, in ohm. An empty tuple
            means the domain is continuous or not enumerated.
    """

    range: SelectableCapabilities[float] = field(default_factory=SelectableCapabilities)
    feedback_resistor: SelectableCapabilities[float] = field(
        default_factory=SelectableCapabilities
    )


@dataclass(frozen=True, slots=True)
class BoostCapabilities:
    """
    Boost stage gain selection.

    The boost stage is a dimensionless voltage-gain stage after the preamp, so
    it scales the preamp output without changing the transimpedance.

    Attributes:
        gain (SelectableCapabilities[float]): Selectable boost gains, as
            dimensionless factors. ``options`` may be empty for a continuously
            settable stage; in that case ``default_gain`` still applies.
        default_gain (float): The gain the device applies at power-on or reset,
            which is unity for this device family.
    """

    gain: SelectableCapabilities[float]
    default_gain: float = 1.0


@dataclass(frozen=True, slots=True)
class OutputVoltageCapabilities:
    """
    Static output voltage swing limits.

    The limits are geometry rather than runtime state, which is why they live in
    the capability set: they do not change while the device runs. The output
    voltage the device currently reports is a field of the state snapshot.

    Attributes:
        min_v (float | None): Most negative output voltage in V, or ``None`` when
            the driver does not know the limit.
        max_v (float | None): Most positive output voltage in V, or ``None`` when
            the driver does not know the limit.
    """

    min_v: float | None = None
    max_v: float | None = None


@dataclass(frozen=True, slots=True)
class DcBiasCapabilities:
    """
    DC bias injection surface.

    Attributes:
        enabled (Access): Whether bias injection can be read and switched.
        level (Access): Whether the bias level can be read and set.
    """

    enabled: Access = field(default_factory=Access)
    level: Access = field(default_factory=Access)


@dataclass(frozen=True, slots=True)
class FilterCapabilities:
    """
    Signal-filter surface.

    Attributes:
        types (tuple[FilterType, ...]): Filter responses the amplifier supports.
            An empty tuple means no filter is available.
        enabled (Access): Whether the filter can be read and switched on or off.
        cutoff (Access): Whether the filter cutoff frequency can be read and set.
            The frequency domain is carried by the state snapshot, so it is not
            enumerated here.
    """

    types: tuple[FilterType, ...] = ()
    enabled: Access = field(default_factory=Access)
    cutoff: Access = field(default_factory=Access)


@dataclass(frozen=True, slots=True)
class IndicationCapabilities:
    """
    A read-only status flag.

    Attributes:
        read (bool): Whether the flag can be read.
    """

    read: bool = False

    def __bool__(self) -> bool:
        """Return whether the flag is reported."""
        return self.read


@dataclass(frozen=True, slots=True)
class CompensationCapabilities:
    """
    Input-capacitance compensation surface.

    Compensation cancels the pole formed by the source capacitance and the
    feedback resistor, so it is a pair of settings rather than one.

    Attributes:
        enabled (Access): Whether compensation can be read and switched.
        level (Access): Whether the compensation level can be read and set.
    """

    enabled: Access = field(default_factory=Access)
    level: Access = field(default_factory=Access)


@dataclass(frozen=True, slots=True)
class CurrentAmplifierCapabilities:
    """
    The complete capability set for one amplifier.

    Every group defaults to "unsupported", so a driver declares only what it
    actually implements.

    A capability answers whether a feature is available; it does not answer
    whether the feature is currently on. A present feature that is switched off
    is truthy here (``bool(...) is True``) while the state flag in the snapshot
    is ``False``. Filtering on capabilities and reading the state are therefore
    both required to act correctly.

    Attributes:
        preamp (PreampCapabilities): Preamp range and feedback-resistor
            selection.
        boost (BoostCapabilities): Boost stage gain selection.
        output_voltage (OutputVoltageCapabilities): Static output voltage swing
            limits, in V.
        dc_bias (DcBiasCapabilities): DC bias injection surface.
        bandwidth (SelectableCapabilities[float]): Selectable bandwidth options,
            in Hz. Options carry device-native values; an empty tuple means the
            domain is continuous or not enumerated.
        filters (FilterCapabilities): Signal-filter surface.
        input_overcurrent (IndicationCapabilities): Input-overcurrent flag.
        output_overload (IndicationCapabilities): Output-overload flag.
        input_compensation (CompensationCapabilities): Input-capacitance
            compensation surface.
        invert_output (Access): Whether the output polarity can be read and set.
    """

    preamp: PreampCapabilities = field(default_factory=PreampCapabilities)
    boost: BoostCapabilities = field(
        default_factory=lambda: BoostCapabilities(gain=SelectableCapabilities())
    )
    output_voltage: OutputVoltageCapabilities = field(
        default_factory=OutputVoltageCapabilities
    )
    dc_bias: DcBiasCapabilities = field(default_factory=DcBiasCapabilities)
    bandwidth: SelectableCapabilities[float] = field(
        default_factory=SelectableCapabilities
    )
    filters: FilterCapabilities = field(default_factory=FilterCapabilities)
    input_overcurrent: IndicationCapabilities = field(
        default_factory=IndicationCapabilities
    )
    output_overload: IndicationCapabilities = field(
        default_factory=IndicationCapabilities
    )
    input_compensation: CompensationCapabilities = field(
        default_factory=CompensationCapabilities
    )
    invert_output: Access = field(default_factory=Access)

    def total_transconductance(
        self, feedback_resistor_ohm: float, boost_gain: float = 1.0
    ) -> float:
        """
        Compute the whole-amplifier transconductance.

        The preamp converts input current to voltage through the feedback
        resistor and the boost stage multiplies that voltage, so the
        transimpedance and the boost are the only two factors.

        Args:
            feedback_resistor_ohm: Transimpedance feedback resistance in ohm.
            boost_gain: Dimensionless boost stage gain. The default of ``1.0``
                is the unity gain this device family applies at power-on.

        Returns:
            float: Transconductance in V/A, equal to ``Rf * boost``.

        Raises:
            ValueError: If ``feedback_resistor_ohm`` is zero or negative, since
                such a resistor cannot define a transimpedance.
        """
        if feedback_resistor_ohm <= 0:
            raise ValueError(
                f"feedback resistor must be positive, got {feedback_resistor_ohm!r} ohm"
            )
        return feedback_resistor_ohm * boost_gain

    def max_output_swing_v(self) -> float | None:
        """
        Compute the largest symmetric output excursion.

        Returns:
            float | None: The smaller of ``|min_v|`` and ``|max_v|``, in V, which
            is how far the output can swing in either direction without
            clipping. ``None`` when either limit is unknown, because a symmetric
            excursion then cannot be guaranteed.
        """
        limits = self.output_voltage
        if limits.min_v is None or limits.max_v is None:
            return None
        return min(abs(limits.min_v), abs(limits.max_v))

    def max_input_current_a(
        self, feedback_resistor_ohm: float, boost_gain: float = 1.0
    ) -> float | None:
        """
        Compute the input current that drives the output to its swing limit.

        Args:
            feedback_resistor_ohm: Transimpedance feedback resistance in ohm.
            boost_gain: Dimensionless boost stage gain. The default of ``1.0``
                is the unity gain this device family applies at power-on.

        Returns:
            float | None: The input-current ceiling in A, equal to
            :meth:`max_output_swing_v` divided by
            :meth:`total_transconductance`. ``None`` when the swing is unknown.
            A transconductance of zero yields ``inf``: no finite input current
            can reach the limit.

        Raises:
            ValueError: If ``feedback_resistor_ohm`` is zero or negative.
        """
        swing_v = self.max_output_swing_v()
        if swing_v is None:
            return None
        transconductance = self.total_transconductance(
            feedback_resistor_ohm, boost_gain
        )
        if transconductance == 0:
            return float("inf")
        return swing_v / transconductance
