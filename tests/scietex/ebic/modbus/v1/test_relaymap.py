"""Tests for the EBIC v1.0 relay-to-function map.

The polarity and the ``Rf`` and gain tables are transcribed from the firmware;
every test here fails if they drift.
"""

try:
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.relaymap import (
        CHANNEL_COILS,
        GAIN_RELAY,
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
        engaged_relays,
        relay_engaged,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.relaymap import (
        CHANNEL_COILS,
        GAIN_RELAY,
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
        engaged_relays,
        relay_engaged,
    )


def _snapshot(*engaged: Relay) -> list[bool]:
    """Build the seventeen coil values that engage exactly ``engaged``."""
    return [coil_level(relay, relay in engaged) for relay in Relay]


def test_coil_index_is_the_relay_number_minus_one():
    """The firmware applies the identity without a lookup table."""
    assert [coil_index(relay) for relay in Relay] == list(range(17))
    assert Relay.RF_LOW_1K.value == 12
    assert coil_index(Relay.RF_LOW_1K) == 11


def test_every_relay_but_the_one_kilohm_one_engages_at_a_low_coil():
    """Relay 12 is the only active-high function on the board."""
    for relay in Relay:
        if relay is Relay.RF_LOW_1K:
            assert coil_level(relay, True) is True
            assert coil_level(relay, False) is False
        else:
            assert coil_level(relay, True) is False
            assert coil_level(relay, False) is True


def test_coil_level_and_relay_engaged_round_trip():
    """Decoding a level written for a wanted state recovers that state."""
    for relay in Relay:
        for engaged in (True, False):
            assert relay_engaged(relay, coil_level(relay, engaged)) is engaged


def test_rf_table_covers_the_eight_resistors_and_their_banks():
    """Ascending ohm, low-Z on relays 9-12 and high-Z on relays 5-8."""
    high_z = (10_000_000, 100_000_000, 1_000_000_000, 10_000_000_000)
    low_z = (1_000, 10_000, 100_000, 1_000_000)

    assert set(RF_RELAY) == set(low_z) | set(high_z)
    assert tuple(float(ohm) for ohm in low_z + high_z) == RF_OHMS
    assert {RF_RELAY[ohm] for ohm in high_z} == {
        Relay.RF_HIGH_10M,
        Relay.RF_HIGH_100M,
        Relay.RF_HIGH_1G,
        Relay.RF_HIGH_10G,
    }
    assert {RF_RELAY[ohm] for ohm in low_z} == {
        Relay.RF_LOW_1M,
        Relay.RF_LOW_100K,
        Relay.RF_LOW_10K,
        Relay.RF_LOW_1K,
    }
    assert {
        int(relay) for relay, bank in RF_CHANNEL.items() if bank is RfChannel.HIGH_Z
    } == {5, 6, 7, 8}
    assert {
        int(relay) for relay, bank in RF_CHANNEL.items() if bank is RfChannel.LOW_Z
    } == {9, 10, 11, 12}


def test_channel_coils_select_low_z_with_a_high_coil():
    """Relays 1 and 2 carry ``True`` for low-Z and ``False`` for high-Z."""
    assert CHANNEL_COILS == {RfChannel.LOW_Z: True, RfChannel.HIGH_Z: False}


def test_gain_relays_are_one_hot_over_the_three_stages():
    """Unity is the absence of all three gain relays."""
    assert GAIN_RELAY == {
        1.0: None,
        3.0: Relay.GAIN_X3,
        10.0: Relay.GAIN_X10,
        30.0: Relay.GAIN_X30,
    }


def test_decodes_the_power_on_snapshot():
    """A blank EEPROM yields low-Z, 1 kOhm, unity gain, bias and comp off."""
    readback = decode_coils(POWER_ON_COILS)

    assert readback.channel is RfChannel.LOW_Z
    assert readback.feedback_resistor_ohm == 1_000.0
    assert readback.boost_gain == 1.0
    assert readback.dc_bias_enabled is False
    assert readback.input_compensation_enabled is False
    assert readback.booster_source_coil is True
    assert readback.bias_compensation_source is BiasCompensationSource.MANUAL


def test_engaged_relays_lists_only_the_engaged_ones():
    """The power-on snapshot engages relay 12 and nothing else."""
    assert engaged_relays(POWER_ON_COILS) == (Relay.RF_LOW_1K,)
    assert engaged_relays(_snapshot(Relay.BIAS_ENABLE, Relay.GAIN_X3)) == (
        Relay.BIAS_ENABLE,
        Relay.GAIN_X3,
    )


def test_idle_rf_relays_leave_the_resistor_unknown():
    """No engaged Rf relay names no resistor, even with the channel known."""
    readback = decode_coils(_snapshot())

    assert readback.channel is RfChannel.LOW_Z
    assert readback.feedback_resistor_ohm is None


def test_two_rf_relays_in_one_bank_leave_the_resistor_unknown():
    """Two closed resistors in a bank have no defined result."""
    readback = decode_coils(_snapshot(Relay.RF_LOW_1M, Relay.RF_LOW_100K))

    assert readback.feedback_resistor_ohm is None


def test_an_rf_relay_of_the_other_bank_leaves_the_resistor_unknown():
    """A high-Z resistor cannot be the feedback of the selected low-Z channel."""
    readback = decode_coils(_snapshot(Relay.RF_HIGH_10M))

    assert readback.channel is RfChannel.LOW_Z
    assert readback.feedback_resistor_ohm is None


def test_two_gain_relays_leave_the_gain_unknown():
    """The gain coding is one-hot, so two stages have no defined gain."""
    readback = decode_coils(_snapshot(Relay.GAIN_X3, Relay.GAIN_X10))

    assert readback.boost_gain is None


def test_disagreeing_channel_relays_leave_the_channel_unknown():
    """Relays 1 and 2 always carry the same coil value on a real device."""
    coils = _snapshot(Relay.CHANNEL_SELECT)
    readback = decode_coils(coils)

    assert coils[0] != coils[1]
    assert readback.channel is None
    assert readback.feedback_resistor_ohm is None


def test_decodes_the_one_kilohm_resistor_from_its_inverted_coil():
    """Relay 12 engages the 1 kOhm resistor at coil value ``True``."""
    coils = _snapshot(Relay.RF_LOW_1K)

    assert coils[coil_index(Relay.RF_LOW_1K)] is True
    assert decode_coils(coils).feedback_resistor_ohm == 1_000.0


def test_decodes_a_high_z_resistor_of_the_selected_channel():
    """Engaging relays 1 and 2 selects high-Z, which relay 6 then serves."""
    readback = decode_coils(
        _snapshot(
            Relay.CHANNEL_SELECT,
            Relay.DESELECTED_FEEDBACK,
            Relay.RF_HIGH_1G,
        )
    )

    assert readback.channel is RfChannel.HIGH_Z
    assert readback.feedback_resistor_ohm == 1_000_000_000.0


def test_decodes_a_single_gain_relay():
    """One engaged gain relay yields its gain."""
    assert decode_coils(_snapshot(Relay.GAIN_X10)).boost_gain == 10.0


def test_decodes_bias_compensation_and_the_dac_source():
    """Relays 4, 17 and 13 drive the three enable-and-source functions."""
    readback = decode_coils(
        _snapshot(
            Relay.BIAS_ENABLE,
            Relay.COMPENSATION_ENABLE,
            Relay.BIAS_COMP_SOURCE,
        )
    )

    assert readback.dc_bias_enabled is True
    assert readback.input_compensation_enabled is True
    assert readback.bias_compensation_source is BiasCompensationSource.DAC


def test_booster_source_is_the_raw_relay_three_coil():
    """The readback reports the level, not a feature flag, for relay 3."""
    assert decode_coils(_snapshot()).booster_source_coil is True
    assert decode_coils(_snapshot(Relay.BOOST_SOURCE)).booster_source_coil is False


def test_a_short_snapshot_is_padded_and_never_raises():
    """A snapshot shorter than seventeen coils decodes as the reset state."""
    assert decode_coils(()) == decode_coils(POWER_ON_COILS)
