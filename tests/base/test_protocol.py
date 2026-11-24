"""Tests for the ``CurrentAmplifierProtocol`` contract and the in-memory fakes."""

import inspect
import re

import pytest

try:
    from src.scietex.hal.current_amplifier.base import (
        AmplifierState,
        BandwidthCapabilities,
        CurrentAmplifierCapabilities,
        CurrentAmplifierProtocol,
        FilterSetting,
        FilterType,
        IndicationCapabilities,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.base import (
        AmplifierState,
        BandwidthCapabilities,
        CurrentAmplifierCapabilities,
        CurrentAmplifierProtocol,
        FilterSetting,
        FilterType,
        IndicationCapabilities,
    )

from fakes import (  # noqa: E402
    FakeAmplifier,
    full_amplifier,
    minimal_amplifier,
    read_only_bandwidth_amplifier,
)

_CORE_METHODS = {"connect", "close", "read_data"}


class MinimalAmplifier(CurrentAmplifierProtocol):
    """Implements only the mandatory methods; optional ones keep the defaults."""

    capabilities = CurrentAmplifierCapabilities()

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def read_data(self) -> AmplifierState:
        return AmplifierState()


def _protocol_methods() -> set[str]:
    """Return the protocol's own public coroutines, excluding the mandatory three."""
    return {
        name
        for name, value in vars(CurrentAmplifierProtocol).items()
        if not name.startswith("_")
        and inspect.iscoroutinefunction(value)
        and name not in _CORE_METHODS
    }


def _protocol_properties() -> set[str]:
    """Return the protocol's own public properties."""
    return {
        name
        for name, value in vars(CurrentAmplifierProtocol).items()
        if isinstance(value, property)
    }


def _duck(*, omit: str | None = None) -> object:
    """Build a plain object exposing every protocol member except ``omit``.

    ``runtime_checkable`` checks attribute presence for all protocol members,
    including the ones with default implementations, so removing a single member
    is only observable on an otherwise complete object.
    """
    names = {
        name for name in dir(CurrentAmplifierProtocol) if not name.startswith("_")
    } - {"capabilities"}
    members = {name: (lambda *args, **kwargs: None) for name in names}
    if omit is not None:
        members.pop(omit)
    members["capabilities"] = CurrentAmplifierCapabilities()
    return type("DuckAmplifier", (), members)()


def test_minimal_subclass_satisfies_protocol():
    """A class inheriting the protocol and implementing the core methods passes."""
    assert isinstance(MinimalAmplifier(), CurrentAmplifierProtocol)


def test_duck_with_every_member_satisfies_protocol():
    """A non-subclass passes once every protocol member is present."""
    assert isinstance(_duck(), CurrentAmplifierProtocol)


def test_missing_read_data_fails_protocol_check():
    """The runtime check rejects an object that does not expose ``read_data``."""
    assert not isinstance(_duck(omit="read_data"), CurrentAmplifierProtocol)


def test_core_methods_alone_do_not_satisfy_protocol():
    """A duck with only connect/close/read_data fails.

    ``runtime_checkable`` also demands the defaulted optional methods and the
    ``supports_*``/``can_*`` properties, so the successful minimal
    implementation must inherit from the protocol.
    """

    class CoreOnly:
        capabilities = CurrentAmplifierCapabilities()

        async def connect(self) -> None:
            pass

        async def close(self) -> None:
            pass

        async def read_data(self) -> AmplifierState:
            return AmplifierState()

    assert not isinstance(CoreOnly(), CurrentAmplifierProtocol)


_OPTIONAL_CALLS = [
    ("get_boost_gain", ()),
    ("set_boost_gain", (10.0,)),
    ("get_feedback_resistor", ()),
    ("select_feedback_resistor", (1e4,)),
    ("get_dc_bias", ()),
    ("set_dc_bias", (True,)),
    ("get_dc_bias_level", ()),
    ("set_dc_bias_level", (0.5,)),
    ("get_bandwidth", ()),
    ("set_bandwidth", (1e3,)),
    ("get_filter", (FilterType.LOW_PASS,)),
    ("set_filter", (FilterSetting(type=FilterType.LOW_PASS),)),
    ("get_input_compensation", ()),
    ("set_input_compensation", (True,)),
    ("get_input_compensation_level", ()),
    ("set_input_compensation_level", (0.5,)),
    ("get_inverted", ()),
    ("set_inverted", (True,)),
]

_SUPPORT_PROPERTIES = [
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

_CAN_PROPERTIES = [
    "can_select_preamp",
    "can_set_boost",
    "can_set_dc_bias",
    "can_set_bandwidth",
    "can_set_filter",
    "can_set_input_compensation",
    "can_set_invert_output",
]


def test_optional_call_table_covers_every_optional_method():
    """The table matches the protocol exactly: 18 optional coroutines."""
    table_names = [name for name, _ in _OPTIONAL_CALLS]

    assert len(table_names) == len(set(table_names)) == 18
    assert set(table_names) == _protocol_methods()
    assert all(
        inspect.iscoroutinefunction(getattr(MinimalAmplifier, name))
        for name in table_names
    )


def test_property_tables_cover_every_property():
    """Nine ``supports_*`` and seven ``can_*`` properties, no more, no less."""
    assert len(_SUPPORT_PROPERTIES) == 9
    assert len(_CAN_PROPERTIES) == 7
    assert set(_SUPPORT_PROPERTIES + _CAN_PROPERTIES) == _protocol_properties()


@pytest.mark.asyncio
@pytest.mark.parametrize(("method_name", "args"), _OPTIONAL_CALLS)
async def test_optional_method_default_raises_not_implemented(method_name, args):
    """An unimplemented optional method reports its own name."""
    amplifier = MinimalAmplifier()

    with pytest.raises(NotImplementedError, match=re.escape(method_name)):
        await getattr(amplifier, method_name)(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", sorted(_protocol_methods()))
async def test_not_implemented_messages_never_call_the_preamp_a_gain_stage(method_name):
    """Only the boost stage is a gain; the preamp names its feedback resistor."""
    amplifier = MinimalAmplifier()
    args = dict(_OPTIONAL_CALLS).get(method_name, ())

    with pytest.raises(NotImplementedError) as excinfo:
        await getattr(amplifier, method_name)(*args)

    message = str(excinfo.value)
    if "preamp" in message:
        assert "gain" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "capability"),
    [
        ("get_boost_gain", "boost.gain"),
        ("set_boost_gain", "boost.gain"),
        ("get_feedback_resistor", "preamp.feedback_resistor"),
        ("select_feedback_resistor", "preamp.feedback_resistor"),
    ],
)
async def test_preamp_and_boost_messages_name_their_capability(method_name, capability):
    """The message points at the capability group the caller should consult."""
    amplifier = MinimalAmplifier()
    args = dict(_OPTIONAL_CALLS)[method_name]

    with pytest.raises(NotImplementedError) as excinfo:
        await getattr(amplifier, method_name)(*args)

    message = str(excinfo.value)
    assert f"capability: {capability}" in message
    if capability.startswith("preamp"):
        assert "gain" not in message


@pytest.mark.parametrize("property_name", _SUPPORT_PROPERTIES + _CAN_PROPERTIES)
def test_default_capabilities_report_no_control(property_name):
    """With no advertised capability every convenience property is false."""
    assert getattr(minimal_amplifier(), property_name) is False


@pytest.mark.parametrize("property_name", _SUPPORT_PROPERTIES + _CAN_PROPERTIES)
def test_full_capabilities_expose_every_control(property_name):
    """A fully capable amplifier reports support and write access."""
    assert getattr(full_amplifier(), property_name) is True


def test_output_voltage_is_read_from_the_capability_set():
    """The swing is static data, not a control, so it has no protocol method."""
    amplifier = full_amplifier()

    assert amplifier.capabilities.output_voltage.min_v == -10.0
    assert amplifier.capabilities.output_voltage.max_v == 10.0
    assert not hasattr(CurrentAmplifierProtocol, "supports_output_voltage")


@pytest.mark.asyncio
async def test_read_only_bandwidth_is_readable_but_not_settable():
    """A read-only feature is advertised, readable, and refuses writes."""
    amplifier = read_only_bandwidth_amplifier()

    assert amplifier.supports_bandwidth is True
    assert amplifier.can_set_bandwidth is False
    assert await amplifier.get_bandwidth() == 1e4
    with pytest.raises(NotImplementedError, match="set_bandwidth"):
        await amplifier.set_bandwidth(1e3)


@pytest.mark.asyncio
async def test_fake_absent_feature_raises_not_implemented():
    """The fake mirrors a driver by rejecting a feature it does not advertise."""
    with pytest.raises(NotImplementedError, match="get_feedback_resistor"):
        await minimal_amplifier().get_feedback_resistor()


@pytest.mark.asyncio
async def test_fake_read_data_requires_connection():
    """The snapshot is only available on an open transport."""
    amplifier = minimal_amplifier()

    with pytest.raises(RuntimeError, match="not connected"):
        await amplifier.read_data()

    await amplifier.connect()
    assert await amplifier.read_data() == AmplifierState()


@pytest.mark.asyncio
async def test_fake_reports_none_for_values_it_cannot_report():
    """Fields outside the advertised capability set stay ``None``."""
    amplifier = read_only_bandwidth_amplifier()
    await amplifier.connect()

    state = await amplifier.read_data()
    assert state.bandwidth_hz == 1e4
    assert state.boost_gain is None
    assert state.output_overload is None


@pytest.mark.asyncio
async def test_fake_setter_updates_the_snapshot():
    """A writable feature changes what the following read reports."""
    amplifier = full_amplifier()
    await amplifier.connect()

    await amplifier.set_bandwidth(1e6)
    await amplifier.set_inverted(True)

    state = await amplifier.read_data()
    assert state.bandwidth_hz == 1e6
    assert state.inverted is True


@pytest.mark.asyncio
async def test_full_amplifier_boost_stage_is_enumerated_and_settable():
    """The boost stage offers at least three gains and accepts a new one."""
    amplifier = full_amplifier()

    assert len(amplifier.capabilities.boost.gain.options) >= 3
    assert amplifier.can_set_boost is True

    await amplifier.set_boost_gain(100.0)
    assert await amplifier.get_boost_gain() == 100.0


@pytest.mark.asyncio
async def test_full_amplifier_feedback_resistor_is_settable():
    """The feedback resistor round-trips through the fake."""
    amplifier = full_amplifier()

    await amplifier.select_feedback_resistor(1e5)
    assert await amplifier.get_feedback_resistor() == 1e5


@pytest.mark.asyncio
async def test_fake_feedback_resistor_requires_write_access():
    """A preamp without write access refuses a resistor change."""
    amplifier = read_only_bandwidth_amplifier()

    with pytest.raises(NotImplementedError, match="select_feedback_resistor"):
        await amplifier.select_feedback_resistor(1e4)


@pytest.mark.asyncio
async def test_fixed_bandwidth_is_known_but_not_selectable():
    """A bandwidth fixed by the design is readable from the capability set."""
    capabilities = CurrentAmplifierCapabilities(
        bandwidth=BandwidthCapabilities(fixed_hz=1e4)
    )
    amplifier = FakeAmplifier(capabilities, AmplifierState(bandwidth_hz=1e4))

    assert amplifier.supports_bandwidth is False
    assert amplifier.can_set_bandwidth is False
    assert amplifier.capabilities.bandwidth.fixed_hz == 1e4
    with pytest.raises(NotImplementedError, match="get_bandwidth"):
        await amplifier.get_bandwidth()


def test_present_but_unobservable_indication_is_not_supported():
    """A signal that exists but cannot be read is present yet unsupported."""
    capabilities = CurrentAmplifierCapabilities(
        input_overcurrent=IndicationCapabilities(present=True)
    )
    amplifier = FakeAmplifier(capabilities, AmplifierState())

    assert amplifier.supports_input_overcurrent is False
    assert amplifier.capabilities.input_overcurrent.present is True
