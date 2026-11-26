"""
Current amplifier capability model.

An amplifier advertises what it can do through a single
:class:`CurrentAmplifierCapabilities` value, grouped by function rather than by
method name. The grouping is semantic: a driver maps its own vocabulary onto
these groups, so a caller can ask "can this amplifier change its feedback
resistor?" without knowing whether the underlying protocol calls the setting a
resistor or a code.

Two kinds of surface are modelled separately. A switch is an :class:`Access`,
which distinguishes "readable" from "writeable" because many devices expose a
setting read-only. A switch that also takes a value is a
:class:`SelectableCapabilities`, which adds the domain of accepted values.

A third kind is static geometry: a limit that never changes while the device
runs, such as the output voltage swing, is capability data rather than state.
It is read from the capability set directly instead of through a protocol
method or a ``supports_*`` property.

A bandwidth is either selectable or fixed by the analog design, so it has its
own :class:`BandwidthCapabilities` rather than reusing
:class:`SelectableCapabilities`, whose empty option tuple cannot express the
difference.

The groups are frozen dataclasses so a driver declares them once as a class
attribute and callers cannot mutate them.

Classes:
    FilterType: The filter responses an amplifier can apply.
    BiasCompensationSource: The source a device selects for DC bias and input
        compensation.
    Access: Whether a setting can be read and whether it can be written.
    SelectableCapabilities: An access plus the values it accepts.
    BandwidthCapabilities: A bandwidth domain and whether it is selectable.
    PreampCapabilities: Preamp feedback-resistor selection and clip geometry.
    BoostCapabilities: Boost stage gain selection.
    OutputVoltageCapabilities: Static output voltage swing limits.
    DcBiasCapabilities: DC bias injection surface.
    FilterCapabilities: Signal-filter surface.
    IndicationCapabilities: A status signal and whether it is readable.
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


class BiasCompensationSource(str, Enum):
    """The source a device selects for DC bias and input compensation.

    One selector feeds both functions together, so a device cannot drive its
    bias from the DAC while taking its compensation level from a manual control.
    The member value is the spelling a driver reports; it doubles as the
    serialised form because the class inherits from ``str``.
    """

    DAC = "dac"
    MANUAL = "manual"


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
class BandwidthCapabilities:
    """
    A bandwidth domain and whether the analog design fixes it.

    Unlike :class:`SelectableCapabilities`, an empty ``options`` tuple here does
    not silently mean "continuous": the four legitimate states are explicit.

    Legitimate states:
        - Selectable, enumerated: access is truthy, ``options`` is non-empty and
          ``fixed_hz`` is ``None``.
        - Selectable, continuous: access is truthy, ``options`` is empty and
          ``fixed_hz`` is ``None``.
        - Fixed, known: ``fixed_hz`` is set, access is falsy and ``options`` is
          empty.
        - Fixed, unknown: access is falsy, ``options`` is empty and ``fixed_hz``
          is ``None``.

    Invalid combinations, each rejected by ``__post_init__``:
        - ``fixed_hz`` set with write access.
        - ``fixed_hz`` set with a non-empty ``options`` tuple.
        - non-empty ``options`` without access.
        - read-only access with neither a domain nor a fixed value.

    Individual ``options`` values are not validated, matching
    :class:`SelectableCapabilities`.

    Attributes:
        access (Access): Whether the bandwidth can be read and written.
        options (tuple[float, ...]): Selectable bandwidths in Hz. Empty when the
            domain is continuous or the bandwidth is fixed.
        fixed_hz (float | None): Bandwidth in Hz when the analog design fixes it,
            or ``None`` when the bandwidth is selectable or unknown.
    """

    access: Access = field(default_factory=Access)
    options: tuple[float, ...] = ()
    fixed_hz: float | None = None

    def __post_init__(self) -> None:
        if self.fixed_hz is not None and self.fixed_hz <= 0:
            raise ValueError(
                f"fixed bandwidth must be positive, got {self.fixed_hz!r} Hz"
            )
        if self.fixed_hz is not None and self.access.write:
            raise ValueError("a fixed bandwidth cannot be writeable")
        if self.fixed_hz is not None and self.options:
            raise ValueError("a fixed bandwidth cannot enumerate options")
        if self.options and not self.access:
            raise ValueError("bandwidth options require access")
        if (
            self.access.read
            and not self.access.write
            and self.fixed_hz is None
            and not self.options
        ):
            raise ValueError(
                "read-only bandwidth requires a known domain or a fixed value"
            )

    def __bool__(self) -> bool:
        """Return whether the bandwidth is selectable in either direction."""
        return bool(self.access)


@dataclass(frozen=True, slots=True)
class PreampCapabilities:
    """
    Preamp feedback-resistor selection and static clip geometry.

    The feedback resistor is the only selectable pre-amp control: it sets the
    transimpedance, and the low- and high-current channels the hardware exposes
    are a grouping of ``feedback_resistor.options`` rather than a value of their
    own. The input-current range is therefore derived from the selected
    resistor together with the boost gain and the static clip limits; it is not
    selected directly.

    Attributes:
        feedback_resistor (SelectableCapabilities[float]): Selectable
            transimpedance feedback-resistor options, in ohm. An empty tuple
            means the domain is continuous or not enumerated.
        max_output_v (float | None): Magnitude of the largest symmetric pre-amp
            output excursion in V, which is where the Overcurrent comparator
            trips. ``None`` means the geometry is unknown.
    """

    feedback_resistor: SelectableCapabilities[float] = field(
        default_factory=SelectableCapabilities
    )
    max_output_v: float | None = None

    def __post_init__(self) -> None:
        if self.max_output_v is not None and self.max_output_v <= 0:
            raise ValueError(
                f"max output voltage must be positive, got {self.max_output_v!r} V"
            )

    def output_ceiling_v(
        self, boost_gain: float, amplifier_swing_v: float | None
    ) -> float | None:
        """
        Compute the pre-amp output ceiling before the boost stage clips it.

        Args:
            boost_gain: Dimensionless boost stage gain. A gain of ``0.0`` means
                the booster never reaches its rail, so the pre-amp ceiling
                applies unchanged.
            amplifier_swing_v: Symmetric boost-stage output swing in V, or
                ``None`` when the amplifier geometry is unknown.

        Returns:
            float | None: ``min(max_output_v, amplifier_swing_v / boost_gain)``
            in V, or ``None`` when the pre-amp ceiling or the amplifier swing is
            unknown.

        Raises:
            ValueError: If ``boost_gain`` is negative or ``amplifier_swing_v``
                is negative.
        """
        if boost_gain < 0:
            raise ValueError(f"boost gain must be non-negative, got {boost_gain!r}")
        if amplifier_swing_v is not None and amplifier_swing_v < 0:
            raise ValueError(
                f"amplifier swing must be non-negative, got {amplifier_swing_v!r} V"
            )
        if self.max_output_v is None or amplifier_swing_v is None:
            return None
        if boost_gain == 0.0:
            return self.max_output_v
        return min(self.max_output_v, amplifier_swing_v / boost_gain)

    def preamp_limited_current_a(self, feedback_resistor_ohm: float) -> float | None:
        """
        Compute the input current the pre-amp alone can accept.

        Args:
            feedback_resistor_ohm: Transimpedance feedback resistance in ohm.

        Returns:
            float | None: ``max_output_v / feedback_resistor_ohm`` in A, ignoring
            the boost stage, or ``None`` when ``max_output_v`` is unknown.

        Raises:
            ValueError: If ``feedback_resistor_ohm`` is zero or negative.
        """
        if feedback_resistor_ohm <= 0:
            raise ValueError(
                f"feedback resistor must be positive, got {feedback_resistor_ohm!r} ohm"
            )
        if self.max_output_v is None:
            return None
        return self.max_output_v / feedback_resistor_ohm

    def input_current_range_a(
        self,
        feedback_resistor_ohm: float,
        boost_gain: float,
        amplifier_swing_v: float | None,
    ) -> float | None:
        """
        Compute the input-current range for a selected feedback resistor.

        The range is derived, never selected: the limiting output voltage is the
        smaller of the pre-amp ceiling and the boost-stage swing divided by the
        gain, and the current follows from the feedback resistor.

        Args:
            feedback_resistor_ohm: Transimpedance feedback resistance in ohm.
            boost_gain: Dimensionless boost stage gain.
            amplifier_swing_v: Symmetric boost-stage output swing in V, or
                ``None`` when the amplifier geometry is unknown.

        Returns:
            float | None: The input-current ceiling in A, equal to
            :meth:`output_ceiling_v` divided by ``feedback_resistor_ohm``, or
            ``None`` when the pre-amp ceiling or the amplifier swing is unknown.

        Raises:
            ValueError: If ``feedback_resistor_ohm`` is non-positive,
                ``boost_gain`` is negative, or ``amplifier_swing_v`` is negative.
        """
        if feedback_resistor_ohm <= 0:
            raise ValueError(
                f"feedback resistor must be positive, got {feedback_resistor_ohm!r} ohm"
            )
        ceiling_v = self.output_ceiling_v(boost_gain, amplifier_swing_v)
        if ceiling_v is None:
            return None
        return ceiling_v / feedback_resistor_ohm


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
    A status signal that may exist without being readable.

    Two questions are distinct: whether the signal exists on the device, and
    whether the firmware can read it.

    Combinations:
        - Absent: ``(present=False, read=False)``.
        - Present but unobservable: ``(present=True, read=False)``.
        - Present and observable: ``(present=True, read=True)``.
        - Invalid: ``(present=False, read=True)``, rejected by
          ``__post_init__``.

    Truthiness answers "does this signal exist", never "can it be read".

    Attributes:
        present (bool): Whether the signal exists on the device.
        read (bool): Whether the driver can read it.
    """

    present: bool = False
    read: bool = False

    def __post_init__(self) -> None:
        if self.read and not self.present:
            raise ValueError("a readable indication must be present")

    def __bool__(self) -> bool:
        """Return whether the signal exists on the device."""
        return self.present


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
        preamp (PreampCapabilities): Preamp feedback-resistor selection and
            static clip geometry.
        boost (BoostCapabilities): Boost stage gain selection.
        output_voltage (OutputVoltageCapabilities): Static output voltage swing
            limits, in V.
        dc_bias (DcBiasCapabilities): DC bias injection surface.
        bandwidth (BandwidthCapabilities): Bandwidth domain and whether the
            analog design fixes it.
        filters (FilterCapabilities): Signal-filter surface.
        input_overcurrent (IndicationCapabilities): Input-overcurrent signal.
        output_overload (IndicationCapabilities): Output-overload signal.
        input_compensation (CompensationCapabilities): Input-capacitance
            compensation surface.
        bias_compensation_source (SelectableCapabilities[BiasCompensationSource]):
            Shared source selector for DC bias and input compensation; the
            options are the accepted source values.
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
    bandwidth: BandwidthCapabilities = field(default_factory=BandwidthCapabilities)
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
    bias_compensation_source: SelectableCapabilities[BiasCompensationSource] = field(
        default_factory=SelectableCapabilities
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
        Compute the input current at which the amplifier clips.

        The ceiling is derived from the preamp feedback resistor, the boost gain
        and the static clip limits; it is not a selectable control.

        Args:
            feedback_resistor_ohm: Transimpedance feedback resistance in ohm.
            boost_gain: Dimensionless boost stage gain. The default of ``1.0``
                is the unity gain this device family applies at power-on.

        Returns:
            float | None: The input-current ceiling in A, delegated to
            :meth:`PreampCapabilities.input_current_range_a`. ``None`` when the
            amplifier swing or the pre-amp ceiling is unknown.

        Raises:
            ValueError: If ``feedback_resistor_ohm`` is zero or negative, or
                ``boost_gain`` is negative.
        """
        return self.preamp.input_current_range_a(
            feedback_resistor_ohm, boost_gain, self.max_output_swing_v()
        )
