# Section 3 — Design Current Determination

LV Cable Sizing and Routing Tool
Revision B — 4 September 2026
Status: Working engineering specification. Not an approved design basis.

Supersedes Section 3 of the Methodology Rev A. Sections 4 to 12 of that document
are unchanged.

## 3.1 Scope and definition

Design current I_b is the current the circuit is designed to carry in normal
service, after diversity, on a continuous basis. It is not the connected load and
it is not the protective device rating.

I_b is the input to the coordination requirement I_b ≤ I_n ≤ I_z, AS/NZS 3000
Clause 2.5. An error in I_b propagates to every subsequent check, so the tool
computes it from declared load data under explicit conventions rather than
accepting a user-entered current.

Reference implementation: `src/design_current.py`. Verification cases:
`tests/test_design_current.py`.

## 3.2 Declaration forms

A load is declared in exactly one of four forms. The form determines which
corrections apply. Applying a correction twice is the most common error in manual
calculation and the tool prevents it by construction.

| Form | Field | Power factor applied | Efficiency applied |
|---|---|---|---|
| Output power | `KW_OUTPUT` | Yes | Yes |
| Input real power | `KW_INPUT` | Yes | No |
| Input apparent power | `KVA_INPUT` | No | No |
| Nameplate current | `AMPS` | No | No |

`KVA_INPUT` already contains the power factor. The tool raises
`DesignCurrentError` if a displacement power factor is supplied alongside a kVA
declaration.

`KW_OUTPUT` is shaft or useful output. It applies to motors, and to any load whose
nameplate states delivered rather than drawn power. A motor declared as
`KW_OUTPUT` without an efficiency is rejected.

`AMPS` is used unmodified. Nameplate full load current already accounts for the
machine's power factor and efficiency at rated condition.

## 3.3 Base equations

| System | Equation |
|---|---|
| Three-phase | I = S × 1000 / (√3 · U_LL) |
| Single-phase line to neutral | I = S × 1000 / U_LN |
| Single-phase line to line | I = S × 1000 / U_LL |
| DC | I = P × 1000 / U |

with S in kVA, P in kW, U in volts, I in amperes.

Apparent power is derived from real power using true power factor:

S = P / λ

Nominal system voltage is used, not the measured or tapped voltage. Voltage
tolerance is addressed in the voltage drop budget, Section 5, not here.

## 3.4 Power factor

Two distinct quantities are required and they are not interchangeable.

**Displacement power factor** cos φ₁ is the phase angle between fundamental
voltage and fundamental current. It governs voltage drop, Section 5.4.

**True power factor** λ is the ratio of real power to total apparent power
including harmonic content. It governs current magnitude, because the conductor
carries harmonic current as well as fundamental.

λ = cos φ₁ / √(1 + THD_i²)

where THD_i is total harmonic distortion of current as a fraction.

The tool stores both against every load. Using cos φ₁ for current understates
I_b: at cos φ₁ = 0.98 and THD_i = 30 %, λ = 0.939 and the understatement is 4.4 %.
Using λ for voltage drop overstates the drop, because harmonic current does not
contribute to fundamental-frequency drop in proportion to its magnitude.

Where a load declares THD_i and a harmonic spectrum, the spectrum is authoritative
and THD_i is computed from it as the RSS of the harmonic magnitudes.

## 3.5 Neutral current

The neutral is a current-carrying conductor in any circuit supplying single-phase
or non-linear load, and in a data centre distribution system it is frequently the
governing conductor.

### 3.5.1 Triplen harmonic contribution

Triplen harmonics, orders h = 3, 9, 15, are co-phasal across the three phases. They
do not cancel in the neutral; they add arithmetically.

I_N,triplen = 3 · I₁ · √(Σ_{h=3,9,15,…} h_ratio_h²)

where I₁ is the fundamental phase current and h_ratio is harmonic magnitude as a
fraction of fundamental.

Non-triplen harmonics form positive and negative sequence sets and cancel in the
neutral under balanced conditions.

### 3.5.2 Unbalance contribution

Fundamental neutral current from unequal phase loading is the vector sum of the
three phase currents at nominal 120° separation.

I_N,unbalance = |I_A + I_B∠−120° + I_C∠+120°|

### 3.5.3 Combination

The two contributions are at different frequencies and combine in RSS:

I_N = √(I_N,unbalance² + I_N,triplen²)

### 3.5.4 Crossover

For a balanced load with third harmonic only, the ratio of neutral to phase current
is:

I_N / I_L = 3·h₃ / √(1 + h₃²)

This reaches unity at h₃ = 1/√8 = 0.354. Above 35.4 % third harmonic content the
neutral carries more current than any phase and governs conductor selection.

| h₃ | I_N / I_L |
|---|---|
| 10 % | 0.299 |
| 15 % | 0.445 |
| 25 % | 0.728 |
| 35.4 % | 1.000 |
| 45 % | 1.231 |
| 60 % | 1.543 |

Computed from the equation above. These are geometric relationships, not tabulated
standard data.

### 3.5.5 Rating factor and governing conductor

Separately from the neutral current calculation, AS/NZS 3008.1.1 applies a rating
factor to four-core and five-core cables carrying triplen harmonic current, banded
by third-harmonic percentage. The band structure determines both the factor and
whether the phase or the neutral current is used for cable selection. Band
boundaries and factor values are read from the licensed copy into the `harmonic`
factor set, Section 8.3 of the Methodology.

The tool applies both: the calculated neutral current sets the governing conductor,
and the tabulated factor derates the cable. They are independent and neither
substitutes for the other.

## 3.6 Load type treatments

### 3.6.1 Motors

Cable is sized on full load current. Starting current is a short-duration transient
and does not govern thermal sizing of the cable. Starting current governs protective
device selection and starting voltage dip, which are separate checks.

Where a motor starts more than the configured frequency threshold, or where the
starting duration exceeds the configured limit, the tool flags the circuit for
manual cyclic rating assessment. Cyclic rating is out of scope, Section 1.

### 3.6.2 UPS input circuits

UPS input current exceeds output current. The input circuit carries:

P_in = P_out / η + P_recharge

Battery recharge allowance is expressed as a fraction of rated output power,
typically 0.10 to 0.25 depending on autonomy and recharge time. The value is a
vendor figure and is recorded as such.

Input displacement power factor for a modern active-front-end UPS is 0.99 or
better. For older six-pulse rectifier units it is lower and THD_i is high; both
are entered from the vendor data sheet.

Static bypass and maintenance bypass circuits are sized for full rated output
current with no efficiency or recharge allowance.

### 3.6.3 IT load circuits

No diversity is applied to final subcircuits serving IT load. Diversity at PDU and
board level is applied only where a measured or contracted limit exists.

Server power supplies present as constant-power loads. Current rises as voltage
falls, which is the opposite of the resistive assumption. Under a sustained
low-voltage condition the design current increases. The tool computes I_b at
nominal voltage and reports sensitivity at the lower voltage tolerance limit.

### 3.6.4 Transformers

Primary and secondary circuits are sized on rated kVA at the respective nominal
voltage, not on the connected downstream load.

### 3.6.5 Resistive loads

λ = 1.0, no harmonic content, no efficiency correction.

## 3.7 Aggregation and diversity

Board design current is the sum of downstream load currents, each multiplied by its
own diversity factor, with a board-level diversity factor applied to the total.

I_b,board = k_board · Σ (I_b,i · d_i)

Currents are summed arithmetically. This is conservative where power factors differ
between loads. A phasor sum is more accurate and requires phase angle data for
every load; it is not implemented.

The tool rejects aggregation across mixed system types or mixed nominal voltages.
These are resolved at the transformer or converter boundary.

Maximum demand may alternatively be established by calculation per AS/NZS 3000
Appendix C, by assessment, by measurement of an existing installation, or by a
contractual limitation. Where the method is not calculation, the source and the
figure are recorded against the board and the calculated value is retained for
comparison.

## 3.8 Governing current

I_b for conductor selection is the greater of phase and neutral current:

I_b = max(I_phase, I_N)

The result records which conductor governs. Where the neutral governs, the phase
conductors are not reduced below the size required for the phase current, and the
protective device continues to be rated against phase current.

## 3.9 Validation rules

The following are rejected at load construction rather than producing a silently
wrong result.

| Condition | Reason |
|---|---|
| Displacement pf supplied with a kVA declaration | Double-counted power factor |
| Motor declared as output power without efficiency | Understated input power |
| Efficiency outside (0, 1] | Not physical |
| Voltage ≤ 0 or negative declared value | Not physical |
| Aggregation across mixed system types | Undefined |
| Aggregation across mixed nominal voltages | Undefined |

## 3.10 Verification cases

Computed by `tests/test_design_current.py`, all passing at Revision B.

| # | Case | Result |
|---|---|---|
| 1 | 100 kW, pf 0.9, 400 V 3ph | 160.38 A |
| 2 | 250 kVA, 400 V 3ph | 360.84 A |
| 3 | 75 kW motor, η 0.94, pf 0.86 | 133.91 A |
| 4 | 100 kW, cos φ₁ 0.98, THD_i 30 % | 153.77 A, versus 147.28 A ignoring THD |
| 6 | 300 kVA, h₃ 45 % | phase 433.0 A, neutral 522.3 A, neutral governs |
| 7 | 500 kW UPS, η 0.96, recharge 10 % | 835.29 A |
| 9 | 7.2 kW 1ph 230 V | 31.30 A |
| 10 | 250 kW DC at 800 V | 312.50 A |
| 11 | Board 100 + 100 + 150×0.7 kVA | 440.23 A, 305.0 kVA |

## 3.11 Open items

1. Constant-power load behaviour under sustained undervoltage is reported as a
   sensitivity but is not iterated to a converged operating point.
2. Phasor summation at board level is not implemented. Arithmetic summation is
   conservative but the margin is not quantified.
3. Harmonic spectra for the specific IT and mechanical equipment are not
   established. Values used are placeholders pending vendor data or site
   measurement.
4. Diversity factors for mechanical plant are not established.
5. Motor starting frequency and duration thresholds that trigger cyclic assessment
   are not set.
6. Whether generator-supplied circuits use a different design current from mains
   circuits, given generator voltage regulation and harmonic response, is
   undecided.
7. Phase angle convention for the unbalance calculation assumes nominal 120°
   separation. Load-specific angle data supersedes it where available and no
   source for that data is identified.

## 3.12 Recommendation

Implement `design_current.py` as the sole entry point for I_b. Downstream modules
consume `DesignCurrentResult` and do not recompute current from power. Establish
harmonic spectra for the UPS input and IT load classes before the tool is used for
any issued design, since the neutral crossover at 35.4 % third harmonic determines
conductor selection and no default value is defensible.
