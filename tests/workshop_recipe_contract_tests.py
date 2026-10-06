"""Recipe identity, manufacturing declarations and bounded evidence reporting."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground"), str(ROOT / "mcp"), str(ROOT)]

from mcp import workshop_components, workshop_construction, workshop_recipe_contract as recipes
from mcp.workshop import ASSEMBLIES, WorkshopDesign, WirePart, assemble
import playable_recipes
import workshop_chat
import workshop_recipe


class RecipeContract(unittest.TestCase):
    def setUp(self):
        self.design, self.overrides = workshop_components.design_from_spec(playable_recipes.recipe("field-pick"))
        self.settings = {"cell_size_m": .05, "workshop_cell_size_m": .04,
                         "process_settings": {"power_w": 500., "work_j_kg": 100., "efficiency": 1.}}

    def report(self, design=None, overrides=None, **kw):
        return recipes.derive(design or self.design, self.overrides if overrides is None else overrides,
                              manufacturing=kw.pop("manufacturing", self.settings), **kw)

    def observation(self, report=None):
        report = report or self.report()
        return {"schema": recipes.EVIDENCE_SCHEMA, "source_hash": report["source"]["hash"],
                "contract_hash": report["contract_hash"], "test": "native-tool-trial",
                "origin": "native", "completed": True, "result": "passed",
                "requested": {"seconds": 2.}, "measured": {"work_j": 12., "removed_m3": .001},
                "environment": {"cell_size_m": .05, "engine": "fixture-build"},
                "limitations": ["one bounded dry ground trial"]}

    def test_builtin_and_authored_sources_share_report_without_source_mutation(self):
        before = deepcopy(self.design)
        report = self.report()
        self.assertEqual(recipes.SCHEMA, report["schema"])
        self.assertEqual({"iron", "aluminum"}, {p["catalog_material"] for p in report["geometry_materials"]})
        self.assertTrue(report["connections"])
        self.assertIn("ground_tool", report["intended_use"])
        self.assertEqual(before, self.design)
        authored = WorkshopDesign("authored", "Carry a small load", [
            WirePart("deck", "panel", (.4, .05, .4), (0, .05, 0), "iron")], kind="custom")
        custom = self.report(authored, {})
        self.assertEqual(recipes.SCHEMA, custom["schema"])
        self.assertEqual("authored", custom["source"]["design_id"])
        self.assertEqual("requires_paid_quote", recipes.derive(authored)["manufacturing"]["settings_status"])
        self.assertIsNone(recipes.derive(authored)["manufacturing"]["process_settings"])

    def test_declared_tests_fit_and_claimed_pass_never_become_measured_qualification(self):
        self.design.tests = [{"name": "Dig", "qualified": True, "passed": True}]
        report = self.report(evidence=[{"passed": True, "fingerprint": "old-bench"}])
        qualification = report["qualification"]
        self.assertEqual("unqualified", qualification["status"])
        self.assertEqual([], qualification["measured_evidence"])
        self.assertEqual(1, len(qualification["rejected_evidence"]))
        self.assertTrue(all(r["status"] == "requires_review" for r in qualification["requirements"]))
        self.assertEqual("not_implemented_by_this_report", qualification["skill_enforcement"])
        self.assertEqual("not_performed", report["manufacturing"]["resource_reservation"])

    def test_completed_matching_observation_is_retained_without_certification(self):
        record = self.observation()
        report = self.report(evidence=[record])
        kept = report["qualification"]["measured_evidence"][0]
        self.assertEqual(record["measured"], kept["measured"])
        self.assertFalse(kept["provenance_verified"])
        self.assertFalse(kept["qualification_granted"])
        self.assertEqual("unqualified", report["qualification"]["status"])
        kept["measured"]["work_j"] = 0
        self.assertEqual(12., record["measured"]["work_j"])

    def test_every_source_revision_rejects_old_evidence(self):
        old = self.observation()
        variants = []
        for field, value in (("size_m", tuple(v * 1.1 for v in self.design.parts[0].size_m)), ("material", "glass"),
                             ("center_m", (.1, .1, .1)), ("rotation_deg", (0, 0, 10))):
            revised = deepcopy(self.design)
            revised.parts[0] = replace(revised.parts[0], **{field: value})
            variants.append((field, revised, self.overrides))
        for field in ("purpose", "design_id"):
            revised = deepcopy(self.design); setattr(revised, field, "revision")
            variants.append((field, revised, self.overrides))
        revised = deepcopy(self.design)
        revised.parameters["primary_use"] = {"label": "Inspect", "steps": [{"do": "inspect"}]}
        variants.append(("use", revised, self.overrides))
        revised = deepcopy(self.design)
        construction = workshop_construction.adopted(revised)
        construction["joints"] = [{"id": "reviewed-mount", "kind": "fixed", "method": "pressed",
                                   "a": revised.parts[0].name, "b": revised.parts[1].name}]
        patches = {**self.overrides, "@construction": construction}
        revised = workshop_components.apply_overrides(assemble(str(revised.kind), design_id=revised.design_id,
            purpose=revised.purpose, parameters=dict(revised.parameters)), patches)
        variants.append(("connection", revised, patches))
        for label, design, overrides in variants:
            with self.subTest(revision=label):
                report = self.report(design, overrides, evidence=[old])
                self.assertNotEqual(old["source_hash"], report["source"]["hash"])
                self.assertEqual([], report["qualification"]["measured_evidence"])
                self.assertIn("revision differs", report["qualification"]["rejected_evidence"][0]["reason"])

    def test_grid_and_process_revision_bind_evidence_without_changing_source(self):
        before = self.report(); old = self.observation(before)
        for patch in ({"cell_size_m": .04}, {"process_settings": {"work_j_kg": 200.}},
                      {"workshop_cell_size_m": .02}):
            with self.subTest(settings=patch):
                after = self.report(manufacturing={**self.settings, **patch}, evidence=[old])
                self.assertEqual(before["source"]["hash"], after["source"]["hash"])
                self.assertNotEqual(before["contract_hash"], after["contract_hash"])
                self.assertEqual([], after["qualification"]["measured_evidence"])

    def test_malformed_incomplete_nonfinite_or_claim_only_evidence_is_rejected(self):
        cases = [{"completed": False}, {"measured": {"passed": True}}, {"measured": {"work_j": float("nan")}},
                 {"environment": {}}, {"origin": "llm"}, {"qualified": True}]
        for patch in cases:
            with self.subTest(patch=patch):
                result = self.report(evidence=[{**self.observation(), **patch}])["qualification"]
                self.assertEqual([], result["measured_evidence"])
                self.assertEqual(1, len(result["rejected_evidence"]))

    def test_invalid_manufacturing_settings_fail_closed(self):
        for settings in ({"skill_level": 10}, {"cell_size_m": float("nan")}, {"cell_size_m": .0001},
                         {"process_settings": {"work_j_kg": -1}}, {"process_settings": {"efficiency": 2}},
                         {"process_settings": {"free_energy_j": 1000}}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.report(manufacturing=settings)

    def test_explicit_local_cells_request_is_identified_not_qualified(self):
        request = {"schema": "banjo.workshop-local-cells.v1", "cell_size_m": .01}
        report = self.report(overrides={**self.overrides, "@local_cells": request})
        self.assertEqual("local-material-cells", report["manufacturing"]["representation"])
        self.assertEqual(request, report["manufacturing"]["local_cells_request"])
        self.assertEqual("required", report["manufacturing"]["native_admission"])
        self.assertEqual("unqualified", report["qualification"]["status"])

    def test_legacy_saved_source_and_historical_oak_are_not_rewritten(self):
        legacy = assemble("field-pick", design_id="saved-before-policy")
        before = legacy.wireframe()
        report = recipes.derive(legacy)
        self.assertEqual("oak", report["geometry_materials"][0]["material"])
        self.assertEqual(before, legacy.wireframe())
        self.assertEqual([], report["qualification"]["measured_evidence"])

    def test_all_active_catalog_sources_use_the_same_contract(self):
        for assembly in ASSEMBLIES:
            with self.subTest(kind=assembly.name):
                source = playable_recipes.recipe(assembly.name)
                design, overrides = workshop_components.design_from_spec(source)
                report = recipes.derive(design, overrides)
                self.assertEqual(recipes.SCHEMA, report["schema"])
                self.assertEqual("unqualified", report["qualification"]["status"])
                self.assertEqual(overrides, report["editable_source"]["component_overrides"])

    def test_historical_material_comparison_reports_actual_presets_without_physics_claim(self):
        hashes = set()
        for material, density in (("glass", 2500.), ("oak", 700.), ("iron", 7870.)):
            design = WorkshopDesign("comparison", "Same declared geometry", [
                WirePart("coupon", "panel", (.2, .05, .2), (0, .05, 0), material)], kind="research")
            report = recipes.derive(design)
            hashes.add(report["source"]["hash"])
            self.assertEqual(density, report["geometry_materials"][0]["material_preset"]["density_kg_m3"])
            self.assertEqual([], report["qualification"]["measured_evidence"])
        self.assertEqual(3, len(hashes))

    def test_readiness_retains_public_gates_and_isolates_cached_reports(self):
        answer = {"ok": True, "says": "fits", "changes": []}
        with mock.patch.object(workshop_recipe.workshop_fitting, "check_validity", return_value=answer):
            ready = workshop_recipe.assess(self.design, self.overrides, world_cell_m=.05)
            self.assertEqual("banjo.workshop-recipe-readiness.v1", ready["schema"])
            self.assertTrue(ready["ready_as_drawn"])
            self.assertTrue(ready["native_preview_required"])
            self.assertTrue(ready["functional_test_required"])
            self.assertEqual("unqualified", ready["recipe_contract"]["qualification"]["status"])
            identity = ready["recipe_contract"]["source"]["hash"]
            ready["recipe_contract"]["source"]["hash"] = "tampered"
            self.assertEqual(identity, workshop_recipe.assess(self.design, self.overrides, world_cell_m=.05)
                             ["recipe_contract"]["source"]["hash"])

    def test_llm_inspections_share_readiness_contract_and_do_not_invoke_provider(self):
        # The bounded tool state itself, no network or provider credentials.
        candidate = self.design.wireframe(); candidate["component_overrides"] = self.overrides
        state = workshop_chat._State(SimpleNamespace(), candidate, None, ["iron", "aluminum"], [])
        inspected = state.execute("inspect_design", {})["recipe_contract"]
        physics = state.execute("inspect_physics", {})["recipe_contract"]
        self.assertEqual(inspected, physics)
        self.assertIn("Requirements and declared tests are obligations", workshop_chat.SYSTEM)
        self.assertIn("neither enforces manufacturing skills", workshop_chat.SYSTEM)


if __name__ == "__main__":
    unittest.main()
