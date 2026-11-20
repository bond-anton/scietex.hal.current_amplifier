# scietex.hal.current_amplifier

A Python library for current amplifiers: devices that convert a photodiode or
ion-collector current into a voltage through a transimpedance preamp, an optional
boost stage, DC bias injection, filtering and input-capacitance compensation.

The package is split in two layers. The capability model and the driver contract
in `scietex.hal.current_amplifier.base` are complete and usable now: they describe
what an amplifier can do, what it currently reads, and the asynchronous methods a
driver implements. The vendor-neutral Modbus driver in
`scietex.hal.current_amplifier.generic.modbus` is a skeleton: its structure, error
handling and capability mapping are in place, but the device's register map has
not been transcribed, so every register access raises `RegisterMapIncomplete`
before any bus traffic starts. The driver is therefore not advertised through the
`scietex.hal.current_amplifier.drivers` entry-point group either.

## Status

| Layer | State |
| --- | --- |
| Capability model (`base.capabilities`) | Complete |
| State snapshot (`base.data`) | Complete |
| Driver contract (`base.protocol`) | Complete |
| Driver registry (`registry`) | Complete, no driver advertised yet |
| Generic Modbus driver (`generic.modbus`) | Skeleton: register map missing |

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

`amplifier` is a driver instance. The repository ships no working hardware
driver yet, so the object is supplied by the application, by a subclass that
implements the optional methods, or by a test double.

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
  has no address or function code in `DEVICE_MAP`. The message names the register
  and the file to fill in.
- `UnexpectedResponse` (an `OSError`) means a response cannot belong to the
  register it answers, such as a wrong register count.
- `ValueError` comes from `total_transconductance` and `max_input_current_a` for a
  non-positive feedback resistor, and from `resolve_driver` for an unknown driver
  name; the message lists the available names.

## The Modbus driver

`GenericModbusCurrentAmplifier` is a `scietex.hal.serial.RS485Client` subclass, so
the shared client opens the port once per operation and `connect()` has nothing to
open. Its capability set is empty and `DEVICE_MAP`, `STATUS_BITS` and
`FILTER_TYPE_CODES` in `scietex/hal/current_amplifier/generic/modbus/registers.py`
carry no device data yet.

```python
from scietex.hal.current_amplifier.generic.modbus import (
    GenericModbusCurrentAmplifier,
    RegisterMapIncomplete,
)
from scietex.hal.serial import ModbusSerialConnectionConfig

serial_config = ModbusSerialConnectionConfig(port="/dev/ttyUSB0", framer="RTU")
amp = GenericModbusCurrentAmplifier(serial_config, address=1)

try:
    await amp.read_data()
except RegisterMapIncomplete as error:
    print(error)
```

`read_data()` resolves its three mandatory registers before the first read, so an
unmapped device fails without partial traffic. Transcribing the register map —
and filling in the capability set that the map implies — is the change that makes
the driver operate.

Because the driver has no entry point, `registry.discover_drivers()` returns an
empty mapping and `registry.resolve_driver("...")` raises `ValueError`. Until the
device is identified the driver is reachable by direct import only.

## Testing

```bash
pytest tests -q
```

The suite drives in-memory amplifiers and asserts that the Modbus skeleton keeps
the port closed; it needs no hardware and never opens a serial port.

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
