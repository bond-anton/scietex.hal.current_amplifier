"""Static relay-to-function map for the EBIC v1.0 preamp board.

A Modbus coil value is the raw GPIO level of its relay, not a feature flag: every
relay except relay 12 engages its function at coil value ``False``, and relay 12
engages at ``True``. This module owns that polarity, the ``Rf`` and booster-gain
tables, and the pure decode from a coil snapshot to the function state it
encodes. It touches no bus, so a caller can name relays and decode readbacks
without a device.

The map transcribes ``docs/relay-function-map.md``, which in turn transcribes the
``ebic_control`` firmware.

Classes:
    Relay: The seventeen relay outputs, numbered 1-17.
    RfChannel: The two input-path channels relays 1 and 2 select.
    BiasCompensationSource: The source relay 13 selects.
    RelayReadback: The function state a coil snapshot encodes.

Constants:
    RF_OHMS: The eight feedback resistors in ohm, ascending.
    RF_RELAY: Feedback resistor to the relay that connects it.
    RF_CHANNEL: ``Rf`` relay to the channel it belongs to.
    GAIN_RELAY: Booster gain to the relay that selects it.
    CHANNEL_COILS: Channel to the coil value that selects it.
    BOOSTER_COILS: Channel to the relay-3 coil that feeds it to the booster.
    POWER_ON_COILS: The coil snapshot of the power-on and blank-EEPROM state.

Functions:
    coil_index: The coil index a relay addresses.
    coil_level: The coil value for a desired feature state.
    relay_engaged: The feature state a coil value encodes.
    engaged_relays: The relays a coil snapshot holds engaged.
    decode_coils: Decode a coil snapshot into a :class:`RelayReadback`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum


class Relay(IntEnum):
    """The seventeen relay outputs, numbered as the board's tester numbers.

    The member value is the one-based relay number; the firmware derives the
    coil index from it without a lookup table.
    """

    CHANNEL_SELECT = 1
    DESELECTED_FEEDBACK = 2
    BOOST_SOURCE = 3
    BIAS_ENABLE = 4
    RF_HIGH_10G = 5
    RF_HIGH_1G = 6
    RF_HIGH_100M = 7
    RF_HIGH_10M = 8
    RF_LOW_1M = 9
    RF_LOW_100K = 10
    RF_LOW_10K = 11
    RF_LOW_1K = 12
    BIAS_COMP_SOURCE = 13
    GAIN_X3 = 14
    GAIN_X10 = 15
    GAIN_X30 = 16
    COMPENSATION_ENABLE = 17


class RfChannel(str, Enum):
    """The two input-path channels relays 1 and 2 select.

    The member value is the spelling a driver reports; it doubles as the
    serialised form because the class inherits from ``str``.
    """

    LOW_Z = "low_z"
    HIGH_Z = "high_z"


class BiasCompensationSource(str, Enum):
    """The source relay 13 selects for bias and compensation together."""

    DAC = "dac"
    MANUAL = "manual"


RF_OHMS: tuple[float, ...] = (
    1_000.0,
    10_000.0,
    100_000.0,
    1_000_000.0,
    10_000_000.0,
    100_000_000.0,
    1_000_000_000.0,
    10_000_000_000.0,
)
"""Feedback resistors in ohm, ascending: the low-Z bank then the high-Z bank."""

RF_RELAY: dict[int, Relay] = {
    1_000: Relay.RF_LOW_1K,
    10_000: Relay.RF_LOW_10K,
    100_000: Relay.RF_LOW_100K,
    1_000_000: Relay.RF_LOW_1M,
    10_000_000: Relay.RF_HIGH_10M,
    100_000_000: Relay.RF_HIGH_100M,
    1_000_000_000: Relay.RF_HIGH_1G,
    10_000_000_000: Relay.RF_HIGH_10G,
}
"""Map a feedback resistor in ohm to the relay that connects it."""

RF_CHANNEL: dict[Relay, RfChannel] = {
    Relay.RF_HIGH_10G: RfChannel.HIGH_Z,
    Relay.RF_HIGH_1G: RfChannel.HIGH_Z,
    Relay.RF_HIGH_100M: RfChannel.HIGH_Z,
    Relay.RF_HIGH_10M: RfChannel.HIGH_Z,
    Relay.RF_LOW_1M: RfChannel.LOW_Z,
    Relay.RF_LOW_100K: RfChannel.LOW_Z,
    Relay.RF_LOW_10K: RfChannel.LOW_Z,
    Relay.RF_LOW_1K: RfChannel.LOW_Z,
}
"""Map each feedback-relay bank to the channel it serves."""

GAIN_RELAY: dict[float, Relay | None] = {
    1.0: None,
    3.0: Relay.GAIN_X3,
    10.0: Relay.GAIN_X10,
    30.0: Relay.GAIN_X30,
}
"""Map a booster gain to the relay that selects it; unity has no relay."""

CHANNEL_COILS: dict[RfChannel, bool] = {
    RfChannel.LOW_Z: True,
    RfChannel.HIGH_Z: False,
}
"""Map a channel to the coil value relays 1 and 2 carry when it is selected."""

BOOSTER_COILS: dict[RfChannel, bool] = {
    RfChannel.LOW_Z: True,
    RfChannel.HIGH_Z: False,
}
"""Map a channel to the relay-3 coil that routes its stage-1 output to the booster.

Firmware commit ``b83e474`` fixes which booster input each level closes: coil
``True`` selects ``OUT2``, the low-Z output, and coil ``False`` selects
``OUT1``, the high-Z output. The level therefore matches ``CHANNEL_COILS`` for
every channel, so the power-on state already feeds the selected low-Z channel
to the booster.
"""

POWER_ON_COILS: tuple[bool, ...] = (True,) * 17
"""Coil values of the power-on and blank-EEPROM state; relay 12 alone engages."""

_OHM_BY_RELAY: dict[Relay, float] = {
    relay: float(ohm) for ohm, relay in RF_RELAY.items()
}
"""Map a feedback relay to its resistor, keeping the ``float`` ohm domain."""

_GAIN_BY_RELAY: dict[Relay, float] = {
    relay: gain for gain, relay in GAIN_RELAY.items() if relay is not None
}
"""Map a gain relay to its gain, the inverse of ``GAIN_RELAY`` without unity."""

_INVERTED_RELAYS: frozenset[Relay] = frozenset({Relay.RF_LOW_1K})
"""Relays that engage at coil value ``True``; relay 12 alone connects at GPIO 1."""


def coil_index(relay: Relay) -> int:
    """
    Return the coil index that addresses ``relay``.

    Args:
        relay: The relay output, numbered 1-17.

    Returns:
        int: The zero-based coil index, equal to ``relay - 1``.
    """
    return int(relay) - 1


def coil_level(relay: Relay, engaged: bool) -> bool:
    """
    Return the coil value that drives ``relay`` to the wanted feature state.

    Args:
        relay: The relay output to drive.
        engaged: Whether the relay's function should be engaged.

    Returns:
        bool: The raw GPIO level to write. Every relay except relay 12 engages at
        ``False``, so for those the level is the negation of ``engaged``.
    """
    if relay in _INVERTED_RELAYS:
        return engaged
    return not engaged


def relay_engaged(relay: Relay, level: bool) -> bool:
    """
    Return whether coil value ``level`` engages ``relay``'s function.

    Args:
        relay: The relay output the level is read for.
        level: The raw GPIO level, as reported by the coil or the mirror.

    Returns:
        bool: The feature state, the inverse of :func:`coil_level`.
    """
    if relay in _INVERTED_RELAYS:
        return level
    return not level


def engaged_relays(coils: Sequence[bool]) -> tuple[Relay, ...]:
    """
    Return the relays a coil snapshot holds engaged, in relay order.

    Args:
        coils: Coil values in relay order, index 0 = relay 1. A sequence shorter
            than seventeen is padded with the power-on level.

    Returns:
        tuple[Relay, ...]: The engaged relays; empty when every function is idle.
    """
    levels = _levels(coils)
    return tuple(
        relay for relay in Relay if relay_engaged(relay, levels[coil_index(relay)])
    )


@dataclass(frozen=True, slots=True)
class RelayReadback:
    """The function state a coil snapshot encodes.

    Every field carries the state of one function, and a field whose encoding is
    ambiguous carries ``None`` instead of guessing.

    Attributes:
        channel: The selected input-path channel, or ``None`` when relays 1 and
            2 disagree, which the firmware never writes on purpose.
        feedback_resistor_ohm: The selected ``Rf`` in ohm, or ``None`` unless the
            ``Rf`` relays name exactly one resistor and that resistor belongs to
            the selected channel.
        boost_gain: The dimensionless booster gain. ``1.0`` when no gain relay is
            engaged, the selected gain when exactly one is, and ``None`` when two
            or more are, since the one-hot coding leaves that state undefined.
        dc_bias_enabled: Whether DC bias injection is on (relay 4).
        input_compensation_enabled: Whether input-capacitance compensation is on
            (relay 17).
        booster_source_coil: The raw coil value of relay 3, which feeds ``OUT1``
            to the booster at ``False`` and ``OUT2`` at ``True``.
        bias_compensation_source: The source relay 13 selects for bias and
            compensation together.
    """

    channel: RfChannel | None
    feedback_resistor_ohm: float | None
    boost_gain: float | None
    dc_bias_enabled: bool
    input_compensation_enabled: bool
    booster_source_coil: bool
    bias_compensation_source: BiasCompensationSource


def decode_coils(coils: Sequence[bool]) -> RelayReadback:
    """
    Decode a coil snapshot into the function state it represents.

    The decode is total: every snapshot yields a readback, and a combination the
    board does not define yields ``None`` for the field it leaves undefined
    rather than an error.

    Args:
        coils: Coil values in relay order, index 0 = relay 1. A sequence shorter
            than seventeen is padded with the power-on level.

    Returns:
        RelayReadback: The decoded function state.
    """
    levels = _levels(coils)
    channel = _decode_channel(levels)
    return RelayReadback(
        channel=channel,
        feedback_resistor_ohm=_decode_feedback_resistor(levels, channel),
        boost_gain=_decode_boost_gain(levels),
        dc_bias_enabled=relay_engaged(
            Relay.BIAS_ENABLE, levels[coil_index(Relay.BIAS_ENABLE)]
        ),
        input_compensation_enabled=relay_engaged(
            Relay.COMPENSATION_ENABLE, levels[coil_index(Relay.COMPENSATION_ENABLE)]
        ),
        booster_source_coil=levels[coil_index(Relay.BOOST_SOURCE)],
        bias_compensation_source=(
            BiasCompensationSource.MANUAL
            if levels[coil_index(Relay.BIAS_COMP_SOURCE)]
            else BiasCompensationSource.DAC
        ),
    )


def _levels(coils: Sequence[bool]) -> tuple[bool, ...]:
    """Pad a snapshot to seventeen values with the power-on level.

    The firmware mirrors seventeen coils, so a shorter sequence cannot be a
    complete snapshot; its missing coils take the reset level instead of making
    the decode raise.
    """
    levels = tuple(coils)[: len(Relay)]
    return levels + (True,) * (len(Relay) - len(levels))


def _decode_channel(levels: tuple[bool, ...]) -> RfChannel | None:
    """Return the channel relays 1 and 2 agree on, or ``None`` when they differ."""
    select = levels[coil_index(Relay.CHANNEL_SELECT)]
    if select != levels[coil_index(Relay.DESELECTED_FEEDBACK)]:
        return None
    if select == CHANNEL_COILS[RfChannel.LOW_Z]:
        return RfChannel.LOW_Z
    return RfChannel.HIGH_Z


def _decode_feedback_resistor(
    levels: tuple[bool, ...], channel: RfChannel | None
) -> float | None:
    """Return the single selected ``Rf`` of the selected channel, else ``None``."""
    if channel is None:
        return None
    engaged = [
        relay for relay in RF_CHANNEL if relay_engaged(relay, levels[coil_index(relay)])
    ]
    if len(engaged) != 1:
        return None
    relay = engaged[0]
    if RF_CHANNEL[relay] is not channel:
        return None
    return _OHM_BY_RELAY[relay]


def _decode_boost_gain(levels: tuple[bool, ...]) -> float | None:
    """Return the one-hot booster gain, ``1.0`` for none and ``None`` for two."""
    engaged = [
        relay
        for relay in _GAIN_BY_RELAY
        if relay_engaged(relay, levels[coil_index(relay)])
    ]
    if not engaged:
        return 1.0
    if len(engaged) > 1:
        return None
    return _GAIN_BY_RELAY[engaged[0]]
