import copy
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "playground"))
from control_contract import UI_SCHEMA, apply_control, default_ui, validate_ui


class PlaygroundControlTests(unittest.TestCase):
    def test_schema_is_strict_and_default_is_valid(self):
        self.assertEqual(UI_SCHEMA["additionalProperties"], False)
        ui = default_ui("plate_drop")
        self.assertIs(validate_ui(ui, "plate_drop"), ui)
        self.assertTrue(any(c["action"] == "height_m" for c in ui["controls"]))

    def test_invalid_action_kind_and_duplicate_ids(self):
        ui = default_ui("panel_impact")
        ui["controls"][0]["action"] = "eval"
        with self.assertRaises(ValueError): validate_ui(ui, "panel_impact")
        ui = default_ui("panel_impact")
        ui["controls"][0]["kind"] = "slider"
        with self.assertRaises(ValueError): validate_ui(ui, "panel_impact")
        ui = default_ui("panel_impact")
        ui["controls"][1]["id"] = ui["controls"][0]["id"]
        with self.assertRaises(ValueError): validate_ui(ui, "panel_impact")

    def test_rejects_nonfinite_unknown_fields_and_material_mismatch(self):
        ui = default_ui("panel_impact")
        ui["controls"][0]["value"] = math.nan
        with self.assertRaises(ValueError): validate_ui(ui, "panel_impact")
        ui = default_ui("panel_impact")
        ui["controls"][0]["extra"] = "x"
        with self.assertRaises(ValueError): validate_ui(ui, "panel_impact")
        ui = default_ui("panel_impact")
        ui["controls"].append({"id":"height","label":"Height","kind":"slider","action":"height_m","min":0,"max":2,"step":.1,"value":.2})
        with self.assertRaises(ValueError): validate_ui(ui, "panel_impact")

    def test_physical_request_bounds_and_immutability(self):
        plan = {"experiment": "plate_drop", "heights_m": [.25, .5], "speeds_m_s": [], "ui": default_ui("plate_drop"), "nested": {"keep": [1]}}
        before = copy.deepcopy(plan)
        updated = apply_control(plan, "height_m", .75, case_index=1)
        self.assertEqual(updated["heights_m"], [.75])
        self.assertEqual(updated["ui"]["controls"][-1]["value"], .75)
        self.assertEqual(plan, before)
        with self.assertRaises(ValueError): apply_control(plan, "height_m", 2.1)
        with self.assertRaises(ValueError): apply_control(plan, "speed_m_s", 1)
        with self.assertRaises(ValueError): apply_control(plan, "height_m", .2, case_index=4)

    def test_pressure_default_and_legacy_plan(self):
        plan = {"experiment": "continuum_pressure_reference", "speeds_m_s": [], "heights_m": []}
        updated = apply_control(plan, "pressure_pa", 500_000_000)
        self.assertEqual(updated["pressure"]["resolution"], 4)
        self.assertEqual(updated["pressure"]["peak_pressure_pa"], 500_000_000)
        self.assertEqual(plan, {"experiment": "continuum_pressure_reference", "speeds_m_s": [], "heights_m": []})
        with self.assertRaises(ValueError): apply_control(plan, "pressure_pa", 0)

    def test_multiple_height_presets_select_by_declared_value(self):
        ui = default_ui("plate_drop")
        height = ui["controls"][-1]
        height["kind"] = "button"
        height["min"], height["max"], height["step"], height["value"] = .25, .25, .01, .25
        # A second preset is valid when its range is a singleton.
        second = dict(height)
        second.update(id="height-half", label="Half metre", min=.5, max=.5, value=.5)
        # Singleton controls are rejected by the general min<max contract, so
        # use narrow ranges while retaining the declared preset values.
        height.update(min=.24, max=.26)
        second.update(min=.49, max=.51)
        ui["controls"].append(second)
        plan = {"experiment": "plate_drop", "heights_m": [.25], "ui": ui}
        updated = apply_control(plan, "height_m", .5)
        self.assertEqual(updated["heights_m"], [.5])
        self.assertEqual([c["value"] for c in updated["ui"]["controls"][-2:]], [.25, .5])
        with self.assertRaises(ValueError): apply_control(plan, "height_m", .255)

    def test_preset_button_rejects_arbitrary_value_and_nullable_pressure(self):
        ui = default_ui("plate_drop")
        height = ui["controls"][-1]
        height["kind"] = "button"
        height["min"], height["max"], height["step"] = 0, 2, .01
        plan = {"experiment": "plate_drop", "heights_m": [.25], "ui": ui}
        with self.assertRaises(ValueError): apply_control(plan, "height_m", .5)
        pressure_plan = {"experiment": "continuum_pressure_reference", "pressure": None}
        updated = apply_control(pressure_plan, "pressure_pa", 400_000_000)
        self.assertEqual(updated["pressure"]["peak_pressure_pa"], 400_000_000)
        self.assertIsNone(pressure_plan["pressure"])


if __name__ == "__main__":
    unittest.main()
