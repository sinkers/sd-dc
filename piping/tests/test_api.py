"""Tests for the service layer and its three front ends: MCP over stdio, MCP
over HTTP and REST. They all call service.py, so most checks are made once
there and the front ends are checked for plumbing.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PIPING = os.path.join(HERE, "..")
sys.path.insert(0, PIPING)

import http_mcp_server  # noqa: E402
import mcp_server  # noqa: E402
import server  # noqa: E402
import service  # noqa: E402
from core import render  # noqa: E402

PUMP_OUT = {"id": "PUMP-1.out", "pos": [500, 0, 600], "dir": [1, 0, 0],
            "dn": 100}
HX_IN = {"id": "HX-1.in", "pos": [3500, 0, 600], "dir": [-1, 0, 0]}
COLUMN = {"id": "COL-1", "min": [1600, -200, 0], "max": [2000, 200, 6000]}
BLOCKER = {"id": "BLOCK-1", "min": [600, -500, 0], "max": [900, 500, 1500]}


def route_req(**extra):
    return {"id": "P-1", "from": PUMP_OUT, "to": HX_IN,
            "obstacles": [COLUMN], **extra}


class Service(unittest.TestCase):
    def test_routed_result(self):
        r = service.route(route_req())
        self.assertEqual(r["status"], "routed")
        self.assertEqual(r["spec"]["dn"], 100)          # taken from the nozzle
        self.assertTrue(r["validation"]["ok"])
        self.assertEqual(r["points"][0], PUMP_OUT["pos"])
        self.assertEqual(r["points"][-1], HX_IN["pos"])
        s = r["summary"]
        self.assertEqual(s["elbows"], len(r["points"]) - 2)
        self.assertAlmostEqual(s["centreline_mm"],
                               s["straight_mm"] + s["elbow_arc_mm"], places=0)
        self.assertEqual(r["bom"][0]["item"], "pipe")
        self.assertEqual(r["bom"][1], {"item": "elbow 90 LR", "dn": 100,
                                       "schedule": "10S", "count": s["elbows"]})
        frag = r["industroml"]
        self.assertEqual((frag["type"], frag["from"], frag["to"]),
                         ("pipe", "PUMP-1.out", "HX-1.in"))
        self.assertEqual(frag["attributes"]["path_mm"], r["points"])

    def test_failure_is_data(self):
        r = service.route(route_req(obstacles=[BLOCKER]))
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["reason"], "blocked_nozzle")
        self.assertEqual(r["obstacle"], "BLOCK-1")
        self.assertIn("suggest", r)
        json.dumps(r, allow_nan=False)

    def test_same_request_same_hash(self):
        self.assertEqual(service.route(route_req())["request_sha256"],
                         service.route(route_req())["request_sha256"])
        self.assertNotEqual(
            service.route(route_req())["request_sha256"],
            service.route(route_req(options={"clearance_mm": 80}))
            ["request_sha256"])

    def test_refusals(self):
        bad = {
            "no dn": {"from": {**PUMP_OUT, "dn": None}, "to": HX_IN},
            "odd dn": route_req(dn=90),
            "diagonal": {"dn": 100, "from": {**PUMP_OUT, "dir": [1, 1, 0]},
                         "to": HX_IN},
            "flat box": route_req(obstacles=[{"min": [0, 0, 0],
                                              "max": [1, 0, 1]}]),
            "unknown option": route_req(options={"speed": 1}),
            "tiny grid": route_req(options={"grid_mm": 1}),
            "dn clash": {"from": PUMP_OUT, "to": {**HX_IN, "dn": 80}},
        }
        for name, req in bad.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    service.route(req)

    def test_batch(self):
        r = service.route_batch({"pipes": [
            {"id": "S", "dn": 100, "from": PUMP_OUT, "to": HX_IN},
            {"id": "R", "dn": 100,
             "from": {"id": "HX-1.out", "pos": [4500, 0, 300], "dir": [1, 0, 0]},
             "to": {"id": "PUMP-1.in", "pos": [-500, 0, 300],
                    "dir": [-1, 0, 0]}},
        ], "obstacles": [COLUMN,
                         {"id": "PUMP-1", "min": [-500, -400, 0],
                          "max": [500, 400, 1200]},
                         {"id": "HX-1", "min": [3500, -400, 0],
                          "max": [4500, 400, 1200]}]})
        self.assertEqual(r["status"], "routed", r)
        self.assertEqual((r["routed"], r["failed"]), (2, 0))
        self.assertTrue(all(x["validation"]["ok"] for x in r["results"]))
        pipe = [b for b in r["bom"] if b["item"] == "pipe"][0]
        total = sum(x["summary"]["straight_mm"] for x in r["results"]) / 1000
        self.assertAlmostEqual(pipe["length_m"], total, places=2)

    def test_batch_partial(self):
        r = service.route_batch({"pipes": [
            {"id": "OK", "dn": 100, "from": PUMP_OUT, "to": HX_IN},
            {"id": "BAD", "dn": 100,
             "from": {"id": "X.out", "pos": [700, 3000, 600], "dir": [1, 0, 0]},
             "to": {"id": "Y.in", "pos": [3500, 3000, 600],
                    "dir": [-1, 0, 0]}},
        ], "obstacles": [{"id": "WALL", "min": [750, 2500, 0],
                          "max": [800, 3500, 1500]}]})
        self.assertEqual(r["status"], "partial")
        self.assertEqual([x["status"] for x in r["results"]],
                         ["routed", "failed"])

    def test_batch_duplicate_ids(self):
        with self.assertRaises(ValueError):
            service.route_batch({"pipes": [
                {"id": "A", "dn": 100, "from": PUMP_OUT, "to": HX_IN},
                {"id": "A", "dn": 100, "from": PUMP_OUT, "to": HX_IN}]})

    def test_validate(self):
        r = service.validate({"dn": 100, "from": PUMP_OUT, "to": HX_IN,
                              "points": [[500, 0, 600], [3500, 0, 600]],
                              "obstacles": [COLUMN]})
        self.assertFalse(r["ok"])
        self.assertEqual(r["issues"][0]["code"], "collision")
        self.assertEqual(r["issues"][0]["obstacle"], "COL-1")

    def test_render_routes_then_draws(self):
        out = service.render({"pipes": [
            {"id": "P-1", "dn": 100, "service": "CHW-S", "from": PUMP_OUT,
             "to": HX_IN}], "obstacles": [COLUMN],
            "render": {"views": ["plan", "iso"], "title": "t<&>"}})
        self.assertEqual((out["mode"], out["routed"]), ("routed", 1))
        svg = out["svg"]
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("t&lt;&amp;&gt;", svg)          # title escaped
        self.assertIn("#1f6fd1", svg)                 # CHW-S colour
        self.assertIn("P-1", svg)
        self.assertNotIn("parts", out["results"][0])
        import xml.dom.minidom
        xml.dom.minidom.parseString(svg)               # well formed

    def test_render_given_points_marks_broken_runs(self):
        out = service.render({"pipes": [
            {"id": "P-1", "dn": 100, "from": PUMP_OUT, "to": HX_IN,
             "points": [[500, 0, 600], [3500, 0, 600]]}],
            "obstacles": [COLUMN]})
        self.assertEqual((out["mode"], out["broken"]), ("checked", 1))
        self.assertEqual(out["results"][0]["issues"][0]["code"], "collision")
        self.assertIn('stroke="#e00000"', out["svg"])

    def test_render_failed_pipe_is_drawn(self):
        out = service.render({"pipes": [
            {"id": "P-1", "dn": 100, "from": PUMP_OUT, "to": HX_IN}],
            "obstacles": [BLOCKER]})
        self.assertEqual(out["status"], "failed")
        self.assertIn("blocked_nozzle", out["svg"])

    def test_render_refusals(self):
        given = {"id": "A", "dn": 100, "from": PUMP_OUT, "to": HX_IN,
                 "points": [[500, 0, 600], [3500, 0, 600]]}
        routed = {"id": "B", "dn": 100, "from": PUMP_OUT, "to": HX_IN}
        for name, req in {
            "mixed": {"pipes": [given, routed]},
            "view": {"pipes": [routed], "render": {"views": ["top"]}},
            "option": {"pipes": [routed], "render": {"dpi": 3}},
            "width": {"pipes": [routed], "render": {"width": 10}},
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                service.render(req)

    def test_render_focus_drops_far_obstacles(self):
        far = {"id": "FAR-BOX", "min": [90000, 0, 0], "max": [91000, 1, 1]}
        out = service.render({"pipes": [
            {"id": "P-1", "dn": 100, "from": PUMP_OUT, "to": HX_IN}],
            "obstacles": [COLUMN, far],
            "render": {"focus": {"min": [0, -1000, 0],
                                 "max": [4000, 1000, 2000]}}})
        self.assertNotIn("FAR-BOX", out["svg"])
        self.assertIn("COL-1", out["svg"])

    def test_specs_and_meta(self):
        sizes = {s["dn"]: s for s in service.specs()["sizes"]}
        self.assertAlmostEqual(sizes[100]["bend_radius"], 171.45)
        m = service.meta()
        self.assertIn("blocked_nozzle", m["failure_reasons"])
        json.dumps(m, allow_nan=False)


INDUSTROML = os.environ.get("INDUSTROML_SCHEMA") or os.path.expanduser(
    "~/workspace/industroml/industroml.schema.json")


@unittest.skipUnless(os.path.exists(INDUSTROML), "IndustroML schema not here")
class IndustroML(unittest.TestCase):
    def test_fragment_is_a_valid_connection(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        with open(INDUSTROML) as fh:
            schema = json.load(fh)
        conn = {"$ref": "#/$defs/connection", "$defs": schema["$defs"]}
        frag = service.route(route_req())["industroml"]
        jsonschema.validate(frag, conn)


class Mcp(unittest.TestCase):
    def call(self, method, params=None, rid=1):
        return mcp_server.handle({"jsonrpc": "2.0", "id": rid,
                                  "method": method, "params": params or {}})

    def test_lists(self):
        names = [t["name"] for t in self.call("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["piping_route_pipe", "piping_route_network",
                                 "piping_validate_route",
                                 "piping_render_routes", "piping_list_specs"])
        for uri in ("piping://meta", "piping://specs", "piping://openapi"):
            r = self.call("resources/read", {"uri": uri})
            json.loads(r["result"]["contents"][0]["text"])

    def test_call_and_refusal(self):
        r = self.call("tools/call", {"name": "piping_route_pipe",
                                     "arguments": route_req()})
        body = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(body["status"], "routed")
        r = self.call("tools/call", {"name": "piping_route_pipe",
                                     "arguments": route_req(dn=90)})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("DN90", r["result"]["content"][0]["text"])

    def test_render_tool_returns_an_image(self):
        r = self.call("tools/call", {"name": "piping_render_routes",
                                     "arguments": {"pipes": [
                                         {"id": "P-1", "dn": 100,
                                          "from": PUMP_OUT, "to": HX_IN}]}})
        first, last = r["result"]["content"][0], r["result"]["content"][-1]
        if render.png_available():
            self.assertEqual(first["type"], "image")
            self.assertTrue(base64.b64decode(first["data"])
                            .startswith(b"\x89PNG"))
        else:
            self.assertEqual(first["resource"]["mimeType"], "image/svg+xml")
        body = json.loads(last["text"])
        self.assertEqual(body["routed"], 1)
        self.assertNotIn("svg", body)

    def test_notification_gets_no_answer(self):
        self.assertIsNone(mcp_server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_stdio_round_trip(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "piping_list_specs", "arguments": {}}}]
        out = subprocess.run(
            [sys.executable, os.path.join(PIPING, "mcp_server.py")],
            input="\n".join(json.dumps(m) for m in msgs) + "\n",
            capture_output=True, text=True, timeout=30, cwd=PIPING)
        lines = [json.loads(x) for x in out.stdout.splitlines()]
        self.assertEqual([x["id"] for x in lines], [1, 2])
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "piping")


def _serve(handler):
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Handler.log_message = lambda *a: None
        http_mcp_server.Handler.log_message = lambda *a: None
        cls.rest, cls.rest_url = _serve(server.Handler)
        cls.mcp, cls.mcp_url = _serve(http_mcp_server.Handler)

    @classmethod
    def tearDownClass(cls):
        cls.rest.shutdown()
        cls.mcp.shutdown()

    def test_rest(self):
        with urllib.request.urlopen(self.rest_url + "/api/health") as r:
            self.assertEqual(json.loads(r.read())["status"], "ok")
        with urllib.request.urlopen(self.rest_url + "/openapi.json") as r:
            self.assertIn("/api/route/batch", json.loads(r.read())["paths"])
        code, body = _post(self.rest_url + "/api/route", route_req())
        self.assertEqual((code, body["status"]), (200, "routed"))
        code, body = _post(self.rest_url + "/api/route",
                           route_req(obstacles=[BLOCKER]))
        self.assertEqual((code, body["reason"]), (200, "blocked_nozzle"))
        code, body = _post(self.rest_url + "/api/route", route_req(dn=90))
        self.assertEqual(code, 400)
        self.assertIn("DN90", body["error"])

    def test_rest_render(self):
        req = {"pipes": [{"id": "P-1", "dn": 100, "from": PUMP_OUT,
                          "to": HX_IN}]}
        for fmt, ctype in (("svg", "image/svg+xml"), ("json",
                                                      "application/json")):
            r = urllib.request.Request(
                f"{self.rest_url}/api/render?format={fmt}",
                json.dumps(req).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=30) as resp:
                self.assertEqual(resp.headers["Content-Type"], ctype)
                body = resp.read()
            if fmt == "svg":
                self.assertTrue(body.startswith(b"<svg"))
        code, body = _post(self.rest_url + "/api/render?format=gif", req)
        self.assertEqual(code, 400)

    def test_http_mcp(self):
        code, body = _post(self.mcp_url + "/mcp", {
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "piping_route_network", "arguments": {
                "pipes": [{"id": "P-1", "dn": 100, "from": PUMP_OUT,
                           "to": HX_IN}]}}})
        self.assertEqual(code, 200)
        result = json.loads(body["result"]["content"][0]["text"])
        self.assertEqual(result["status"], "routed")


if __name__ == "__main__":
    unittest.main()
