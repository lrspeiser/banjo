"""Game admission, durable legacy preservation and transactional AI edits."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import io
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "mcp")]
import game_materials
import playable_recipes
import workshop_chat
import workshop_library
import world_chat
from mcp import engine_materials, workshop, workshop_components


class MaterialPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = SimpleNamespace(world_id="a" * 32, workshop_owner_id="owner",
            runs_path=Path(self.temp.name) / "runs", room=SimpleNamespace(scene="new-game"), api_key="")

    def test_body_presets_aliases_and_coal_have_explicit_different_boundaries(self):
        for name in game_materials.body_materials():
            self.assertTrue(engine_materials.known(name))
            game_materials.require_material(self.app, name)
        for name in ("aluminium", "ceramic", "freshwater_ice"):
            game_materials.require_material(self.app, name)
        for name in ("oak", "natural_rubber", "wood", "pine", "plastic", "leather", "unlisted-material"):
            with self.subTest(material=name), self.assertRaises(ValueError):
                game_materials.require_material(self.app, name)
        game_materials.require_material(self.app, "coal", body=False)
        with self.assertRaises(ValueError): game_materials.require_material(self.app, "coal")

    def test_historical_oak_glass_iron_catalog_remains_real_and_available(self):
        research = SimpleNamespace(room=SimpleNamespace(scene="bench"))
        for material, density in (("oak", 700.), ("glass", 2500.), ("iron", 7870.)):
            game_materials.require_material(research, material)
            self.assertEqual(density, engine_materials.density(material))
        self.assertFalse(game_materials.active(research))

    def test_nested_organic_parts_and_loose_stock_cannot_hide_under_a_metal_root(self):
        legal = {"bodies": [], "precise_rigid_bodies": [{"name": "tool", "material": "iron",
            "parts": [{"material": "glass"}]}], "goods": {"stockpiles": [{"holds": {"coal": 5}}]}}
        game_materials.require_spec(legal)
        for change in ("part", "pile"):
            source = deepcopy(legal)
            if change == "part": source["precise_rigid_bodies"][0]["parts"][0]["material"] = "oak"
            else: source["goods"]["stockpiles"][0]["holds"]["rubber"] = 1
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "save is preserved"):
                game_materials.require_spec(source)

    def test_old_world_is_refused_without_rewriting_saved_state_or_starting_a_clock(self):
        import server
        base = SimpleNamespace(store=SimpleNamespace(folder=Path(self.temp.name)),
                               engine_path=Path("unused"))
        hub = server.WorldHub(base)
        world = "b" * 32
        folder = hub._folder(world)
        (folder / "rooms").mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"format": "banjo.world.v1", "id": world,
            "name": "Kept legacy world"}), encoding="utf-8")
        save = folder / "rooms/new-game.json"
        save.write_text(json.dumps({"format": "banjo.room.v2", "scene": "new-game",
            "spec": {"bodies": [{"name": "kept plank", "material": "oak"}]}, "chat": []}), encoding="utf-8")
        before = save.read_bytes()
        with mock.patch.object(server, "Playground") as factory:
            with self.assertRaisesRegex(ValueError, "Choose New game"): hub.get(world)
            factory.assert_not_called()
        self.assertEqual(before, save.read_bytes())
        self.assertEqual({}, hub.apps)

    def test_legacy_stock_is_hidden_and_retained_without_crediting_replacement_metal(self):
        archive = SimpleNamespace(runs_path=self.app.runs_path, workshop_owner_id="owner")
        workshop_library.set_rack(archive, "oak", 17.25)
        workshop_library.set_rack(archive, "rubber", 3.5)
        before = {r["material"]: r["mass_kg"] for r in workshop_library.rack(archive)["materials"]}
        visible = {r["material"]: r["mass_kg"] for r in workshop_library.rack(self.app)["materials"]}
        self.assertNotIn("oak", visible); self.assertNotIn("rubber", visible)
        self.assertEqual(before["iron"], visible["iron"])
        self.assertEqual(before["aluminum"], visible["aluminum"])
        after = {r["material"]: r["mass_kg"] for r in workshop_library.rack(archive)["materials"]}
        self.assertEqual(before, after)
        with self.assertRaises(ValueError): workshop_library.set_rack(self.app, "oak", 0)

    def test_implicit_organic_recipe_and_explicit_organic_library_writes_are_refused(self):
        import workshop_build
        before = workshop_library.list_items(self.app)
        source = {"kind": "table", "parameters": {}}
        with self.assertRaises(ValueError):
            workshop_library.save_item(self.app, item_type="assembly", name="retired", payload=source)
        self.assertEqual(before, workshop_library.list_items(self.app))
        with self.assertRaisesRegex(ValueError, "unavailable in the game"):
            workshop_build.starting_overrides(self.app, {"family": "beam", "length_m": .4})
        legal = workshop_build.starting_overrides(self.app, {"family": "beam", "length_m": .4,
                                                            "material": "iron"})
        self.assertEqual("iron", legal["@construction"]["added"][0]["material"])

    def test_defaults_are_inorganic_but_explicit_wood_is_refused_instead_of_converted(self):
        spec = game_materials.recipe_spec(self.app, {"kind": "field-pick"})
        design, _ = workshop_components.design_from_spec(spec)
        game_materials.require_design(self.app, design)
        with self.assertRaises(ValueError):
            game_materials.recipe_spec(self.app, {"kind": "field-pick", "parameters": {"material": "oak"}})

    def test_chat_rejected_parameter_is_atomic_and_a_following_legal_edit_still_works(self):
        source = playable_recipes.recipe("field-pick")
        design, overrides = workshop_components.design_from_spec(source)
        candidate = {**design.wireframe(), "component_overrides": overrides}
        state = workshop_chat._State(self.app, candidate, None, ["iron", "aluminum", "oak"], [])
        before = deepcopy(candidate)
        with self.assertRaises(ValueError):
            state.execute("set_parameter", {"name": "material", "value": "oak"})
        self.assertEqual(before, candidate)
        game_materials.require_design(self.app, state.design)
        state.execute("edit_components", {"selector": {"names": ["arm"]}, "action": "material", "material": "iron"})
        game_materials.require_design(self.app, state.design)
        self.assertEqual([], workshop_library.list_items(self.app))

    def test_world_chat_policy_context_restores_after_failed_turn(self):
        with mock.patch.object(world_chat, "_ask", side_effect=lambda *a: world_chat.payload("test", [])):
            reply = world_chat.ask("test", "test", self.app.room, {}, "help", [])
            self.assertIn("PLAYABLE MATERIAL POLICY", reply["instructions"])
        self.assertNotIn("PLAYABLE MATERIAL POLICY", world_chat.payload("test", [])["instructions"])
        with mock.patch.object(world_chat, "_ask", side_effect=ValueError("transport")):
            with self.assertRaises(ValueError): world_chat.ask("test", "test", self.app.room, {}, "help", [])
        self.assertFalse(world_chat.GAME_CHAT.get())

    def test_new_game_request_can_leave_a_retired_world_without_opening_it(self):
        import server
        raw = b'{"name":"New inorganic world"}'
        handler = object.__new__(server.Handler)
        handler.path = "/api/worlds"
        handler.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json",
                           "X-Banjo-Token": "local-token", "X-Banjo-World": "a" * 32}
        handler.rfile = io.BytesIO(raw)
        handler.close_connection = False
        handler.server = SimpleNamespace(app=SimpleNamespace(csrf_token="local-token"))
        handler.trusted_host = mock.Mock()
        handler._dispatch_POST = mock.Mock(return_value="created")
        with mock.patch.object(server.access_gate, "answered", return_value=False), \
             mock.patch.object(server.Handler, "app", new_callable=mock.PropertyMock,
                               side_effect=ValueError("retired world must not open")):
            self.assertEqual("created", handler.do_POST())
        handler._dispatch_POST.assert_called_once_with("/api/worlds", {"name": "New inorganic world"})

    def test_saved_organic_sources_are_hidden_without_deleting_their_files(self):
        import workshop_store
        import workshop_api_core
        folder = workshop_api_core._store(self.app)
        old = workshop.assemble("table", design_id="old-wood")
        workshop_store.save(folder, old)
        design, _ = workshop_components.design_from_spec(playable_recipes.recipe("field-pick", design_id="metal-pick"))
        workshop_store.save(folder, design)
        before = {p: p.read_bytes() for p in folder.rglob("*.json")}
        rows = game_materials.saved_designs(self.app, folder)
        self.assertEqual(["metal-pick"], [r["design_id"] for r in rows])
        for view in (workshop_api_core.library(self.app), workshop_api_core.remembered(self.app)):
            self.assertEqual(["metal-pick"], [r["design_id"] for r in view["saved_designs"]])
        candidate = {**design.wireframe(), "component_overrides": design.lineage.get("component_overrides", {})}
        state = workshop_chat._State(self.app, candidate, None, ["iron", "aluminum"], [])
        self.assertEqual(["metal-pick"], [r["design_id"] for r in state.execute("list_saved_designs", {})["saved"]])
        self.assertEqual(before, {p: p.read_bytes() for p in folder.rglob("*.json")})


if __name__ == "__main__": unittest.main()
