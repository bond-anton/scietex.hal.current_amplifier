# EBIC v1.0 preamp: analog architecture

Reference for the analog signal chain of the `EBIC_Preamp` v1.0 board and the
consequences it has for the semantic amplifier layer that will sit on top of the
relay driver in `scietex.ebic.modbus.v1`.

## 1. Scope

**In scope.** The two-stage signal chain, the relay-controlled elements that
configure it, the bias and compensation injection points, the signal equations,
the clipping limits and the resulting full-scale input current, the relay budget,
what the digital interface can and cannot reach, and the mapping of the analog
architecture onto the HAL capability contract in
`scietex.hal.current_amplifier.base.capabilities`.

**Out of scope.** The relay-to-coil index map (produced separately by the
hardware owner; this document counts relays but never assigns an index). The
Modbus register map and transport behaviour — see [../README.md](../README.md)
and the driver package under
`src/scietex/hal/current_amplifier/scietex/ebic/modbus/v1/`. Resistor values are
unknown and appear as `TBD`.

## 2. Block diagram

Signal path, single BNC input, two stages. Elements marked `[relay]` are
relay-controlled. `clip` marks where a stage saturates.

```
                    Vbias (external, level not readable)
                     |                          |
             [BIAS ENABLE, 1 relay]            |
                     |                          |
                     v                          v
 BNC --[CH SEL]--> +-------------+  Vpre   +----------------+  Vout
       1 relay     | STAGE 1     |-------->| STAGE 2        |-------> OUT
 Iin ------------> | pre-amp TIA | /-5 V   | booster        | /-10 V
                   | (+) <--Vbias|  clip   | G = 1/3/10/30  |  clip
                   +------+------+         | (ref)<--Vbias  |
                          | Rf bank        |        + Vcomp |
                   +------+-------+        +----------------+
                   | Low  Rf_L1..L4| 4 rly        ^
                   | High Rf_H1..H4| 4 rly        |
                   +---------------+         Vcomp (external)
                                          [COMP ENABLE, 1 relay]
```

Relay-controlled elements in the diagram, counted:

| Element | Relays |
| --- | --- |
| Channel select | 1 |
| `Rf` low-current bank (`Rf_L1..L4`) | 4 |
| `Rf` high-current bank (`Rf_H1..H4`) | 4 |
| Gain select (one relay per discrete gain) | 4 |
| Bias enable | 1 |
| Compensation enable | 1 |
| **Total** | **15** |

The board exposes 17 relay outputs, so 2 are unaccounted for by this description;
see §8 and §11.

## 3. Stage 1 - pre-amplifier

A transimpedance stage, current to voltage, driven from a single BNC input.

- One relay selects the active input-current path: the low-input-current channel
  or the high-input-current channel.
- Each channel owns **four** feedback resistors `Rf`, and each `Rf` has its own
  dedicated relay. Eight `Rf` relays in total: four for the low-current channel
  (`Rf_L1..Rf_L4`), four for the high-current channel (`Rf_H1..Rf_H4`). The
  relays are independent; there is no binary encoding among them.
- The stage is rated for a maximum output of **+/-5 V**. At that level the
  **Overcurrent** signal goes active (high = active). The signal is generated on
  the board but never reaches a register; see §9.
- Bias voltage, when enabled, is applied to the non-inverting (`+`) input of the
  pre-amplifier.

Whether closing two `Rf` relays in the same channel in parallel is intended
(summed conductance, parallel resistance) or undefined is a bench question; the
model assumes exactly one `Rf` relay per active channel is closed. See §11.

## 4. Stage 2 - booster

An instrumentation amplifier providing dimensionless voltage gain after the
pre-amp.

- Discrete gains **1, 3, 10, 30**, selected by relays.
- The bias and compensation voltages are **summed** on the booster's second
  (reference) input and **subtracted** from the pre-amplifier signal.
- Powered from **+/-12 V**; the output is linear over **+/-10 V**.

Whether the gain relays are break-before-make, and therefore whether a gain change
glitches the output, is not stated; see §11.

## 5. Bias and compensation

Both are applied from external analog voltages. This board has **no internal
generation and no level control** for either; it can only connect or disconnect
each through its enable relay.

| Signal | Enable relay | Reaches pre-amp `+` | Reaches booster ref | Effect |
| --- | --- | --- | --- | --- |
| Bias (`Vbias`) | 1 | yes | yes | Sets the pre-amp DC operating point and cancels at the output |
| Compensation (`Vcomp`) | 1 | no | yes | Nulls DC input current at the output |

The asymmetry is deliberate. Bias enters the pre-amp `+` input, so it shifts the
pre-amp operating point; because the same `Vbias` is also summed into the booster
reference, it cancels at the amplifier output. Compensation reaches only the
booster reference, so it removes a DC error at the output without moving the
pre-amp.

Compensation is required at high gain because a small DC input current produces
an output offset that is multiplied by `G`. At `G = 30` an uncorrected offset
that is harmless at unity gain pushes the output past the +/-10 V linear range;
`Vcomp` nulls it.

## 6. Signal equations

Pre-amp output, with the active channel's feedback resistor `Rf_ch`:

```
Vpre = +/- Rf_ch * Iin + Vbias
```

Booster output, subtracting bias and compensation on its reference input:

```
Vout = G * (Vpre - Vbias - Vcomp)
     = G * (+/- Rf_ch * Iin - Vcomp)
```

Bias cancels between the two stages. Compensation nulls the input current at the
output when

```
Iin = +/- Vcomp / Rf_ch
```

**Sign convention.** The leading `+/-` depends on whether the pre-amp is wired
inverting or non-inverting, which the description does not state. The magnitudes
above are independent of that choice; the polarity of the output relative to
`Iin` is not. This is an open item (§11) until confirmed on the bench.

## 7. Limits and full-scale current

Two clipping conditions bound the input current:

- **Pre-amp clip:** `|Vpre| <= 5 V`, so `|Iin| <= 5 / Rf_ch` (bias ignored, as
  it cancels and is set only to establish the operating point).
- **Booster clip:** `|Vout| <= 10 V`, and `Vout ~= G * Rf_ch * Iin`, so
  `|Iin| <= (10 / G) / Rf_ch` (compensation assumed nulled).

Together:

```
I_fullscale(G) = min(5, 10/G) / Rf_ch
```

| Gain `G` | `10/G` [V] | `min(5, 10/G)` [V] | Binding limit |
| --- | --- | --- | --- |
| 1 | 10.0 | 5.0 | Pre-amp (and therefore Overcurrent) |
| 3 | 3.33 | 3.33 | Booster |
| 10 | 1.0 | 1.0 | Booster |
| 30 | 0.33 | 0.33 | Booster |

The pre-amp is the binding limit only at `G = 1`; at `G = 3, 10, 30` the booster
output clips first.

Full-scale input current per resistor. Values `TBD` until the `Rf` resistors are
known; fill by `I = min(5, 10/G) / Rf`.

| Symbol | `Rf` [ohm] | `I_fullscale(1)` [A] | `I_fullscale(3)` [A] | `I_fullscale(10)` [A] | `I_fullscale(30)` [A] |
| --- | --- | --- | --- | --- | --- |
| `Rf_L1` | TBD | TBD | TBD | TBD | TBD |
| `Rf_L2` | TBD | TBD | TBD | TBD | TBD |
| `Rf_L3` | TBD | TBD | TBD | TBD | TBD |
| `Rf_L4` | TBD | TBD | TBD | TBD | TBD |
| `Rf_H1` | TBD | TBD | TBD | TBD | TBD |
| `Rf_H2` | TBD | TBD | TBD | TBD | TBD |
| `Rf_H3` | TBD | TBD | TBD | TBD | TBD |
| `Rf_H4` | TBD | TBD | TBD | TBD | TBD |

## 8. Relay budget

| Function | Relays |
| --- | --- |
| Channel select | 1 |
| `Rf` low-current bank | 4 |
| `Rf` high-current bank | 4 |
| Gain select (four one-hot) | 4 |
| Bias enable | 1 |
| Compensation enable | 1 |
| **Used** | **15** |
| Available | 17 |
| **Unaccounted** | **2** |

Two relays are unaccounted for. If the gain selector were binary-coded instead of
one-hot, four gains need 2 relays and the total would be **13**, leaving four
unaccounted. The exact split is therefore a relay-map question, not a settled
fact; see §11.

## 9. What Modbus can and cannot reach

The firmware exposes coils, holding registers and read-only identity, and has no
input pins and no ADC: every GPIO is an output. A board signal that is not routed
to a coil or register cannot be observed over the bus.

| Quantity | Present on board | Reachable over Modbus |
| --- | --- | --- |
| Overcurrent (pre-amp `+/-5 V`) | yes (comparator output) | no - not connected to any register |
| Output overload / clipping | yes (analog behaviour) | no - no measurement path |
| Bias level | external voltage | no - no readback, no level control |
| Compensation level | external voltage | no - no readback, no level control |
| Enable states (bias, compensation, relays) | yes | yes - coils 0-16, readable by FC01, writable by FC05/FC0F |
| Bandwidth / filtering | fixed by design | no - not adjustable, not reportable |
| Invert | absent | absent |
| Voltage / current measurements | absent | absent |

The Overcurrent comparator output exists physically and is **not reportable over
Modbus**; it matters only if the board brings it out to a connector a gateway
could read (open item, §11).

## 10. Mapping to the HAL capability contract

Field and property names are those of
`src/scietex/hal/current_amplifier/base/capabilities.py`. `Access(read, write)`
is used for switches, `SelectableCapabilities[float]` for switches with a domain.
`BandwidthCapabilities` describes the bandwidth, which may be fixed rather than
selectable, and `IndicationCapabilities(present, read)` describes status flags,
since a signal can exist without being readable.

| Contract member | Mapping for this board | Notes |
| --- | --- | --- |
| `output_voltage.min_v` / `max_v` | `-10.0` / `+10.0` | Static geometry of the booster's linear range |
| `boost.gain` | `SelectableCapabilities(access=Access(read=True, write=True), options=(1.0, 3.0, 10.0, 30.0))` | Readable and writable through the gain relays |
| `boost.default_gain` | `1.0` | Unit gain at power-on |
| `preamp.feedback_resistor` | `SelectableCapabilities` over the eight `Rf` values, `TBD` | The single selectable pre-amp control; the channel is implied by the resistor |
| `preamp.max_output_v` | `5.0` | Static geometry: pre-amp clip point, where Overcurrent trips |
| `preamp.range` | no longer a contract member | Derived: `min(preamp.max_output_v, amplifier_swing / G) / Rf` |
| `input_overcurrent` | `IndicationCapabilities(present=True, read=False)` | Comparator exists on the board, unreachable over Modbus (§9) |
| `output_overload` | `IndicationCapabilities()` | No detector: clipping is a rail behaviour, not a flag (§9) |
| `bandwidth` | `BandwidthCapabilities()` (falsy) | Fixed by the analog design, value unknown, not selectable, not reportable |
| `dc_bias.enabled` | `Access(read=True, write=True)` | Bias enable relay; readable and writable |
| `dc_bias.level` | `Access()` (both `False`) | Absent: external voltage, no readback, no level control |
| `input_compensation.enabled` | `Access(read=True, write=True)` | Compensation enable relay |
| `input_compensation.level` | `Access()` (both `False`) | Absent: external voltage, no readback, no level control |
| `filters` | `FilterCapabilities()` | Absent: no filter relays, fixed filtering |
| `invert_output` | `Access()` (both `False`) | Absent: no invert relay |

### Derived input-current range

The input-current range is not a control: it follows from the selected feedback
resistor, the boost gain and the two clip points. With this board's 5 V pre-amp
ceiling and 10 V booster swing,

```
I_range = min(preamp.max_output_v, amp_swing_v / boost_gain) / Rf
```

which is the `min(5, 10/G) / Rf` rule of §7: the pre-amp binds at `G = 1` and the
booster at `G = 3, 10, 30` (see the binding table in §7).

The capability API exposes the same rule. `PreampCapabilities` carries
`input_current_range_a(rf, gain, swing)`, `preamp_limited_current_a(rf)` and
`output_ceiling_v(gain, swing)`. `CurrentAmplifierCapabilities.max_input_current_a(
rf, gain)` supplies the swing from `capabilities.output_voltage` and returns
`None` when either the pre-amp ceiling or the amplifier swing is unknown.

The channel designator is deliberately not a contract member. The low- and
high-current channels are a grouping of `feedback_resistor.options`, and a flat
`SelectableCapabilities` cannot express the 2x4 cross product; choosing an `Rf`
already determines the channel, so the grouping lives in the relay map rather
than in the contract.

`AmplifierState.preamp_range` is gone for the same reason: the range is derived
from `feedback_resistor_ohm`, `boost_gain` and the clip limits, and it is not
readable on this board anyway.

### Empty state snapshot and derived quantities

`read_data()` returns an `AmplifierState` with every field `None` and an empty
filter tuple. By the contract's own definition (`base/data.py`), `None` means
"this driver cannot report the field" — not zero, not off — so this snapshot is
correct for a board with no ADC and no status register.

The derived helpers remain computable from the capability set alone once the `Rf`
values are known: `total_transconductance(feedback_resistor_ohm, boost_gain)`,
`max_output_swing_v()` (returns `10.0` from `min_v`/`max_v`), and
`max_input_current_a(feedback_resistor_ohm, boost_gain)`, which returns
`min(5, 10/G) / Rf`. They take the resistor and gain as arguments, so they do not
depend on a populated snapshot; `max_input_current_a` returns `None` when the
pre-amp ceiling is unknown as well as when the amplifier swing is unknown.

## 11. Open items

- [ ] `Rf` values for `Rf_L1..L4` and `Rf_H1..H4` (referenced in §7, §10).
- [ ] Relay-to-coil index map for all 17 relays (out of scope here; §1, §8).
- [ ] Gain relay coding: four one-hot relays versus two binary relays (§8).
- [ ] Pre-amp sign convention: inverting or non-inverting, confirmed on the bench
      (§6).
- [ ] Behaviour when two `Rf` relays in one channel are closed simultaneously:
      parallel resistors (summed conductance) or undefined (§3).
- [ ] The two unaccounted relays and what they drive (§8).
- [ ] Whether the gain relays are break-before-make: output glitch during a gain
      change (§4).
- [ ] Whether the Overcurrent signal is brought out to a connector a gateway could
      read (§9).
