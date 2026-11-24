# scietex.hal.current_amplifier

A Python library for current amplifiers: devices that convert a photodiode or
ion-collector current into a voltage through a transimpedance preamp, an optional
boost stage, DC bias injection, filtering and input-capacitance compensation.

The package is split in two layers. The capability model and the driver contract
in `scietex.hal.current_amplifier.base` are complete and usable now: they describe
what an amplifier can do, what it currently reads, and the asynchronous methods a
driver implements. The first hardware driver talks to the EBIC v1.0 preamp over
Modbus RTU; it covers the device's relay outputs and communication settings,
which is what that firmware implements. Mapping those relays to preamp ranges,
boost, bias or filters needs the board's relay table and is not part of this
driver yet, so the driver advertises no amplifier capability and its state
snapshot is empty.

## Status

| Layer | State |
| --- | --- |
| Capability model (`base.capabilities`) | Complete |
| State snapshot (`base.data`) | Complete |
| Driver contract (`base.protocol`) | Complete |
| Driver registry (`registry`) | Complete, one driver advertised |
| EBIC v1.0 preamp (`scietex.ebic.modbus.v1`) | Complete: relay layer and communication settings |

## Install

```bash
pip install scietex.hal.current_amplifier
```

The package is not on PyPI yet; install from a clone in the meantime:

```bash
git clone https://github.com/bond-anton/scietex.hal.current_amplifier.git
cd scietex.hal.current_amplifier
pip install .
```

Requirements:

- Python 3.10 or higher.
- `msgspec` 0.20 for the state snapshot.
- `scietex.hal.serial` 2.5 or newer for the asynchronous RS485 transport.
- `pymodbus` 3.15 for the Modbus request types.

## Usage

Every driver satisfies `CurrentAmplifierProtocol`: `connect`, `close` and
`read_data` are mandatory coroutines, and every optional control method is a
coroutine too. The `supports_*` and `can_*` properties are synchronous and read
straight from `capabilities`, so a caller rejects an unsupported command before
dispatching it.

```python
import asyncio

from scietex.hal.current_amplifier.base import CurrentAmplifierProtocol


async def main(amp: CurrentAmplifierProtocol) -> None:
    """Read one snapshot and normalise the boost stage."""
    await amp.connect()
    try:
        state = await amp.read_data()
        print(state.output_voltage_v, state.output_current_a, state.input_current_a)

        if amp.can_set_boost:
            await amp.set_boost_gain(amp.capabilities.boost.default_gain)
    finally:
        await amp.close()


asyncio.run(main(amplifier))
```

`amplifier` is a driver instance. The EBIC v1.0 driver accepts commands through
its relay methods but reports no amplifier value, so `read_data()` returns an
empty snapshot; callers that need a populated snapshot must wait for the semantic
driver layer or supply their own driver.

Where an operation is advertised, the capability set answers whether it is
writable; where a value is available, the snapshot carries it. The two are
separate questions: a feature that exists but is switched off is truthy in
`capabilities` and `False` in the state.

```python
capabilities = amp.capabilities
limits = capabilities.output_voltage
print(limits.min_v, limits.max_v)  # static swing limits, or None while unknown

state = await amp.read_data()
if state.feedback_resistor_ohm is not None:
    boost_gain = state.boost_gain
    if boost_gain is None:
        boost_gain = capabilities.boost.default_gain

    transconductance = capabilities.total_transconductance(
        state.feedback_resistor_ohm, boost_gain
    )
    ceiling = capabilities.max_input_current_a(
        state.feedback_resistor_ohm, boost_gain
    )
    print(transconductance, ceiling)
```

`total_transconductance` returns `Rf * boost` in V/A and raises `ValueError` for a
zero or negative resistor. `max_input_current_a` divides the symmetric swing by
that transconductance: it returns `None` when either output limit is unknown and
`inf` when the transconductance is zero.

## Capabilities

`CurrentAmplifierCapabilities` groups the control surface by function, not by
method name, and every group defaults to "unsupported". A driver declares the
whole set as a class attribute, so it is known before the instance connects.

| Group | Capability fields | Snapshot fields | Support query | Write query |
| --- | --- | --- | --- | --- |
| Preamp | `preamp.range`, `preamp.feedback_resistor` | `preamp_range`, `feedback_resistor_ohm` | `supports_preamp` | `can_select_preamp` |
| Boost | `boost.gain`, `boost.default_gain` | `boost_gain` | `supports_boost` | `can_set_boost` |
| DC bias | `dc_bias.enabled`, `dc_bias.level` | `dc_bias_enabled`, `dc_bias_level` | `supports_dc_bias` | `can_set_dc_bias` |
| Bandwidth | `bandwidth` | `bandwidth_hz` | `supports_bandwidth` | `can_set_bandwidth` |
| Filters | `filters.types`, `filters.enabled`, `filters.cutoff` | `filters` | `supports_filters` | `can_set_filter` |
| Input overcurrent | `input_overcurrent.read` | `input_overcurrent` | `supports_input_overcurrent` | not writable |
| Output overload | `output_overload.read` | `output_overload` | `supports_output_overload` | not writable |
| Input compensation | `input_compensation.enabled`, `input_compensation.level` | `input_compensation_enabled`, `input_compensation_level` | `supports_input_compensation` | `can_set_input_compensation` |
| Output inversion | `invert_output` | `inverted` | `supports_invert_output` | `can_set_invert_output` |

The output voltage swing is static geometry rather than a controllable feature, so
it has no `supports_*` property: `capabilities.output_voltage` is read directly
and holds the `min_v` and `max_v` limits, while the voltage the device currently
reports is `state.output_voltage_v`.

The two status indications are read only through `read_data()`; there are no
dedicated accessors. `output_voltage_v`, `output_current_a` and `input_current_a`
are always present in the snapshot and are not gated by a capability.

Some rules the model enforces:

- `SelectableCapabilities.options` is in device-native units and in the device's
  own order. An empty tuple means the device does not enumerate the domain, which
  is typical of a continuous setting such as a boost gain or a cutoff frequency;
  it does not mean no value is accepted.
- `Access(read=..., write=...)` separates reading from writing, and
  `bool(access)` is true when either direction is supported.
- `preamp.range` is a designator the device chooses; `preamp.feedback_resistor`
  is a physical resistance in ohm. The two are independent and must not be
  converted into one another.
- `FilterType` covers `LOW_PASS`, `HIGH_PASS` and `BAND_PASS`; a filter entry is a
  `FilterSetting` with `enabled` and the cutoff corners in Hz that apply.
- `boost.default_gain` is the gain applied at power-on, which is unity for this
  device family. An unreported `state.boost_gain` is not unity: it is unknown.

## Errors

- `NotImplementedError` from an optional method means the driver does not
  implement that capability. Consult `capabilities` and take another path; do not
  treat it as a transport failure.
- A `None` field in `AmplifierState` means the driver cannot report that value.
  It is not `0.0` and not `False`, so a caller must not substitute either.
- `RegisterMapIncomplete` (a `RuntimeError`) means the register an operation needs
  has no map entry. The message names the register and the missing detail.
- `UnexpectedResponse` (an `OSError`) means a response cannot belong to the
  register it answers, such as a wrong register count.
- `ValueError` comes from `total_transconductance` and `max_input_current_a` for a
  non-positive feedback resistor, and from `resolve_driver` for an unknown driver
  name; the message lists the available names.

## EBIC v1.0 preamp

`EBICModbusV1Preamp` drives the `EBIC_Preamp` board (vendor `SCIETEX.RU`,
STM32F411) over Modbus RTU. The register map is transcribed from the firmware;
the device exposes seventeen relay outputs and the two settings that reach them,
and nothing else. There is no ADC, DAC, measurement, status or unlock register,
so the driver does not invent one.

| Item | Value |
| --- | --- |
| Identity | `SCIETEX.RU` / `EBIC_Preamp`, version 1.0.0, 32-bit serial number |
| Transport | Modbus RTU, 8N1, no flow control |
| Defaults | slave address 2, baud index 2 (19200 baud) |
| Holding registers | 0 = slave address, 1 = baud index, 10/11 = serial number (read only) |
| Input registers | 0-34 identity, 35 constant 7, 36-52 relay-level mirror |
| Coils | 0-16 relay levels |

`read_identity()`, `read_firmware_version()` and `read_serial_number()` read the
read-only input registers. The relay API is the working part of the driver:

```python
from scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
    EBICModbusV1Preamp,
)
from scietex.hal.serial import ModbusSerialConnectionConfig

serial_config = ModbusSerialConnectionConfig(port="/dev/ttyUSB0", framer="RTU")
amp = EBICModbusV1Preamp(serial_config)  # address 2, 19200 baud by default

await amp.connect()
try:
    levels = await amp.read_relays()   # FC01, coils 0-16
    await amp.set_relay(0, True)       # FC05, one coil
    await amp.set_relays([False] * 17) # FC0F, all coils
finally:
    await amp.close()
```

- `read_relays()` reads FC01 coils 0-16. The same levels are mirrored in input
  registers 36-52, but reaching that mirror needs a 53-register FC04 read, so
  coils are the narrower path. `read_relay(index)` reads a single coil.
- `set_relay(index, state)` writes FC05; `set_relays(states)` writes FC0F with
  exactly seventeen levels. FC0F is not atomic: the firmware applies and
  persists each level in turn, so a failure can leave a partial group. Re-read
  after an error instead of assuming a state.
- Every relay write is persisted to EEPROM. The interface is a state switch, not
  a PWM output, and frequent switching consumes flash write cycles. The level
  reaches the GPIO; the driver board may invert it at the relay contact.
- `get_slave_address()` / `set_slave_address()` and `get_baud_index()` /
  `set_baud_rate()` read and write holding registers 0 and 1. A write is
  acknowledged at the OLD address and baud rate, persisted to EEPROM, and
  followed by a firmware restart after about 500 ms. The device then answers
  only at the new setting, so construct a new instance after the restart. Writing
  the value already stored answers normally and causes no restart. `set_baud_rate`
  accepts only 9600, 14400, 19200, 38400, 57600 or 115200 and writes the index,
  never the rate.

The driver advertises no amplifier capability (`capabilities` is empty) and
`read_data()` returns an `AmplifierState` whose fields are all `None` with an
empty filter tuple. That is deliberate: the firmware reports no voltage,
current, range, gain, bias, bandwidth or status, and `None` is not zero. Preamp
ranges, boost, bias and filters become available only when the relay-to-function
map is documented and a semantic layer is built on top of this one.

The driver is advertised through the `scietex.hal.current_amplifier.drivers`
entry-point group as `ebic_modbus_v1_preamp`, so
`registry.discover_drivers()` returns it and `registry.resolve_driver()` loads
it by name.

## Testing

```bash
pytest tests -q
```

The suite exercises the capability model and drives the EBIC driver through a
stub transport that records requests and returns canned responses, so it checks
request construction and response validation without opening a serial port or
needing hardware.

Other checks:

```bash
tox -e format,lint,type
```

`format` and `lint` run `ruff`, `type` runs `ty` over `src`. Continuous
integration runs the same checks plus a distribution build; its test matrix
covers Python 3.10, 3.12 and 3.14.

## License

This project is licensed under the **MIT License** - see the LICENSE file for
details.
