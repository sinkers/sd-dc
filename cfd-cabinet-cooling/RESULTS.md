# Results

Six converged runs sweeping the fan wall discharge velocity against a fixed
30 kW cabinet, 20 °C supply, a 4.0 m cold aisle, and a 0.2 m containment
leakage gap between the containment panel and the plenum floor.

![sweep](runs/sweep.png)

| discharge [m/s] | % of demand | intake mean [°C] | intake peak [°C] | exhaust [°C] | supply [kg/s] | through servers [kg/s] | gap flow [kg/s] | verdict |
|---|---|---|---|---|---|---|---|---|
| 0.70 | 68 % | 28.9 | 37.7 | 48.0 | 1.011 | 1.486 | −0.475 | **FAIL** |
| 0.99 | 84 % | 24.5 | 37.0 | 41.2 | 1.430 | 1.702 | −0.272 | **MARGINAL** |
| 1.15 | 93 % | 22.4 | 36.6 | 38.4 | 1.661 | 1.791 | −0.130 | **MARGINAL** |
| 1.29 | 103 % | 20.2 | 20.2 | 36.5 | 1.864 | 1.811 | +0.053 | **PASS** |
| 1.41 | 110 % | 20.2 | 20.2 | 36.2 | 2.037 | 1.847 | +0.191 | **PASS** |
| 1.83 | 127 % | 20.2 | 20.2 | 34.3 | 2.644 | 2.089 | +0.555 | **PASS** |

Negative gap flow is hot air recirculating into the cold aisle; positive is cold
air bypassing into the hot aisle.

## Does the setup provide sufficient cooling?

**Yes, at the design point.** At 1.41 m/s the servers ingest 20.2 °C air with a
worst-case intake of 20.2 °C — essentially the supply temperature, well inside
the 27 °C ASHRAE A1 recommended limit. The cabinet rejects its 30 kW at a 16.0 K
rise, exhausts at 36.2 °C, and the air arrives back at the unit intake at
34.8 °C. (This read 33.7 °C until 19 Aug 2026. The domain is adiabatic, so at
steady state the return temperature is fixed by energy conservation at
T_supply + Q / (m_total · cp) = 20.2 + 30000 / (2.037 × 1005) = 34.85 °C, which
the mass-weighted mix of exhaust and bypass air confirms at 34.7 °C. The run that
produced the original figure has been overwritten, so it cannot be re-read, but
33.7 °C is not consistent with a closed adiabatic energy balance.) The full 4 m cold aisle stays uniformly cold right up to the cabinet
face.

## The threshold is the airflow balance point

The verdict flips between 1.15 m/s and 1.29 m/s, and that is exactly where gap
flow crosses zero: at 1.29 m/s the unit supplies 1.864 kg/s against a server
demand of 1.811 kg/s, and the gap carries a negligible +0.053 kg/s.

This is the governing rule. The servers move their design airflow regardless of
what the fan wall delivers; any shortfall is made up from the only other air
available, which is their own exhaust drawn back through the containment gap.
There is no partial-credit region.

## The peak intake temperature is very nearly binary

This is the finding worth carrying away, and the new layout makes it sharper
than a longer cold aisle might suggest.

Across the three sub-threshold runs the **mean** intake moves gently and
plausibly — 28.9, 24.5, 22.4 °C — sliding toward the limit the way an engineer
would expect a design margin to behave. The **peak** intake does nothing of the
kind. It sits at 37.7, 37.0, 36.6 °C: pinned near the cabinet exhaust
temperature, barely responding to a doubling of supply air. Then, the moment gap
flow turns positive, it collapses to 20.2 °C.

So the peak is effectively a switch with two positions — roughly exhaust
temperature, or roughly supply temperature — and it is thrown by the sign of the
containment gap flow, not by how much air the fan wall moves.

At 1.15 m/s, 93 % of demand, the mean intake reads **22.4 °C** and would pass any
sensible review. The top of the rack is ingesting **36.6 °C**, above the 32 °C
allowable limit. The slice below shows why: recirculated air rides back along
the underside of the plenum floor as a hot layer spanning the entire 4 m cold
aisle, and the 27 °C isotherm dips to about z = 1.7 m at the cabinet face. The
bottom ~77 % of the rack breathes clean 20 °C supply; the top ~0.5 m does not.

![marginal](runs/anim/frame_02.png)

Two practical consequences:

- **Judging this configuration on mean intake temperature does not work.** The
  mean is a blend of two populations that never mix, and it lands in the gap
  between them.
- **The useful design margin is not thermal, it is the gap flow sign.** Aim to
  keep containment gap flow comfortably positive; the temperatures then take
  care of themselves.

## Oversupply buys nothing

1.83 m/s gives 20.17 °C against 20.19 °C at 1.41 m/s — no measurable benefit —
while gap flow grows from +0.191 to +0.555 kg/s. That surplus is cold air pushed
straight into the hot aisle without passing a server. Fan power scales roughly
with the cube of flow, so it is about 2.2× the energy for nothing.

## Recommendation

Operate at **≈1.41 m/s**, about 110 % of server demand.

- It clears the 1.29 m/s balance point with margin for filter loading, fan
  degradation and load growth, none of which are modelled here.
- The margin costs roughly 1.3× the fan power of running exactly at balance.
- Running below balance is not an efficiency play at any level: the first run
  under it already produces a 36.6 °C hot spot at the top of the rack.

The cheaper lever remains the containment. Every failure here is air crossing
one 0.2 m gap. Sealing it to the plenum floor (`containmentTopZ = 2.6`) removes
the recirculation path entirely and should let the unit run closer to balance
safely. Quantify it with:

```bash
PARAM=containmentTopZ ./sweep.sh 2.2 2.3 2.4 2.5
```

## Visual comparison

Design point at 1.41 m/s — cold aisle uniformly cold across all 4 m, hot air
confined to the hot aisle and the return plenum, cold air bypassing outward
through the gap:

![pass](case/slice.png)

At 0.70 m/s the hot layer fills the upper cold aisle and reaches the fan wall
unit itself; see `runs/anim/frame_00.png`, or the animation in
[runs/sweep.mp4](runs/sweep.mp4).

## A note on the numbers

Temperatures are area-averages over the cabinet face. Where the face flow is
strongly non-uniform, `ṁ · cp · ΔT` computed from area-averaged temperatures
under-reports the heat removed; this is an artefact of area-averaging, not an
energy imbalance in the solver. In the well-behaved runs the check closes to
about 1 % (1.847 kg/s × 1005 × 16.02 K = 29.7 kW against 30 kW at 1.41 m/s).

All runs used 3,000 SIMPLE iterations on 107,520 cells; the metrics are flat well
before the end (see `case/metrics.png`).

## Changed from the earlier configuration

These results supersede an earlier geometry in which the return was a grille in
the hot-aisle ceiling and the cold aisle was 1.8 m. Moving the intake to the top
of the fan wall unit required adding a ceiling return plenum, which changes the
answer in two ways worth noting:

- **Failures are gentler.** Hot air now has a designed route back to the unit,
  so undersupply no longer forces the entire return through the cold aisle. The
  worst case fell from 44.2 °C mean / 78.8 °C peak to 28.9 / 37.7 °C.
- **The peak/mean split got sharper, not milder.** Capping the cold aisle with
  the plenum floor gives the recirculating layer a ceiling to spread along, so
  it reaches the cabinet face across the full aisle depth rather than pooling in
  a corner.

The balance-point threshold landed at 1.29 m/s in both geometries, which is
reassuring: it is set by the server airflow demand, not by the return path.
