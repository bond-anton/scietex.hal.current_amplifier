"""
Base current amplifier subpackage.

Holds the transport-agnostic pieces every driver shares: the capability model
that advertises what an amplifier can do, the state snapshot it reports, and the
driver contract concrete protocols implement.

Classes:
    Access: Whether a setting can be read and whether it can be written.
    AmplifierState: A snapshot of the values an amplifier reports.
    BoostCapabilities: Boost stage gain selection.
    CompensationCapabilities: Input-capacitance compensation surface.
    CurrentAmplifierCapabilities: The complete capability set for one amplifier.
    CurrentAmplifierProtocol: The contract every current amplifier driver
        implements.
    DcBiasCapabilities: DC bias injection surface.
    FilterCapabilities: Signal-filter surface.
    FilterSetting: One filter in the amplifier's signal path.
    FilterType: The filter responses an amplifier can apply.
    IndicationCapabilities: A read-only status flag.
    OutputVoltageCapabilities: Static output voltage swing limits.
    PreampCapabilities: Preamp range and feedback-resistor selection.
    SelectableCapabilities: An access plus the values it accepts.

Modules:
    capabilities: Defines the capability model.
    data: Defines the state snapshot and the filter setting.
    protocol: Defines the `CurrentAmplifierProtocol` driver contract.
"""

from .capabilities import (
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
from .data import AmplifierState, FilterSetting
from .protocol import CurrentAmplifierProtocol

__all__ = [
    "Access",
    "AmplifierState",
    "BoostCapabilities",
    "CompensationCapabilities",
    "CurrentAmplifierCapabilities",
    "CurrentAmplifierProtocol",
    "DcBiasCapabilities",
    "FilterCapabilities",
    "FilterSetting",
    "FilterType",
    "IndicationCapabilities",
    "OutputVoltageCapabilities",
    "PreampCapabilities",
    "SelectableCapabilities",
]
