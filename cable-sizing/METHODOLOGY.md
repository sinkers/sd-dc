# LV Cable Sizing and Routing Tool — Calculation Methodology and Data Schema

Revision A — 4 September 2026
Status: Working engineering specification. Not an approved design basis.

## 1. Scope

Covers low voltage AC circuits to 1000 V, three-phase four-wire 400 V and
single-phase 230 V, copper and aluminium conductors, PVC (V-75) and XLPE (X-90)
insulation. DC circuits are covered for the voltage drop and adiabatic checks only.

Not covered: HV cable systems, cyclic and emergency rating assessment, fire-rated
and MIMS cable systems, cable systems in hazardous areas, and thermal modelling of
multiple heat sources in a common trench.

This document specifies method and data structure. It contains no rating tables.
Numeric current-carrying capacity, impedance and rating-factor data is sourced as
set out in Section 9 and populated into the schema in Section 8. Where AS/NZS
3008.1.1:2025 or AS/NZS 3000 is the governing reference for a value, the clause or
table is cited and the value is read from the licensed copy at build time.

## 2. Selection procedure

The tool applies the checks in the following order. A conductor size passes only if
it satisfies every check.

| Step | Check | Governing criterion |
|---|---|---|
| 1 | Design current | I_b from connected load, diversity and power factor |
| 2 | Protective device | I_n ≥ I_b |
| 3 | Rating factors | Product of applicable factors, Section 4 |
| 4 | Current-carrying capacity | I_z ≥ I_n, where I_z = I_t × Π k |
| 5 | Voltage drop | Section 5 |
| 6 | Short-circuit withstand | Section 6 |
| 7 | Earth fault loop impedance | Section 7 |
| 8 | Protective earthing conductor | Section 7 |
| 9 | Neutral conductor | Section 3.3 |

Coordination requirement, AS/NZS 3000 Clause 2.5: I_b ≤ I_n ≤ I_z.

## 3. Design current

> **Superseded.** Section 3 is replaced by Revision B, 4 September 2026, in `METHODOLOGY-S3-RevB.md`. Sections 1 to 2 and 4 to 12 below are unchanged. The text retained here is Revision A, kept for the record.

### 3.1 Three-phase

I_b = P / (√3 · U · cos φ · η)

### 3.2 Single-phase

I_b = P / (U_o · cos φ · η)

where P is real power in watts, U is line-to-line voltage, U_o is line-to-neutral
voltage, cos φ is displacement power factor and η is efficiency where the load is
specified as output power.

### 3.3 Harmonic loading

For non-linear loads the neutral current is not assumed to be less than the phase
current. Where third-harmonic content exceeds 15 % of the fundamental, the neutral
is sized on the calculated neutral current and a rating factor is applied to the
circuit. Where third-harmonic content exceeds 33 %, the neutral current exceeds the
phase current and the cable is sized on neutral current.

Harmonic rating factors are tabulated against third-harmonic percentage in
AS/NZS 3008.1.1 and are read into the `harmonic` factor set of the schema.

This case is the normal condition for UPS input circuits, six-pulse rectifier loads
and unfiltered switch-mode server load. It is not an edge case in a data centre
distribution design.

## 4. Rating factors

Derated capacity:

I_z = I_t × k_amb × k_grp × k_soil × k_depth × k_sol × k_ins × k_harm

| Factor | Applies to | Independent variable |
|---|---|---|
| k_amb | All | Ambient air or soil temperature, insulation class |
| k_grp | All | Number of circuits, arrangement, spacing, touching or spaced |
| k_soil | Buried | Soil thermal resistivity, °C·m/W |
| k_depth | Buried | Depth of laying |
| k_sol | Exposed in air | Direct solar radiation |
| k_ins | Enclosed | Contact with thermal insulation |
| k_harm | All | Third-harmonic content |

Factors are multiplicative. The tool records which factors were applied and their
values against each result so that the derivation is auditable.

Where a circuit is installed through more than one installation condition along its
route, the tool evaluates each segment and applies the most onerous result to the
whole circuit, unless the segment is shorter than the length threshold set in
configuration.

## 5. Voltage drop

### 5.1 Conductor resistance at operating temperature

DC resistance at 20 °C is corrected to the operating temperature:

R_θ = R_20 · [1 + α_20 (θ − 20)]

| Conductor | α_20, /°C | ρ_20, Ω·mm | Q_c, J/(°C·mm³) | β, °C |
|---|---|---|---|---|
| Copper | 0.00393 | 17.241 × 10⁻⁶ | 3.45 × 10⁻³ | 234.5 |
| Aluminium | 0.00403 | 28.264 × 10⁻⁶ | 2.50 × 10⁻³ | 228.0 |

Source: standard physical constants for electrical-grade conductor, as used in
IEC 60287 and IEC 60364-5-54.

### 5.2 Operating temperature

Where the circuit is not fully loaded, the conductor operates below its maximum
rated temperature. The tool estimates operating temperature from the load ratio:

θ = θ_a + (θ_max − θ_a) · (I_b / I_z)²

θ_max is 75 °C for V-75 PVC and 90 °C for X-90 XLPE. Using θ_max unconditionally is
the conservative option and is selectable in configuration; the load-ratio estimate
is the default.

### 5.3 AC resistance

R_ac = R_θ · (1 + y_s + y_p)

Skin effect y_s and proximity effect y_p per IEC 60287-1-1. Below 95 mm² the
correction is under 1 % and may be neglected; above 300 mm² it is significant and
is not neglected. Where manufacturer catalogue data already states R_ac at
operating temperature, that value is used directly and the correction is not
applied twice.

### 5.4 Voltage drop

Three-phase:

ΔU = √3 · I_b · L · (R_ac cos φ + X sin φ) / 1000

Single-phase:

ΔU = 2 · I_b · L · (R_ac cos φ + X sin φ) / 1000

DC:

ΔU = 2 · I_b · L · R_θ / 1000

with I in amperes, L in metres, R and X in Ω/km, ΔU in volts.

Equivalent form using the tabulated millivolt drop V_c in mV/A/m:

ΔU = V_c · I_b · L / 1000

The tool implements the impedance form as primary and uses V_c only for
cross-checking against published data.

### 5.5 Parallel circuits

For m identical parallel cables per phase, current divides equally and effective
impedance is R/m and X/m. Cables in parallel are required to be of the same
construction, size and length. The tool rejects a parallel arrangement where
segment lengths differ by more than the configured tolerance.

### 5.6 Limit

Total voltage drop from the point of supply to any point in the installation is
limited to 5 %, AS/NZS 3000 Clause 3.6.2. The tool tracks cumulative drop through
the distribution tree rather than testing each circuit in isolation, and permits a
per-level allocation to be set in configuration.

## 6. Short-circuit withstand

Adiabatic check:

S ≥ √(I² t) / k

where I is prospective fault current in amperes, t is protective device clearing
time in seconds and S is conductor cross-sectional area in mm².

k is computed from conductor and insulation properties rather than looked up:

k = √[ (Q_c (β + 20) / ρ_20) · ln((β + θ_f) / (β + θ_i)) ]

θ_i is the initial conductor temperature, taken as the maximum operating
temperature. θ_f is the limiting temperature under short circuit: 160 °C for PVC and
250 °C for XLPE.

Computed values, which reconcile with the published constants:

| Combination | θ_i → θ_f | k |
|---|---|---|
| Cu / PVC | 70 → 160 | 115 |
| Cu / XLPE | 90 → 250 | 143 |
| Al / PVC | 70 → 160 | 76 |
| Al / XLPE | 90 → 250 | 95 |

The adiabatic equation is valid for clearing times up to about 5 s. For longer
times heat loss to the surroundings is not negligible and the result is
conservative. For current-limiting devices the let-through energy I²t from the
manufacturer's curve is used in place of the calculated value.

## 7. Earth fault protection

### 7.1 Loop impedance

Z_s ≤ U_o · C / I_a

where C is the voltage factor and I_a is the current causing operation of the
protective device within the required disconnection time. Disconnection times are
per AS/NZS 3000 Clause 5.7.

Z_s is accumulated along the route as the phasor sum of source impedance, active
conductor impedance and protective earthing conductor impedance, at the fault
temperature rather than at 20 °C.

### 7.2 Protective earthing conductor

Sized by the greater of the AS/NZS 3000 Table 5.1 minimum and the adiabatic result
from Section 6 applied to the earth fault current and clearing time.

## 8. Data schema

### 8.1 Cable

```json
{
  "id": "cu-xlpe-4c-185",
  "conductor": "Cu",
  "insulation": "XLPE",
  "sheath": "PVC",
  "cores": 4,
  "csa_mm2": 185,
  "construction": "multicore",
  "armour": null,
  "max_operating_temp_c": 90,
  "short_circuit_temp_c": 250,
  "r_dc_20_ohm_km": null,
  "r_ac_operating_ohm_km": null,
  "x_ohm_km": null,
  "od_mm": null,
  "mass_kg_km": null,
  "min_bend_radius_mm": null,
  "ratings": [
    { "install_method": "ladder_touching_trefoil", "amps": null }
  ],
  "source": { "type": "manufacturer_catalogue", "ref": null, "revision": null }
}
```

`r_*` and `ratings[].amps` are null in the schema and are populated from the
sources in Section 9. Every populated value carries its `source` record.

### 8.2 Installation method

```json
{
  "id": "ladder_touching_trefoil",
  "family": "air",
  "description": "Perforated ladder, horizontal, single-core trefoil, touching",
  "reference_ambient_c": 40,
  "applicable_factors": ["k_amb", "k_grp", "k_sol", "k_harm"],
  "standard_ref": "AS/NZS 3008.1.1:2025 — installation arrangement"
}
```

### 8.3 Rating factor set

```json
{
  "factor": "k_grp",
  "install_family": "air",
  "arrangement": "ladder_touching",
  "axis": "circuits",
  "points": [ { "circuits": null, "factor": null } ],
  "interpolation": "none",
  "source": { "type": "standard", "ref": null, "table": null }
}
```

Rating factor tables are stepped, not continuous. `interpolation` defaults to
`none`; where interpolation is permitted for a given factor the field is set
explicitly and the method recorded.

### 8.4 Protective device

```json
{
  "id": "mccb-400-lsig",
  "type": "MCCB",
  "in_amps": 400,
  "curve": "adjustable_LSIG",
  "ir_range": [0.4, 1.0],
  "isd_range": [1.5, 10],
  "clearing_time_s": null,
  "i2t_let_through": null,
  "breaking_capacity_ka": 50
}
```

### 8.5 Route

```json
{
  "circuit_id": "MSB-01-UPS-A",
  "from": "MSB-01",
  "to": "UPS-A-INPUT",
  "segments": [
    {
      "length_m": null,
      "install_method": "ladder_touching_trefoil",
      "ambient_c": null,
      "grouped_circuits": null,
      "soil_resistivity_c_m_w": null,
      "depth_m": null,
      "solar_exposed": false
    }
  ],
  "parallel_sets": 1,
  "vertical_rise_m": null,
  "bends": []
}
```

Route length for voltage drop is the sum of segment lengths plus vertical rise plus
the configured termination allowance. Bend count and minimum bend radius are carried
for pulling-tension and containment checks, not for electrical calculation.

## 9. Data sources

| Data | Source | Licence position |
|---|---|---|
| Current-carrying capacity | Manufacturer catalogue, computed to AS/NZS 3008.1.1 | Published, freely usable |
| R, X per km | Manufacturer catalogue; IEC 60228 for nominal R_dc | Published |
| Physical constants ρ, α, Q_c, β | IEC 60287, IEC 60364-5-54 | Published |
| Rating factors | AS/NZS 3008.1.1:2025 | Read from licensed copy |
| Generic capacity tables | AS/NZS 3008.1.1:2025 | Read from licensed copy |
| Voltage drop limit, coordination, disconnection times | AS/NZS 3000 | Read from licensed copy |
| Device clearing times and I²t | Manufacturer curves | Published |

Building the conductor library from manufacturer catalogue data ties results to
specifiable part numbers and gives R and X at stated operating temperature.
Generic standard tables remain the fallback where a product is not yet selected.

## 10. Worked example

Three-phase 400 V circuit, 4-core 185 mm² Cu XLPE, ladder in air, ambient 40 °C,
three circuits grouped, route length 85 m, I_b = 320 A, cos φ = 0.9, derated
capacity I_z = 380 A.

| Quantity | Value | Basis |
|---|---|---|
| θ operating | 75.5 °C | Section 5.2, load ratio 320/380 |
| R_20 | 0.0991 Ω/km | IEC 60228 nominal, illustrative |
| R_θ | 0.1207 Ω/km | Section 5.1 |
| R_ac | 0.1231 Ω/km | 2 % skin and proximity, illustrative |
| X | 0.0755 Ω/km | Manufacturer catalogue, illustrative |
| ΔU | 6.77 V | Section 5.4 |
| ΔU % | 1.69 % | Against 400 V |

Short-circuit check at 25 kA for 0.2 s, Cu/XLPE, k = 143: minimum 78.3 mm².
The 185 mm² selection passes.

R_20, R_ac and X in this example are illustrative values used to verify the
arithmetic. They are not a specification of any product.

## 11. Open items

1. Rating factor tables are not populated. The `points` arrays in Section 8.3 are
   empty pending entry from the licensed standard.
2. No harmonic rating factor data is populated. Third-harmonic factors govern most
   data centre distribution circuits and are the first data set required.
3. Cyclic and emergency ratings are out of scope. Whether the tool must support
   short-term overload rating for generator and UPS bypass circuits is undecided.
4. Soil thermal resistivity for site conditions is not established. The default of
   1.2 °C·m/W is an assumption pending site thermal resistivity testing.
5. Tray and ladder fill, and containment sizing, are not specified in this revision.
   The route schema carries the geometry but no fill rule is implemented.
6. Whether the tool sizes the neutral independently of the phase conductors, or
   applies a full-size neutral by policy, is undecided.
7. Aluminium conductor termination and joint requirements are not addressed.

## 12. Recommendation

Implement Sections 3 to 7 as the calculation engine against the schema in Section 8,
with the conductor library populated from manufacturer catalogue data. Populate the
rating factor sets from the licensed standard as a separate data entry task, with
each entry carrying its table citation. Validate the engine against worked examples
from a second independent source before it is used for any issued design.
