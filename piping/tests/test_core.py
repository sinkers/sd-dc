"""Tests for piping/core: the FreeCAD-free router and validator.

  cd piping && python3 -m pytest -q tests      (or: python3 -m unittest)

Scenarios A-E are the five in routing_report.html. D and E are layouts that
cannot be built, so the router must refuse them with the right reason.
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core import (Box, Nozzle, RouteOptions, centreline_parts,  # noqa: E402
                  list_specs, route_network, route_pipe, spec_for,
                  validate_route)

DN100 = spec_for(100)
BR = DN100.bend_radius


def codes(issues):
    return sorted({i["code"] for i in issues})


def assert_buildable(tc, res, spec, a, b, obstacles, clearance=50.0):
    tc.assertTrue(res.ok, res.failure)
    tc.assertEqual(res.points[0], a.pos, "route must start on the outlet")
    tc.assertEqual(res.points[-1], b.pos, "route must end on the inlet")
    tc.assertEqual(validate_route(res.points, spec, a, b, obstacles,
                                  clearance), [])


class Specs(unittest.TestCase):
    def test_long_radius(self):
        self.assertAlmostEqual(BR, 171.45)
        self.assertEqual(DN100.od, 114.3)

    def test_unknown_dn_refused(self):
        with self.assertRaises(ValueError):
            spec_for(90)

    def test_list(self):
        self.assertEqual([s["dn"] for s in list_specs()][:3], [25, 32, 40])


class Validate(unittest.TestCase):
    a = Nozzle("P.out", (0, 0, 0), (1, 0, 0))
    b = Nozzle("H.in", (2000, 1000, 0), (0, -1, 0))

    def test_good_l(self):
        self.assertEqual(validate_route([(0, 0, 0), (2000, 0, 0),
                                         (2000, 1000, 0)], DN100,
                                        self.a, self.b), [])

    def test_each_rule(self):
        cases = {
            "not_orthogonal": [(0, 0, 0), (2000, 1000, 0)],
            "start_direction": [(0, 0, 0), (0, 1000, 0), (2000, 1000, 0)],
            "end_off_nozzle": [(0, 0, 0), (2000, 0, 0), (2000, 900, 0)],
            "segment_too_short": [(0, 0, 0), (100, 0, 0), (100, 1000, 0),
                                  (2000, 1000, 0)],
        }
        for code, pts in cases.items():
            with self.subTest(code):
                self.assertIn(code, codes(validate_route(pts, DN100,
                                                         self.a, self.b)))

    def test_reversal(self):
        issues = validate_route([(0, 0, 0), (1000, 0, 0), (500, 0, 0)], DN100)
        self.assertIn("reversal", codes(issues))

    def test_interior_needs_two_bend_radii(self):
        pts = [(0, 0, 0), (500, 0, 0), (500, 300, 0), (2000, 300, 0)]
        issues = validate_route(pts, DN100)
        short = [i for i in issues if i["code"] == "segment_too_short"]
        self.assertEqual(short[0]["segment"], 1)
        self.assertAlmostEqual(short[0]["min_mm"], 2 * BR, places=1)

    def test_collision_uses_radius_plus_clearance(self):
        pts = [(0, 0, 0), (2000, 0, 0), (2000, 1000, 0)]
        near = Box("TRAY", (500, 150, -50), (900, 400, 50))   # 150 from axis
        self.assertIn("collision", codes(validate_route(
            pts, DN100, self.a, self.b, [near], clearance=100)))
        self.assertEqual(validate_route(pts, DN100, self.a, self.b, [near],
                                        clearance=50), [])


class ScenarioA(unittest.TestCase):
    """Pump to heat exchanger past a full-height column and a cable tray."""

    def test_route_around(self):
        a = Nozzle("PUMP.out", (500, 0, 600), (1, 0, 0))
        b = Nozzle("HX.in", (3500, 0, 600), (-1, 0, 0))
        obs = [Box("PUMP", (-500, -400, 0), (500, 400, 1200)),
               Box("HX", (3500, -400, 0), (4500, 400, 1200)),
               Box("COLUMN", (1600, -200, 0), (2000, 200, 6000)),
               Box("TRAY", (0, -1500, 0), (5000, -1200, 150))]
        res = route_pipe(DN100, a, b, obs)
        assert_buildable(self, res, DN100, a, b, obs)
        self.assertEqual(len(res.points) - 2, 4)


class ScenarioB(unittest.TestCase):
    """Ground-level pump up over a platform into the top of a tank."""

    def test_rise_and_top_entry(self):
        a = Nozzle("PUMP.out", (500, 0, 300), (1, 0, 0))
        b = Nozzle("TANK.in", (3000, 0, 2500), (0, 0, 1))
        obs = [Box("PUMP", (-500, -300, 0), (500, 300, 600)),
               Box("TANK", (2500, -500, 1000), (3500, 500, 2500)),
               Box("PLATFORM", (1200, -1000, 0), (2000, 1000, 1200))]
        res = route_pipe(DN100, a, b, obs)
        assert_buildable(self, res, DN100, a, b, obs)
        d = [res.points[-1][k] - res.points[-2][k] for k in range(3)]
        self.assertLess(d[2], 0, "must arrive downwards into a top inlet")


class ScenarioC(unittest.TestCase):
    """Three parallel pumps into one DN200 header."""

    def test_manifold(self):
        header = Box("HEADER", (1890, -500, 90), (2110, 3500, 310))
        items, obs = [], [header]
        for k, y in enumerate((0, 1500, 3000)):
            obs.append(Box(f"PUMP{k}", (-500, y - 300, 0), (500, y + 300, 900)))
            items.append((f"B{k}", DN100,
                          Nozzle(f"PUMP{k}.out", (500, y, 600), (1, 0, 0)),
                          Nozzle(f"HEADER.in{k}", (1890, y, 200), (-1, 0, 0))))
        results = route_network(items, obs)
        for (pid, spec, a, b), (_, res) in zip(items, results):
            with self.subTest(pid):
                assert_buildable(self, res, spec, a, b, obs)
                self.assertEqual(len(res.points) - 2, 2)


class ScenarioD(unittest.TestCase):
    """An obstacle 100 mm in front of the outlet: no room for the first elbow."""

    def test_blocked_outlet(self):
        a = Nozzle("PUMP.out", (500, 0, 600), (1, 0, 0))
        b = Nozzle("HX.in", (3500, 0, 600), (-1, 0, 0))
        obs = [Box("PUMP", (-500, -400, 0), (500, 400, 1200)),
               Box("BLOCKER", (600, -500, 0), (900, 500, 1500)),
               Box("HX", (3500, -400, 0), (4500, 400, 1200))]
        res = route_pipe(DN100, a, b, obs)
        self.assertFalse(res.ok)
        f = res.failure
        self.assertEqual(f["reason"], "blocked_nozzle")
        self.assertEqual((f["nozzle"], f["obstacle"]), ("PUMP.out", "BLOCKER"))
        self.assertEqual(f["measured"]["gap_mm"], 100)
        # BR + radius + clearance = 171.45 + 57.15 + 50
        self.assertAlmostEqual(f["measured"]["need_mm"], 278.6)
        self.assertTrue(f["suggest"])

    def test_moving_it_by_the_shortfall_clears_it(self):
        a = Nozzle("PUMP.out", (500, 0, 600), (1, 0, 0))
        b = Nozzle("HX.in", (3500, 0, 600), (-1, 0, 0))
        x = 500 + 278.6 + 0.5
        obs = [Box("PUMP", (-500, -400, 0), (500, 400, 1200)),
               Box("BLOCKER", (x, -500, 0), (x + 300, 500, 1500)),
               Box("HX", (3500, -400, 0), (4500, 400, 1200))]
        res = route_pipe(DN100, a, b, obs)
        assert_buildable(self, res, DN100, a, b, obs)


class ScenarioE(unittest.TestCase):
    """An inlet boxed in on every side it could be approached from."""

    def test_enclosed_inlet(self):
        a = Nozzle("PUMP.out", (0, 0, 600), (1, 0, 0))
        b = Nozzle("HX.in", (3500, 0, 600), (-1, 0, 0))
        obs = [Box("PUMP", (-1000, -400, 0), (0, 400, 1200)),
               Box("HX", (3500, -300, 300), (4500, 300, 1000)),
               Box("FRONT", (3000, -400, 200), (3100, 400, 1100)),
               Box("LEFT", (3000, 300, 200), (4600, 400, 1100)),
               Box("RIGHT", (3000, -400, 200), (4600, -300, 1100)),
               Box("ROOF", (3000, -400, 1000), (4600, 400, 1100)),
               Box("FLOOR", (3000, -400, 200), (4600, 400, 300))]
        res = route_pipe(DN100, a, b, obs)
        self.assertFalse(res.ok)
        self.assertEqual(res.failure["reason"], "enclosed_inlet")
        self.assertEqual(res.failure["nozzle"], "HX.in")


class RouterRules(unittest.TestCase):
    def test_endpoints_are_never_snapped(self):
        a = Nozzle("A", (123.4, 56.7, 890.1), (0, 1, 0))
        b = Nozzle("B", (2345.6, 1789.0, 410.2), (0, 0, 1))
        res = route_pipe(DN100, a, b)
        assert_buildable(self, res, DN100, a, b, [])

    def test_short_jog_is_routed_long_way(self):
        # 200 mm offset is less than 2 x BR, so a plain Z-bend cannot be built.
        a = Nozzle("A", (0, 0, 0), (1, 0, 0))
        b = Nozzle("B", (3000, 200, 0), (-1, 0, 0))
        res = route_pipe(DN100, a, b)
        assert_buildable(self, res, DN100, a, b, [])
        self.assertGreater(len(res.points) - 2, 2)

    def test_straight_through(self):
        a = Nozzle("A", (0, 0, 0), (1, 0, 0))
        b = Nozzle("B", (1000, 0, 0), (-1, 0, 0))
        res = route_pipe(DN100, a, b)
        self.assertEqual(res.points, [a.pos, b.pos])

    def test_budget(self):
        a = Nozzle("A", (0, 0, 0), (1, 0, 0))
        b = Nozzle("B", (5000, 3000, 2000), (0, 1, 0))
        res = route_pipe(DN100, a, b, opts=RouteOptions(max_expansions=2))
        self.assertEqual(res.failure["reason"], "no_path_within_budget")

    def test_second_pipe_avoids_first(self):
        items = [("P1", DN100, Nozzle("A1", (0, 0, 0), (1, 0, 0)),
                  Nozzle("B1", (4000, 0, 0), (-1, 0, 0))),
                 ("P2", DN100, Nozzle("A2", (2000, -1000, 0), (0, 1, 0)),
                  Nozzle("B2", (2000, 1000, 0), (0, -1, 0)))]
        (_, r1), (_, r2) = route_network(items)
        self.assertTrue(r1.ok and r2.ok)
        self.assertEqual(r1.points, [(0, 0, 0), (4000, 0, 0)])
        self.assertGreater(len(r2.points), 2, "P2 must step over P1")

    def test_pipes_meet_at_a_tee(self):
        tee = (3000, 0, 1000)
        items = [("IN", DN100, Nozzle("S.out", (0, 0, 1000), (1, 0, 0)),
                  Nozzle("TEE.in", tee, (-1, 0, 0))),
                 ("A", DN100, Nozzle("TEE.a", tee, (0, 1, 0)),
                  Nozzle("X.in", (5000, 3000, 300), (0, -1, 0))),
                 ("B", DN100, Nozzle("TEE.b", tee, (1, 0, 0)),
                  Nozzle("Y.in", (8000, 0, 1000), (-1, 0, 0)))]
        for pid, res in route_network(items):
            self.assertTrue(res.ok, (pid, res.failure))


class Parts(unittest.TestCase):
    def test_cut_lengths_and_elbows(self):
        pts = [(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (2000, 1000, 0)]
        parts = centreline_parts(pts, DN100)
        kinds = [p["type"] for p in parts]
        self.assertEqual(kinds, ["straight", "elbow", "straight", "elbow",
                                 "straight"])
        lengths = [p["length_mm"] for p in parts if p["type"] == "straight"]
        self.assertAlmostEqual(lengths[0], 1000 - BR, places=1)
        self.assertAlmostEqual(lengths[1], 1000 - 2 * BR, places=1)
        e = parts[1]
        self.assertEqual(e["entry"], [round(1000 - BR, 2), 0, 0])
        self.assertEqual(e["exit"], [1000, round(BR, 2), 0])
        self.assertEqual(e["centre"], [round(1000 - BR, 2), round(BR, 2), 0])
        # Chain: each part starts where the last ended.
        ends = [p.get("end", p.get("exit")) for p in parts[:-1]]
        starts = [p.get("start", p.get("entry")) for p in parts[1:]]
        self.assertEqual(ends, starts)


class Agreement(unittest.TestCase):
    """Whatever the router returns, the validator must accept."""

    def test_random_layouts(self):
        rng = random.Random(7)
        routed = 0
        for trial in range(60):
            obs = []
            for k in range(rng.randint(0, 6)):
                lo = [rng.uniform(-1000, 5000), rng.uniform(-2000, 2000),
                      rng.uniform(0, 2000)]
                size = [rng.uniform(200, 1500) for _ in range(3)]
                obs.append(Box(f"O{k}", tuple(lo),
                               tuple(lo[i] + size[i] for i in range(3))))
            dirs = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)]
            a = Nozzle("A", (rng.uniform(-500, 0), rng.uniform(-500, 500),
                             rng.uniform(200, 1500)), rng.choice(dirs))
            b = Nozzle("B", (rng.uniform(3000, 4500), rng.uniform(-500, 500),
                             rng.uniform(200, 1500)), rng.choice(dirs))
            spec = spec_for(rng.choice((50, 80, 100, 150)))
            res = route_pipe(spec, a, b, obs,
                             RouteOptions(max_expansions=20_000))
            if res.ok:
                routed += 1
                with self.subTest(trial=trial):
                    self.assertEqual(
                        validate_route(res.points, spec, a, b, obs, 50.0), [])
            else:
                self.assertIn(res.failure["reason"],
                              {"blocked_nozzle", "enclosed_inlet",
                               "enclosed_outlet", "no_path",
                               "no_path_within_budget"})
        self.assertGreater(routed, 30)


REVB = os.environ.get("PIPING_REVB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "private", "revb_chw.json")


@unittest.skipUnless(os.path.exists(REVB),
                     "no Rev B benchmark; see tools/extract_revb.py")
class RevB(unittest.TestCase):
    """34 hand-routed pipes from a real plant room (project data, not in git)."""

    def test_router_matches_or_beats_hand_routes(self):
        sys.path.insert(0, os.path.join(os.path.dirname(REVB), "..", "tools"))
        import bench_revb
        rows = bench_revb.run(REVB)
        self.assertEqual(len(rows), 34)
        for r in rows:
            with self.subTest(r["id"]):
                self.assertTrue(r["ok"], r.get("failure"))
                self.assertEqual(r["hand_issues"], [])
                self.assertEqual(r["router_issues"], [])
                self.assertLessEqual(r["router_m"], r["hand_m"] + 0.01)
                self.assertLessEqual(r["router_elbows"], r["hand_elbows"])

    def test_network(self):
        sys.path.insert(0, os.path.join(os.path.dirname(REVB), "..", "tools"))
        import bench_revb
        rows = bench_revb.run(REVB, network=True)
        self.assertTrue(all(r["ok"] for r in rows),
                        [r["id"] for r in rows if not r["ok"]])


if __name__ == "__main__":
    unittest.main()
