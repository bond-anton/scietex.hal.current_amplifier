"""In-memory amplifiers used by the test suite.

The fakes model the driver contract rather than hardware. A feature the
capability set does not advertise raises ``NotImplementedError`` from the
corresponding method, and a value the fake cannot report stays ``None`` in the
snapshot.
"""

from typing import ClassVar

from msgspec.structs import replace

try:
    from src.scietex.hal.current_amplifier.base import (
        Access,
        AmplifierState,
        BoostCapabilities,
        CompensationCapabilities,
        CurrentAmplifierCapabilities,
        CurrentAmplifierProtocol,
        DcBiasCapabilities,
        FilterCapabilities,
        FilterSetting,
        FilterType,
        IndicationCapabilities,
        OutputVoltageCapabilities,
        PreampCapabilities,
        SelectableCapabilities,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.base import (
        Access,
        AmplifierState,
        BoostCapabilities,
        CompensationCapabilities,
        CurrentAmplifierCapabilities,
        CurrentAmplifierProtocol,
        DcBiasCapabilities,
        FilterCapabilities,
        FilterSetting,
        FilterType,
        IndicationCapabilities,
        OutputVoltageCapabilities,
        PreampCapabilities,
        SelectableCapabilities,
    )


class FakeAmplifier(CurrentAmplifierProtocol):
    """In-memory driver that enforces its declared capability set."""

    capabilities: ClassVar[CurrentAmplifierCapabilities]

    def __init__(
        self,
        capabilities: CurrentAmplifierCapabilities,
        initial_state: AmplifierState,
    ) -> None:
        self.capabilities = capabilities
        self._state = initial_state
        self._connected = False

    async def connect(self) -> None:
        """Mark the fake transport as open."""
        self._connected = True

    async def close(self) -> None:
        """Mark the fake transport as closed."""
        self._connected = False

    async def read_data(self) -> AmplifierState:
        """Return the current snapshot, refusing to read while disconnected."""
        if not self._connected:
            raise RuntimeError("amplifier is not connected")
        return self._state

    @staticmethod
    def _require_read(access: Access, name: str) -> None:
        if not access.read:
            raise NotImplementedError(f"{name}() is unavailable: no read capability")

    @staticmethod
    def _require_write(access: Access, name: str) -> None:
        if not access.write:
            raise NotImplementedError(f"{name}() is unavailable: no write capability")

    def _filter_access(self) -> Access:
        filters = self.capabilities.filters
        return Access(
            read=filters.enabled.read or filters.cutoff.read,
            write=filters.enabled.write or filters.cutoff.write,
        )

    async def get_preamp_range(self) -> float:
        self._require_read(self.capabilities.preamp.range.access, "get_preamp_range")
        return self._state.preamp_range

    async def select_preamp_range(self, range_value: float) -> None:
        self._require_write(
            self.capabilities.preamp.range.access,
            "select_preamp_range",
        )
        self._state = replace(self._state, preamp_range=range_value)

    async def get_boost_gain(self) -> float:
        self._require_read(self.capabilities.boost.gain.access, "get_boost_gain")
        return self._state.boost_gain

    async def set_boost_gain(self, gain: float) -> None:
        self._require_write(self.capabilities.boost.gain.access, "set_boost_gain")
        self._state = replace(self._state, boost_gain=gain)

    async def get_feedback_resistor(self) -> float:
        self._require_read(
            self.capabilities.preamp.feedback_resistor.access,
            "get_feedback_resistor",
        )
        return self._state.feedback_resistor_ohm

    async def select_feedback_resistor(self, resistance_ohm: float) -> None:
        self._require_write(
            self.capabilities.preamp.feedback_resistor.access,
            "select_feedback_resistor",
        )
        self._state = replace(self._state, feedback_resistor_ohm=resistance_ohm)

    async def get_dc_bias(self) -> bool:
        self._require_read(self.capabilities.dc_bias.enabled, "get_dc_bias")
        return self._state.dc_bias_enabled

    async def set_dc_bias(self, enabled: bool) -> None:
        self._require_write(self.capabilities.dc_bias.enabled, "set_dc_bias")
        self._state = replace(self._state, dc_bias_enabled=enabled)

    async def get_dc_bias_level(self) -> float:
        self._require_read(self.capabilities.dc_bias.level, "get_dc_bias_level")
        return self._state.dc_bias_level

    async def set_dc_bias_level(self, level: float) -> None:
        self._require_write(self.capabilities.dc_bias.level, "set_dc_bias_level")
        self._state = replace(self._state, dc_bias_level=level)

    async def get_bandwidth(self) -> float:
        self._require_read(self.capabilities.bandwidth.access, "get_bandwidth")
        return self._state.bandwidth_hz

    async def set_bandwidth(self, bandwidth_hz: float) -> None:
        self._require_write(self.capabilities.bandwidth.access, "set_bandwidth")
        self._state = replace(self._state, bandwidth_hz=bandwidth_hz)

    async def get_filter(self, filter_type: FilterType) -> FilterSetting:
        self._require_read(self._filter_access(), "get_filter")
        for setting in self._state.filters:
            if setting.type == filter_type:
                return setting
        return FilterSetting(type=filter_type)

    async def set_filter(self, setting: FilterSetting) -> None:
        self._require_write(self._filter_access(), "set_filter")
        filters = self._state.filters
        if any(existing.type == setting.type for existing in filters):
            filters = tuple(
                setting if existing.type == setting.type else existing
                for existing in filters
            )
        else:
            filters = (*filters, setting)
        self._state = replace(self._state, filters=filters)

    async def get_input_compensation(self) -> bool:
        self._require_read(
            self.capabilities.input_compensation.enabled,
            "get_input_compensation",
        )
        return self._state.input_compensation_enabled

    async def set_input_compensation(self, enabled: bool) -> None:
        self._require_write(
            self.capabilities.input_compensation.enabled,
            "set_input_compensation",
        )
        self._state = replace(self._state, input_compensation_enabled=enabled)

    async def get_input_compensation_level(self) -> float:
        self._require_read(
            self.capabilities.input_compensation.level,
            "get_input_compensation_level",
        )
        return self._state.input_compensation_level

    async def set_input_compensation_level(self, level: float) -> None:
        self._require_write(
            self.capabilities.input_compensation.level,
            "set_input_compensation_level",
        )
        self._state = replace(self._state, input_compensation_level=level)

    async def get_inverted(self) -> bool:
        self._require_read(self.capabilities.invert_output, "get_inverted")
        return self._state.inverted

    async def set_inverted(self, inverted: bool) -> None:
        self._require_write(self.capabilities.invert_output, "set_inverted")
        self._state = replace(self._state, inverted=inverted)


def full_amplifier() -> FakeAmplifier:
    """An amplifier that advertises and reports every modelled feature."""
    read_write = Access(read=True, write=True)
    capabilities = CurrentAmplifierCapabilities(
        preamp=PreampCapabilities(
            range=SelectableCapabilities(
                access=read_write,
                options=(1.0, 2.0, 3.0),
            ),
            feedback_resistor=SelectableCapabilities(
                access=read_write,
                options=(1e4, 1e5, 1e6),
            ),
        ),
        boost=BoostCapabilities(
            gain=SelectableCapabilities(
                access=read_write,
                options=(1.0, 10.0, 100.0),
            ),
            default_gain=1.0,
        ),
        output_voltage=OutputVoltageCapabilities(min_v=-10.0, max_v=10.0),
        dc_bias=DcBiasCapabilities(enabled=read_write, level=read_write),
        bandwidth=SelectableCapabilities(
            access=read_write,
            options=(1e3, 1e4, 1e6),
        ),
        filters=FilterCapabilities(
            types=(FilterType.LOW_PASS, FilterType.HIGH_PASS),
            enabled=read_write,
            cutoff=read_write,
        ),
        input_overcurrent=IndicationCapabilities(read=True),
        output_overload=IndicationCapabilities(read=True),
        input_compensation=CompensationCapabilities(
            enabled=read_write,
            level=read_write,
        ),
        invert_output=read_write,
    )
    state = AmplifierState(
        output_voltage_v=1.25,
        output_current_a=2.5e-3,
        input_current_a=1.0e-6,
        preamp_range=2.0,
        boost_gain=10.0,
        feedback_resistor_ohm=1e4,
        dc_bias_enabled=True,
        dc_bias_level=0.25,
        bandwidth_hz=1e4,
        filters=(
            FilterSetting(type=FilterType.LOW_PASS, enabled=True, high_cutoff_hz=1e3),
        ),
        input_overcurrent=False,
        output_overload=False,
        input_compensation_enabled=True,
        input_compensation_level=0.5,
        inverted=False,
    )
    return FakeAmplifier(capabilities, state)


def read_only_bandwidth_amplifier() -> FakeAmplifier:
    """An amplifier whose only feature is a readable bandwidth."""
    capabilities = CurrentAmplifierCapabilities(
        bandwidth=SelectableCapabilities(
            access=Access(read=True),
            options=(1e3, 1e4),
        )
    )
    return FakeAmplifier(capabilities, AmplifierState(bandwidth_hz=1e4))


def minimal_amplifier() -> FakeAmplifier:
    """An amplifier with no advertised feature beyond the core contract."""
    return FakeAmplifier(CurrentAmplifierCapabilities(), AmplifierState())
