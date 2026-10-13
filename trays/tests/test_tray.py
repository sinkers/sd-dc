"""Tray supports: span choice, spacing, splices, clashes and the service.

Uses a synthetic tray so the tests carry no vendor data.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import service  # noqa: E402
import tray as T  # noqa: E402
from core.geom import Box, Nozzle  # noqa: E402

LADDER = T.TrayType("SYN", 600, 660, 100, 6.6, 6000,
                    ((3000, 60), (2500, 80), (2000, 120), (1500, 200)),
                    bend_radius=600)
STRAIGHT = [(0, 0, 3000), (30000, 0, 3000)]


def gaps(sups):
    s = [x["s_mm"] for x in sups]
    return [b - a for a, b in zip(s, s[1:])]


def boxes(sup):
    return [Box(b["id"], tuple(b["min"]), tuple(b["max"]))
            for b in sup["boxes"] if b["id"] != "arm"]


def overlaps(a, b):
    return all(a.lo[i] < b.hi[i] and a.hi[i] > b.lo[i] for i in range(3))


class Span(unittest.TestCase):
    def test_longest_span_that_carries_the_load(self):
        self.assertEqual(T.choose_span(LADDER, 50), (3000, 60))
        self.assertEqual(T.choose_span(LADDER, 61), (2500, 80))
        self.assertEqual(T.choose_span(LADDER, 199), (1500, 200))
        self.assertIsNone(T.choose_span(LADDER, 201))

    def test_growth_is_applied(self):
        r = T.support_run(STRAIGHT, LADDER, 50, opts=T.SupportOptions(
            growth=0.25))
        self.assertEqual(r["design_kg_per_m"], 62.5)
        self.assertEqual(r["span_mm"], 2500)

    def test_overload_is_reported_not_supported(self):
        r = T.support_run(STRAIGHT, LADDER, 190)
        self.assertEqual(r["issues"][0]["code"], "overloaded")
        self.assertEqual(r["supports"], [])


class Spacing(unittest.TestCase):
    def setUp(self):
        self.r = T.support_run(STRAIGHT, LADDER, 40)

    def test_never_more_than_a_span_apart(self):
        self.assertTrue(self.r["supports"])
        self.assertLessEqual(max(gaps(self.r["supports"])),
                             self.r["span_mm"] + 1)
        self.assertEqual(self.r["issues"], [])

    def test_supports_near_both_ends(self):
        s = [x["s_mm"] for x in self.r["supports"]]
        self.assertLessEqual(s[0], 600)
        self.assertGreaterEqual(s[-1], 30000 - 600)

    def test_every_splice_has_a_support_within_a_quarter_span(self):
        reach = 0.25 * self.r["span_mm"]
        s = [x["s_mm"] for x in self.r["supports"]]
        for splice in range(6000, 30000, 6000):
            self.assertTrue(any(abs(x - splice) <= reach for x in s), splice)

    def test_supports_clear_the_bend_fitting(self):
        pts = [(0, 0, 3000), (10000, 0, 3000), (10000, 10000, 3000)]
        r = T.support_run(pts, LADDER, 40)
        R = LADDER.centre_bend_radius
        for x in r["supports"]:
            if x["run"] == 0:
                self.assertLessEqual(x["s_mm"], 10000 - R)
            else:
                self.assertGreaterEqual(x["s_mm"], R)

    def test_posts_reach_the_floor_under_the_tray(self):
        x = self.r["supports"][0]
        self.assertEqual(x["post_height_mm"], 3000 - 50)
        post = [b for b in x["boxes"] if b["id"] == "post"][0]
        self.assertEqual(post["min"][2], 0)
        self.assertEqual(post["max"][2], 2950)

    def test_bom_counts_posts_and_plates(self):
        bom = {b["item"]: b for b in self.r["bom"]}
        posts = sum(b.get("posts", 0) for b in self.r["bom"])
        self.assertEqual(bom["base plate 400x400x10"]["count"], posts)
        self.assertEqual(bom["SYN straight, 6000 mm"]["count"], 5)


class Choice(unittest.TestCase):
    def test_light_load_takes_a_cantilever(self):
        r = T.support_run(STRAIGHT, LADDER, 10)
        self.assertTrue(all(x["kind"] == "cantilever"
                            for x in r["supports"]))

    def test_heavy_span_takes_a_goalpost(self):
        r = T.support_run(STRAIGHT, LADDER, 45)
        mids = [x for x in r["supports"][1:-1]]
        self.assertTrue(mids)
        self.assertTrue(all(x["kind"] == "goalpost" for x in mids))

    def test_wide_tray_takes_a_goalpost(self):
        wide = T.TrayType("SYN", 900, 960, 100, 9.5, 6000,
                          ((3000, 50),), bend_radius=900)
        r = T.support_run(STRAIGHT, wide, 5)
        self.assertTrue(all(x["kind"] == "goalpost" for x in r["supports"]))

    def test_tall_posts_are_flagged(self):
        r = T.support_run([(0, 0, 6000), (9000, 0, 6000)], LADDER, 10)
        self.assertTrue(all("flag" in x for x in r["supports"]))


class Obstacles(unittest.TestCase):
    def test_support_slides_off_an_obstacle(self):
        pad = Box("PAD", (5500, -2000, 0), (7500, 2000, 1000))
        r = T.support_run(STRAIGHT, LADDER, 40, [pad])
        self.assertEqual(r["issues"], [])
        for x in r["supports"]:
            for b in boxes(x):
                self.assertFalse(overlaps(b, pad), x["id"])
        self.assertLessEqual(max(gaps(r["supports"])), r["span_mm"] + 1)

    def test_cantilever_switches_side(self):
        wall = Box("WALL", (0, 300, 0), (30000, 600, 6000))
        r = T.support_run(STRAIGHT, LADDER, 10, [wall])
        self.assertTrue(r["supports"])
        self.assertTrue(all(x["side"] == -1 for x in r["supports"]))

    def test_blocked_support_is_reported(self):
        slab = Box("SLAB", (4000, -3000, 0), (16000, 3000, 2000))
        r = T.support_run(STRAIGHT, LADDER, 40, [slab])
        codes = {i["code"] for i in r["issues"]}
        self.assertIn("support_blocked", codes)
        blocked = [i for i in r["issues"] if i["code"] == "support_blocked"]
        self.assertEqual(blocked[0]["obstacle"], "SLAB")

    def test_riser_is_an_open_item(self):
        pts = [(0, 0, 3000), (5000, 0, 3000), (5000, 0, 500)]
        r = T.support_run(pts, LADDER, 10)
        self.assertEqual(r["open_items"][0]["code"], "riser_fixing")


TRAY = {"family": "SYN", "width": 600, "overall_width": 660,
        "side_height": 100, "self_weight": 6.6, "standard_length": 6000,
        "bend_radius": 600,
        "load_ratings": [[3000, 60], [2500, 80], [2000, 120], [1500, 200]]}


class Service(unittest.TestCase):
    def req(self, **kw):
        return {"id": "T-1", "tray": TRAY,
                "from": {"id": "A", "pos": [0, 0, 3000], "dir": [1, 0, 0]},
                "to": {"id": "B", "pos": [20000, 8000, 3000],
                       "dir": [-1, 0, 0]},
                "cables": [{"kg_per_m": 8.2, "count": 4}], **kw}

    def test_routes_and_supports(self):
        r = service.route_and_support(self.req())
        self.assertEqual(r["status"], "supported", r.get("issues"))
        self.assertEqual(r["route"], "routed")
        self.assertEqual(r["cable_kg_per_m"], 32.8)
        self.assertEqual(r["route_issues"], [])
        self.assertTrue(r["supports"])

    def test_given_points_are_supported_as_drawn(self):
        pts = [[0, 0, 3000], [10000, 0, 3000], [10000, 8000, 3000],
               [20000, 8000, 3000]]
        r = service.route_and_support(self.req(points=pts))
        self.assertEqual(r["route"], "given")
        self.assertEqual(r["points"], [[float(c) for c in p] for p in pts])

    def test_render(self):
        r = service.route_and_support(self.req(render={"views": ["plan"]}))
        self.assertTrue(r["svg"].startswith("<svg"))
        self.assertIn("#d18f00", r["svg"])        # the tray
        self.assertIn(service.STEEL, r["svg"])    # its supports

    def test_refusals(self):
        for name, req in {
            "no load": {k: v for k, v in self.req().items()
                        if k != "cables"},
            "short tray": self.req(tray={"family": "SYN", "width": 600,
                                         "load_ratings": [[3000, 60]]}),
            "bad option": self.req(supports={"spacing": 1}),
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                service.route_and_support(req)

    def test_unroutable_is_data(self):
        r = service.route_and_support(self.req(obstacles=[
            {"id": "WALL", "min": [10000, -100000, -100000],
             "max": [10300, 100000, 100000]}]))
        self.assertEqual(r["status"], "failed")
        self.assertIn("reason", r)


if __name__ == "__main__":
    unittest.main()
