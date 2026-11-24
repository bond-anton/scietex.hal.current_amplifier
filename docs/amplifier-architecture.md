# EBIC v1.0 preamp: analog architecture

Reference for the analog signal chain of the `EBIC_Preamp` v1.0 board and the
consequences it has for the semantic amplifier layer
(`EBICModbusV1Amplifier`) that sits on top of the relay driver in
`scietex.ebic.modbus.v1`.

## 1. Scope

**In scope.** The two-stage signal chain, the relay-controlled elements that
configure it, the bias and compensation injection points, the signal equations,
the clipping limits and the resulting full-scale input current, the relay budget,
what the digital interface can and cannot reach, and the mapping of the analog
architecture onto the HAL capability contract in
`scietex.hal.current_amplifier.base.capabilities`.

**Out of scope.** The Modbus register map and transport behaviour — see
[../README.md](../README.md) and the driver package under
`src/scietex/hal/current_amplifier/scietex/ebic/modbus/v1/`. The per-relay
function, coil index and GPIO pin of all 17 relays are documented in
[relay-function-map.md](relay-function-map.md); this document uses the relay
numbers from that map and discusses the analog architecture behind them.

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
       2 relays    | STAGE 1     |-------->| STAGE 2        |-------> OUT
 Iin ------------> | pre-amp TIA | /-5 V   | booster        | /-10 V
                   | (+) <--Vbias|  clip   | G = 1/3/10/30  |  clip
                   +------+------+         | (ref)<--Vbias  |
                          | Rf bank        |        + Vcomp |
                   +------+-------+        +----------------+
                   | Low-Z 1k-1M   | 4 rly        ^
                   | High-Z 10M-10G| 4 rly        |
                   +---------------+         Vcomp (external)
                                          [COMP ENABLE, 1 relay]
```

The diagram draws the selected path only. The unselected channel is kept in a
defined state by relay 2, which closes its feedback, and relay 3 selects which of
the two stage-1 outputs reaches the booster.

Relay-controlled elements in the diagram, counted:

| Element | Relays |
| --- | --- |
| Channel select (relays 1–2) | 2 |
| Booster source (`OUT1`/`OUT2`, relay 3) | 1 |
| `Rf`, high-Z bank (relays 5–8) | 4 |
| `Rf`, low-Z bank (relays 9–12) | 4 |
| Gain select (one relay per non-unity gain) | 3 |
| Bias enable | 1 |
| Compensation enable | 1 |
| Bias/compensation source select | 1 |
| **Total** | **17** |

All 17 relay outputs are accounted for by this description; see §8 for the relay
budget and [relay-function-map.md](relay-function-map.md) for the per-relay
functions.

## 3. Stage 1 - pre-amplifier

A transimpedance stage, current to voltage, driven from a single BNC input.

- Relay 1 selects the active input path: the low-Z channel or the high-Z channel.
  Relay 2 closes the feedback of the deselected channel, so the unused stage stays
  in a defined state; the two relays always carry the same coil value.
- Each channel owns **four** feedback resistors `Rf`, each with its own dedicated
  relay. Eight in total, in relay order: relays 5–8 are the high-Z bank
  (10 GΩ, 1 GΩ, 100 MΩ, 10 MΩ) and relays 9–12 the low-Z bank (1 MΩ, 100 kΩ,
  10 kΩ, 1 kΩ). The relays are independent; there is no binary encoding among
  them.
- The stage is rated for a maximum output of **+/-5 V**. At that level the
  **Overcurrent** signal goes active (high = active). The signal is generated on
  the board but never reaches a register; see §9.
- Bias voltage, when enabled, is applied to the non-inverting (`+`) input of the
  pre-amplifier.

Whether closing two `Rf` relays in the same channel in parallel is intended
(summed conductance, parallel resistance) or undefined is a bench question. The
driver takes the strict reading: every write leaves exactly one `Rf` per bank
engaged, and a readback naming zero or several resistors of the active channel
decodes to `None`. See §11.

## 4. Stage 2 - booster

An instrumentation amplifier providing dimensionless voltage gain after the
pre-amp.

- Discrete gains **1, 3, 10, 30**, selected by three relays (14–16); ×1 is the
  absence of all three.
- The bias and compensation voltages are **summed** on the booster's second
  (reference) input and **subtracted** from the pre-amplifier signal.
- Powered from **+/-12 V**; the output is linear over **+/-10 V**.

Whether the gain relays are break-before-make, and therefore whether a gain change
glitches the output, is not stated by the source. The driver does not rely on it:
it sequences a gain change break-before-make, releasing the old stage before
engaging the new one. The physical glitch on the bench is still unmeasured
(§11).

## 5. Bias and compensation

Both are applied from external analog voltages, but the board is not limited to a
manual path: relay 13 selects DAC or manual as the source for bias and
compensation together, so a DAC path exists. There is still **no level control**
over Modbus for either: the board can enable or disable each (relays 4 and 17)
and select the source (relay 13), nothing more. What drives the DAC path, and
whether it is reachable over Modbus, is an open item (§11).

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

Full-scale input current per resistor, computed by `I = min(5, 10/G) / Rf`
with the `Rf` values from the relay map.

| Channel | Relay | `Rf` [Ω] | `I_fullscale(1)` [A] | `I_fullscale(3)` [A] | `I_fullscale(10)` [A] | `I_fullscale(30)` [A] |
| --- | --- | --- | --- | --- | --- | --- |
| low-Z | 9 | 1 MΩ (1 000 000) | 5.00e-6 | 3.33e-6 | 1.00e-6 | 3.33e-7 |
| low-Z | 10 | 100 kΩ (100 000) | 5.00e-5 | 3.33e-5 | 1.00e-5 | 3.33e-6 |
| low-Z | 11 | 10 kΩ (10 000) | 5.00e-4 | 3.33e-4 | 1.00e-4 | 3.33e-5 |
| low-Z | 12 | 1 kΩ (1 000) | 5.00e-3 | 3.33e-3 | 1.00e-3 | 3.33e-4 |
| high-Z | 5 | 10 GΩ (10 000 000 000) | 5.00e-10 | 3.33e-10 | 1.00e-10 | 3.33e-11 |
| high-Z | 6 | 1 GΩ (1 000 000 000) | 5.00e-9 | 3.33e-9 | 1.00e-9 | 3.33e-10 |
| high-Z | 7 | 100 MΩ (100 000 000) | 5.00e-8 | 3.33e-8 | 1.00e-8 | 3.33e-9 |
| high-Z | 8 | 10 MΩ (10 000 000) | 5.00e-7 | 3.33e-7 | 1.00e-7 | 3.33e-8 |

## 8. Relay budget

| Function | Relays |
| --- | --- |
| Channel selection (relays 1–2) | 2 |
| Booster source (relay 3) | 1 |
| Bias enable (relay 4) | 1 |
| `Rf`, low-Z and high-Z (relays 5–12) | 8 |
| Gain select (relays 14–16) | 3 |
| Compensation enable (relay 17) | 1 |
| Bias/compensation source select (relay 13) | 1 |
| **Total** | **17** |

All 17 relay outputs are accounted for. The per-relay function table, with coil
index and GPIO pin, is in [relay-function-map.md](relay-function-map.md).

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
| Bias/compensation source (DAC vs manual) | yes (relay 13) | yes - coil writable; the DAC level is not |
| Enable states (bias, compensation, relays) | yes | yes - coils 0-16, readable by FC01, writable by FC05/FC0F |
| Bandwidth / filtering | fixed by design | no - not adjustable, not reportable |
| Invert | absent | absent |
| Voltage / current measurements | absent | absent |

The Overcurrent comparator output exists physically and is **not reportable over
Modbus**; it matters only if the board brings it out to a connector a gateway
could read (open item, §11).

Bias and compensation can come from a manual source or from a DAC path, selected
together by relay 13, so a DAC path exists. What drives it and whether it is
reachable over Modbus is an open item (§11). The *level* of either is still not
settable over Modbus.

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
| `boost.gain` | `SelectableCapabilities(access=Access(read=True, write=True), options=(1.0, 3.0, 10.0, 30.0))` | Readable and writable through the gain relays; ×1 is all gain relays off. Implemented by `EBICModbusV1Amplifier` |
| `boost.default_gain` | `1.0` | Unit gain at power-on |
| `preamp.feedback_resistor` | `SelectableCapabilities` over `(1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0, 100_000_000.0, 1_000_000_000.0, 10_000_000_000.0)` | The single selectable pre-amp control; low-Z {1 kΩ … 1 MΩ}, high-Z {10 MΩ … 10 GΩ}. Implemented by `EBICModbusV1Amplifier`; a change within a bank or across banks is break-before-make |
| `preamp.max_output_v` | `5.0` | Static geometry: pre-amp clip point, where Overcurrent trips |
| `preamp.range` | no longer a contract member | Derived: `min(preamp.max_output_v, amplifier_swing / G) / Rf` |
| `input_overcurrent` | `IndicationCapabilities(present=True, read=False)` | Comparator exists on the board, unreachable over Modbus (§9) |
| `output_overload` | `IndicationCapabilities()` | No detector: clipping is a rail behaviour, not a flag (§9) |
| `bandwidth` | `BandwidthCapabilities()` (falsy) | Fixed by the analog design, value unknown, not selectable, not reportable |
| `dc_bias.enabled` | `Access(read=True, write=True)` | Bias enable relay 4; readable and writable |
| `dc_bias.level` | `Access()` (both `False`) | Absent: external voltage, no readback, no level control |
| `input_compensation.enabled` | `Access(read=True, write=True)` | Compensation enable relay 17 |
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

The channel designator is deliberately not a contract member. The low-Z and
high-Z channels are a grouping of `feedback_resistor.options`, and a flat
`SelectableCapabilities` cannot express the 2×4 cross product; choosing an `Rf`
already determines the channel, so the grouping lives in the relay map rather
than in the contract.

`AmplifierState.preamp_range` is gone for the same reason: the range is derived
from `feedback_resistor_ohm`, `boost_gain` and the clip limits, and it is not
readable on this board anyway.

### State snapshot and derived quantities

The raw `EBICModbusV1Preamp` returns an `AmplifierState` with every field `None`
and an empty filter tuple. By the contract's own definition (`base/data.py`),
`None` means "this driver cannot report the field" — not zero, not off — so this
snapshot is correct for a board with no ADC and no status register.

The semantic `EBICModbusV1Amplifier` decodes the coil readback into that same
snapshot: it fills `feedback_resistor_ohm`, `boost_gain`, `dc_bias_enabled` and
`input_compensation_enabled`, and leaves every measured quantity `None` and the
filter tuple empty. A coil pattern that does not name exactly one resistor of the
active channel, or whose gain relays are not one-hot, yields `None` for that
field; the strict getter raises `UnexpectedResponse` rather than guessing.

### Chosen driver defaults (D1, D3)

- **D1 — booster source.** The firmware states OUT1 is the high-Z output and OUT2
  the low-Z output (commit `b83e474`). The driver always routes the selected
  channel's output to the booster: `relaymap.BOOSTER_COILS` maps low-Z to
  relay-3 coil 1 (OUT2) and high-Z to coil 0 (OUT1), and `select_feedback_resistor`
  writes it on every channel change. Relay 3 is independent in hardware; the
  non-contract `set_booster_source(out2)` overrides the tracking.
- **D3 — break-before-make.** Gain changes and in-bank `Rf` changes release the
  old stage before engaging the new one, so the driver never presents two gain
  stages or two same-bank `Rf` relays at once. Cross-bank `Rf` changes keep a
  feedback path engaged throughout.

The derived helpers remain computable from the capability set alone once the `Rf`
values are known: `total_transconductance(feedback_resistor_ohm, boost_gain)`,
`max_output_swing_v()` (returns `10.0` from `min_v`/`max_v`), and
`max_input_current_a(feedback_resistor_ohm, boost_gain)`, which returns
`min(5, 10/G) / Rf`. They take the resistor and gain as arguments, so they do not
depend on a populated snapshot; `max_input_current_a` returns `None` when the
pre-amp ceiling is unknown as well as when the amplifier swing is unknown.

## 11. Open items

### Resolved (firmware / policy)

- [x] OUT1/OUT2 ↔ channel correspondence: firmware commit `b83e474` states OUT1
      is the high-Z output and OUT2 the low-Z output (§8).
- [x] Booster source tracking: relay 3 is independent in hardware, but the driver
      always routes the selected channel's output to the booster via
      `relaymap.BOOSTER_COILS`; `set_booster_source(out2)` overrides it (§8).
- [x] Gain break-before-make: the driver sequences gain and in-bank `Rf` changes
      break-before-make, so it needs no guarantee from the relays (§4).

### Still open in hardware

- [ ] Pre-amp sign convention: inverting or non-inverting, confirmed on the bench
      (§6).
- [ ] What drives the DAC path (relay 13) and whether it is reachable over Modbus
      (§9).
- [ ] Behaviour when two `Rf` relays in one channel are closed simultaneously:
      parallel resistors (summed conductance) or undefined; the driver forbids it,
      but the physical intent is unresolved (§3).
- [ ] Output glitch actually produced by a gain change on the bench (§4).
- [ ] Whether the Overcurrent signal is brought out to a connector a gateway could
      read (§9).
