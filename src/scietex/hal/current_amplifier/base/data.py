"""Current amplifier data structures.

:class:`AmplifierState` is a snapshot of what the device reports at one moment;
:class:`FilterSetting` is one entry of the filter list inside it.

``None`` means "this driver cannot report the field", not "zero" and not "off".
A field that is ``None`` has no known value at all, so a caller must check for
``None`` rather than treating a missing reading as an idle amplifier.

Filter fields are device-native engineering units. No unit or scale is invented
at this layer: a driver that speaks counts or register codes stores the value it
reads and documents the conversion in the driver.
"""

import msgspec

from .capabilities import BiasCompensationSource, FilterType


class FilterSetting(msgspec.Struct, frozen=True, kw_only=True):
    """One filter in the amplifier's signal path.

    Attributes:
        type: The filter response the entry configures.
        enabled: Whether this filter is currently switched on. The field is a
            plain ``bool``, not ``bool | None``: a driver either reports the
            filter entry together with its on/off state or omits the entry.
        low_cutoff_hz: Lower cutoff frequency in Hz, or ``None`` when the filter
            has no lower corner or the driver does not report it. A high-pass
            or band-pass filter may report only one corner.
        high_cutoff_hz: Upper cutoff frequency in Hz, or ``None`` when the
            filter has no upper corner or the driver does not report it.
    """

    type: FilterType
    enabled: bool = False
    low_cutoff_hz: float | None = None
    high_cutoff_hz: float | None = None


class AmplifierState(msgspec.Struct, frozen=True, kw_only=True):
    """A snapshot of the values an amplifier reports.

    Each field is ``None`` when the driver cannot report it. ``None`` is not
    ``0.0`` and not ``False``: an unreported boost gain is unknown, not unity,
    and an unreadable overload flag is unknown, not clear.

    Attributes:
        output_voltage_v: Output voltage in V, or ``None`` when unreadable.
        output_current_a: Output current in A, or ``None`` when unreadable.
        input_current_a: Input (source) current in A, or ``None`` when
            unreadable.
        boost_gain: Dimensionless boost stage setting, or ``None`` when the
            driver does not report it. ``None`` is not ``1.0``: an unreported
            gain may be anything, while unity is the value the device applies
            at power-on.
        feedback_resistor_ohm: Feedback resistor in ohm, or ``None`` when
            unreadable.
        dc_bias_enabled: Whether DC bias injection is on, or ``None`` when
            unreadable.
        dc_bias_level: DC bias level in device-native units, or ``None`` when
            unreadable.
        bandwidth_hz: Bandwidth in Hz, or ``None`` when unreadable.
        filters: Configured filters, in the order the device reports them.
        input_overcurrent: Input-overcurrent flag, or ``None`` when unreadable.
        output_overload: Output-overload flag, or ``None`` when unreadable.
        input_compensation_enabled: Whether input-capacitance compensation is
            on, or ``None`` when unreadable.
        input_compensation_level: Compensation level in device-native units, or
            ``None`` when unreadable.
        bias_compensation_source: The source the device selects for DC bias and
            input compensation together, or ``None`` when unreadable.
        inverted: Whether the output polarity is inverted, or ``None`` when
            unreadable.
    """

    output_voltage_v: float | None = None
    output_current_a: float | None = None
    input_current_a: float | None = None
    boost_gain: float | None = None
    feedback_resistor_ohm: float | None = None
    dc_bias_enabled: bool | None = None
    dc_bias_level: float | None = None
    bandwidth_hz: float | None = None
    filters: tuple[FilterSetting, ...] = ()
    input_overcurrent: bool | None = None
    output_overload: bool | None = None
    input_compensation_enabled: bool | None = None
    input_compensation_level: float | None = None
    bias_compensation_source: BiasCompensationSource | None = None
    inverted: bool | None = None
