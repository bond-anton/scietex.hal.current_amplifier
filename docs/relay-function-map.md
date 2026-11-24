# Relay function map

EBIC CONTROL preamp board

## Source

Transcribed from the firmware repository
`git.buro-nts.ru/a.kudryavtsev/ebic_control`, files `RELAY_FUNCTION_MAP.md` and
`README.md`. The map content comes from two commits:

- `e127278` ("fix relay map in globals.c") changed only the GPIO pin assignment
  of relays 9–17 in `Core/Src/globals.c` and `README.md`; the coil indices did
  not move, and the function table is unchanged since `c1bb7b0`.
- `b83e474` ("fix relay map in RELAY_FUNCTION_MAP.md") corrected the relay-3 row
  and prose, fixing the relay/firmware-output correspondence: OUT1 is the high-Z
  output and OUT2 the low-Z output.

The current HEAD is `94f5068`, which only removes the rendered PDF snapshot of the
map from the repository. This file is a transcription for driver use: the
firmware repository is authoritative.

## Coil polarity and power-on state

Every relay is de-energised when its GPIO is 1 and energised when its GPIO is 0.
The firmware powers up with GPIO = 1 on all 17 relays, so every relay starts
de-energised. The tables below describe the *function* state (ON = feature
engaged), not the coil state; in the GPIO = 1 column, ON/OFF is the power-on
function state. Relay 12 is the only relay whose resistor is connected at
GPIO = 1.

## Coil values are GPIO levels

`Relay_Apply()` writes `level ? GPIO_PIN_SET : GPIO_PIN_RESET`, so a Modbus coil
value is the raw GPIO level, not a feature-enable flag. Coil value 1 = GPIO high
= relay de-energised; coil value 0 = GPIO low = relay energised. Combined with
the function convention above (GPIO = 0 engages the function):

- Relays 1–11 and 13–17: the active state is coil value 0. For the enable and
  engagement functions (bias, compensation, `Rf`, gain) that means feature ON;
  for the selectors (relays 1–3 and 13) it means the GPIO = 0 column of the
  table. Coil value 1 is the idle, default state.
- Relay 12: feature ON (1 kΩ connected) = coil value 1. It is the only
  active-high function.

A driver API that takes a boolean "enable" must therefore invert for every relay
except relay 12. This is the most error-prone fact in the map. The input-register
mirror reports the same coil value, so a 1 read from register `36 + n` also means
the relay is de-energised, not that the feature is active. The driver encodes the
polarity in `relaymap.coil_level` / `relaymap.relay_engaged`, never in the coil
write path.

Writing coil value 1 to all 17 coils (the power-up state, and what the firmware
loads when the EEPROM is blank) yields: Low-Z channel, 1 kΩ `Rf`, gain ×1, bias
off, compensation off, manual source.

## Full map

| Relay | Coil | GPIO | Input reg | Section | Function | GPIO = 0 (energised) | GPIO = 1 (de-energised, power-on) | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | PA0 | 36 | §01 | input path select | High-Z | Low-Z | |
| 2 | 1 | PA1 | 37 | §01 | connects the amplifier's inverting input to the feedback of the *deselected* channel | low-Z feedback | high-Z feedback | Works in anti-phase with relay 1: with low-Z selected it closes the high-Z (deselected) feedback, and vice versa. Functional relationship only; both relays default to GPIO = 1. |
| 3 | 2 | PA2 | 38 | §01 | selects which amplifier output feeds the booster | OUT1 (High-Z) → booster | OUT2 (Low-Z) → booster | Independently selects the booster's source. OUT1 is the high-Z output, OUT2 the low-Z output (commit `b83e474`). |
| 4 | 3 | PA3 | 39 | §01 | bias enable | ON | OFF | |
| 5 | 4 | PA4 | 40 | §02 | 10 GΩ resistor | ON | OFF | |
| 6 | 5 | PA5 | 41 | §02 | 1 GΩ resistor | ON | OFF | |
| 7 | 6 | PA6 | 42 | §02 | 100 MΩ resistor | ON | OFF | |
| 8 | 7 | PA7 | 43 | §02 | 10 MΩ resistor | ON | OFF | |
| 9 | 8 | PB0 | 44 | §03 | 1 MΩ resistor | ON | OFF | |
| 10 | 9 | PB1 | 45 | §03 | 100 kΩ resistor | ON | OFF | |
| 11 | 10 | PB2 | 46 | §03 | 10 kΩ resistor | ON | OFF | |
| 12 | 11 | PA8 | 47 | §03 | 1 kΩ resistor | OFF | ON | Only inverted function: at GPIO = 1 relay 12 is de-energised yet the 1 kΩ resistor is connected. |
| 13 | 12 | PA9 | 48 | §05 | simultaneous source select for bias and compensation (DAC vs Manual) | DAC | Manual | Switches bias and compensation together: GPIO = 1 = manual (power-on default), GPIO = 0 = DAC. The DAC is an external device; the firmware never drives it and no Modbus write reaches it, so the level is not settable through the driver. |
| 14 | 13 | PA10 | 49 | §04 | 3 kΩ resistor; gain ×3 | ON | OFF | With relays 14–16 all off the booster gain is ×1; simultaneous closure of several stages is undefined in the source records. |
| 15 | 14 | PA11 | 50 | §04 | 665 Ω resistor; gain ×10 | ON | OFF | |
| 16 | 15 | PA12 | 51 | §04 | 205 Ω resistor; gain ×30 | ON | OFF | |
| 17 | 16 | PA15 | 52 | §05 | compensation enable | ON | OFF | |

### Coil map provenance

The relay-number → coil-index identity is taken directly from the firmware: coil
= relay − 1, and the firmware applies that index without a lookup table. The GPIO
pin is a separate, informational mapping; the driver never addresses pins.

- `README.md:25-34`: protocol addresses are zero-based and tester relay numbers
  are 1-based; coil = relay − 1. Pin grouping: relays 1–8 → coils 0–7 →
  `PA0–PA7`, relays 9–11 → coils 8–10 → `PB0–PB2`, relays 12–16 → coils 11–15 →
  `PA8–PA12`, relay 17 → coil 16 → `PA15`; input registers 36–52.
- `Core/Src/globals.c:18-27` `Relay_Apply()` derives the port and pin from the
  index: GPIOA `1<<index` for indices 0–7, GPIOB `1<<(index-8)` for indices 8–10,
  GPIOA `1<<(index-3)` for indices 11–15, and `GPIO_PIN_15` for index 16. There
  is no lookup table and no remap.
- `Core/Src/ModbusRTU_Slave.c:264-277` (FC05) and `:299-315` (FC0F) use the coil
  address directly as `g_relay_levels[index]` and pass it to `Relay_Apply()`.
- `Core/Src/ModbusRTU_Slave.c:48-53` mirrors coil `i` into input register
  `RELAY_INPUT_START + i` = `36 + i`; `Core/Inc/globals.h:81` defines
  `RELAY_INPUT_START 36`.

The pin grouping changed in `e127278`, which corrected relays 9–17 in
`globals.c`; the coil indices did not move. Boards on the older firmware keep the
previous pin map, which `README.md:94-98` addresses: it lists the old coil
sequence `0,1,2,3,4,5,6,7,14,15,16,8,9,10,11,12,13` that reproduces the prior
physical levels under the new numbering, and notes that `PA13`/`PA14` remain SWD.
Because the driver talks to coils 0–16 only, none of this reaches the interface.

The firmware source carries no functional naming for any relay: no enum, macro,
comment or pin label names the channel, gain, bias, compensation, source, `Rf`,
booster, `OUT1`/`OUT2`, DAC or Manual function. The Function column exists only
in `RELAY_FUNCTION_MAP.md`; the function meaning is documentation-only and is not
asserted by the firmware.

## Feedback resistors per channel

| Channel | `Rf` values | Relays |
| --- | --- | --- |
| high-Z channel | 10 GΩ, 1 GΩ, 100 MΩ, 10 MΩ | 5–8 |
| low-Z channel | 1 MΩ, 100 kΩ, 10 kΩ, 1 kΩ | 9–12 |

Exactly one resistor per channel is intended. Combined feedback resistors are out
of scope for this driver: the contract exposes the eight discrete `Rf` values and
the driver enforces exactly one engaged `Rf` per bank on every write. The
physical result of two closed same-bank relays is not needed because the
combination is unsupported by decision.

## Booster gain coding

Three relays, one-hot: relay 14 → ×3, relay 15 → ×10, relay 16 → ×30, and none
closed → ×1. The coding is one-hot, not binary; ×1 is the absence of all three.

## Derived driver invariants

These are derived from the table above. Items 4 and 5 combine a firmware
statement with the driver policy built on it.

1. Relays 1 and 2 always carry the **same coil value**. Both are 1 at power-on;
   selecting low-Z means relay 1 = 1 and relay 2 = 1 because relay 2 closes the
   high-Z (deselected) feedback. Channel selection is therefore one bit written
   to two coils.
2. Relay 12 is the only inverted function: coil de-energised (value 1) = 1 kΩ
   connected.
3. The power-on defaults therefore give the low-Z channel selected, the high-Z
   feedback closed, and 1 kΩ as the active `Rf` → default transimpedance 1 kΩ,
   the least sensitive setting.
4. The firmware states OUT1 is the high-Z output and OUT2 the low-Z output
   (commit `b83e474`). Relay 3 at its power-on default routes OUT2, the low-Z
   output, to the booster, which matches the low-Z channel that relays 1/2 select
   at power-on. The relay-3 coil value is 1 for the low-Z output (OUT2) and 0 for
   the high-Z output (OUT1).
5. The driver always tracks the selected channel: `select_feedback_resistor`
   writes relay 3 from `relaymap.BOOSTER_COILS` (`{LOW_Z: True, HIGH_Z: False}`),
   so the booster amplifies the selected channel's output. Relay 3 is still
   independent in hardware; the non-contract `set_booster_source(out2)` overrides
   the tracking.

## Driver questions, resolved

### Resolved by firmware documentation

- [x] **OUT1/OUT2 ↔ channel correspondence.** Commit `b83e474` states OUT1 is the
      high-Z output and OUT2 the low-Z output, so the correspondence is firmware
      fact. The power-on relay-3 default (OUT2 → booster) now matches the power-on
      low-Z channel by construction.

### Settled driver policy

- [x] **Booster source tracking.** Relay 3 is independent in hardware, but the
      driver always routes the selected channel's output to the booster:
      `relaymap.BOOSTER_COILS = {LOW_Z: True, HIGH_Z: False}` supplies the
      relay-3 coil write on every channel select. The non-contract
      `set_booster_source(out2: bool)` overrides it.

### Resolved in code

- [x] **Relay 13 source select.** Taken as option A: exposed as the non-contract
      extension methods `get_bias_compensation_source` /
      `set_bias_compensation_source` on `EBICModbusV1Amplifier`, not as a member
      of `CurrentAmplifierCapabilities`. The layer never writes relay 13
      implicitly, so it stays at the firmware's Manual source until a caller
      selects otherwise. The DAC on the other branch is an external device the
      firmware never drives and no Modbus write reaches (see "Source" and the
      relay-13 row above).
- [x] **Two `Rf` relays closed in one channel.** The driver enforces exactly one
      `Rf` per bank on every write; a readback that names zero or several
      resistors of the active channel decodes to `None`, and the strict getter
      raises `UnexpectedResponse`. Combined feedback resistors are unsupported by
      decision, so their physical behaviour is not needed.
- [x] **Gain / in-bank `Rf` break-before-make.** The transition engine releases
      the old stage before engaging the new one, so a gain change or a same-bank
      `Rf` change is break-before-make. The resulting output transient is a
      hardware property the driver cannot measure; downstream consumers should
      expect it.
- [x] **Overcurrent.** No ADC, no discrete-input function code and no MCU input
      pin reach the signal, so it is unobservable through this firmware; whether
      it reaches a connector is hardware-documentation only.

## Consequences for the capability contract

The semantic layer (`EBICModbusV1Amplifier`) now implements the map; this is what
it fixes:

- `PreampCapabilities.feedback_resistor.options` =
  `(1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0, 100_000_000.0, 1_000_000_000.0, 10_000_000_000.0)`
  (ohm): the eight values. The channel grouping is low-Z {1 kΩ … 1 MΩ} and
  high-Z {10 MΩ … 10 GΩ}.
- `BoostCapabilities.gain.options` = `(1.0, 3.0, 10.0, 30.0)`, and
  `default_gain = 1.0` is exactly the all-relays-off state; no separate "gain 1"
  relay exists.
- `DcBiasCapabilities.enabled` ← relay 4; compensation `enabled` ← relay 17.
- Implemented and readable through `read_data()`: feedback resistor, boost gain,
  DC bias enable and input compensation enable.
- Still unsupported on this board: bandwidth, filters, invert, bias level,
  compensation level, and any measurement.
- **Relay 13 resolved as option A:** the shared bias/compensation source select
  has no member in `CurrentAmplifierCapabilities`, so it is exposed only as the
  non-contract `get_bias_compensation_source` / `set_bias_compensation_source`
  extension and is never written implicitly. Relay 3 is likewise a non-contract
  `get_booster_source` / `set_booster_source` extension.
- **Chosen code defaults:** the booster always tracks the selected channel
  (`relaymap.BOOSTER_COILS`; low-Z → relay-3 coil 1, high-Z → coil 0), with
  `set_booster_source(out2)` as the manual override; break-before-make ordering
  for gain and in-bank `Rf` changes; and exactly one `Rf` per bank on every
  write.
- The full-scale current `min(5, 10/G) / Rf` is derived in
  [amplifier-architecture.md §7](amplifier-architecture.md#7-limits-and-full-scale-current);
  it is not restated here.
