# Relay function map

EBIC CONTROL preamp board

## Source

Transcribed from the firmware repository
`git.buro-nts.ru/a.kudryavtsev/ebic_control`, commit `e127278`, files
`RELAY_FUNCTION_MAP.md`, `README.md` and `ebic_control_relay_map.pdf` (the PDF is
the same content rendered as two pages). The function table is unchanged since
`c1bb7b0`; `e127278` ("fix relay map in globals.c") changed only the GPIO pin
assignment of relays 9–17 in `Core/Src/globals.c` and `README.md`. This file is a
transcription for driver use: the firmware repository is authoritative, and the
PDF there is a rendered copy.

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
the relay is de-energised, not that the feature is active.

Writing coil value 1 to all 17 coils (the power-up state, and what the firmware
loads when the EEPROM is blank) yields: Low-Z channel, 1 kΩ `Rf`, gain ×1, bias
off, compensation off, manual source.

## Full map

| Relay | Coil | GPIO | Input reg | Section | Function | GPIO = 0 (energised) | GPIO = 1 (de-energised, power-on) | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | PA0 | 36 | §01 | input path select | High-Z | Low-Z | |
| 2 | 1 | PA1 | 37 | §01 | connects the amplifier's inverting input to the feedback of the *deselected* channel | low-Z feedback | high-Z feedback | Works in anti-phase with relay 1: with low-Z selected it closes the high-Z (deselected) feedback, and vice versa. Functional relationship only; both relays default to GPIO = 1. |
| 3 | 2 | PA2 | 38 | §01 | selects which amplifier output feeds the booster | OUT1 → booster | OUT2 → booster | Independently selects the booster's source. |
| 4 | 3 | PA3 | 39 | §01 | bias enable | ON | OFF | |
| 5 | 4 | PA4 | 40 | §02 | 10 GΩ resistor | ON | OFF | |
| 6 | 5 | PA5 | 41 | §02 | 1 GΩ resistor | ON | OFF | |
| 7 | 6 | PA6 | 42 | §02 | 100 MΩ resistor | ON | OFF | |
| 8 | 7 | PA7 | 43 | §02 | 10 MΩ resistor | ON | OFF | |
| 9 | 8 | PB0 | 44 | §03 | 1 MΩ resistor | ON | OFF | |
| 10 | 9 | PB1 | 45 | §03 | 100 kΩ resistor | ON | OFF | |
| 11 | 10 | PB2 | 46 | §03 | 10 kΩ resistor | ON | OFF | |
| 12 | 11 | PA8 | 47 | §03 | 1 kΩ resistor | OFF | ON | Only inverted function: at GPIO = 1 relay 12 is de-energised yet the 1 kΩ resistor is connected. |
| 13 | 12 | PA9 | 48 | §05 | simultaneous source select for bias and compensation (DAC vs Manual) | DAC | Manual | Switches bias and compensation together: GPIO = 1 = manual, GPIO = 0 = DAC. |
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

Exactly one resistor per channel is intended. The source does not define the
result of two being closed at once; parallel summing is an assumption, not a
fact.

## Booster gain coding

Three relays, one-hot: relay 14 → ×3, relay 15 → ×10, relay 16 → ×30, and none
closed → ×1. The coding is one-hot, not binary; ×1 is the absence of all three.

## Derived driver invariants

These are derived from the table above. The last two are inference, marked as
such, not fact from the source.

1. Relays 1 and 2 always carry the **same coil value**. Both are 1 at power-on;
   selecting low-Z means relay 1 = 1 and relay 2 = 1 because relay 2 closes the
   high-Z (deselected) feedback. Channel selection is therefore one bit written
   to two coils.
2. Relay 12 is the only inverted function: coil de-energised (value 1) = 1 kΩ
   connected.
3. The power-on defaults therefore give the low-Z channel selected, the high-Z
   feedback closed, and 1 kΩ as the active `Rf` → default transimpedance 1 kΩ,
   the least sensitive setting.
4. With relay 3 at its default (OUT2 → booster), the power-on state is only
   self-consistent if OUT2 is the low-Z output. The source does not state which
   output is which. *Inference; recorded as an open item, not resolved.*
5. Relay 3 must logically agree with relays 1/2, otherwise the booster amplifies
   the unselected channel, but the source calls it independent and does not
   define the required correspondence. *Inference; open item.*

## Open items for the driver

- [ ] OUT1/OUT2 ↔ channel correspondence.
- [ ] Whether relay 3 must track the channel or is a free control.
- [ ] What drives the DAC path (relay 13) and whether it is reachable over
      Modbus.
- [ ] Behaviour of two `Rf` relays closed in one channel.
- [ ] Whether the gain relays are break-before-make.
- [ ] Whether the Overcurrent comparator is brought out to a connector.

## Consequences for the capability contract

No design changes here; this is what the map now fixes:

- `PreampCapabilities.feedback_resistor.options` =
  `(1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0, 100_000_000.0, 1_000_000_000.0, 10_000_000_000.0)`
  (ohm): the eight values. The channel grouping is low-Z {1 kΩ … 1 MΩ} and
  high-Z {10 MΩ … 10 GΩ}.
- `BoostCapabilities.gain.options` = `(1.0, 3.0, 10.0, 30.0)`, and
  `default_gain = 1.0` is exactly the all-relays-off state; no separate "gain 1"
  relay exists.
- `DcBiasCapabilities.enabled` ← relay 4; compensation `enabled` ← relay 17.
- Still unsupported on this board: bandwidth, filters, invert, bias level,
  compensation level, and any measurement.
- **Contract gap:** relay 13 (bias/compensation source select) has no member in
  `CurrentAmplifierCapabilities`. It is a real control the semantic layer will
  have to express somehow; this is flagged here, not added.
- The full-scale current `min(5, 10/G) / Rf` is derived in
  [amplifier-architecture.md §7](amplifier-architecture.md#7-limits-and-full-scale-current);
  it is not restated here.
