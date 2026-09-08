"""Hydraulic elements: what each one does to pressure as a function of flow.

Every element answers one question - given a mass flow, what pressure does it
consume (or, for a pump, produce)? - and answers it together with the
derivative, because the Newton solve in hydraulics.py needs both and computing
them separately would evaluate the friction factor twice.

Sign convention throughout: `dp` is pressure *consumed* along the branch's own
direction. Resistances are positive; a pump is negative. So the branch equation
is always `p_from - p_to = sum(dp)`, with no special case for pumps.

Units are SI and absolute: Pa, kg/s, m. Datasheet units - m3/h, metres of head,
Kv - are converted at the constructor, never in the solve loop.

## The regularisation, and why it is here

Turbulent loss is `dp = K * m * |m|`, whose derivative `2*K*|m|` vanishes at
zero flow. A branch that happens to sit at zero flow would put a zero on the
Jacobian diagonal and make the step singular - and a shut valve puts a branch
there deliberately, every time the headline scenario runs.

So below `M_LAM` the quadratic is replaced by the straight line through the
same point: `dp = K * M_LAM * m`. Continuous in value at the crossover, with a
kink in the derivative, which Newton tolerates comfortably. The alternative -
flooring the derivative - is discontinuous in value, which it does not.

M_LAM is 1e-4 kg/s: seven orders below a nominal branch flow, so no operating
point of interest is ever inside the linear region.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import fluid

G = 9.80665  # m/s2

M_LAM = 1.0e-4  # kg/s - below this, loss is linearised. See the module docstring.

# Kv is m3/h of water at 1 bar. Converting Kv to K in Pa/(kg/s)^2:
#   dp[bar] = (Q[m3/h] / Kv)^2 * (rho/1000)   and   Q = m * 3600 / rho
#   => dp[Pa] = 1e5 * 3600^2 / 1000 * m^2 / (Kv^2 * rho)
KV_TO_K = 1.0e5 * 3600.0**2 / 1000.0  # = 1.296e9


def _quadratic_loss(k: float, m_dot: float) -> tuple[float, float]:
    """`dp = k*m*|m|` with the small-flow linearisation. Returns (dp, d(dp)/dm)."""
    if abs(m_dot) < M_LAM:
        return k * M_LAM * m_dot, k * M_LAM
    return k * m_dot * abs(m_dot), 2.0 * k * abs(m_dot)


class Element:
    """One hydraulic element. Subclasses implement `evaluate`."""

    name: str = "element"

    def evaluate(self, m_dot: float, t_c: float) -> tuple[float, float]:
        """Pressure consumed [Pa] and its derivative w.r.t. mass flow [Pa/(kg/s)]."""
        raise NotImplementedError


@dataclass
class Resistance(Element):
    """A bare loss coefficient. `dp = k * m * |m|`.

    The general case, and what a heat exchanger side reduces to once its rated
    pressure drop is known: `from_rating` turns one datasheet line into k.
    """

    k: float
    name: str = "resistance"

    @classmethod
    def from_rating(cls, dp_pa: float, m_dot: float, name: str = "resistance") -> "Resistance":
        """k from a rated pressure drop at a rated flow - the datasheet form."""
        if m_dot <= 0:
            raise ValueError("rated flow must be positive")
        return cls(k=dp_pa / (m_dot * m_dot), name=name)

    def evaluate(self, m_dot: float, t_c: float) -> tuple[float, float]:
        return _quadratic_loss(self.k, m_dot)


@dataclass
class Pipe(Element):
    """A straight run plus its fittings, by Darcy-Weisbach.

        dp = [ f*L/D + sum(zeta) ] * m^2 / (2 * rho * A^2)

    The friction factor is recomputed from the current flow every call, so the
    temperature dependence of viscosity reaches the pressure drop - the reason
    fluid.py exists. Its *derivative* is not carried into the Jacobian: df/dm is
    a small term next to the m^2, and dropping it costs an iteration at most
    while keeping the derivative in closed form. That makes this a quasi-Newton
    step, which converges to the same answer.

    Transition: laminar below Re 2300, Swamee-Jain above 4000, linear blend
    between. The blend is there so the solver never meets a step change in
    resistance mid-iteration; a real pipe's transition is not this tidy, and no
    conclusion in this model should rest on flow inside it.
    """

    length_m: float
    diameter_m: float
    roughness_m: float = 4.5e-5
    fittings_k: float = 0.0  # sum of fitting zeta values
    name: str = "pipe"

    @property
    def area_m2(self) -> float:
        return math.pi * self.diameter_m**2 / 4.0

    def friction_factor(self, m_dot: float, t_c: float) -> float:
        re = float(fluid.reynolds(m_dot, self.diameter_m, t_c))
        if re < 1.0:
            return 64.0  # vanishing flow; value is irrelevant, finiteness is not
        f_lam = 64.0 / max(re, 1.0)
        if re <= 2300.0:
            return f_lam
        f_turb = self._swamee_jain(max(re, 4000.0))
        if re >= 4000.0:
            return f_turb
        w = (re - 2300.0) / 1700.0
        return (1.0 - w) * (64.0 / 2300.0) + w * f_turb

    def _swamee_jain(self, re: float) -> float:
        term = self.roughness_m / (3.7 * self.diameter_m) + 5.74 / re**0.9
        return 0.25 / math.log10(term) ** 2

    def k_at(self, m_dot: float, t_c: float) -> float:
        rho = float(fluid.density(t_c))
        f = self.friction_factor(m_dot, t_c)
        zeta = f * self.length_m / self.diameter_m + self.fittings_k
        return zeta / (2.0 * rho * self.area_m2**2)

    def evaluate(self, m_dot: float, t_c: float) -> tuple[float, float]:
        return _quadratic_loss(self.k_at(m_dot, t_c), m_dot)

    def volume_m3(self) -> float:
        """Fluid held. Phase 2 needs it for the thermal capacitance."""
        return self.area_m2 * self.length_m


# Valve characteristics: fraction of rated Kv at fractional lift x in [0, 1].
def linear_characteristic(x: float, rangeability: float) -> float:
    return x


def equal_percentage_characteristic(x: float, rangeability: float) -> float:
    """Kv/Kv_rated = R^(x-1). Note this is R^-1 at x=0, not zero - a real
    equal-percentage plug seats against a hard cutoff, which `Valve` applies
    separately at `x <= seat_x`."""
    return rangeability ** (x - 1.0)


def quick_opening_characteristic(x: float, rangeability: float) -> float:
    return math.sqrt(max(x, 0.0))


CHARACTERISTICS = {
    "linear": linear_characteristic,
    "equal_percentage": equal_percentage_characteristic,
    "quick_opening": quick_opening_characteristic,
}


@dataclass
class Valve(Element):
    """A valve at fractional lift `position` in [0, 1].

    Isolation valves are linear; control valves are equal-percentage, which is
    what makes valve authority worth computing rather than assuming.

    A shut valve is `closed_k`, a large finite resistance - never infinite, and
    never a removed branch. loop_params.json `hydraulic.closed_valve_k` carries
    the reasoning; the short version is that infinity is singular and removing
    the branch would discard the thermal states whose temperature rise is the
    thing the scenario exists to show.
    """

    kv_rated: float  # m3/h at 1 bar, on water
    position: float = 1.0
    characteristic: str = "equal_percentage"
    rangeability: float = 50.0
    seat_x: float = 0.0  # at or below this lift the valve is shut
    closed_k: float = 1.0e10
    name: str = "valve"

    def __post_init__(self):
        if self.characteristic not in CHARACTERISTICS:
            raise ValueError(
                f"unknown valve characteristic {self.characteristic!r}; "
                f"expected one of {sorted(CHARACTERISTICS)}"
            )
        if self.kv_rated <= 0:
            raise ValueError("kv_rated must be positive")

    @property
    def is_closed(self) -> bool:
        return self.position <= self.seat_x

    def kv(self) -> float:
        if self.is_closed:
            return 0.0
        frac = CHARACTERISTICS[self.characteristic](
            min(max(self.position, 0.0), 1.0), self.rangeability
        )
        return self.kv_rated * frac

    def k_at(self, t_c: float) -> float:
        if self.is_closed:
            return self.closed_k
        rho = float(fluid.density(t_c))
        return KV_TO_K / (self.kv() ** 2 * rho)

    def evaluate(self, m_dot: float, t_c: float) -> tuple[float, float]:
        return _quadratic_loss(self.k_at(t_c), m_dot)


# How steeply head rises when flow reverses, as a multiple of the curve's own
# mean forward gradient. See PumpCurve.head_m.
REVERSE_STEEPNESS = 2.0


@dataclass
class PumpCurve:
    """Head curve in datasheet units: H[m] = h0 + h1*Q + h2*Q^2, Q in m3/h.

    Affinity for a speed ratio s = N/N_ref follows from H ~ N^2, Q ~ N:

        H(Q, s) = s^2*h0 + s*h1*Q + h2*Q^2

    which is the same quadratic with the first two coefficients scaled - the
    tidy result of substituting Q/s into the reference curve.

    ## Reverse flow, and a spurious root

    Below zero flow the published quadratic is not merely unmeasured, it is
    actively wrong: with h2 negative it curves back down, so H falls again as
    flow goes more negative. That gives the loop equation a second root at large
    negative flow which is a perfectly good solution of the algebra and complete
    nonsense as a pump - and the Newton solve will find it, given a network
    loose enough to push the operating point out that far.

    So for Q < 0 the quadratic is replaced by a steep straight line rising from
    shutoff head. A real pump does push back harder as flow is forced backwards
    through it, and monotonic-decreasing head over the whole flow range leaves
    the loop equation exactly one root. The line is scaled by the curve's own
    size (through `q_zero_head`) so it needs no tuning per pump, and it is
    written so the affinity relation still holds across it.

    ## And a rising portion near shutoff

    Three ordinary datasheet points routinely fit a quadratic whose vertex sits
    at positive flow - (0, 50), (100, 45), (200, 25) peaks at 16.7 m3/h, half a
    metre above shutoff. Harmless as a picture, but it makes head *rise* with
    flow over that stretch, and a network solve is only guaranteed a unique
    solution when every branch's pressure is monotonic in its flow. The failure
    is not subtle: Newton points downhill inside the rising region, the
    reverse-flow line points back up, and the iteration settles into a clean
    two-point limit cycle that never terminates.

    So head is clipped flat at shutoff over the rising stretch. The error is the
    half-metre the fit invented, in a region where a real curve is flat anyway,
    and in exchange the characteristic is monotonic over its whole range and the
    problem is well posed. `rise_above_shutoff_m` reports how much the clip is
    doing, because a large rise means the three points deserve a second look
    rather than a clip.
    """

    h0: float
    h1: float
    h2: float

    @classmethod
    def from_points(cls, points: list[tuple[float, float]]) -> "PumpCurve":
        """Fit through three (flow m3/h, head m) datasheet points.

        Three points is what a pump is usually specified by - shutoff, duty and
        runout - and three points determine a quadratic exactly, so this is an
        interpolation rather than a fit and cannot quietly smooth a bad point.
        """
        if len(points) != 3:
            raise ValueError("need exactly three (flow, head) points")
        qs = [p[0] for p in points]
        if len(set(qs)) != 3:
            raise ValueError("the three points must be at distinct flows")
        (q1, h1_), (q2, h2_), (q3, h3_) = points
        a = [[1.0, q1, q1 * q1], [1.0, q2, q2 * q2], [1.0, q3, q3 * q3]]
        c = _solve3(a, [h1_, h2_, h3_])
        return cls(h0=c[0], h1=c[1], h2=c[2])

    @property
    def q_zero_head(self) -> float:
        """Reference-curve flow at which head reaches zero [m3/h].

        Sets the scale of the reverse-flow extension. For a curve that never
        crosses zero at positive flow, falls back to the shutoff head over the
        linear coefficient, which is the same order of magnitude.
        """
        a, b, c = self.h2, self.h1, self.h0
        if abs(a) > 1e-15:
            disc = b * b - 4 * a * c
            if disc >= 0:
                roots = [(-b + math.sqrt(disc)) / (2 * a), (-b - math.sqrt(disc)) / (2 * a)]
                positive = [r for r in roots if r > 0]
                if positive:
                    return max(positive)
        if abs(b) > 1e-15:
            return abs(c / b)
        return 1.0

    @property
    def _reverse_slope(self) -> float:
        """Gradient of the reverse-flow line [m per m3/h]. Negative."""
        return -REVERSE_STEEPNESS * self.h0 / self.q_zero_head

    @property
    def q_peak(self) -> float:
        """Reference-curve flow at which the fitted quadratic peaks [m3/h].

        Zero unless the fit rises, in which case head is clipped flat below it.
        """
        if self.h2 >= 0 or self.h1 <= 0:
            return 0.0
        return -self.h1 / (2.0 * self.h2)

    @property
    def has_rising_fit(self) -> bool:
        return self.q_peak > 0.0

    def rise_above_shutoff_m(self) -> float:
        """How much head the fit invents above shutoff. Small is fine; a large
        value means the three datasheet points deserve a second look."""
        if not self.has_rising_fit:
            return 0.0
        q = self.q_peak
        return self.h0 + self.h1 * q + self.h2 * q * q - self.h0

    def head_m(self, q_m3h: float, speed: float = 1.0) -> float:
        if q_m3h < 0.0:
            return speed * speed * self.h0 + speed * self._reverse_slope * q_m3h
        q_ref = q_m3h / speed if speed > 0 else q_m3h
        if q_ref < self.q_peak:
            return speed * speed * self.h0  # clipped flat; see the class docstring
        return speed * speed * self.h0 + speed * self.h1 * q_m3h + self.h2 * q_m3h**2

    def slope_m_per_m3h(self, q_m3h: float, speed: float = 1.0) -> float:
        """dH/dQ, matching head_m in all three regions."""
        if q_m3h < 0.0:
            return speed * self._reverse_slope
        q_ref = q_m3h / speed if speed > 0 else q_m3h
        if q_ref < self.q_peak:
            return 0.0
        return speed * self.h1 + 2.0 * self.h2 * q_m3h


def _solve3(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination on a 3x3. Avoids importing numpy for one small solve
    at construction time."""
    m = [row[:] + [rhs] for row, rhs in zip(a, b)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(m[r][i]))
        if abs(m[p][i]) < 1e-14:
            raise ValueError("pump points are degenerate")
        m[i], m[p] = m[p], m[i]
        for r in range(3):
            if r == i:
                continue
            factor = m[r][i] / m[i][i]
            for c in range(i, 4):
                m[r][c] -= factor * m[i][c]
    return [m[i][3] / m[i][i] for i in range(3)]


@dataclass
class Pump(Element):
    """A pump on the branch, producing pressure rather than consuming it.

    Returns a negative `dp`, so the branch equation `p_from - p_to = sum(dp)`
    needs no special case: the pump simply makes the sum negative and pressure
    rises along the branch.

    Density enters twice and correctly: mass flow converts to the volumetric
    flow the curve is written in, and the resulting head in metres converts back
    to Pa. Over PG25's 0-60 C range that is a ~2.5 % effect, small but free.

    Beyond runout the quadratic goes negative, which is the right behaviour for
    a solver - the pump becomes a resistance - but is extrapolation past the
    published curve, so `beyond_curve` flags it for the caller to report.
    """

    curve: PumpCurve
    speed: float = 1.0
    max_flow_m3h: float = math.inf  # published runout, for the flag only
    name: str = "pump"

    def evaluate(self, m_dot: float, t_c: float) -> tuple[float, float]:
        rho = float(fluid.density(t_c))
        to_q = 3600.0 / rho  # m_dot [kg/s] -> Q [m3/h]
        q = m_dot * to_q
        head = self.curve.head_m(q, self.speed)
        dp = -rho * G * head
        # d(dp)/dm = -rho*g*(dH/dQ)*(dQ/dm) = -g*3600*(dH/dQ)
        ddp_dm = -G * 3600.0 * self.curve.slope_m_per_m3h(q, self.speed)
        return dp, ddp_dm

    def beyond_curve(self, m_dot: float, t_c: float) -> bool:
        q = m_dot * 3600.0 / float(fluid.density(t_c))
        return q > self.max_flow_m3h

    def shaft_kw(self, m_dot: float, t_c: float, efficiency: float = 0.75) -> float:
        rho = float(fluid.density(t_c))
        q_m3s = m_dot / rho
        head = self.curve.head_m(m_dot * 3600.0 / rho, self.speed)
        return max(rho * G * head * q_m3s, 0.0) / efficiency / 1000.0
