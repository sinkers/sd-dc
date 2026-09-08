"""Heat exchangers by effectiveness-NTU. One class for the CDU plate and the
dry cooler coil, because they are the same object with different cold streams.

SPEC.md section 4.2 sets this out: reduce each exchanger to a couple of numbers
and there is no flow field left to resolve, which is the whole reason this model
is not CFD.

## The relations

    UA:   1/UA = 1/(c_h * m_h^0.8) + 1/(c_c * m_c^0.8)
    C     = m * cp                     per side
    NTU   = UA / C_min ,  Cr = C_min / C_max
    eps   = (1 - exp[-NTU(1-Cr)]) / (1 - Cr*exp[-NTU(1-Cr)])      counterflow
    Q     = eps * C_min * (T_h,in - T_c,in)

The flow exponent of 0.8 on each side is the turbulent Dittus-Boelter form. It
is why UA is not a constant: throttle the facility side and the plate's
conductance falls with it, roughly as the 0.8 power, so a CDU at 70 % flow is
not 70 % of a heat exchanger.

## Two different temperature differences, and getting them confused

This bit was wrong first time and the error is worth keeping visible, because
"approach" is used for both of these and they are not the same number.

For RD110's CDU plate: secondary 50 -> 40 C, facility 37 -> 47 C.

  * **inlet-to-inlet**, `T_h,in - T_c,in` = 50 - 37 = **13 K**. This is what the
    eps-NTU relation uses. eps is a fraction of *this*.
  * **terminal approach**, `T_h,out - T_c,in` = 40 - 37 = **3 K**. This is what
    an engineer means by the approach, and what RD110's four temperatures state.

Calibrating with `Q = eps * C_min * 3 K` asks for eps = 3.33, which is not a
fraction. The constructor now raises exactly that, with those words - it is how
the mistake was found. Read correctly, eps = (50-40)/(50-37) = 10/13 = 0.769,
which at Cr = 1 needs NTU = eps/(1-eps) = 3.33. The 3.33 turning up in both
places is a coincidence of RD110's numbers, and a misleading one.

## Reading it the other way round

Q is not what a plate decides here. The IT load fixes the duty, so the useful
question is the inlet-to-inlet difference the plate needs in order to shift it:

    dT_inlet_required = Q / (eps * C_min)

from which the terminal approach follows. `calibrate_from_temperatures` takes
RD110's four temperatures, so the model reproduces them by construction, and
`ua_scale` then says what a better or worse plate would do.

## Cr -> 1, and the limit that bites

Both sides of a CDU plate carry the same duty at the same delta-T, so C_h and
C_c are nearly equal and Cr is nearly 1. That is the worst case for a
counterflow exchanger: the eps-NTU expression above becomes 0/0 there and its
limit is eps = NTU/(1+NTU), which caps effectiveness well below 1 for any
realistic NTU. A plate matched like this cannot be made highly effective by
adding area alone, and that is a real constraint on the approach, not an
artefact - `effectiveness` handles the limit explicitly rather than dividing by
a number that is nearly zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import fluid

# Below this, Cr is treated as 1 and the limiting form is used. Set from where
# the general expression starts losing precision rather than from taste.
CR_UNITY_TOL = 1.0e-4

FLOW_EXPONENT = 0.8  # turbulent, Dittus-Boelter


def effectiveness(ntu: float, cr: float) -> float:
    """Counterflow effectiveness. Handles Cr -> 1 and Cr -> 0 explicitly."""
    if ntu <= 0.0:
        return 0.0
    if cr < CR_UNITY_TOL:
        return 1.0 - math.exp(-ntu)          # one side isothermal
    if abs(1.0 - cr) < CR_UNITY_TOL:
        return ntu / (1.0 + ntu)             # the limit that bites on a CDU plate
    e = math.exp(-ntu * (1.0 - cr))
    return (1.0 - e) / (1.0 - cr * e)


def ntu_for_effectiveness(eps: float, cr: float) -> float:
    """Inverse of `effectiveness`. Used to size UA from a target approach."""
    if not 0.0 < eps < 1.0:
        raise ValueError(f"effectiveness must be strictly between 0 and 1, got {eps}")
    if cr < CR_UNITY_TOL:
        return -math.log(1.0 - eps)
    if abs(1.0 - cr) < CR_UNITY_TOL:
        if eps >= 1.0:
            raise ValueError("effectiveness of 1 needs infinite area at Cr = 1")
        return eps / (1.0 - eps)
    arg = (1.0 - eps) / (1.0 - eps * cr)
    if arg <= 0.0:
        raise ValueError(f"effectiveness {eps} is unreachable at Cr = {cr}")
    return math.log(1.0 / arg) / (1.0 - cr)


@dataclass
class PlateExchanger:
    """A liquid-to-liquid plate, both sides PG25.

    `c_hot` and `c_cold` are the per-side conductance coefficients in the UA
    relation, in kW/K at unit mass flow. `ua_scale` multiplies the resulting UA,
    so a reviewer can ask "what if the plate were 20 % better" without touching
    the calibration.
    """

    name: str
    c_hot: float
    c_cold: float
    hot_t_c: float
    cold_t_c: float
    ua_scale: float = 1.0

    @classmethod
    def calibrate_from_temperatures(
        cls,
        name: str,
        hot_in_c: float,
        hot_out_c: float,
        cold_in_c: float,
        hot_flow_kgs: float,
        cold_flow_kgs: float,
    ) -> "PlateExchanger":
        """Find the UA implied by the four design temperatures.

        RD110 states all of them - secondary 50 -> 40 C, facility 37 C in - so
        the plate follows rather than being assumed:

            eps = (T_h,in - T_h,out) / (T_h,in - T_c,in) = 10/13 = 0.769

        Conductance is split evenly between the two sides, which is what a
        symmetric plate with similar flows gives - and both sides of a CDU are
        similar by construction.
        """
        hot_t_c = (hot_in_c + hot_out_c) / 2.0
        c_hot_flow = hot_flow_kgs * float(fluid.cp(hot_t_c)) / 1000.0
        c_cold_flow = cold_flow_kgs * float(fluid.cp(cold_in_c)) / 1000.0
        c_min = min(c_hot_flow, c_cold_flow)
        c_max = max(c_hot_flow, c_cold_flow)
        cr = c_min / c_max

        inlet_delta = hot_in_c - cold_in_c
        if inlet_delta <= 0:
            raise ValueError(
                f"{name}: hot inlet {hot_in_c} C is not above cold inlet "
                f"{cold_in_c} C, so no heat moves"
            )
        # eps is a fraction of the INLET-TO-INLET difference, not of the
        # terminal approach. Using the approach here asks for eps = 3.33.
        eps = (hot_in_c - hot_out_c) / inlet_delta
        if not 0.0 < eps < 1.0:
            raise ValueError(
                f"{name}: the stated temperatures imply effectiveness "
                f"{eps:.2f}, which is not a fraction. Check whether the 'approach' "
                f"being used is the terminal difference (T_h,out - T_c,in) rather "
                f"than the inlet-to-inlet difference (T_h,in - T_c,in) that "
                f"eps-NTU is defined against."
            )
        ua = ntu_for_effectiveness(eps, cr) * c_min

        # Split evenly: 1/UA = 1/(2*half) + 1/(2*half) => half = 2*UA... solve
        # 1/UA = 1/A + 1/A with A = c*m^0.8 on each side, so A = 2*UA.
        a_side = 2.0 * ua
        return cls(
            name=name,
            c_hot=a_side / hot_flow_kgs**FLOW_EXPONENT,
            c_cold=a_side / cold_flow_kgs**FLOW_EXPONENT,
            hot_t_c=hot_t_c,
            cold_t_c=cold_in_c,
        )

    # -- the relations ----------------------------------------------------

    def ua_kw_per_k(self, hot_flow_kgs: float, cold_flow_kgs: float) -> float:
        if hot_flow_kgs <= 0 or cold_flow_kgs <= 0:
            return 0.0
        inv = (1.0 / (self.c_hot * hot_flow_kgs**FLOW_EXPONENT)
               + 1.0 / (self.c_cold * cold_flow_kgs**FLOW_EXPONENT))
        return self.ua_scale / inv

    def capacities_kw_per_k(self, hot_flow_kgs: float, cold_flow_kgs: float):
        c_h = hot_flow_kgs * float(fluid.cp(self.hot_t_c)) / 1000.0
        c_c = cold_flow_kgs * float(fluid.cp(self.cold_t_c)) / 1000.0
        return c_h, c_c

    def state(self, hot_flow_kgs: float, cold_flow_kgs: float) -> dict:
        """Everything about the plate at these flows, load-independent."""
        ua = self.ua_kw_per_k(hot_flow_kgs, cold_flow_kgs)
        c_h, c_c = self.capacities_kw_per_k(hot_flow_kgs, cold_flow_kgs)
        c_min, c_max = min(c_h, c_c), max(c_h, c_c)
        if c_min <= 0 or ua <= 0:
            return {"name": self.name, "ua_kw_per_k": 0.0, "ntu": 0.0, "cr": 0.0,
                    "effectiveness": 0.0, "c_min_kw_per_k": 0.0, "c_max_kw_per_k": 0.0}
        ntu = ua / c_min
        cr = c_min / c_max
        return {
            "name": self.name,
            "ua_kw_per_k": round(ua, 2),
            "ntu": round(ntu, 4),
            "cr": round(cr, 4),
            "effectiveness": round(effectiveness(ntu, cr), 4),
            "c_min_kw_per_k": round(c_min, 2),
            "c_max_kw_per_k": round(c_max, 2),
            "ua_scale": self.ua_scale,
        }

    def inlet_delta_for_duty_k(self, duty_kw: float, hot_flow_kgs: float,
                               cold_flow_kgs: float) -> float | None:
        """Inlet-to-inlet difference the plate needs to shift `duty_kw`.

        The useful direction: the IT load fixes the duty, and this is what
        follows. Returns None where the plate cannot do it at all.
        """
        s = self.state(hot_flow_kgs, cold_flow_kgs)
        denom = s["effectiveness"] * s["c_min_kw_per_k"]
        if denom <= 0:
            return None
        return duty_kw / denom

    def terminal_approach_k(self, duty_kw: float, hot_flow_kgs: float,
                            cold_flow_kgs: float) -> float | None:
        """`T_h,out - T_c,in` - the approach an engineer means.

        Follows from the inlet-to-inlet difference less the hot side's own drop:
        the hot stream enters `dT_inlet` above the cold inlet and falls by
        `Q/C_h` across the plate.
        """
        inlet = self.inlet_delta_for_duty_k(duty_kw, hot_flow_kgs, cold_flow_kgs)
        if inlet is None:
            return None
        c_h, _ = self.capacities_kw_per_k(hot_flow_kgs, cold_flow_kgs)
        if c_h <= 0:
            return None
        return inlet - duty_kw / c_h

    def max_duty_kw(self, approach_k: float, hot_flow_kgs: float,
                    cold_flow_kgs: float) -> float:
        """Most it can shift across a given approach. Q = eps * C_min * dT."""
        s = self.state(hot_flow_kgs, cold_flow_kgs)
        return s["effectiveness"] * s["c_min_kw_per_k"] * approach_k
