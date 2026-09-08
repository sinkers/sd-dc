"""The reduced-order hall model: state, derivatives, and the integrator.

Node graph (see topology.py):

    fan-wall modules -> cold zones -> racks -> hot aisle -> return -> modules

Every node is a well-mixed, mass-balanced air volume, so the loop conserves
energy by construction: the only source is IT load and the only sink is the
coils. `test_energy_balance.py` holds it to the same 0.1% closure the CFD
achieves.

Dynamic states (58 for a 24-rack hall):

    T_m    (n_racks)    rack thermal mass — sets the 30-60 s lag after a load step
    Q      (n_racks)    rack fan airflow, lagging its target (see params.fan_tau_s)
    T_cold (n_zones)    cold aisle air, a few seconds of mixing
    T_hot  (1)          hot aisle air
    T_ret  (1)          return path back to the unit intakes, ~10 s of transport
    T_sup  (n_modules)  coil discharge, first-order lag on the setpoint

Rack exhaust temperature is *not* a state: the air inside a rack has a
sub-second residence time, so it is solved algebraically from the mass
temperature each step. The lag the twin shows after a load step comes from the
metal, which is where it comes from in reality.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from . import gap, rackfan
from .constants import CP, density, to_celsius, to_kelvin
from .params import RomParams
from .topology import HallSpec


@dataclass
class Inputs:
    """Boundary conditions / control setpoints at one instant."""

    rack_kw: np.ndarray
    unit_on: np.ndarray
    supply_temp_c: float
    airflow_fraction: np.ndarray

    @classmethod
    def design(cls, spec: HallSpec) -> "Inputs":
        return cls(
            rack_kw=np.array([r.design_kw for r in spec.racks], dtype=float),
            unit_on=np.ones(len(spec.modules), dtype=bool),
            supply_temp_c=spec.supply_temp_c,
            airflow_fraction=np.ones(len(spec.modules)),
        )

    def with_units_off(self, spec: HallSpec, names) -> "Inputs":
        on = self.unit_on.copy()
        for n in names:
            on[spec.module_names.index(n)] = False
        return replace(self, unit_on=on)


@dataclass
class State:
    t: float
    T_m: np.ndarray
    Q: np.ndarray
    T_cold: np.ndarray
    T_hot: float
    T_ret: float
    T_sup: np.ndarray

    def pack(self) -> np.ndarray:
        return np.concatenate(
            [self.T_m, self.Q, self.T_cold, [self.T_hot], [self.T_ret], self.T_sup]
        )

    @classmethod
    def unpack(cls, vec: np.ndarray, t: float, n_racks: int, n_zones: int) -> "State":
        i = 0
        T_m = vec[i : i + n_racks]
        i += n_racks
        Q = vec[i : i + n_racks]
        i += n_racks
        T_cold = vec[i : i + n_zones]
        i += n_zones
        T_hot = float(vec[i])
        i += 1
        T_ret = float(vec[i])
        i += 1
        return cls(
            t=t, T_m=T_m, Q=Q, T_cold=T_cold, T_hot=T_hot, T_ret=T_ret, T_sup=vec[i:]
        )


@dataclass
class Observables:
    """Everything derived from a state — what telemetry publishes."""

    rack_flow: np.ndarray  # kg/s
    rack_inlet_k: np.ndarray
    rack_inlet_peak_k: np.ndarray
    rack_exhaust_k: np.ndarray
    rack_recirc_fraction: np.ndarray
    rack_kw: np.ndarray
    module_flow: np.ndarray  # kg/s
    module_duty_kw: np.ndarray
    module_saturated: np.ndarray
    zone_net_flow: np.ndarray  # kg/s, sign = the verdict
    zone_spill: np.ndarray
    zone_supply: np.ndarray
    zone_demand: np.ndarray
    it_load_kw: float
    cooling_kw: float
    storage_kw: float  # rate heat is going INTO the hall's thermal mass
    return_flow: float
    mass_residual: float
    field_scale: float
    field_offset_k: float
    extras: dict = field(default_factory=dict)


class HallModel:
    def __init__(self, spec: HallSpec, params: RomParams | None = None):
        self.spec = spec
        self.params = params or RomParams.load()
        self.n_racks = len(spec.racks)
        self.n_zones = len(spec.zones)
        self.n_modules = len(spec.modules)
        self._zone_of = np.array(spec.rack_zone_indices())
        self._zone_volume = np.array([z.volume_m3 for z in spec.zones])
        self._capacity_w = np.array([m.capacity_kw * 1000.0 for m in spec.modules])
        self._mass_j_per_k = np.array(
            [
                max(self.params.thermal_mass(r.rack_class), 1.0) * 1000.0
                for r in spec.racks
            ]
        )
        # Metal-to-air conductance, sized per rack from its design load and the
        # heatsink temperature difference it runs at. A rack with no design load
        # gets a nominal value so the algebra stays well posed.
        self._ua_w_per_k = np.array(
            [
                max(r.design_kw, 1.0) * 1000.0 / self.params.rack_metal_delta_t_k
                for r in spec.racks
            ]
        )
        self._w = gap.distribution_matrix(spec, self.params)
        # The reference operating point the baked CFD field textures were
        # rendered at, used to remap them for the current state.
        self._field_ref_dt = spec.design_delta_t_k

    # -- initialisation ------------------------------------------------------
    def initial_state(self, inputs: Inputs | None = None) -> State:
        inputs = inputs or Inputs.design(self.spec)
        t_sup = to_kelvin(inputs.supply_temp_c)
        rack_w = np.asarray(inputs.rack_kw, dtype=float) * 1000.0

        # Guess the hall's temperature rise from the load and the airflow the
        # fans are actually delivering, rather than assuming the design rise.
        # The real rise is smaller (the fan wall moves more air than the racks
        # need), and starting 7 K too hot makes the coils look momentarily
        # capacity-limited and costs integration time settling out of it.
        m_mod = rackfan.module_mass_flow(
            self.spec,
            inputs.unit_on,
            inputs.airflow_fraction,
            np.full(self.n_modules, t_sup),
            self.params,
        )
        hall_dt = rack_w.sum() / max(float(m_mod.sum()) * CP, 1e-9)
        t_hot = t_sup + min(hall_dt, 3.0 * self.spec.design_delta_t_k)

        return State(
            t=0.0,
            # the metal sits above the air by whatever its own load requires
            T_m=t_sup + 0.5 * hall_dt + rack_w / self._ua_w_per_k,
            Q=rackfan.rack_mass_flow(self.spec, self.params, inputs.rack_kw),
            T_cold=np.full(self.n_zones, t_sup),
            T_hot=t_hot,
            T_ret=t_hot,
            T_sup=np.full(self.n_modules, t_sup),
        )

    # -- core ---------------------------------------------------------------
    def evaluate(self, state: State, inputs: Inputs) -> tuple[np.ndarray, Observables]:
        """Derivatives of the packed state, plus the observables for this instant."""
        p = self.params
        spec = self.spec
        rack_kw = np.asarray(inputs.rack_kw, dtype=float)
        rack_w = rack_kw * 1000.0

        # Fans chase their target rather than jumping to it (params.fan_tau_s).
        m_target = rackfan.rack_mass_flow(spec, p, rack_kw)
        m_rack = np.maximum(state.Q, 0.0)
        dQ = (m_target - state.Q) / p.fan_tau_s
        m_mod = rackfan.module_mass_flow(
            spec, inputs.unit_on, inputs.airflow_fraction, state.T_sup, p
        )

        sol = gap.solve(spec, p, m_rack, m_mod)
        phi = sol.rack_recirc_fraction

        # Rack intake: a blend of its cold zone and whatever it entrains from
        # the hot aisle. This is the line the whole model turns on.
        T_zone_of_rack = state.T_cold[self._zone_of]
        T_in = (1.0 - phi) * T_zone_of_rack + phi * state.T_hot

        # Rack air is quasi-steady: solve the exhaust temperature that balances
        # the heat the metal is giving up against the air carrying it away.
        #   m cp (T_ex - T_in) = UA (T_m - (T_in + T_ex)/2)
        a = m_rack * CP
        b = self._ua_w_per_k
        denom = a + b / 2.0
        T_ex = np.where(
            m_rack > 1e-6,
            (a * T_in + b * state.T_m - b * T_in / 2.0) / np.maximum(denom, 1e-9),
            T_in,
        )
        q_to_air = a * (T_ex - T_in)

        dT_m = (rack_w - q_to_air) / self._mass_j_per_k

        # -- cold zones ------------------------------------------------------
        rho_cold = np.array([density(t) for t in state.T_cold])
        cap_cold = rho_cold * self._zone_volume
        # supply streams: module i contributes w[i,j] of its flow at T_sup[i]
        supply_flux = self._w.T @ (m_mod * state.T_sup)  # kg/s * K
        supply_mass = self._w.T @ m_mod
        # zone-to-zone migration: donors pool, takers draw from the pool
        transfer = sol.zone_supply - sol.zone_supply_direct
        gives = np.clip(-transfer, 0.0, None)
        takes = np.clip(transfer, 0.0, None)
        pooled = gives.sum()
        T_pool = (
            float((gives * state.T_cold).sum() / pooled) if pooled > 1e-9 else 0.0
        )
        dT_cold = (
            supply_flux
            - supply_mass * state.T_cold
            + takes * (T_pool - state.T_cold)
            - gives * 0.0  # outflow at own temperature: no effect on the mean
        ) / np.maximum(cap_cold, 1e-9)

        # -- hot aisle -------------------------------------------------------
        cap_hot = density(state.T_hot) * spec.hot_aisle_volume_m3
        dT_hot = (
            float((m_rack * (T_ex - state.T_hot)).sum())
            + float((sol.zone_spill * (state.T_cold - state.T_hot)).sum())
        ) / max(cap_hot, 1e-9)

        # -- return path -----------------------------------------------------
        return_flow = float(m_mod.sum())
        cap_ret = (
            density(state.T_ret) * spec.return_volume_m3 * p.return_mix_factor
        )
        dT_ret = return_flow * (state.T_hot - state.T_ret) / max(cap_ret, 1e-9)

        # -- coils -----------------------------------------------------------
        setpoint = to_kelvin(inputs.supply_temp_c)
        with np.errstate(divide="ignore", invalid="ignore"):
            floor = state.T_ret - self._capacity_w / np.maximum(m_mod * CP, 1e-9)
        target = np.where(m_mod > 1e-6, np.maximum(setpoint, floor), setpoint)
        saturated = (target > setpoint + 1e-6) & (m_mod > 1e-6)
        dT_sup = (target - state.T_sup) / p.coil_tau_s

        # -- observables -----------------------------------------------------
        phi_peak = np.clip(phi * p.peak_multiplier, 0.0, 1.0)
        T_in_peak = (1.0 - phi_peak) * T_zone_of_rack + phi_peak * state.T_hot

        duty_w = np.where(m_mod > 1e-6, m_mod * CP * (state.T_ret - state.T_sup), 0.0)
        it_kw = float(rack_kw.sum())
        cooling_kw = float(duty_w.sum()) / 1000.0

        # Rate at which heat is accumulating in the hall's thermal mass. At
        # steady state this is zero and IT load equals cooling duty; during a
        # load step it is the difference between them, which is why comparing
        # load against duty alone is only a meaningful check at equilibrium.
        storage_w = (
            float((self._mass_j_per_k * dT_m).sum())
            + float((cap_cold * CP * dT_cold).sum())
            + cap_hot * CP * dT_hot
            + cap_ret * CP * dT_ret
        )

        # Field remap for the baked CFD slice textures: shift by the supply-temp
        # difference and stretch by the ratio of hall dT to the baked case's.
        hall_dt = max(float(state.T_hot - state.T_sup.mean()), 0.1)
        obs = Observables(
            rack_flow=m_rack,
            rack_inlet_k=T_in,
            rack_inlet_peak_k=T_in_peak,
            rack_exhaust_k=T_ex,
            rack_recirc_fraction=phi,
            rack_kw=rack_kw,
            module_flow=m_mod,
            module_duty_kw=duty_w / 1000.0,
            module_saturated=saturated,
            zone_net_flow=sol.zone_net,
            zone_spill=sol.zone_spill,
            zone_supply=sol.zone_supply,
            zone_demand=sol.zone_demand,
            it_load_kw=it_kw,
            cooling_kw=cooling_kw,
            storage_kw=storage_w / 1000.0,
            return_flow=return_flow,
            mass_residual=float(
                m_rack.sum() + sol.spill_total - sol.recirc_total - return_flow
            ),
            field_scale=hall_dt / self._field_ref_dt,
            field_offset_k=float(state.T_sup.mean()) - spec.supply_temp_k(),
            extras={
                "zone_recirc_fraction": sol.zone_recirc_fraction,
                "recirc_total": sol.recirc_total,
                "spill_total": sol.spill_total,
            },
        )

        deriv = np.concatenate([dT_m, dQ, dT_cold, [dT_hot], [dT_ret], dT_sup])
        return deriv, obs

    # -- integration --------------------------------------------------------
    def step(self, state: State, inputs: Inputs, dt: float) -> tuple[State, Observables]:
        """One explicit midpoint (RK2) step. Returns the new state and the
        observables evaluated at the *start* of the step."""
        k1, obs = self.evaluate(state, inputs)
        y0 = state.pack()
        mid = State.unpack(y0 + 0.5 * dt * k1, state.t + 0.5 * dt, self.n_racks, self.n_zones)
        k2, _ = self.evaluate(mid, inputs)
        y1 = y0 + dt * k2
        return State.unpack(y1, state.t + dt, self.n_racks, self.n_zones), obs

    def steady_state(
        self,
        inputs: Inputs | None = None,
        dt: float = 0.5,
        max_time: float = 4000.0,
        tol: float = 1e-6,
        state: State | None = None,
    ) -> tuple[State, Observables]:
        """Integrate to steady state. Used for calibration and validation, where
        the comparison is against converged CFD."""
        inputs = inputs or Inputs.design(self.spec)
        state = state or self.initial_state(inputs)
        steps = int(max_time / dt)
        converged = False
        for _ in range(steps):
            deriv, _ = self.evaluate(state, inputs)
            if float(np.abs(deriv).max()) < tol:
                converged = True
                break
            state, _ = self.step(state, inputs, dt)
        deriv, obs = self.evaluate(state, inputs)
        # A hall whose coils are saturated below its IT load has no steady state:
        # it heats until something trips. Flag it rather than returning the state
        # the integrator happened to stop at as if it had settled.
        obs.extras["converged"] = converged
        obs.extras["max_derivative_k_per_s"] = float(np.abs(deriv).max())
        return state, obs

    # -- reporting helpers --------------------------------------------------
    def verdict(self, obs: Observables) -> tuple[str, str]:
        """ASHRAE verdict on an observable set, matching plot_hall.py's logic:
        FAIL on any rack mean above allowable, MARGINAL on any face peak above
        allowable, otherwise PASS."""
        spec = self.spec
        live = obs.rack_kw > 0.0
        if not live.any():
            return "PASS", "no live racks"
        mean_c = to_celsius(obs.rack_inlet_k[live])
        peak_c = to_celsius(obs.rack_inlet_peak_k[live])
        names = [r.name for r, on in zip(spec.racks, live) if on]
        worst = int(np.argmax(mean_c))
        worst_peak = int(np.argmax(peak_c))
        if mean_c[worst] > spec.allowable_max_c:
            return (
                "FAIL",
                f"rack {names[worst]} ingests {mean_c[worst]:.2f} C, above the "
                f"{spec.allowable_max_c:.0f} C allowable limit",
            )
        if peak_c[worst_peak] > spec.allowable_max_c:
            return (
                "MARGINAL",
                f"every rack passes on mean intake (worst {mean_c[worst]:.2f} C) but "
                f"rack {names[worst_peak]} has a face peak of {peak_c[worst_peak]:.2f} C",
            )
        if mean_c[worst] > spec.recommended_max_c:
            return (
                "PASS",
                f"worst rack mean {mean_c[worst]:.2f} C is inside the "
                f"{spec.allowable_max_c:.0f} C allowable envelope",
            )
        return "PASS", f"worst rack mean {mean_c[worst]:.2f} C, inside recommended"
