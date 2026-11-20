"""Tests for the capability model."""

from dataclasses import FrozenInstanceError, fields

import pytest

try:
    from src.scietex.hal.current_amplifier.base.capabilities import (
        Access,
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


def _with_output_voltage(min_v, max_v):
    """Return capabilities carrying only an output voltage range."""
    return CurrentAmplifierCapabilities(
        output_voltage=OutputVoltageCapabilities(min_v=min_v, max_v=max_v)
    )


def test_defaults_advertise_nothing():
    """Every capability group defaults to unsupported with no enumerated options."""
    capabilities = CurrentAmplifierCapabilities()

    assert capabilities.preamp.range.access == Access(False, False)
    assert capabilities.preamp.feedback_resistor.access == Access(False, False)
    assert capabilities.boost.gain.access == Access(False, False)
    assert capabilities.output_voltage.min_v is None
    assert capabilities.output_voltage.max_v is None
    assert capabilities.dc_bias.enabled == Access(False, False)
    assert capabilities.dc_bias.level == Access(False, False)
    assert capabilities.bandwidth.access == Access(False, False)
    assert capabilities.filters.enabled == Access(False, False)
    assert capabilities.filters.cutoff == Access(False, False)
    assert capabilities.input_overcurrent.read is False
    assert capabilities.output_overload.read is False
    assert capabilities.input_compensation.enabled == Access(False, False)
    assert capabilities.input_compensation.level == Access(False, False)
    assert capabilities.invert_output == Access(False, False)
    assert capabilities.bandwidth.options == ()
    assert capabilities.filters.types == ()


def test_preamp_range_defaults_to_unsupported():
    """A preamp advertises nothing until a driver declares a setting."""
    preamp = PreampCapabilities()

    assert bool(preamp.range) is False
    assert bool(preamp.feedback_resistor) is False
    assert preamp.range.options == ()


def test_preamp_range_and_feedback_resistor_stay_independent():
    """The range designator and the resistance are separate quantities."""
    preamp = PreampCapabilities(
        range=SelectableCapabilities(access=Access(read=True), options=(1.0, 2.0)),
        feedback_resistor=SelectableCapabilities(
            access=Access(read=True), options=(1e4, 1e6)
        ),
    )

    assert preamp.range.options == (1.0, 2.0)
    assert preamp.feedback_resistor.options == (1e4, 1e6)


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
        PreampCapabilities(),
        BoostCapabilities(gain=SelectableCapabilities(access=Access(read=True))),
        OutputVoltageCapabilities(min_v=-5.0, max_v=5.0),
        DcBiasCapabilities(),
        FilterCapabilities(),
        IndicationCapabilities(read=True),
        CompensationCapabilities(),
        CurrentAmplifierCapabilities(),
    ],
    ids=[
        "access",
        "selectable",
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
    assert _with_output_voltage(-5.0, 10.0).max_output_swing_v() == 5.0


@pytest.mark.parametrize(
    ("min_v", "max_v"),
    [(None, 10.0), (-5.0, None), (None, None)],
    ids=["no-min", "no-max", "no-limits"],
)
def test_max_output_swing_is_unknown_when_a_limit_is_missing(min_v, max_v):
    """A missing limit makes the symmetric excursion unknown, not unbounded."""
    assert _with_output_voltage(min_v, max_v).max_output_swing_v() is None


def test_max_input_current_divides_swing_by_transconductance():
    """A symmetric 5 V range at 1e8 V/A allows 5e-8 A."""
    assert _with_output_voltage(-5.0, 5.0).max_input_current_a(1e7, 10) == 5e-8


def test_max_input_current_defaults_to_unity_boost():
    """The default boost gain keeps the ceiling at swing divided by the resistor."""
    capabilities = _with_output_voltage(-5.0, 5.0)

    assert capabilities.max_input_current_a(1e7) == 5e-7


def test_max_input_current_is_unknown_without_a_swing():
    """Without both output limits no input-current ceiling can be derived."""
    assert CurrentAmplifierCapabilities().max_input_current_a(1e7) is None


@pytest.mark.parametrize("feedback_resistor_ohm", [0.0, -1.0])
def test_max_input_current_rejects_non_positive_resistance(feedback_resistor_ohm):
    """A non-positive feedback resistor is rejected before any division."""
    capabilities = _with_output_voltage(-5.0, 5.0)

    with pytest.raises(ValueError, match="feedback resistor"):
        capabilities.max_input_current_a(feedback_resistor_ohm)


def test_max_input_current_is_infinite_at_zero_transconductance():
    """A silent boost stage cannot be driven to the rail by any input current."""
    capabilities = _with_output_voltage(-5.0, 5.0)

    assert capabilities.max_input_current_a(1e7, 0.0) == float("inf")
