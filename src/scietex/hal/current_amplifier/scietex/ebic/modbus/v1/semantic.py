"""Semantic current-amplifier layer over the EBIC v1.0 relay driver.

The raw driver speaks coil indices; the firmware gives those coils no meaning.
This module owns the relay-to-function map and turns coil levels into the
current amplifier contract: feedback resistor, boost gain, DC bias, input
compensation and a state snapshot. Every write is validated before any bus
traffic. ``Rf`` changes are make-before-break: the target resistor engages
before the old one releases, so the write order never commands the pre-amp
feedback loop open and the transimpedance stage is not deliberately left to
saturate against its output clamp. No settle delay is inserted, so whether the
new relay actually closes before the old opens depends on the relay operate and
release times. Two ``Rf`` of one bank share both terminals, so the transient
parallel pair is electrically defined. Booster gain changes follow the same
engage-before-release order: the gain network is parallel too, so a transiently
closed pair is an electrically defined state and the booster's feedback path is
never commanded open. The readback still codes a gain one-hot, so a closed pair
decodes to an undefined gain until the old relay releases. The active channel
therefore always has at least one engaged ``Rf``: exactly one at rest,
transiently two during a same-bank swap, never zero.

The relay map records the firmware's relay-3 correspondence: ``OUT2`` is the
low-Z output and ``OUT1`` the high-Z output. The firmware calls relay 3
independent, so steering it is a driver policy rather than a hardware
constraint: every channel selection also routes the selected channel's stage-1
output to the booster, so the amplifier never boosts the unselected channel.
:meth:`EBICModbusV1Amplifier.set_booster_source` overrides that choice
explicitly.

The layer is a :class:`CurrentAmplifierProtocol` implementation. Its
capabilities declare the selectable controls the map now fixes; the raw driver
keeps declaring only static geometry because it exposes coils rather than
functions.

Classes:
    RelayAccess: The relay operations the semantic layer needs from a transport.
    RelayTransitionError: A relay could not be driven to the requested state.
    EBICModbusV1Amplifier: The EBIC v1.0 amplifier driver.
"""

import asyncio
import math
from collections.abc import Callable, Iterable
from logging import Logger
from typing import ClassVar, Protocol

from scietex.hal.serial import (
    ModbusSerialConnectionConfig,
    SerialConnectionConfig,
)

from .....base import (
    Access,
    AmplifierState,
    BoostCapabilities,
    CompensationCapabilities,
    CurrentAmplifierCapabilities,
    CurrentAmplifierProtocol,
    DcBiasCapabilities,
    IndicationCapabilities,
    OutputVoltageCapabilities,
    PreampCapabilities,
    SelectableCapabilities,
    UnexpectedResponse,
)
from .client import EBICModbusV1Preamp
from .constants import DEFAULT_SLAVE_ADDRESS
from .relaymap import (
    BOOSTER_COILS,
    CHANNEL_COILS,
    GAIN_RELAY,
    RF_CHANNEL,
    RF_OHMS,
    RF_RELAY,
    BiasCompensationSource,
    Relay,
    RelayReadback,
    coil_index,
    coil_level,
    decode_coils,
    engaged_relays,
)

_BOOST_GAINS: tuple[float, ...] = (1.0, 3.0, 10.0, 30.0)
"""The four booster gains, the domain of :meth:`EBICModbusV1Amplifier.set_boost_gain`."""


class RelayAccess(Protocol):
    """The relay transport the semantic layer drives.

    The raw :class:`EBICModbusV1Preamp` satisfies this structurally, and so does
    an in-memory fake. A relay level is a raw coil value, not a feature state:
    polarity belongs to the relay map, not to the transport.
    """

    async def connect(self) -> None:
        """Open the transport."""
        ...

    async def close(self) -> None:
        """Close the transport."""
        ...

    async def read_relays(self) -> tuple[bool, ...]:
        """Return all seventeen relay levels in coil order."""
        ...

    async def set_relay(self, index: int, state: bool) -> None:
        """Drive one relay to a raw coil level."""
        ...


class RelayTransitionError(RuntimeError):
    """Raised when a relay transition does not reach the requested state.

    Args:
        operation: The operation that was in flight, such as
            ``"select feedback resistor"``.
        failed_coil: The coil whose write raised, or ``None`` when every write
            succeeded but the readback disagreed with the target vector.
        target: The coil vector the operation was driving toward. When a write
            failed it includes the coils already written and the one that
            failed, not the steps that were never attempted.
        observed: The best-effort readback after a failed write, or the
            disagreeing readback after a successful sequence. ``None`` when the
            quiet readback itself failed.

    Attributes:
        operation (str): The operation that was in flight.
        failed_coil (int | None): The failing coil, or ``None`` for a post-write
            verification mismatch.
        target (tuple[bool, ...]): The intended coil vector.
        observed (tuple[bool, ...] | None): The readback, when one was obtained.
    """

    operation: str
    failed_coil: int | None
    target: tuple[bool, ...]
    observed: tuple[bool, ...] | None

    def __init__(
        self,
        operation: str,
        failed_coil: int | None,
        target: tuple[bool, ...],
        observed: tuple[bool, ...] | None,
    ) -> None:
        self.operation = operation
        self.failed_coil = failed_coil
        self.target = target
        self.observed = observed
        if failed_coil is None:
            detail = "post-write verification mismatch"
        else:
            detail = f"writing coil {failed_coil} failed"
        super().__init__(
            f"{operation}: {detail}; target={target!r}, observed={observed!r}"
        )


class EBICModbusV1Amplifier(CurrentAmplifierProtocol):
    """Current amplifier contract over the EBIC v1.0 relay board.

    The driver maps the eight feedback resistors, the four booster gains, the
    bias enable, the compensation enable and the two source selectors onto the
    relay map. It reports the four readable functions in
    :meth:`read_data`; every quantity the board cannot measure stays ``None``.

    Attributes:
        capabilities: The selectable controls the relay map fixes, plus the
            board's static output range and present-but-unreadable Overcurrent
            comparator.
        relays: The relay transport every operation is forwarded to.
    """

    capabilities: ClassVar[CurrentAmplifierCapabilities] = CurrentAmplifierCapabilities(
        preamp=PreampCapabilities(
            feedback_resistor=SelectableCapabilities(
                access=Access(read=True, write=True),
                options=RF_OHMS,
            ),
            max_output_v=5.0,
        ),
        boost=BoostCapabilities(
            gain=SelectableCapabilities(
                access=Access(read=True, write=True),
                options=_BOOST_GAINS,
            ),
            default_gain=1.0,
        ),
        output_voltage=OutputVoltageCapabilities(min_v=-10.0, max_v=10.0),
        dc_bias=DcBiasCapabilities(enabled=Access(read=True, write=True)),
        input_compensation=CompensationCapabilities(
            enabled=Access(read=True, write=True)
        ),
        input_overcurrent=IndicationCapabilities(present=True, read=False),
    )

    relays: RelayAccess
    _write_lock: asyncio.Lock

    # The signature mirrors the raw driver's four parameters and adds the
    # injected transport keyword-only, which is needed for a driver that can
    # run without a serial port.
    def __init__(
        self,
        con_params: SerialConnectionConfig | ModbusSerialConnectionConfig | None = None,
        address: int = DEFAULT_SLAVE_ADDRESS,
        label: str = "EBIC Preamp",
        logger: Logger | None = None,
        *,
        relay_driver: RelayAccess | None = None,
    ) -> None:
        """
        Initialize the amplifier.

        Args:
            con_params: Serial port and framing configuration. Ignored when
                ``relay_driver`` is given.
            address: Modbus slave address the raw driver answers at.
            label: Human-readable label used by the raw driver in log messages.
            logger: Optional logger for raw transport diagnostics.
            relay_driver: A relay transport to drive instead of opening a serial
                port. An in-memory fake uses this path.

        Raises:
            TypeError: If neither ``con_params`` nor ``relay_driver`` is given,
                since there is then no transport to drive.
        """
        if relay_driver is None:
            if con_params is None:
                raise TypeError("con_params or relay_driver is required")
            # The raw driver implements the relay layer and inherits the
            # contract's unimplemented stubs, so a type checker sees it as
            # abstract even though the stubs raise only when called. It is the
            # documented transport for this layer.
            relay_driver = EBICModbusV1Preamp(  # ty: ignore[abstract-class-instantiation]
                con_params=con_params,
                address=address,
                label=label,
                logger=logger,
            )
        self.relays = relay_driver
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open the relay transport."""
        await self.relays.connect()

    async def close(self) -> None:
        """Close the relay transport."""
        await self.relays.close()

    # -- state -------------------------------------------------------------

    async def read_data(self) -> AmplifierState:
        """
        Return the function state one coil readback encodes.

        The board reports no output voltage, current or status value, so every
        field beyond the four relay-backed functions stays ``None`` and the
        filter tuple stays empty. ``None`` is not zero and not ``False``: a
        quantity the board cannot measure is unknown, not idle.

        Returns:
            AmplifierState: The decoded snapshot. A readback whose ``Rf`` or
            gain coding is ambiguous yields ``None`` for that field instead of
            raising.
        """
        readback = await self._readback()
        return AmplifierState(
            boost_gain=readback.boost_gain,
            feedback_resistor_ohm=readback.feedback_resistor_ohm,
            dc_bias_enabled=readback.dc_bias_enabled,
            input_compensation_enabled=readback.input_compensation_enabled,
            filters=(),
        )

    async def get_feedback_resistor(self) -> float:
        """
        Read the selected feedback resistor.

        Returns:
            float: Resistance in ohm.

        Raises:
            UnexpectedResponse: If the readback does not name exactly one
                resistor of the selected channel.
        """
        state = await self.read_data()
        if state.feedback_resistor_ohm is None:
            raise UnexpectedResponse(
                "feedback resistor",
                "the relay readback selects no single resistor of the active channel",
            )
        return state.feedback_resistor_ohm

    async def get_boost_gain(self) -> float:
        """
        Read the booster gain.

        Returns:
            float: The dimensionless gain, ``1.0`` when no gain relay is engaged.

        Raises:
            UnexpectedResponse: If the gain coding is ambiguous.
        """
        state = await self.read_data()
        if state.boost_gain is None:
            raise UnexpectedResponse(
                "boost gain",
                "the gain relays are not one-hot, so the gain is undefined",
            )
        return state.boost_gain

    async def get_dc_bias(self) -> bool:
        """
        Read the DC bias injection state.

        Returns:
            bool: Whether bias injection is on.

        Raises:
            UnexpectedResponse: If the snapshot reports no bias state.
        """
        state = await self.read_data()
        if state.dc_bias_enabled is None:
            raise UnexpectedResponse("dc bias", "no bias state in the snapshot")
        return state.dc_bias_enabled

    async def get_input_compensation(self) -> bool:
        """
        Read the input-capacitance compensation state.

        Returns:
            bool: Whether compensation is on.

        Raises:
            UnexpectedResponse: If the snapshot reports no compensation state.
        """
        state = await self.read_data()
        if state.input_compensation_enabled is None:
            raise UnexpectedResponse(
                "input compensation", "no compensation state in the snapshot"
            )
        return state.input_compensation_enabled

    # -- contract writes ---------------------------------------------------

    async def select_feedback_resistor(self, resistance_ohm: float) -> None:
        """
        Select one feedback resistor.

        A change engages the target resistor before it releases the old one, so
        the active channel always keeps a feedback path. A cross-bank change
        also switches the channel relays and steers the booster source between
        the two ``Rf`` writes, so the amplifier follows the new channel while the
        transient parallel pair holds the loop closed.

        Args:
            resistance_ohm: One of ``RF_OHMS``, in ohm.

        Raises:
            ValueError: If the value is not a finite whole-numbered one of the
                eight resistors, before any bus traffic.
            RelayTransitionError: If a relay write or the post-write readback
                does not reach the target vector.
        """
        resistance = _feedback_resistance(resistance_ohm)

        def plan(current: tuple[bool, ...]) -> list[tuple[Relay, bool]]:
            return self._feedback_steps(resistance, current)

        await self._transition("select feedback resistor", plan)

    async def set_boost_gain(self, gain: float) -> None:
        """
        Set the booster gain.

        A change engages the target gain relay before it releases the old one.
        The gain network is parallel, so the transient pair is an electrically
        defined state and the booster's feedback path is never commanded open.
        Unity selects no relay, so moving to it only releases the engaged one.

        Args:
            gain: One of ``1.0``, ``3.0``, ``10.0`` or ``30.0``.

        Raises:
            ValueError: If the gain is not one the board selects, before any bus
                traffic.
            RelayTransitionError: If a relay write or the post-write readback
                does not reach the target vector.
        """
        if gain not in GAIN_RELAY:
            raise ValueError(
                f"unsupported boost gain {gain!r}; expected one of "
                f"{', '.join(str(value) for value in _BOOST_GAINS)}"
            )
        target = GAIN_RELAY[gain]

        def plan(_current: tuple[bool, ...]) -> list[tuple[Relay, bool]]:
            steps: list[tuple[Relay, bool]] = []
            if target is not None:
                steps.append((target, coil_level(target, True)))
            for relay in (Relay.GAIN_X3, Relay.GAIN_X10, Relay.GAIN_X30):
                if relay is not target:
                    steps.append((relay, coil_level(relay, False)))
            return steps

        await self._transition("set boost gain", plan)

    async def set_dc_bias(self, enabled: bool) -> None:
        """
        Switch DC bias injection on or off.

        Args:
            enabled: Whether to turn bias injection on.

        Raises:
            RelayTransitionError: If a relay write or the post-write readback
                does not reach the target vector.
        """

        def plan(_current: tuple[bool, ...]) -> list[tuple[Relay, bool]]:
            return [(Relay.BIAS_ENABLE, coil_level(Relay.BIAS_ENABLE, enabled))]

        await self._transition("set dc bias", plan)

    async def set_input_compensation(self, enabled: bool) -> None:
        """
        Switch input-capacitance compensation on or off.

        Args:
            enabled: Whether to turn compensation on.

        Raises:
            RelayTransitionError: If a relay write or the post-write readback
                does not reach the target vector.
        """

        def plan(_current: tuple[bool, ...]) -> list[tuple[Relay, bool]]:
            return [
                (
                    Relay.COMPENSATION_ENABLE,
                    coil_level(Relay.COMPENSATION_ENABLE, enabled),
                )
            ]

        await self._transition("set input compensation", plan)

    # -- non-contract extensions ------------------------------------------

    async def get_bias_compensation_source(self) -> BiasCompensationSource:
        """
        Read the source relay 13 selects for bias and compensation.

        This is not a ``CurrentAmplifierProtocol`` member: the capability model
        has no group for the shared source selector.

        Returns:
            BiasCompensationSource: ``DAC`` or ``MANUAL``.
        """
        return (await self._readback()).bias_compensation_source

    async def set_bias_compensation_source(
        self, source: BiasCompensationSource
    ) -> None:
        """
        Select the shared bias and compensation source.

        This is not a ``CurrentAmplifierProtocol`` member: the capability model
        has no group for the shared source selector. ``MANUAL`` is the power-on
        state, so writing it on a fresh board changes nothing.

        Args:
            source: The source to select.

        Raises:
            ValueError: If ``source`` names no known source.
            RelayTransitionError: If a relay write or the post-write readback
                does not reach the target vector.
        """
        selected = BiasCompensationSource(source)
        level = selected is BiasCompensationSource.MANUAL

        def plan(_current: tuple[bool, ...]) -> list[tuple[Relay, bool]]:
            return [(Relay.BIAS_COMP_SOURCE, level)]

        await self._transition("set bias compensation source", plan)

    async def get_booster_source(self) -> bool:
        """
        Read which preamp output feeds the booster.

        This is not a ``CurrentAmplifierProtocol`` member: the relay reports the
        selector's raw coil, not a contract quantity.

        Returns:
            bool: ``True`` when ``OUT2`` feeds the booster, ``False`` for
            ``OUT1``.
        """
        return (await self._readback()).booster_source_coil

    async def set_booster_source(self, out2: bool) -> None:
        """
        Select which preamp output feeds the booster.

        This is not a ``CurrentAmplifierProtocol`` member: the relay reports the
        selector's raw coil, not a contract quantity.

        Args:
            out2: ``True`` to feed ``OUT2`` to the booster, ``False`` for ``OUT1``.

        Raises:
            RelayTransitionError: If a relay write or the post-write readback
                does not reach the target vector.
        """

        def plan(_current: tuple[bool, ...]) -> list[tuple[Relay, bool]]:
            return [(Relay.BOOST_SOURCE, out2)]

        await self._transition("set booster source", plan)

    # -- transition engine -------------------------------------------------

    def _feedback_steps(
        self, resistance: int, current: tuple[bool, ...]
    ) -> list[tuple[Relay, bool]]:
        """Return the coil-level steps that select ``resistance`` from ``current``.

        The target relay is engaged before every other ``Rf`` relay is released,
        so a same-bank swap briefly closes the parallel pair and the feedback
        loop never opens. Only the eight ``Rf`` relays are considered for
        release. Deselecting every engaged relay would also switch off bias,
        gain, compensation and the channel selectors.
        """
        target_relay = RF_RELAY[resistance]
        target_channel = RF_CHANNEL[target_relay]

        rf_relays = set(RF_RELAY.values())
        engaged_rf = [relay for relay in engaged_relays(current) if relay in rf_relays]

        steps: list[tuple[Relay, bool]] = []
        if target_relay not in engaged_rf:
            steps.append((target_relay, coil_level(target_relay, True)))
        steps.append((Relay.CHANNEL_SELECT, CHANNEL_COILS[target_channel]))
        steps.append((Relay.DESELECTED_FEEDBACK, CHANNEL_COILS[target_channel]))
        steps.append((Relay.BOOST_SOURCE, BOOSTER_COILS[target_channel]))
        for relay in engaged_rf:
            if relay is not target_relay:
                steps.append((relay, coil_level(relay, False)))
        return steps

    async def _transition(
        self,
        operation: str,
        plan: Callable[[tuple[bool, ...]], Iterable[tuple[Relay, bool]]],
    ) -> None:
        """Read once, apply a coil-level plan, then verify the result.

        ``plan`` receives the readback the engine just took, so a plan that
        depends on the current state costs no second bus read. A failed write is
        not retried: the half-applied vector is read back and reported.

        Args:
            operation: The operation name carried by a
                :class:`RelayTransitionError`.
            plan: Builds the steps from the current coil vector. Each step is a
                relay and the raw coil level to drive it to.

        Raises:
            RelayTransitionError: If a write raises or the readback after a
                successful write disagrees with the target vector.
        """
        async with self._write_lock:
            current = list(await self.relays.read_relays())
            target = list(current)
            wrote = False
            for relay, level in plan(tuple(current)):
                coil = coil_index(relay)
                if target[coil] == level:
                    continue
                target[coil] = level
                try:
                    await self.relays.set_relay(coil, level)
                    wrote = True
                except Exception as exc:
                    raise RelayTransitionError(
                        operation,
                        coil,
                        tuple(target),
                        await self._read_quietly(),
                    ) from exc
            if wrote:
                observed = tuple(await self.relays.read_relays())
                if observed != tuple(target):
                    raise RelayTransitionError(operation, None, tuple(target), observed)

    async def _readback(self) -> RelayReadback:
        """Read the coils once and decode them."""
        return decode_coils(await self.relays.read_relays())

    async def _read_quietly(self) -> tuple[bool, ...] | None:
        """Read the coils after a failed write, swallowing a second failure."""
        try:
            return tuple(await self.relays.read_relays())
        except Exception:
            return None


def _feedback_resistance(resistance_ohm: float) -> int:
    """Validate a feedback resistance and return its integer ohm key.

    Raises:
        ValueError: If the value is not finite, is not a whole number of ohm, or
            names no resistor on the board.
    """
    if not math.isfinite(resistance_ohm):
        options = ", ".join(str(int(ohm)) for ohm in RF_OHMS)
        raise ValueError(
            f"feedback resistor must be finite, got {resistance_ohm!r}; "
            f"expected one of {options} ohm"
        )
    value = int(resistance_ohm)
    if value != resistance_ohm or value not in RF_RELAY:
        options = ", ".join(str(int(ohm)) for ohm in RF_OHMS)
        raise ValueError(
            f"unsupported feedback resistor {resistance_ohm!r} ohm; "
            f"expected one of {options} ohm"
        )
    return value
