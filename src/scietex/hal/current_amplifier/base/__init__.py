"""
Base current amplifier subpackage.

Holds the transport-agnostic pieces every driver shares: the capability model
that advertises what an amplifier can do, the state snapshot it reports, and the
driver contract concrete protocols implement.

Classes:
    Access: Whether a setting can be read and whether it can be written.
    AmplifierState: A snapshot of the values an amplifier reports.
    BandwidthCapabilities: A bandwidth domain and whether it is selectable.
    BiasCompensationSource: The source a device selects for DC bias and input
        compensation.
    BoostCapabilities: Boost stage gain selection.
    CompensationCapabilities: Input-capacitance compensation surface.
    CurrentAmplifierCapabilities: The complete capability set for one amplifier.
    CurrentAmplifierProtocol: The contract every current amplifier driver
        implements.
    DcBiasCapabilities: DC bias injection surface.
    FilterCapabilities: Signal-filter surface.
    FilterSetting: One filter in the amplifier's signal path.
    FilterType: The filter responses an amplifier can apply.
    IndicationCapabilities: A status signal and whether it is readable.
    OutputVoltageCapabilities: Static output voltage swing limits.
    PreampCapabilities: Preamp feedback-resistor selection and clip geometry.
    RegisterMapIncomplete: A register needed by the operation is not mapped.
    SelectableCapabilities: An access plus the values it accepts.
    UnexpectedResponse: A response cannot belong to the register it answers.

Modules:
    capabilities: Defines the capability model.
    data: Defines the state snapshot and the filter setting.
    errors: Defines the errors shared by drivers.
    protocol: Defines the `CurrentAmplifierProtocol` driver contract.
"""

from .capabilities import (
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
from .data import AmplifierState, FilterSetting
from .errors import RegisterMapIncomplete, UnexpectedResponse
from .protocol import CurrentAmplifierProtocol

__all__ = [
    "Access",
    "AmplifierState",
    "BandwidthCapabilities",
    "BiasCompensationSource",
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
    "RegisterMapIncomplete",
    "SelectableCapabilities",
    "UnexpectedResponse",
]
