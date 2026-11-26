"""Tests for the EBIC v1.0 semantic amplifier layer.

An in-memory relay fake replaces the Modbus transport, so these cover the
relay-to-function mapping, the transition ordering and the readback decoding
rather than the serial port. No test opens a port.

The coil indices asserted here are ``relay - 1``: a relay number and its coil
index differ by one. Feedback relays are 5-12, gain relays are 14-16, and the
bias/compensation source is relay 13 at coil 12.
"""

import asyncio

import pytest

try:
    from src.scietex.hal.current_amplifier.base import (
        Access,
        CurrentAmplifierProtocol,
        FilterSetting,
        FilterType,
        UnexpectedResponse,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1Amplifier,
        RelayTransitionError,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.relaymap import (
        BOOSTER_COILS,
        CHANNEL_COILS,
        POWER_ON_COILS,
        RF_CHANNEL,
        RF_OHMS,
        RF_RELAY,
        BiasCompensationSource,
        Relay,
        RfChannel,
        coil_index,
        coil_level,
        decode_coils,
        relay_engaged,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.base import (
        Access,
        CurrentAmplifierProtocol,
        FilterSetting,
        FilterType,
        UnexpectedResponse,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1Amplifier,
        RelayTransitionError,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.relaymap import (
        BOOSTER_COILS,
        CHANNEL_COILS,
        POWER_ON_COILS,
        RF_CHANNEL,
        RF_OHMS,
        RF_RELAY,
        BiasCompensationSource,
        Relay,
        RfChannel,
        coil_index,
        coil_level,
        decode_coils,
        relay_engaged,
    )


class TransitionLog:
    """Ordered log of relay writes and settle sleeps for one test.

    Attributes:
        entries: ``("write", coil, level)`` and ``("sleep", seconds)`` tuples in
            the order the driver produced them.
        sleeps: The recorded sleep durations, in seconds.
    """

    def __init__(self) -> None:
        self.entries: list[tuple[str, int, bool] | tuple[str, float]] = []
        self.sleeps: list[float] = []

    def write(self, index: int, state: bool) -> None:
        """Record one relay write."""
        self.entries.append(("write", index, state))

    def sleep(self, seconds: float) -> None:
        """Record one settle sleep."""
        self.entries.append(("sleep", seconds))
        self.sleeps.append(seconds)


@pytest.fixture(autouse=True)
def transition_log(monkeypatch):
    """Record ``asyncio.sleep`` calls instead of waiting, for every test.

    The settle delay is a real 8 ms per barrier in production; the suite skips
    it so a test that exercises many transitions stays fast, and so the delay
    itself becomes observable next to the writes.
    """
    log = TransitionLog()

    async def sleep(seconds: float) -> None:
        log.sleep(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return log


class FakeRelayAccess:
    """In-memory relay transport that records reads and writes.

    Attributes:
        coils: The current seventeen coil levels. Mutated by ``set_relay`` unless
            ``echo_only`` is set.
        writes: Every ``(index, state)`` handed to ``set_relay``, in order.
        log: The order-preserving log of writes shared with the patched sleep.
        reads: The number of ``read_relays`` calls.
        fail_at: The one-based write ordinal that raises, or ``None``.
        echo_only: Whether a write is acknowledged without changing ``coils``.
    """

    def __init__(
        self,
        coils=None,
        *,
        fail_at=None,
        echo_only=False,
        log=None,
    ) -> None:
        self.coils = list(POWER_ON_COILS if coils is None else coils)
        self.writes: list[tuple[int, bool]] = []
        self.log = TransitionLog() if log is None else log
        self.reads = 0
        self.fail_at = fail_at
        self.echo_only = echo_only
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        """Mark the fake transport as open."""
        self.connected = True

    async def close(self) -> None:
        """Mark the fake transport as closed."""
        self.closed = True

    async def read_relays(self) -> tuple[bool, ...]:
        """Return a copy of the coil vector and count the read."""
        self.reads += 1
        return tuple(self.coils)

    async def set_relay(self, index: int, state: bool) -> None:
        """Record a write, optionally fail it, and apply it unless echoing only."""
        self.writes.append((index, state))
        self.log.write(index, state)
        if self.fail_at is not None and len(self.writes) == self.fail_at:
            raise OSError(f"injected failure writing coil {index}")
        if not self.echo_only:
            self.coils[index] = state


def _driver(fake, **kwargs) -> EBICModbusV1Amplifier:
    """Build a semantic driver over ``fake``, with no serial configuration."""
    return EBICModbusV1Amplifier(relay_driver=fake, **kwargs)


def _coils(*engaged: Relay) -> list[bool]:
    """Build the seventeen coil values that engage exactly ``engaged``."""
    return [coil_level(relay, relay in engaged) for relay in Relay]


def _replay(initial, writes):
    """Apply ``writes`` to ``initial`` and return the final vector and every state."""
    vector = list(initial)
    states = [list(vector)]
    for index, state in writes:
        vector[index] = state
        states.append(list(vector))
    return tuple(vector), states


def _rf_bank_counts(coils) -> dict[RfChannel, int]:
    """Count engaged feedback relays per bank."""
    counts = {RfChannel.LOW_Z: 0, RfChannel.HIGH_Z: 0}
    for relay, bank in RF_CHANNEL.items():
        if relay_engaged(relay, coils[coil_index(relay)]):
            counts[bank] += 1
    return counts


def _engaged_gains(coils) -> list[Relay]:
    """List the engaged booster-gain relays."""
    return [
        relay
        for relay in (Relay.GAIN_X3, Relay.GAIN_X10, Relay.GAIN_X30)
        if relay_engaged(relay, coils[coil_index(relay)])
    ]


def _assert_feedback_path_never_opens(states) -> bool:
    """Assert every replayed state keeps a feedback path closed.

    Returns whether a same-bank parallel pair appears, which is the
    make-before-break signature: the active channel transiently has two engaged
    ``Rf`` instead of zero.
    """
    saw_parallel_pair = False
    for coils in states:
        counts = _rf_bank_counts(coils)
        channel = decode_coils(coils).channel
        if channel is None:
            # The one-write gap between relays 1 and 2 leaves the channel
            # undecoded; a feedback path must still be closed somewhere.
            assert sum(counts.values()) >= 1
        else:
            assert counts[channel] >= 1
        if max(counts.values()) == 2:
            saw_parallel_pair = True
    return saw_parallel_pair


def _assert_gain_make_before_break(sequences) -> bool:
    """Assert each gain sequence engages before it releases.

    Each sequence is the coil vector before the call followed by the vector after
    every write. No state holds more than two engaged gain relays, the incoming
    relay closes on the first write, and a relay-to-relay change never drops
    below one engaged relay. Returns whether such a change actually passed
    through the two-relay parallel pair.
    """
    saw_parallel_pair = False
    for states in sequences:
        assert len(_engaged_gains(states[-1])) <= 1
        old = set(_engaged_gains(states[0]))
        new = set(_engaged_gains(states[-1]))
        if new - old:
            assert new <= set(_engaged_gains(states[1]))
        if old and new:
            assert all(_engaged_gains(coils) for coils in states)
        for coils in states:
            assert len(_engaged_gains(coils)) <= 2
        if len(old | new) == 2:
            saw_parallel_pair = True
            assert any(len(_engaged_gains(coils)) == 2 for coils in states)
    return saw_parallel_pair


# -- polarity ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_enable_setters_write_the_inverted_coil_level():
    """Relays 4 and 17 engage at coil value ``False``."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.set_dc_bias(True)
    assert fake.writes == [(3, False)]

    await driver.set_input_compensation(True)
    assert fake.writes == [(3, False), (16, False)]


# -- feedback resistor ordering --------------------------------------------


@pytest.mark.asyncio
async def test_selecting_a_same_bank_resistor_engages_the_new_one_first():
    """Power-on is 1 kOhm, so 10 kOhm engages coil 10 before releasing coil 11."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.select_feedback_resistor(10_000)

    assert fake.writes == [(10, False), (11, False)]


@pytest.mark.asyncio
async def test_selecting_the_engaged_resistor_writes_nothing():
    """Selecting 1 kOhm on the power-on state is already satisfied."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.select_feedback_resistor(1_000)

    assert fake.writes == []
    assert fake.reads == 1


@pytest.mark.asyncio
async def test_selecting_one_kilohm_from_ten_kilohm_is_new_before_old():
    """The 1 kOhm relay engages before the 10 kOhm relay is released."""
    fake = FakeRelayAccess(_coils(Relay.RF_LOW_10K))
    driver = _driver(fake)

    await driver.select_feedback_resistor(1_000)

    assert fake.writes == [(11, True), (10, True)]


@pytest.mark.asyncio
async def test_a_same_bank_swap_closes_both_resistors_before_breaking():
    """1 kOhm to 10 kOhm engages coil 10 first, so both low-bank relays close."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.select_feedback_resistor(10_000)

    assert [index for index, _ in fake.writes] == [10, 11]
    _, states = _replay(POWER_ON_COILS, fake.writes)
    assert _assert_feedback_path_never_opens(states) is True
    assert _rf_bank_counts(states[1])[RfChannel.LOW_Z] == 2
    assert _rf_bank_counts(states[-1])[RfChannel.LOW_Z] == 1
    assert decode_coils(states[-1]).feedback_resistor_ohm == 10_000.0


@pytest.mark.asyncio
async def test_cross_bank_transition_engages_then_switches_then_releases():
    """1 kOhm to 10 MOhm engages the target, switches the channel, then releases."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.select_feedback_resistor(10_000_000)

    assert fake.writes == [(7, False), (0, False), (1, False), (2, False), (11, False)]
    final, states = _replay(POWER_ON_COILS, fake.writes)
    assert _assert_feedback_path_never_opens(states) is False
    assert final == tuple(fake.coils)
    readback = decode_coils(final)
    assert readback.channel is RfChannel.HIGH_Z
    assert readback.feedback_resistor_ohm == 10_000_000.0


@pytest.mark.asyncio
async def test_every_feedback_selection_keeps_a_feedback_path_closed():
    """All eight selections never leave the active channel without an engaged Rf."""
    saw_parallel_pair = False
    for ohm in RF_OHMS:
        fake = FakeRelayAccess()
        driver = _driver(fake)

        await driver.select_feedback_resistor(ohm)

        final, states = _replay(POWER_ON_COILS, fake.writes)
        saw_parallel_pair |= _assert_feedback_path_never_opens(states)
        readback = decode_coils(final)
        assert readback.channel is RF_CHANNEL[RF_RELAY[int(ohm)]]
        assert readback.feedback_resistor_ohm == ohm
        counts = _rf_bank_counts(final)
        assert counts[readback.channel] == 1
        assert sum(counts.values()) == 1
    assert saw_parallel_pair, "no same-bank swap closed the parallel pair"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial", "resistance", "target_channel"),
    [
        (POWER_ON_COILS, 10_000_000, RfChannel.HIGH_Z),
        (
            _coils(
                Relay.CHANNEL_SELECT,
                Relay.DESELECTED_FEEDBACK,
                Relay.RF_HIGH_10M,
                Relay.BOOST_SOURCE,
            ),
            1_000,
            RfChannel.LOW_Z,
        ),
    ],
)
async def test_selecting_a_channel_also_routes_it_to_the_booster(
    initial, resistance, target_channel
):
    """Relay 3 takes the ``BOOSTER_COILS`` level after the channel relays."""
    fake = FakeRelayAccess(initial)
    driver = _driver(fake)

    await driver.select_feedback_resistor(resistance)

    booster = (coil_index(Relay.BOOST_SOURCE), BOOSTER_COILS[target_channel])
    assert fake.writes.index(booster) == 3
    assert fake.coils[coil_index(Relay.BOOST_SOURCE)] is BOOSTER_COILS[target_channel]
    assert decode_coils(fake.coils).booster_source_coil is BOOSTER_COILS[target_channel]


# -- booster gain -----------------------------------------------------------


@pytest.mark.asyncio
async def test_gain_changes_engage_the_new_relay_before_releasing_the_old():
    """x10 engages coil 14 first; x30 then engages coil 15 before coil 14 releases."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.set_boost_gain(10.0)
    assert fake.writes == [(14, False)]

    count = len(fake.writes)
    await driver.set_boost_gain(30.0)
    assert fake.writes[count:] == [(15, False), (14, True)]
    assert _engaged_gains(fake.coils) == [Relay.GAIN_X30]

    count = len(fake.writes)
    await driver.set_boost_gain(1.0)
    assert fake.writes[count:] == [(15, True)]
    assert _engaged_gains(fake.coils) == []


@pytest.mark.asyncio
async def test_every_gain_change_closes_the_parallel_pair_before_opening_it():
    """x3 to x10 to x30 to x1 to x3 never releases before it engages."""
    fake = FakeRelayAccess(_coils(Relay.GAIN_X3))
    driver = _driver(fake)

    sequences = []
    for gain in (10.0, 30.0, 1.0, 3.0):
        before = tuple(fake.coils)
        count = len(fake.writes)
        await driver.set_boost_gain(gain)
        _, states = _replay(before, fake.writes[count:])
        sequences.append(states)

    assert _assert_gain_make_before_break(sequences) is True
    assert _engaged_gains(fake.coils) == [Relay.GAIN_X3]


# -- settle barrier ---------------------------------------------------------


@pytest.mark.asyncio
async def test_same_bank_feedback_swap_settles_between_make_and_break(transition_log):
    """1 kOhm to 10 kOhm logs the engage write, the settle sleep, then the release."""
    fake = FakeRelayAccess(log=transition_log)
    driver = _driver(fake)

    await driver.select_feedback_resistor(10_000)

    assert transition_log.entries == [
        ("write", 10, False),
        ("sleep", 0.008),
        ("write", 11, False),
    ]


@pytest.mark.asyncio
async def test_cross_bank_feedback_swap_settles_before_the_channel_writes(
    transition_log,
):
    """The target engages and settles before relays 1-3 move the circuit onto it."""
    fake = FakeRelayAccess(log=transition_log)
    driver = _driver(fake)

    await driver.select_feedback_resistor(10_000_000)

    assert transition_log.entries == [
        ("write", 7, False),
        ("sleep", 0.008),
        ("write", 0, False),
        ("write", 1, False),
        ("write", 2, False),
        ("write", 11, False),
    ]


@pytest.mark.asyncio
async def test_gain_change_settles_between_make_and_break(transition_log):
    """x10 to x30 logs the engage of coil 15, the settle sleep, then coil 14's release."""
    fake = FakeRelayAccess(log=transition_log)
    driver = _driver(fake)
    await driver.set_boost_gain(10.0)
    transition_log.entries.clear()

    await driver.set_boost_gain(30.0)

    assert transition_log.entries == [
        ("write", 15, False),
        ("sleep", 0.008),
        ("write", 14, True),
    ]


@pytest.mark.asyncio
async def test_a_gain_change_to_unity_has_no_barrier(transition_log):
    """Unity only releases the engaged relay, so nothing is made and nothing settles."""
    fake = FakeRelayAccess(_coils(Relay.GAIN_X10), log=transition_log)
    driver = _driver(fake)

    await driver.set_boost_gain(1.0)

    assert transition_log.entries == [("write", 14, True)]
    assert transition_log.sleeps == []


@pytest.mark.asyncio
async def test_an_idempotent_call_neither_writes_nor_settles(transition_log):
    """A repeat of the power-on selection produces zero writes and zero sleeps."""
    fake = FakeRelayAccess(log=transition_log)
    driver = _driver(fake)

    await driver.select_feedback_resistor(1_000)
    await driver.select_feedback_resistor(1_000)

    assert transition_log.entries == []
    assert fake.writes == []


@pytest.mark.asyncio
async def test_zero_settle_disables_the_barrier_and_keeps_the_write_order(
    transition_log,
):
    """A zero settle time skips the sleep call and leaves the writes unchanged."""
    fake = FakeRelayAccess(log=transition_log)
    driver = _driver(fake, relay_settle_s=0)

    await driver.select_feedback_resistor(10_000_000)

    assert transition_log.sleeps == []

    default_fake = FakeRelayAccess()
    await _driver(default_fake).select_feedback_resistor(10_000_000)
    assert fake.writes == default_fake.writes


@pytest.mark.asyncio
async def test_default_settle_is_the_im03_operate_plus_bounce_maximum(transition_log):
    """The IM03 operate max 3 ms plus bounce max 5 ms is the default 8 ms wait."""
    fake = FakeRelayAccess(log=transition_log)
    driver = _driver(fake)

    assert driver.relay_settle_s == 0.008

    await driver.select_feedback_resistor(10_000)

    assert transition_log.sleeps == [0.008]


def test_a_negative_settle_time_is_rejected_before_io(transition_log):
    """A negative settle time raises at construction, before any bus read or write."""
    fake = FakeRelayAccess(log=transition_log)

    with pytest.raises(ValueError, match="relay_settle_s"):
        EBICModbusV1Amplifier(relay_driver=fake, relay_settle_s=-1)

    assert fake.writes == []
    assert fake.reads == 0


# -- idempotence and validation --------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "argument"),
    [
        ("set_dc_bias", True),
        ("set_input_compensation", True),
        ("set_boost_gain", 10.0),
        ("select_feedback_resistor", 10_000.0),
        ("set_bias_compensation_source", BiasCompensationSource.MANUAL),
    ],
)
async def test_setters_read_once_and_write_nothing_on_a_repeat(method_name, argument):
    """A second identical call does one FC01 and no FC05."""
    fake = FakeRelayAccess()
    driver = _driver(fake)
    setter = getattr(driver, method_name)

    await setter(argument)
    reads = fake.reads
    writes = len(fake.writes)

    await setter(argument)

    assert fake.reads == reads + 1
    assert len(fake.writes) == writes


@pytest.mark.asyncio
async def test_invalid_settings_are_rejected_before_any_io():
    """A non-listed resistor and gain raise without reading or writing."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    with pytest.raises(ValueError, match="unsupported feedback resistor"):
        await driver.select_feedback_resistor(2_000)
    with pytest.raises(ValueError, match="unsupported boost gain"):
        await driver.set_boost_gain(2.0)
    with pytest.raises(ValueError, match="must be finite"):
        await driver.select_feedback_resistor(float("inf"))
    with pytest.raises(ValueError, match="unsupported feedback resistor"):
        await driver.select_feedback_resistor(1_000.5)

    assert fake.writes == []
    assert fake.reads == 0


# -- readback ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_readback_round_trips_every_setting():
    """Every Rf, gain and enable combination decodes to the values just written."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    for ohm in RF_OHMS:
        for gain in (1.0, 3.0, 10.0, 30.0):
            for bias in (False, True):
                for compensation in (False, True):
                    await driver.select_feedback_resistor(ohm)
                    await driver.set_boost_gain(gain)
                    await driver.set_dc_bias(bias)
                    await driver.set_input_compensation(compensation)

                    state = await driver.read_data()

                    assert state.feedback_resistor_ohm == ohm
                    assert state.boost_gain == gain
                    assert state.dc_bias_enabled is bias
                    assert state.input_compensation_enabled is compensation
                    assert state.filters == ()
                    assert state.output_voltage_v is None
                    assert state.output_current_a is None
                    assert state.input_current_a is None
                    assert state.dc_bias_level is None
                    assert state.bandwidth_hz is None
                    assert state.input_overcurrent is None
                    assert state.output_overload is None
                    assert state.input_compensation_level is None
                    assert (
                        state.bias_compensation_source is BiasCompensationSource.MANUAL
                    )
                    assert state.inverted is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("coils", "expected"),
    [
        (POWER_ON_COILS, BiasCompensationSource.MANUAL),
        (_coils(Relay.BIAS_COMP_SOURCE), BiasCompensationSource.DAC),
    ],
    ids=["power-on-manual", "relay-13-dac"],
)
async def test_read_data_carries_the_bias_compensation_source(coils, expected):
    """The snapshot decodes relay 13's coil into the shared source selector."""
    driver = _driver(FakeRelayAccess(coils))

    state = await driver.read_data()

    assert state.bias_compensation_source is expected


@pytest.mark.asyncio
async def test_read_only_operations_write_nothing():
    """The snapshot, the five getters and the extension only read."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.read_data()
    await driver.get_feedback_resistor()
    await driver.get_boost_gain()
    await driver.get_dc_bias()
    await driver.get_input_compensation()
    await driver.get_bias_compensation_source()
    await driver.get_booster_source()

    assert fake.writes == []
    assert fake.reads == 7


@pytest.mark.asyncio
async def test_two_feedback_relays_make_the_resistance_unknown_without_raising():
    """The snapshot reports ``None`` while a dedicated getter raises."""
    fake = FakeRelayAccess(_coils(Relay.RF_LOW_10K, Relay.RF_LOW_1K))
    driver = _driver(fake)

    state = await driver.read_data()
    assert state.feedback_resistor_ohm is None

    with pytest.raises(UnexpectedResponse) as excinfo:
        await driver.get_feedback_resistor()
    assert excinfo.value.register == "feedback resistor"


# -- failures ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_write_reports_the_coil_and_the_half_applied_vector():
    """The second write of a cross-bank switch fails and is not retried."""
    fake = FakeRelayAccess(fail_at=2)
    driver = _driver(fake)

    with pytest.raises(RelayTransitionError) as excinfo:
        await driver.select_feedback_resistor(10_000_000)

    error = excinfo.value
    assert error.operation == "select feedback resistor"
    assert error.failed_coil == 0
    assert isinstance(error.__cause__, OSError)
    observed, _ = _replay(POWER_ON_COILS, fake.writes[:1])
    assert error.observed == observed
    assert error.target[7] is False
    assert error.target[0] is False
    assert error.target[11] is True

    count = len(fake.writes)
    assert count == 2
    assert len(fake.writes) == count


@pytest.mark.asyncio
async def test_a_failed_same_bank_release_leaves_a_parallel_pair_and_recovers():
    """A release that raises leaves both resistors; a later select trims to one."""
    fake = FakeRelayAccess(fail_at=2)
    driver = _driver(fake)

    with pytest.raises(RelayTransitionError) as excinfo:
        await driver.select_feedback_resistor(10_000)

    error = excinfo.value
    assert error.operation == "select feedback resistor"
    assert error.failed_coil == coil_index(Relay.RF_LOW_1K)
    assert error.target[coil_index(Relay.RF_LOW_10K)] is False
    assert error.target[coil_index(Relay.RF_LOW_1K)] is False
    assert len(fake.writes) == 2
    assert _rf_bank_counts(fake.coils)[RfChannel.LOW_Z] == 2

    state = await driver.read_data()
    assert state.feedback_resistor_ohm is None
    with pytest.raises(UnexpectedResponse):
        await driver.get_feedback_resistor()

    fake.fail_at = None
    await driver.select_feedback_resistor(1_000)

    assert _rf_bank_counts(fake.coils)[RfChannel.LOW_Z] == 1
    assert decode_coils(fake.coils).feedback_resistor_ohm == 1_000.0


@pytest.mark.asyncio
async def test_a_failed_gain_release_leaves_a_parallel_pair_and_recovers():
    """A release that raises leaves two gain relays; a later set trims to one."""
    fake = FakeRelayAccess(_coils(Relay.GAIN_X3), fail_at=2)
    driver = _driver(fake)

    with pytest.raises(RelayTransitionError) as excinfo:
        await driver.set_boost_gain(10.0)

    error = excinfo.value
    assert error.operation == "set boost gain"
    assert error.failed_coil == coil_index(Relay.GAIN_X3)
    assert error.target[coil_index(Relay.GAIN_X10)] is False
    assert error.target[coil_index(Relay.GAIN_X3)] is True
    assert len(fake.writes) == 2
    assert _engaged_gains(fake.coils) == [Relay.GAIN_X3, Relay.GAIN_X10]

    state = await driver.read_data()
    assert state.boost_gain is None
    with pytest.raises(UnexpectedResponse):
        await driver.get_boost_gain()

    fake.fail_at = None
    await driver.set_boost_gain(10.0)

    assert _engaged_gains(fake.coils) == [Relay.GAIN_X10]
    assert decode_coils(fake.coils).boost_gain == 10.0


@pytest.mark.asyncio
async def test_an_acknowledged_write_that_does_not_change_the_device_is_an_error():
    """A readback that disagrees with the target is a verification failure."""
    fake = FakeRelayAccess(echo_only=True)
    driver = _driver(fake)

    with pytest.raises(RelayTransitionError) as excinfo:
        await driver.set_dc_bias(True)

    error = excinfo.value
    assert error.failed_coil is None
    assert error.observed == POWER_ON_COILS
    assert error.target != error.observed


# -- channel, source and booster selectors ---------------------------------


@pytest.mark.asyncio
async def test_operations_leave_the_bias_compensation_source_relay_alone():
    """Relays 1-17 except 13 never touch coil 12; the source setter owns it."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.select_feedback_resistor(100_000)
    await driver.set_boost_gain(30.0)
    await driver.set_dc_bias(True)
    await driver.set_input_compensation(True)

    assert all(index != 12 for index, _ in fake.writes)

    await driver.set_bias_compensation_source(BiasCompensationSource.DAC)
    assert fake.writes[-1] == (12, False)
    assert await driver.get_bias_compensation_source() is BiasCompensationSource.DAC

    fake.writes.clear()
    await driver.set_bias_compensation_source(BiasCompensationSource.MANUAL)
    assert fake.writes == [(12, True)]
    assert await driver.get_bias_compensation_source() is BiasCompensationSource.MANUAL

    await driver.set_booster_source(False)
    assert fake.writes[-1] == (2, False)
    assert await driver.get_booster_source() is False


@pytest.mark.asyncio
async def test_the_channel_relays_always_carry_the_same_level():
    """Channel selection is one bit written to relays 1 and 2."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.select_feedback_resistor(10_000_000)

    readback = decode_coils(fake.coils)
    assert readback.channel is RfChannel.HIGH_Z
    assert (
        fake.coils[coil_index(Relay.CHANNEL_SELECT)] is CHANNEL_COILS[RfChannel.HIGH_Z]
    )
    assert (
        fake.coils[coil_index(Relay.CHANNEL_SELECT)]
        == fake.coils[coil_index(Relay.DESELECTED_FEEDBACK)]
    )


# -- contract surface -------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_surface_matches_the_relay_map():
    """The selectable groups are declared; everything else stays unsupported."""
    capabilities = EBICModbusV1Amplifier.capabilities

    assert capabilities.preamp.feedback_resistor.access == Access(read=True, write=True)
    assert capabilities.preamp.feedback_resistor.options == RF_OHMS
    assert capabilities.preamp.max_output_v == 5.0
    assert capabilities.boost.gain.access == Access(read=True, write=True)
    assert capabilities.boost.gain.options == (1.0, 3.0, 10.0, 30.0)
    assert capabilities.boost.default_gain == 1.0
    assert capabilities.dc_bias.enabled == Access(read=True, write=True)
    assert capabilities.dc_bias.level == Access()
    assert capabilities.input_compensation.enabled == Access(read=True, write=True)
    assert capabilities.input_compensation.level == Access()
    assert capabilities.bias_compensation_source.access == Access(read=True, write=True)
    assert capabilities.bias_compensation_source.options == (
        BiasCompensationSource.MANUAL,
        BiasCompensationSource.DAC,
    )
    assert capabilities.input_overcurrent.present is True
    assert capabilities.input_overcurrent.read is False
    assert not capabilities.bandwidth
    assert capabilities.filters.types == ()
    assert not capabilities.filters.enabled
    assert not capabilities.filters.cutoff
    assert not capabilities.output_overload
    assert not capabilities.invert_output

    fake = FakeRelayAccess()
    driver = _driver(fake)

    assert isinstance(driver, CurrentAmplifierProtocol)
    for name in (
        "supports_preamp",
        "supports_boost",
        "supports_dc_bias",
        "supports_input_compensation",
        "can_select_preamp",
        "can_set_boost",
        "can_set_dc_bias",
        "can_set_input_compensation",
    ):
        assert getattr(driver, name) is True
    for name in (
        "supports_bandwidth",
        "supports_filters",
        "supports_output_overload",
        "supports_invert_output",
        "can_set_bandwidth",
        "can_set_filter",
        "can_set_invert_output",
    ):
        assert getattr(driver, name) is False


@pytest.mark.asyncio
async def test_unsupported_contract_methods_stay_not_implemented():
    """Bandwidth, filters, levels and inversion are inherited and still raise."""
    driver = _driver(FakeRelayAccess())
    calls = [
        ("get_bandwidth", ()),
        ("set_bandwidth", (1_000.0,)),
        ("get_filter", (FilterType.LOW_PASS,)),
        ("set_filter", (FilterSetting(type=FilterType.LOW_PASS),)),
        ("get_dc_bias_level", ()),
        ("set_dc_bias_level", (0.1,)),
        ("get_input_compensation_level", ()),
        ("set_input_compensation_level", (0.1,)),
        ("get_inverted", ()),
        ("set_inverted", (True,)),
    ]

    for name, args in calls:
        with pytest.raises(NotImplementedError):
            await getattr(driver, name)(*args)


# -- construction and derived math -----------------------------------------


@pytest.mark.asyncio
async def test_relay_driver_injection_needs_no_serial_configuration():
    """An injected fake is used as-is and the lifecycle is forwarded."""
    fake = FakeRelayAccess()
    driver = _driver(fake)

    await driver.connect()
    assert fake.connected is True

    await driver.close()
    assert fake.closed is True


def test_missing_transport_raises_type_error():
    """With neither a serial config nor a relay driver there is nothing to drive."""
    with pytest.raises(TypeError):
        EBICModbusV1Amplifier()


def test_derived_geometry_matches_the_amplifier_architecture():
    """The declared current range follows ``min(5, 10/G) / Rf``."""
    capabilities = EBICModbusV1Amplifier.capabilities

    assert capabilities.max_input_current_a(1e6, 1.0) == pytest.approx(5e-6)
    assert capabilities.max_input_current_a(1e6, 10.0) == pytest.approx(1e-6)
    assert capabilities.max_output_swing_v() == 10.0
