"""Tests for the capability model."""

from dataclasses import FrozenInstanceError, fields

import pytest

try:
    from src.scietex.hal.current_amplifier.base.capabilities import (
        Access,
        BandwidthCapabilities,
        BiasCompensationSource,
        BoostCapabilities,
        CompensationCapabilities,
        CurrentAmplifierCapabilities,
        DcBiasCapabilities,
        FilterCapabilities,
        FilterType,
        IndicationCapabilities,
        OutputVoltageCapabilities,
        PreampCapabilities,
        SelectableCapabilities,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.base.capabilities import (
        Access,
        BandwidthCapabilities,
        BiasCompensationSource,
        BoostCapabilities,
        CompensationCapabilities,
        CurrentAmplifierCapabilities,
        DcBiasCapabilities,
        FilterCapabilities,
        FilterType,
        IndicationCapabilities,
        OutputVoltageCapabilities,
        PreampCapabilities,
        SelectableCapabilities,
    )


def _with_known_geometry(min_v, max_v):
    """Return capabilities carrying an output range and a known preamp ceiling."""
    return CurrentAmplifierCapabilities(
        preamp=PreampCapabilities(max_output_v=5.0),
        output_voltage=OutputVoltageCapabilities(min_v=min_v, max_v=max_v),
    )


def test_defaults_advertise_nothing():
    """Every capability group defaults to unsupported with no enumerated options."""
    capabilities = CurrentAmplifierCapabilities()

    assert capabilities.preamp.feedback_resistor.access == Access(False, False)
    assert capabilities.preamp.max_output_v is None
    assert capabilities.boost.gain.access == Access(False, False)
    assert capabilities.output_voltage.min_v is None
    assert capabilities.output_voltage.max_v is None
    assert capabilities.dc_bias.enabled == Access(False, False)
    assert capabilities.dc_bias.level == Access(False, False)
    assert capabilities.bandwidth.access == Access(False, False)
    assert capabilities.bandwidth.fixed_hz is None
    assert capabilities.filters.enabled == Access(False, False)
    assert capabilities.filters.cutoff == Access(False, False)
    assert capabilities.input_overcurrent.present is False
    assert capabilities.input_overcurrent.read is False
    assert capabilities.output_overload.read is False
    assert capabilities.input_compensation.enabled == Access(False, False)
    assert capabilities.input_compensation.level == Access(False, False)
    assert capabilities.bias_compensation_source.access == Access(False, False)
    assert capabilities.bias_compensation_source.options == ()
    assert capabilities.invert_output == Access(False, False)
    assert capabilities.bandwidth.options == ()
    assert capabilities.filters.types == ()
    assert bool(capabilities.bias_compensation_source) is False


def test_boost_default_gain_is_unity_on_a_fresh_instance():
    """A continuously settable boost stage still reports the power-on gain."""
    boost = BoostCapabilities(gain=SelectableCapabilities(access=Access(write=True)))

    assert boost.default_gain == 1.0
    assert boost.gain.options == ()
    assert bool(boost.gain) is True


def test_boost_default_gain_is_overridable():
    """A device whose reset gain is not unity can say so."""
    boost = BoostCapabilities(
        gain=SelectableCapabilities(access=Access(read=True), options=(2.0,)),
        default_gain=2.0,
    )

    assert boost.default_gain == 2.0


def test_output_voltage_limits_default_to_unknown():
    """An undeclared output voltage range is unknown in both directions."""
    output = OutputVoltageCapabilities()

    assert output.min_v is None
    assert output.max_v is None


@pytest.mark.parametrize(
    ("access", "expected"),
    [
        (Access(False, False), False),
        (Access(read=True), True),
        (Access(write=True), True),
    ],
)
def test_access_bool_reflects_either_direction(access, expected):
    """An access is truthy when at least one direction is available."""
    assert bool(access) is expected


def test_selectable_capabilities_bool_tracks_access_not_options():
    """A selectable setting is supported even when its domain is not enumerated."""
    assert bool(SelectableCapabilities()) is False
    assert bool(SelectableCapabilities(access=Access(read=True), options=())) is True


def test_selectable_capabilities_preserve_options():
    """Options keep their device order and exact values."""
    options = (1e-9, 0.1, 1234.5678)
    capabilities = SelectableCapabilities(access=Access(read=True), options=options)

    assert capabilities.options == options
    assert capabilities.options[0] == 1e-9
    assert capabilities.options[-1] == 1234.5678


@pytest.mark.parametrize(
    "instance",
    [
        Access(read=True, write=True),
        SelectableCapabilities(access=Access(read=True), options=(1.0, 2.0)),
        BandwidthCapabilities(access=Access(read=True, write=True), options=(1e3, 1e4)),
        PreampCapabilities(),
        BoostCapabilities(gain=SelectableCapabilities(access=Access(read=True))),
        OutputVoltageCapabilities(min_v=-5.0, max_v=5.0),
        DcBiasCapabilities(),
        FilterCapabilities(),
        IndicationCapabilities(present=True, read=True),
        CompensationCapabilities(),
        CurrentAmplifierCapabilities(),
    ],
    ids=[
        "access",
        "selectable",
        "bandwidth",
        "preamp",
        "boost",
        "output_voltage",
        "dc_bias",
        "filters",
        "indication",
        "compensation",
        "current_amplifier",
    ],
)
def test_capability_dataclasses_are_frozen(instance):
    """A capability value is immutable once constructed."""
    field_name = fields(instance)[0].name

    with pytest.raises(FrozenInstanceError):
        setattr(instance, field_name, None)


def test_filter_type_is_a_string_enum():
    """The filter member value is the wire spelling a driver sends."""
    assert FilterType.LOW_PASS == "low_pass"
    assert isinstance(FilterType.LOW_PASS, str)


def test_bias_compensation_source_is_a_string_enum():
    """The source member value is the wire spelling a driver sends."""
    assert BiasCompensationSource.MANUAL == "manual"
    assert BiasCompensationSource.DAC == "dac"
    assert isinstance(BiasCompensationSource.MANUAL, str)
    assert [source.value for source in BiasCompensationSource] == ["dac", "manual"]


def test_bias_compensation_source_group_is_selectable():
    """A device can advertise a read-write source selector with its options."""
    group = SelectableCapabilities(
        access=Access(read=True, write=True),
        options=(BiasCompensationSource.MANUAL, BiasCompensationSource.DAC),
    )
    capabilities = CurrentAmplifierCapabilities(bias_compensation_source=group)

    assert bool(capabilities.bias_compensation_source) is True
    assert capabilities.bias_compensation_source.options == (
        BiasCompensationSource.MANUAL,
        BiasCompensationSource.DAC,
    )


def test_total_transconductance_multiplies_feedback_by_boost():
    """The whole-amplifier transconductance is the resistor times the boost."""
    assert CurrentAmplifierCapabilities().total_transconductance(1e7, 10) == 1e8


def test_total_transconductance_defaults_to_unity_boost():
    """An omitted boost gain is unity, not zero."""
    assert CurrentAmplifierCapabilities().total_transconductance(1e7) == 1e7


@pytest.mark.parametrize("feedback_resistor_ohm", [0.0, -1.0])
def test_total_transconductance_rejects_non_positive_resistance(feedback_resistor_ohm):
    """A non-positive feedback resistor cannot define a transimpedance."""
    with pytest.raises(ValueError, match="feedback resistor"):
        CurrentAmplifierCapabilities().total_transconductance(feedback_resistor_ohm)


def test_max_output_swing_takes_the_smaller_magnitude():
    """An asymmetric range allows only the excursion both rails permit."""
    assert _with_known_geometry(-5.0, 10.0).max_output_swing_v() == 5.0


@pytest.mark.parametrize(
    ("min_v", "max_v"),
    [(None, 10.0), (-5.0, None), (None, None)],
    ids=["no-min", "no-max", "no-limits"],
)
def test_max_output_swing_is_unknown_when_a_limit_is_missing(min_v, max_v):
    """A missing limit makes the symmetric excursion unknown, not unbounded."""
    assert _with_known_geometry(min_v, max_v).max_output_swing_v() is None


def test_max_input_current_divides_swing_by_transconductance():
    """A symmetric 5 V range at 1e8 V/A allows 5e-8 A."""
    assert _with_known_geometry(-5.0, 5.0).max_input_current_a(1e7, 10) == 5e-8


def test_max_input_current_defaults_to_unity_boost():
    """The default boost gain keeps the ceiling at swing divided by the resistor."""
    capabilities = _with_known_geometry(-5.0, 5.0)

    assert capabilities.max_input_current_a(1e7) == 5e-7


def test_max_input_current_is_unknown_without_a_swing():
    """Without both output limits no input-current ceiling can be derived."""
    assert CurrentAmplifierCapabilities().max_input_current_a(1e7) is None


@pytest.mark.parametrize("feedback_resistor_ohm", [0.0, -1.0])
def test_max_input_current_rejects_non_positive_resistance(feedback_resistor_ohm):
    """A non-positive feedback resistor is rejected before any division."""
    capabilities = _with_known_geometry(-5.0, 5.0)

    with pytest.raises(ValueError, match="feedback resistor"):
        capabilities.max_input_current_a(feedback_resistor_ohm)


def test_zero_boost_is_limited_by_the_preamp():
    """A non-amplifying boost leaves the preamp ceiling as the only limit."""
    capabilities = _with_known_geometry(-5.0, 5.0)

    assert capabilities.max_input_current_a(1e7, 0.0) == 5e-7


def test_preamp_has_no_range_member():
    """The preamp exposes only the resistor and the static clip ceiling."""
    names = {field.name for field in fields(PreampCapabilities)}

    assert names == {"feedback_resistor", "max_output_v"}
    assert not hasattr(PreampCapabilities(), "range")


@pytest.mark.parametrize(
    ("boost_gain", "expected"),
    [(1.0, 5.0), (3.0, 10 / 3), (10.0, 1.0), (30.0, 10 / 30)],
)
def test_output_ceiling_binds_at_the_preamp_at_unity_gain(boost_gain, expected):
    """The smaller of the preamp ceiling and the amplifier swing / gain wins."""
    preamp = PreampCapabilities(max_output_v=5.0)

    assert preamp.output_ceiling_v(boost_gain, 10.0) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("feedback_resistor_ohm", "boost_gain", "expected"),
    [(1e6, 1.0, 5e-6), (1e6, 10.0, 1e-6)],
)
def test_input_current_range_uses_the_preamp_ceiling(
    feedback_resistor_ohm, boost_gain, expected
):
    """The preamp ceiling bounds the range, not the wider booster swing."""
    preamp = PreampCapabilities(max_output_v=5.0)

    result = preamp.input_current_range_a(feedback_resistor_ohm, boost_gain, 10.0)

    assert result == pytest.approx(expected)


def test_amplifier_max_input_current_binds_at_the_preamp():
    """The amplifier ceiling follows the preamp, not only the output swing."""
    capabilities = _with_known_geometry(-10.0, 10.0)

    assert capabilities.max_input_current_a(1e6, 1.0) == pytest.approx(5e-6)
    assert capabilities.max_input_current_a(1e6, 3.0) == pytest.approx((10 / 3) / 1e6)


def test_input_current_range_is_unknown_without_the_preamp_ceiling():
    """An unset preamp ceiling makes both levels of the range unknown."""
    preamp = PreampCapabilities()
    capabilities = CurrentAmplifierCapabilities(
        output_voltage=OutputVoltageCapabilities(min_v=-10.0, max_v=10.0)
    )

    assert preamp.input_current_range_a(1e6, 1.0, 10.0) is None
    assert capabilities.max_input_current_a(1e6, 1.0) is None


def test_preamp_limited_current_ignores_the_booster():
    """The preamp-only ceiling divides its clip point by the resistor."""
    preamp = PreampCapabilities(max_output_v=5.0)

    assert preamp.preamp_limited_current_a(1e6) == pytest.approx(5e-6)


def test_preamp_rejects_non_positive_geometry():
    """A non-positive ceiling, resistor, gain or swing is rejected."""
    with pytest.raises(ValueError, match="max output voltage"):
        PreampCapabilities(max_output_v=0.0)
    with pytest.raises(ValueError, match="max output voltage"):
        PreampCapabilities(max_output_v=-5.0)

    preamp = PreampCapabilities(max_output_v=5.0)
    with pytest.raises(ValueError, match="feedback resistor"):
        preamp.preamp_limited_current_a(0.0)
    with pytest.raises(ValueError, match="boost gain"):
        preamp.output_ceiling_v(-1.0, 10.0)
    with pytest.raises(ValueError, match="swing"):
        preamp.output_ceiling_v(1.0, -10.0)


@pytest.mark.parametrize(
    ("bandwidth", "expected_bool", "expected_options", "expected_fixed"),
    [
        (
            BandwidthCapabilities(
                access=Access(read=True, write=True), options=(1e3, 1e4)
            ),
            True,
            (1e3, 1e4),
            None,
        ),
        (BandwidthCapabilities(access=Access(read=True, write=True)), True, (), None),
        (BandwidthCapabilities(fixed_hz=1e4), False, (), 1e4),
        (BandwidthCapabilities(), False, (), None),
    ],
    ids=[
        "selectable-enumerated",
        "selectable-continuous",
        "fixed-known",
        "fixed-unknown",
    ],
)
def test_bandwidth_four_legitimate_states(
    bandwidth, expected_bool, expected_options, expected_fixed
):
    """The four states differ in truthiness, domain and fixed value."""
    assert bool(bandwidth) is expected_bool
    assert bandwidth.options == expected_options
    assert bandwidth.fixed_hz == expected_fixed


def test_bandwidth_rejects_fixed_with_write_access():
    """A value fixed by the analog design cannot also be written."""
    with pytest.raises(ValueError, match="write"):
        BandwidthCapabilities(access=Access(write=True), fixed_hz=1e4)


def test_bandwidth_rejects_fixed_with_options():
    """A fixed bandwidth cannot also enumerate a selectable domain."""
    with pytest.raises(ValueError, match="options"):
        BandwidthCapabilities(fixed_hz=1e4, options=(1e3,))


def test_bandwidth_rejects_read_only_without_domain_or_fixed():
    """A read-only bandwidth must say what domain it reads."""
    with pytest.raises(ValueError, match="read-only"):
        BandwidthCapabilities(access=Access(read=True))


def test_bandwidth_rejects_options_without_access():
    """An enumerated domain that cannot be read or written is meaningless."""
    with pytest.raises(ValueError, match="options"):
        BandwidthCapabilities(options=(1e3,))


@pytest.mark.parametrize("fixed_hz", [0.0, -1.0])
def test_bandwidth_rejects_non_positive_fixed_hz(fixed_hz):
    """A fixed bandwidth must be a positive frequency."""
    with pytest.raises(ValueError, match="fixed bandwidth"):
        BandwidthCapabilities(fixed_hz=fixed_hz)


def test_bandwidth_is_not_a_selectable_capability():
    """The dedicated bandwidth type is deliberately not a selectable setting."""
    assert not isinstance(BandwidthCapabilities(), SelectableCapabilities)


def test_indication_read_requires_presence():
    """A signal cannot be readable without existing."""
    with pytest.raises(ValueError, match="present"):
        IndicationCapabilities(present=False, read=True)


def test_indication_bool_tracks_presence():
    """Truthiness answers whether the signal exists, not whether it is readable."""
    assert bool(IndicationCapabilities(present=True)) is True
    assert bool(IndicationCapabilities(present=True, read=True)) is True
    assert bool(IndicationCapabilities()) is False


def test_indication_distinguishes_the_four_combinations():
    """Presence and observability are independent except for the invalid state."""
    absent = IndicationCapabilities()
    present_unobservable = IndicationCapabilities(present=True)
    present_observable = IndicationCapabilities(present=True, read=True)

    assert (absent.present, absent.read) == (False, False)
    assert (present_unobservable.present, present_unobservable.read) == (True, False)
    assert (present_observable.present, present_observable.read) == (True, True)
    with pytest.raises(ValueError):
        IndicationCapabilities(present=False, read=True)
