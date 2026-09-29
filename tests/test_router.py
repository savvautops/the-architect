"""
Tests for The Architect v0.7 - Sub-1GB Local Decision Router & Benchmark (Build Order #5).
"""

import json
import unittest

from appctl.registry import registry
from appctl.router import (
    LocalRouter,
    TIER_S,
    TIER_A,
    TIER_B,
    TIER_C,
    TIER_D,
    run_benchmark,
)


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.router = LocalRouter(registry)

    def test_route_tier_s_lifecycle(self):
        # Open app
        dec = self.router.route("launch firefox")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_S)
        self.assertEqual(dec.tool_id, "app.open")
        self.assertEqual(dec.args["app"], "firefox")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Quit app
        dec = self.router.route("quit notepad --force")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_S)
        self.assertEqual(dec.tool_id, "app.quit")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Status
        dec = self.router.route("check status of code")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_S)
        self.assertEqual(dec.tool_id, "app.status")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # List
        dec = self.router.route("list running processes")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_S)
        self.assertEqual(dec.tool_id, "app.list")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

    def test_route_tier_a_desktop_dom(self):
        # Tree dump
        dec = self.router.route("dump tree for explorer")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_A)
        self.assertEqual(dec.tool_id, "a11y.tree")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Query element
        dec = self.router.route("find button Submit")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_A)
        self.assertEqual(dec.tool_id, "a11y.query")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Click element
        dec = self.router.route("click Save button in notepad")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_A)
        self.assertEqual(dec.tool_id, "a11y.click")
        self.assertEqual(dec.args["app"], "notepad")
        self.assertEqual(dec.args["name"], "Save")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

    def test_route_tier_b_keyboard_macro(self):
        # Editor save all
        dec = self.router.route("save all files in editor")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_B)
        self.assertEqual(dec.tool_id, "editor.save_all")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Key press
        dec = self.router.route("press ctrl+s in code")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_B)
        self.assertEqual(dec.tool_id, "app.key")
        self.assertEqual(dec.args["key"], "ctrl+s")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Typing
        dec = self.router.route("type Hello World into notepad")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_B)
        self.assertEqual(dec.tool_id, "app.type")
        self.assertEqual(dec.args["text"], "Hello World")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Macro workflow
        dec = self.router.route("execute workflow commit_and_push")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_B)
        self.assertEqual(dec.tool_id, "app.macro_node")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

    def test_route_tier_c_vision_and_fallback(self):
        # Screenshot see
        dec = self.router.route("take a screenshot of firefox to screen.png")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_C)
        self.assertEqual(dec.tool_id, "app.see")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Diff
        dec = self.router.route("diff before.png and after.png")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_C)
        self.assertEqual(dec.tool_id, "app.diff")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

        # Fallback to vision when a11y unavailable
        dec = self.router.route("click button Submit", context={"has_a11y": False})
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_C)
        self.assertEqual(dec.tool_id, "vision.click")
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

    def test_route_tier_d_explicit_coordinates(self):
        dec = self.router.route("click at coordinates 350, 420 in firefox")
        self.assertTrue(dec.ok)
        self.assertEqual(dec.lane, TIER_D)
        self.assertEqual(dec.tool_id, "app.click")
        self.assertEqual(dec.args["x"], 350)
        self.assertEqual(dec.args["y"], 420)
        valid, err = self.router.validate_decision(dec)
        self.assertTrue(valid, err)

    def test_run_benchmark(self):
        rep = run_benchmark(self.router)
        self.assertTrue(rep["ok"])
        sc = rep["scorecard"]
        self.assertGreaterEqual(sc["lane_accuracy"], 95.0)
        self.assertGreaterEqual(sc["schema_compliance"], 95.0)
        self.assertGreaterEqual(sc["semantic_coverage"], 70.0)
        self.assertTrue(sc["sub_1gb_compliant"])
        self.assertEqual(sc["local_ratio"], 100.0)
        self.assertLess(sc["average_latency_ms"], 10.0)


if __name__ == "__main__":
    unittest.main()
