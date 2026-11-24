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

Combined feedback resistors are explicitly out of scope for this driver. The
contract exposes exactly the eight discrete `Rf` values. At rest — after any
completed write and the driver's own verification read — the active channel has
exactly one engaged `Rf`; a readback naming zero or several resistors of the
active channel decodes to `feedback_resistor_ohm = None`. The four same-bank `Rf`
resistors share both terminals, so two closed same-bank relays form a genuine
parallel resistance `R1*R2/(R1+R2)`. The driver deliberately passes through that
state during a same-bank change (make-before-break, §4); it is electrically
defined but not a supported *selection* (§11).

## 4. Stage 2 - booster

An instrumentation amplifier providing dimensionless voltage gain after the
pre-amp.

- Discrete gains **1, 3, 10, 30**, selected by three relays (14–16); ×1 is the
  absence of all three.
- The bias and compensation voltages are **summed** on the booster's second
  (reference) input and **subtracted** from the pre-amplifier signal.
- Powered from **+/-12 V**; the output is linear over **+/-10 V**.

The two selectors use the same ordering policy, because both are parallel
networks. The four same-bank `Rf` resistors share both terminals, and the
booster's gain relays add parallel elements, so closing a gain relay alongside
another is an electrically defined state — a parallel gain — exactly as two
closed same-bank `Rf` relays form `R1*R2/(R1+R2)`. Both selectors are therefore
**make-before-break**: the driver engages the target relay first, then releases
the others, so the transconductance or feedback loop is never commanded open.

A same-bank `Rf` change engages the target relay first, then writes the channel
relays and relay 3, then releases the old `Rf`. The intermediate value is a small
step — 1 kΩ || 10 kΩ = 909 Ω, about 10 % — and remains linear. Cross-bank `Rf`
changes already kept a feedback path engaged and still do.

A gain change engages the target gain relay first, then releases the others.
`×1` is the all-relays-open state and the power-on default working gain, so it
has no engage step: it only releases whichever gain relay was engaged. Because
the booster always has a closed feedback path, a gain step's transient is the
parallel combination of the two gain elements together with the gain change
itself, but the loop is never commanded open.

**Write order is not relay timing.** The driver issues these writes back to back
with no settle delay, so whether the new relay actually closes before the old
one opens depends on the two relays' operate and release times. The ordering
removes the deliberate break; it does not prove the physical overlap.
Guaranteeing the overlap would need a delay sized from measured relay timing.

## 5. Bias and compensation

Both are applied from external analog voltages. Relay 13 selects, for bias and
compensation together, between an external DAC and a manual source. The DAC is an
external device the MCU never drives: the firmware instantiates only `USART1`,
enables no ADC/DAC/I2C/SPI peripheral, and rejects Modbus writes to every holding
register beyond the two communication settings. The board boots with relay 13
selecting the manual source (`DEFAULT_RELAY_LEVEL 1U`, `globals.h:78`). There is
**no level control** over Modbus for either signal: the board can enable or
disable each (relays 4 and 17) and select the source (relay 13), nothing more, so
`dc_bias.level` and `compensation.level` remain permanently unsupported for this
board and firmware (§9, §11).

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

Stage 1 is an inverting transimpedance amplifier; stage 2 is an inverting booster
whose reference input sums bias and compensation. With the active channel's
feedback resistor `Rf_ch`, the pre-amp output is

```
Vpre = -Rf_ch * Iin + Vbias
```

The booster's reference input is `Vref = Vbias + Vcomp`, and it amplifies the
difference between that reference and its inverting input:

```
Vout = G * (Vref - Vpre)
```

Substituting `Vpre` and `Vref`:

```
Vout = G * ((Vbias + Vcomp) - (-Rf_ch * Iin + Vbias))
     = G * (Rf_ch * Iin + Vcomp)
```

The two inversions cancel: the pre-amp inverts `Iin` and the booster inverts
again, so the overall stage is non-inverting with respect to `Iin`. `Vbias`
appears in both stages with opposite sign and cancels. Compensation enters `Vout`
with a `+`, so it nulls a negative input current:

```
Iin = -Vcomp / Rf_ch
```

**Sign convention (confirmed).** The pre-amp is inverting and the booster is
inverting with bias and compensation summed on its reference, so the overall
output is non-inverting with respect to `Iin`; `Vbias` cancels. This is fixed by
the board design, not assumed, and is recorded in §11.

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
| Overcurrent (pre-amp `+/-5 V`) | signal may exist (comparator) | no - no ADC, no discrete-input function code, no input pin |
| Output overload / clipping | yes (analog behaviour) | no - no measurement path |
| Bias level | external voltage | no - no readback, no level control |
| Compensation level | external voltage | no - no readback, no level control |
| Bias/compensation source (DAC vs manual) | yes (relay 13) | yes - coil writable; the DAC level is not |
| Enable states (bias, compensation, relays) | yes | yes - coils 0-16, readable by FC01, writable by FC05/FC0F |
| Bandwidth / filtering | fixed by design | no - not adjustable, not reportable |
| Invert | absent | absent |
| Voltage / current measurements | absent | absent |

The Overcurrent comparator output may exist physically, but this firmware could
not report it even if it does: there is no ADC, no discrete-input object (the
implemented function codes are `0x01, 0x03, 0x04, 0x05, 0x06, 0x0F, 0x10`, with
no `0x02`), and every pin is a relay output, SWD, or USART, with no MCU input
allocated to the signal. `IndicationCapabilities(present=True, read=False)` is
final. Whether the signal reaches a connector is hardware-documentation only and
cannot affect the driver contract (§11).

Bias and compensation come from a manual source or from an external DAC, selected
together by relay 13. The MCU never drives the DAC — only `USART1` is
instantiated, and Modbus writes beyond the two communication settings are
rejected — so the DAC level is not settable or readable over Modbus, and the
`*.level` members stay permanently unsupported (§11).

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
| `boost.gain` | `SelectableCapabilities(access=Access(read=True, write=True), options=(1.0, 3.0, 10.0, 30.0))` | Readable and writable through the gain relays; ×1 is all gain relays off. A gain change is make-before-break, and ×1 has no engage step (it releases only). Implemented by `EBICModbusV1Amplifier` |
| `boost.default_gain` | `1.0` | Unit gain at power-on |
| `preamp.feedback_resistor` | `SelectableCapabilities` over `(1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0, 100_000_000.0, 1_000_000_000.0, 10_000_000_000.0)` | The single selectable pre-amp control; low-Z {1 kΩ … 1 MΩ}, high-Z {10 MΩ … 10 GΩ}. Implemented by `EBICModbusV1Amplifier`; a same-bank change is make-before-break and a cross-bank change keeps a feedback path engaged |
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
field; the strict getter raises `UnexpectedResponse` rather than guessing. A
readback taken during a same-bank `Rf` transition is likewise ambiguous — two
resistors are engaged — and decodes to `None`; the driver's own verification read
happens after the transition completes.

### Chosen driver defaults (D1, D3)

- **D1 — booster source.** The firmware states OUT1 is the high-Z output and OUT2
  the low-Z output (commit `b83e474`). The driver always routes the selected
  channel's output to the booster: `relaymap.BOOSTER_COILS` maps low-Z to
  relay-3 coil 1 (OUT2) and high-Z to coil 0 (OUT1), and `select_feedback_resistor`
  writes it on every channel change. Relay 3 is independent in hardware; the
  non-contract `set_booster_source(out2)` overrides the tracking.
- **D3 — both selectors make-before-break.** `Rf` and gain are parallel networks,
  so both changes engage the target relay before releasing the others. A same-bank
  `Rf` change forms a defined parallel resistance (`R1*R2/(R1+R2)`) and cross-bank
  changes keep a feedback path engaged; a gain change forms a parallel gain, and
  ×1 has no engage step because it is the all-relays-open state — it releases the
  engaged relay only. The loop is never commanded open; the ordering is not a
  timing guarantee (no settle delay, §4).

The derived helpers remain computable from the capability set alone once the `Rf`
values are known: `total_transconductance(feedback_resistor_ohm, boost_gain)`,
`max_output_swing_v()` (returns `10.0` from `min_v`/`max_v`), and
`max_input_current_a(feedback_resistor_ohm, boost_gain)`, which returns
`min(5, 10/G) / Rf`. They take the resistor and gain as arguments, so they do not
depend on a populated snapshot; `max_input_current_a` returns `None` when the
pre-amp ceiling is unknown as well as when the amplifier swing is unknown.

## 11. Resolved questions

### Resolved (firmware / policy)

- [x] OUT1/OUT2 ↔ channel correspondence: firmware commit `b83e474` states OUT1
      is the high-Z output and OUT2 the low-Z output (§8).
- [x] Booster source tracking: relay 3 is independent in hardware, but the driver
      always routes the selected channel's output to the booster via
      `relaymap.BOOSTER_COILS`; `set_booster_source(out2)` overrides it (§8).
- [x] Gain and `Rf` make-before-break: both selectors drive parallel networks
      (the gain relays add parallel elements; same-bank `Rf` resistors share both
      terminals), so the driver engages the target relay before releasing the
      others and the loop is never commanded open. A gain change engages the target
      gain relay first and releases the rest; ×1 has no engage step and only
      releases the engaged relay, since it is the all-relays-open state (§4).

### Resolved (firmware evidence)

- [x] DAC path (relay 13): the DAC is an external device the MCU never drives.
      The firmware enables no ADC/DAC/I2C/SPI peripheral and instantiates only
      `USART1`; Modbus rejects writes beyond the two communication settings; the
      EEPROM map holds only slave address, baud index and serial number. Relay 13
      therefore selects between an external DAC and a manual source and boots on
      the manual source (`DEFAULT_RELAY_LEVEL 1U`). `dc_bias.level` and
      `compensation.level` are permanently unsupported, not "not yet
      implemented"; the driver never writes relay 13 implicitly (§5, §9).
- [x] Overcurrent: unobservable through this firmware. There is no ADC, no
      discrete-input function code, and no MCU pin allocated to the signal, so
      `IndicationCapabilities(present=True, read=False)` is final. Whether it
      reaches a connector is hardware-documentation only and cannot affect the
      driver contract (§9).

### Resolved (board design)

- [x] Sign convention: the pre-amp is inverting and the booster is inverting with
      bias and compensation summed on its reference, so the two inversions cancel
      and the overall stage is non-inverting with respect to `Iin`; `Vbias`
      cancels. The derivation is in §6.

### Settled by policy

- [x] Parallel `Rf`: combined feedback resistors are not a supported *selection*.
      The contract exposes the eight discrete values and, at rest, the active
      channel has exactly one engaged `Rf`; a doubly-engaged bank decodes to
      `None`. A same-bank change nonetheless passes through a parallel pair,
      because the resistors share both terminals and make-before-break keeps the
      loop closed (§4). That transient state is electrically defined
      (`R1*R2/(R1+R2)`) but is never a target selection (§3).
- [x] Gain-change transient: resolved by make-before-break. The driver no longer
      commands the booster's feedback path open, so the rail-slam / overload-recovery
      transient is not deliberately produced. A gain step still produces a
      transient — the intermediate value is the parallel gain and the gain itself
      changes — but the loop stays closed. The mitigation is ordering-based, not
      timing-guaranteed: the two writes carry no settle delay, so physical overlap
      depends on relay operate and release times (§4).
