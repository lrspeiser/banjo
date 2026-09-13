#include "fastlattice/LiveWorld.hpp"

#include "core/Plane.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticePhysics.hpp"
#include "fastlattice/Refracture.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "material/MaterialCompiler.hpp"
#include "rigid/JoltWorld.hpp"
#include "thermo/ThermoJson.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <thread>
#include <deque>
#include <future>
#include <map>
#include <optional>
#include <tuple>
#include <set>
#include <unordered_set>
#include <unordered_map>

namespace banjo::fastlattice {
namespace {
// The lattice's own vector type. The support planes are templated on it, and a
// scene's Vec3 is a different struct with the same three numbers in it.
V3<double> toV3(const Vec3 &v) { return {v.x, v.y, v.z}; }

// How big a piece is, from the cells it is made of. A body authored as a box or
// a sphere reports the size it was asked for; a piece that broke off something
// was never asked for at any size, and a host still has to draw it, so it gets
// the extent of its own cells rather than nothing at all.
Vec3 cellBounds(const std::vector<std::uint32_t> &nodes,
                const std::vector<Vec3> &offsets, double cell_m) {
    if (nodes.empty()) return {cell_m, cell_m, cell_m};
    Vec3 low = offsets[nodes.front()], high = low;
    for (const std::uint32_t node : nodes) {
        const Vec3 &at = offsets[node];
        low = {std::min(low.x, at.x), std::min(low.y, at.y), std::min(low.z, at.z)};
        high = {std::max(high.x, at.x), std::max(high.y, at.y), std::max(high.z, at.z)};
    }
    // The offsets are cell CENTRES, so the piece reaches half a cell past each.
    return {high.x - low.x + cell_m, high.y - low.y + cell_m, high.z - low.z + cell_m};
}
} // namespace

// One fracture in progress: everything the three phases pass between them.
struct LiveWorld::Pending {
    std::string name;
    double window_s{};
    // Set when prepare decided there was nothing to run -- an anchored body, a
    // name that is not there, something in a hand. `answer` is what fracture()
    // would have returned.
    bool settled{};
    std::size_t answer{};
    bool worked{};
    double cost_ms{};
    // Captured, and started. They are not the same moment for anything that had
    // to wait its turn, and reporting the gap as cost made the log say a
    // fracture took four seconds when it took thirty milliseconds and spent the
    // rest queued. A log that misattributes time is worse than no log: it sends
    // you to optimise the wrong thing.
    std::chrono::steady_clock::time_point began{};
    std::chrono::steady_clock::time_point started{};
    double waited_ms{};

    FragmentLattice island{};
    LatticeState state{};
    std::unique_ptr<LatticeBackend> backend;
    RunControl control{};
    SphereState<double> parked{};
    RunStatus status{};
    std::size_t which{};
    std::size_t anvil{static_cast<std::size_t>(-1)};
    std::vector<std::size_t> island_bodies;
    std::unordered_map<std::size_t, RigidSnapshot> poses_before;
    std::unordered_map<std::uint32_t, std::size_t> body_of_node;
    RigidSnapshot snap{};
    const MaterialDefinition *struck_material{};
    double yield_extension{};
    // Set when this run was started before the collision happened, so it can be
    // checked against the collision that actually turned up.
    // The cells of the bodies that were ADMITTED for breaking at this contact.
    //
    // An island has to contain whatever struck the thing being broken -- a body
    // entered alone is a free-flying object with no stress in it and cannot
    // break however hard it was hit. But the striker is then in a lattice run
    // that is not about it, and its own bonds can fail there: measured, an iron
    // ball hit a glass plate at 11.5 m/s against its own breaking threshold of
    // 25.03 m/s, with every contact reporting would_break false, and came out
    // of the plate's run as twenty-nine pieces.
    //
    // A threshold is "the speed below which nothing CAN happen". A body that
    // never cleared its own is not allowed to come apart in somebody else's
    // island, so its cells are recorded here and its bonds are put back before
    // the pieces are counted.
    //
    // Kept as cells rather than body numbers because cells are not renumbered
    // by anything, and the body table is.
    std::unordered_set<std::uint32_t> may_break;
    bool guessed{};
    std::string guessed_striker;
    double guessed_speed{};
    Vec3 guessed_at{};
};

struct LiveWorld::Impl {
    TileImpactRequest request{};
    std::unique_ptr<TileImpactSetup> setup;
    std::unique_ptr<JoltWorld> world;
    std::vector<LiveBodyPose> described;   // one per rigid fragment, static parts
    std::vector<MatterBodyId> body_of;     // parallel to described
    // What each body is made of, kept because breaking one means rebuilding its
    // lattice from the parent it was cut out of.
    std::vector<std::vector<std::uint32_t>> nodes_of;
    std::vector<FragmentFractureLimits> limits_of;
    std::vector<double> impedance_of;
    std::vector<double> density_of;
    // What each PART of the scene is made of, in the words the room uses.
    //
    // Filled once, when the scene opens, because that is the only place both
    // halves are in hand at the same time: the part index, and the common name
    // the bodies carry. A piece works out what it is from the part its cells
    // mostly belong to, and looking that up through whichever body happened to
    // be in the island was wrong twice over -- a part with no body in the
    // island gave a piece no material at all ("2,833 g of "), and a part whose
    // slot had been claimed by something else gave it the wrong one (iron
    // shards reported as 4.3 kg of glass where there were 2.5).
    std::vector<std::string> material_of_part;
    // This step's contacts, which is what breakable() and the step-back
    // decision are about: a body that has already been answered for must not be
    // re-offered on the strength of a contact from three steps ago.
    std::vector<LiveImpact> last_impacts;
    // Every contact since the host last said it had read them. The hardest of
    // each pair survives, because a landing reports the same pair many times as
    // it settles and the one that matters is the one that arrived.
    std::vector<LiveImpact> reported;
    // For each body the last step would have broken, the body that hit it, or
    // npos for the ground. An island built without the thing that struck it is
    // a free-flying object with no stress in it, which breaks nothing.
    std::unordered_map<std::size_t, std::size_t> partner_of;
    bool stepped_back{};
    LiveOutcome last_outcome{LiveOutcome::Nothing};
    std::vector<LiveDelay> delays;
    std::unique_ptr<LiveWorld::Pending> pending;
    std::future<void> worker;
    // Breaks that arrived while one was already being worked out.
    //
    // They are PREPARED at the moment they are detected -- from the rolled-back
    // step, which is the only state that still has the closing speed in it --
    // and only the expensive part waits. Preparing is a copy; the run is the
    // third of a second.
    //
    // Without this the clock simply stopped. A break the world has not resolved
    // is a step it will not take, and the host cannot resolve it because asking
    // for a second fracture while one is running gets nothing back. So the
    // world sat at one instant for as long as the run took: measured in the
    // owner's own session, 756 ms of wall clock in which the world advanced
    // 0 ms, twice in one cascade.
    std::deque<std::unique_ptr<LiveWorld::Pending>> queued;
    // A run started for a collision that has not happened yet. Kept apart from
    // `pending` on purpose: nothing has actually broken, so the world must look
    // exactly as it did -- nothing is pinned, `working_on` is empty, and a host
    // behaves as though no fracture were running, because none is.
    std::unique_ptr<LiveWorld::Pending> guessing;
    std::future<void> guess_worker;
    // How many passes in a row the collision a guess was made for has not been
    // expected. One is nothing -- the instant somebody lets go of a thing, it
    // stops being a held drop and has not yet become a falling one, and a guess
    // binned in that gap is binned at the exact moment it was about to pay.
    // That happened: a run started while the object was being held, finished
    // 816 ms of work, and was thrown away on release.
    int guess_unseen{};
    LiveWorld::Foresight guess{};
    double guess_error_pct{};
    // Pinned while their fracture is worked out, so they do not carry on as
    // though nothing were about to happen to them. A ball that bounced off a
    // pane which was in fact shattering would have to be put back afterwards,
    // and that correction is more jarring than the wait it replaced.
    std::vector<std::size_t> held_for_fracture;
    // How far ahead to look, and how often. Looking every step would cost a ray
    // per moving body per step; every eighth is thirty times a second at the
    // rate a live host runs, which is far finer than the tenths of a second
    // this is trying to see coming.
    // Far enough ahead to be worth having: the lattice run costs about as long
    // as a two-metre fall takes, so a horizon shorter than that can only ever
    // narrate what is about to happen rather than get ahead of it. It was 0,
    // which means off -- and nothing in the playground ever turned it on, so
    // the foresight this engine already had was never once used.
    double foresee_horizon_s{2.5};
    std::uint64_t steps_taken{};
    // What has already been said about, so one approach is not reported on
    // every step for a third of a second.
    std::set<std::string> foreseen;
    // The rigid step that was taken back. The lattice has to cover it before it
    // can cover the impact, because the world is that far short of contact.
    double last_dt_s{};
    // Where each parent cell sits in its body's frame, in parent node order --
    // the same array the batch lane keeps, because buildFragmentLattice reads
    // it that way. Rewritten whenever a body is replaced by its pieces.
    std::vector<Vec3> cell_offset_m;
    // Permanent extension a bond carries. Zero in a world that has not broken
    // anything yet; a piece that has flowed comes back having flowed.
    std::vector<double> plastic_extension_m, plastic_strain_m;
    MatterBodyId next_body_id{1000};
    // How many cells one authored part has, so a component that is all of them
    // can be recognised as still being that object rather than a piece of it.
    std::vector<std::size_t> part_cells;
    [[nodiscard]] std::size_t cellsOfPart(std::size_t part) const {
        return part < part_cells.size() ? part_cells[part] : 0;
    }
    // The floor is concrete, not a rigid abstraction: it has a finite impedance
    // and the admission test uses it like any other partner.
    double ground_impedance{};
    std::unordered_map<std::string, std::size_t> index_of;
    double time_s{};
    std::size_t holding{static_cast<std::size_t>(-1)};
    // Where the hand is. A held body is put back here after every step, which
    // is what makes it a hold rather than a shove: gravity and contacts still
    // act on everything else, and the held object simply does not move unless
    // the hand does.
    Vec3 held_at{};
    Quat held_facing{};
    // How hard the hand can pull on something attached to other things.
    //
    // 800 N is a hard two-handed heave -- enough to draw a stiff bow, work a
    // winch or wrench a gate open, and not enough to tear the gate off its
    // hinges, which is the line this number draws.
    double hand_strength_n{800.0};
    // Bodies that were put back into the lattice for this contact and came
    // through it whole.
    //
    // Without this the world deadlocks. A step that would break something is
    // taken back, so the world sits one step short of the impact. If the
    // fracture then finds the object HELD, nothing has changed -- the next step
    // meets the same contact, is judged breakable again, and is taken back
    // again, for ever. The scene freezes and the host is told the same thing
    // over and over.
    //
    // An object that has already been tried at this contact therefore stops
    // being a reason to refuse a step. It is cleared again the moment its
    // contacts stop being hard enough to break it, which is what happens as
    // soon as the two bodies separate.
    std::set<std::string> held_through;
    // What is carrying more than it can hold up, from the last survey. Kept
    // rather than recomputed on every ask, because a host reads it once a frame
    // and the survey is a stride thing.
    std::vector<LiveOverload> overloaded;
    // For an overloaded body, the heaviest thing sitting on it.
    //
    // The island a fracture is run on is built from the CONTACT that caused it,
    // and a sustained load has no contact -- so an overloaded shelf would go
    // into the lattice on its own, with nothing pressing on it, and come out
    // whole however much was piled on. This is what gives it its load back.
    std::unordered_map<std::size_t, std::size_t> bearing_on;
    // What each part is made of, in the engine's terms, so a survey can ask a
    // body what it can take without going back through the scene.
    std::vector<double> tensile_of;
    // Heat, chemistry and gas (thermo/ThermoWorld.hpp). Null until something
    // declares any, so a world without them pays nothing for them.
    std::unique_ptr<thermo::ThermoWorld> thermo;
    // Terrain and water (terrain/Environment.hpp). Null unless the scene
    // declares them, so a room without them pays nothing.
    std::unique_ptr<terrain::Environment> environment;
    // A broken piece's cells in its own frame, for the water to press on,
    // kept by name while its cell count stays the same.
    std::unordered_map<std::string, std::pair<std::size_t, std::vector<Vec3>>> water_cells_of;
    // An authored box's own tilt, which lives in its collision shape rather
    // than in its pose: the water has to press on the box that is there.
    std::unordered_map<std::string, Quat> tilt_of;
    // A hull's surface, from its cells, worked out once per body.
    mutable std::unordered_map<std::string, std::pair<std::size_t, double>> hull_area_of;

    // Pins, by name. See LiveJoint in the header for why it is names and not
    // bodies. `rigid` is the engine-level constraint that is currently standing
    // in for it, remade every time the body table is rearranged.
    struct SceneJoint {
        unsigned id{};
        std::string a, b;
        // Where the pin sits inside each body's OWN matter, and which way it
        // runs in the first one's. This is the part that survives: the assembly
        // can be carried across the room or turned over and the pin is still in
        // the same place in the wood.
        Vec3 point_local_a{}, point_local_b{}, axis_local_a{};
        JoltWorld::JointKind kind{JoltWorld::JointKind::Hinge};
        double lower{}, upper{}, friction{};
        // A link's second attachment, which a pin and a slide do not have: they
        // are one point shared by two bodies, while a rope is tied at one place
        // on each and the two are not the same place.
        Vec3 point_local_b_tie{};
        double breaks_at_n{};
        // A pulley's two fixed points and its advantage. The points are in the
        // WORLD and stay there: a sheave bolted to a beam is the fixed half of
        // the relationship, and making it follow a body would make it not fixed.
        Vec3 over_a{}, over_b{};
        double ratio{1.0};
        // A fixing's two strengths, and where its axis points in the first
        // body's own frame -- so that tension and shear stay tension and shear
        // when the whole assembly is carried somewhere else or turned over.
        double holds_tension_n{}, holds_shear_n{};
        // An elastic's declared model.
        double rest_m{}, stiffness_n_m{}, damping_n_s_m{};
        // How far it had got, last time anyone could ask. Kept up to date every
        // step because the thing that destroys the constraint is the same thing
        // that needs to know it -- once the wood is rebuilt there is nobody left
        // to ask, and a door that had swung 60 degrees, or a portcullis hauled
        // a metre up, would be re-made as though it were shut.
        double at_when_hung{};
        unsigned rigid{};        // 0 when the pin is not currently in anything
        bool attached{true};
    };
    std::vector<SceneJoint> joints;
    unsigned next_joint{1};
    void rememberJointAngles(const JoltWorld &in) {
        for (SceneJoint &joint : joints)
            if (joint.rigid != 0 && in.hasJoint(joint.rigid))
                joint.at_when_hung = in.jointState(joint.rigid).at;
    }
};

LiveWorld::LiveWorld() : impl_(std::make_unique<Impl>()) {}
LiveWorld::~LiveWorld() = default;

std::unique_ptr<LiveWorld> LiveWorld::open(const TileImpactRequest &request) {
    std::unique_ptr<LiveWorld> live(new LiveWorld());
    Impl &impl = *live->impl_;
    impl.request = request;
    // Ledges belong to the single-tile lane, which drops one plate across two
    // of them. A scene of objects stands on the ground, and leaving the bridge
    // layout in place puts a support plane at the ledge height through the
    // middle of everything -- a pane resting on the floor then reads as 140 mm
    // buried and every attempt to break it is refused as too deeply penetrated.
    if (!impl.request.bodies.empty()) impl.request.layout = SceneLayout::Flat;
    impl.setup = buildTileImpactSetup(impl.request);
    TileImpactSetup &setup = *impl.setup;
    const TileImpactRequest &r = impl.request;
    // Terrain and water. With ground that is not flat, the flat floor the
    // setup assumes goes under all of it -- to the rock's own floor -- where it
    // is a safety net and not a surface: the floor under a lattice run and the
    // plane heat conducts into both follow it there.
    if (!r.environment_scene_json.empty()) {
        impl.environment = terrain::Environment::fromScene(r.environment_scene_json);
        if (impl.environment) setup.ground_y = std::min(setup.ground_y, impl.environment->floorY());
    }

    // The setup leaves its matter in the frame of the scene's own origin. The
    // batch lane only ever sees world coordinates because its lattice phase
    // writes a state back before the handoff, and that write-back is where the
    // origin is added. Nothing has been simulated here, so do the same round
    // trip with no steps in it: build a state and write it straight back, which
    // moves the cells into world coordinates and changes nothing else.
    {
        const LatticeState rest = buildLatticeState(setup.matter, setup.schedule, setup.origin);
        writeBackLatticeState(rest, setup.schedule, setup.matter);
    }

    impl.cell_offset_m.assign(setup.matter.nodes.size(), Vec3{});
    impl.part_cells.assign(setup.part_bodies.size(), 0);
    for (const std::uint32_t part : setup.part_of_node)
        if (part < impl.part_cells.size()) ++impl.part_cells[part];
    impl.plastic_extension_m.assign(setup.asset.bonds.size(), 0.0);
    impl.plastic_strain_m.assign(setup.asset.bonds.size(), 0.0);

    // Nothing has been struck, so every part is still one whole component.
    const auto components = findConnectedComponents(setup.matter);
    if (components.empty()) throw std::runtime_error("a live world needs at least one body");

    FragmentBuildResult build = buildFragmentRepresentations(setup.matter, components, {
        .first_body_id = 1000,
        .maximum_rigid_fragments = std::max<std::size_t>(1, components.size()),
        .minimum_nodes_per_rigid_fragment = 1,
        .maximum_collision_points = 192,
        .friction = setup.tile_ground.dynamic_friction,
        .restitution = setup.tile_ground.restitution,
    });

    // Give each whole un-joined body the shape it was authored as, so a tilted
    // ramp collides as a ramp and a ball rolls. This is the batch lane's rule
    // and the same conditions: a join is a union that no primitive describes,
    // and a cone's cell hull is already its true surface.
    std::vector<std::size_t> part_size(setup.part_bodies.size(), 0);
    for (const std::uint32_t part : setup.part_of_node) ++part_size[part];
    std::size_t fragment_index = 0;
    for (const auto &component : components) {
        if (fragment_index >= build.rigid_fragments.size()) break;
        RigidFragmentDescription &fragment = build.rigid_fragments[fragment_index];
        if (fragment.source_node_count != component.node_indices.size()) continue;
        const std::size_t here = fragment_index++;
        if (component.node_indices.empty()) continue;

        LiveBodyPose described{};
        described.name = "piece " + std::to_string(here);
        if (setup.multi_body && !setup.part_of_node.empty()) {
            const std::uint32_t part = setup.part_of_node[component.node_indices.front()];
            bool whole = part_size[part] == component.node_indices.size();
            for (const std::uint32_t node : component.node_indices)
                if (setup.part_of_node[node] != part) { whole = false; break; }
            if (part < setup.part_bodies.size() && !setup.part_bodies[part].empty()) {
                const SceneBody &lead = r.bodies[setup.part_bodies[part].front()];
                described.name = lead.name;
                described.material = materialPresetName(lead.material);
                described.color_rgba = lead.color_rgba;
                for (const std::size_t which : setup.part_bodies[part])
                    if (r.bodies[which].anchored) described.anchored = true;
                fragment.anchored = described.anchored;
                if (whole && setup.part_bodies[part].size() == 1 &&
                    lead.shape != BodyShape::Cone) {
                    fragment.primitive = lead.shape == BodyShape::Sphere
                                             ? FragmentPrimitive::Sphere
                                             : FragmentPrimitive::Box;
                    fragment.primitive_dimensions_m = lead.dimensions_m;
                    rotationQuaternion(lead.rotation_deg, fragment.primitive_rotation_wxyz);
                    if (lead.rotation_deg.x != 0.0 || lead.rotation_deg.y != 0.0 || lead.rotation_deg.z != 0.0)
                        impl.tilt_of[lead.name] = Quat{fragment.primitive_rotation_wxyz[0],
                                                       fragment.primitive_rotation_wxyz[1],
                                                       fragment.primitive_rotation_wxyz[2],
                                                       fragment.primitive_rotation_wxyz[3]};
                    described.shape = lead.shape == BodyShape::Sphere ? "sphere" : "box";
                    described.dimensions_m = lead.dimensions_m;
                }
            }
        }
        // What it would take to break this one. The impedance is the struck
        // body's own material, not the tile's: a glass pin and an oak lane in
        // the same scene do not break at the same speed.
        const MaterialDefinition *definition = &setup.tile_material;
        if (setup.multi_body && !setup.part_of_node.empty()) {
            const std::uint32_t part = setup.part_of_node[component.node_indices.front()];
            if (part < setup.part_definitions.size()) definition = &setup.part_definitions[part];
        }
        impl.limits_of.push_back(fragmentFractureLimits(
            setup.matter, component.node_indices,
            definition->density_kg_m3, definition->young_modulus_pa,
            definition->yield_strength_pa));
        impl.impedance_of.push_back(
            acousticImpedance(definition->density_kg_m3, definition->young_modulus_pa));
        // Kept so a piece can say what it weighs. Its cells are its volume, and
        // volume times this is matter somebody can carry away.
        impl.density_of.push_back(definition->density_kg_m3);
        // And what it can take in bending, for the load survey. A beam fails on
        // the tension side, so this is the number that decides a loaded shelf.
        impl.tensile_of.push_back(definition->tensile_strength_pa);
        if (!setup.part_of_node.empty()) {
            if (impl.material_of_part.size() < setup.part_bodies.size())
                impl.material_of_part.resize(setup.part_bodies.size());
            for (const std::uint32_t node : component.node_indices) {
                const std::uint32_t part = setup.part_of_node[node];
                if (part < impl.material_of_part.size() &&
                    impl.material_of_part[part].empty())
                    impl.material_of_part[part] = described.material;
            }
        }
        // How it meets the floor, from the same material the threshold came
        // from. Without this every body in the scene carried the contact of the
        // scene's default matter and nothing bounced differently from anything
        // else.
        const CombinedContactMaterial against_ground = combineContactMaterials(
            compileContactMaterial(*definition), compileContactMaterial(setup.ground_material));
        fragment.friction = against_ground.dynamic_friction;
        fragment.restitution = against_ground.restitution;
        impl.nodes_of.emplace_back(component.node_indices.begin(), component.node_indices.end());
        for (const std::uint32_t node : component.node_indices)
            impl.cell_offset_m[node] = setup.matter.nodes[node].position_world_m -
                                       fragment.mass_properties.center_of_mass_world_m;
        impl.next_body_id = std::max(impl.next_body_id, fragment.body_id + 1);
        if (described.shape == "hull")
            described.dimensions_m = cellBounds(impl.nodes_of.back(), impl.cell_offset_m,
                                                r.cell_size_m);
        impl.described.push_back(std::move(described));
        impl.body_of.push_back(fragment.body_id);
    }

    // The most bodies a live world will hold: what runReversibleTrial allows,
    // which is what breaking depends on.
    constexpr std::size_t kLiveBodyCeiling = 2048;
    const auto clampCapacity = [](std::size_t value, unsigned low, unsigned high) {
        return static_cast<unsigned>(std::clamp<std::size_t>(value, low, high));
    };
    impl.world = std::make_unique<JoltWorld>(
        std::clamp(std::thread::hardware_concurrency(), 1U, 64U),
        // Sized for what the world may GROW to, not for what it opened with.
        //
        // A live world starts with a few dozen bodies and reaches hundreds by
        // breaking them, and the capacity was worked out once from the opening
        // count. That was fine while the reversible trial capped the world at
        // 256; with the cap at 2,048 it is not, and going over does not slow
        // anything down -- it drops contacts and says "the step is not
        // validated", which is a worse failure than any pause.
        RigidContactCapacity{clampCapacity(64U * kLiveBodyCeiling, 16384U, 262144U),
                             clampCapacity(128U * kLiveBodyCeiling, 8192U, 65536U)});
    impl.ground_impedance = acousticImpedance(setup.ground_material.density_kg_m3,
                                             setup.ground_material.young_modulus_pa);
    impl.world->setGravity(r.gravity_m_s2);
    // A live world always watches contacts: they are how it will know when
    // something has been hit hard enough to break, and they are what a host
    // narrates back to whoever is playing with it.
    impl.world->setImpactObservationsEnabled(true);
    // The floor reaches as far as a hand can carry something.
    //
    // The batch lane's ground is 8 m square, which is ample for a plate dropped
    // where it was authored -- nothing in a recording ever moves sideways on
    // its own. A live world is different: someone picks an object up and takes
    // it where they like, and past 4 m there was simply no floor. An iron ball
    // carried to x = 5 m and let go fell to -7.9 m and kept going, which is not
    // a physics answer, it is the absence of one.
    //
    // A support plane costs one entry in a fixed-size set however big it is, so
    // there is nothing to trade: make it larger than anywhere a pointer can
    // reasonably drag something.
    // Hitting the floor is something that happens to things, so it is judged
    // like any other contact. The batch lane does not ask for this and is
    // unchanged by it.
    impl.world->setSurfaceImpactObservations(true);
    constexpr double kLiveGroundHalfSpanM = 200.0;
    impl.world->addSupportSurface({
        .frame = makeSupportPlane({0.0, setup.ground_y, 0.0}, {0.0, 1.0, 0.0}),
        .material = setup.ground_material,
        .half_length_tangent_m = kLiveGroundHalfSpanM,
        .half_length_bitangent_m = kLiveGroundHalfSpanM,
        .thickness_m = 0.5,
    });
    if (impl.environment) impl.environment->attach(*impl.world);
    MatterBodyId next_static = 900;
    for (const StaticBox &ledge : setup.ledges)
        impl.world->addBox({.body_id = next_static++, .dimensions_m = ledge.dimensions_m,
                            .material = setup.ground_material,
                            .state = {.center_of_mass_world_m = ledge.center_m}, .fixed = true});
    impl.world->addFragments(build.rigid_fragments);

    for (std::size_t i = 0; i < impl.described.size(); ++i)
        impl.index_of.emplace(impl.described[i].name, i);
    // What the scene declares about heat, chemistry and gas. A declaration the
    // network refuses refuses the scene, with the network's own words, rather
    // than opening a world that quietly lacks the fire it was asked for.
    if (!r.thermo_scene_json.empty()) {
        const thermo::Declarations declared = thermo::readSceneDeclarations(r.thermo_scene_json);
        if (declared.any()) thermo::apply(live->ensureThermo(), declared);
    }
    return live;
}

// Fills last_impacts and partner_of from the contacts of the step just taken,
// and answers whether any of them would break something.
bool LiveWorld::judgeStep() {
    impl_->last_impacts.clear();
    impl_->partner_of.clear();
    std::unordered_map<MatterBodyId, std::size_t> index_of_body;
    for (std::size_t i = 0; i < impl_->body_of.size(); ++i)
        index_of_body.emplace(impl_->body_of[i], i);
    bool any_would_break = false;
    std::set<std::string> breaking_now;
    std::unordered_map<std::size_t, double> worst_speed;
    for (const ImpactEvent &event : impl_->world->drainImpacts()) {
        const auto a = index_of_body.find(event.body_a);
        const auto b = index_of_body.find(event.body_b);
        const bool a_known = a != index_of_body.end();
        const bool b_known = b != index_of_body.end();
        if (!a_known && !b_known) continue;
        const std::size_t pair[2] = {a_known ? a->second : b->second,
                                     b_known ? b->second : a->second};
        for (int which = 0; which < 2; ++which) {
            const std::size_t struck = pair[which];
            const std::size_t other = pair[1 - which];
            const bool both = a_known && b_known;
            if (which == 1 && !both) break;
            if (impl_->described[struck].anchored) continue;
            // The ground is what it is made of where it was hit: a stone that
            // lands on sand meets soft ground, and one that lands on bare rock
            // meets stone. Judging every landing against the flat floor's
            // concrete shattered a boulder that rolled into a hole in sand.
            const bool on_terrain = impl_->environment &&
                                    (event.body_a == kGroundPatchMatterId || event.body_b == kGroundPatchMatterId);
            const double ground_impedance =
                on_terrain ? impl_->environment->contactImpedanceAt(event.contact_point_world_m)
                           : impl_->ground_impedance;
            const double other_impedance = both && other != struck
                                               ? impl_->impedance_of[other]
                                               : ground_impedance;
            const RefractureAdmission admission = admitRefracture(
                impl_->limits_of[struck], other_impedance,
                event.closing_speed_m_s, event.available_normal_energy_j);
            LiveImpact impact{};
            impact.struck = impl_->described[struck].name;
            impact.by = both && other != struck ? impl_->described[other].name
                                                : std::string("the ground");
            impact.closing_speed_m_s = event.closing_speed_m_s;
            impact.threshold_speed_m_s = admission.threshold_speed_m_s;
            impact.energy_j = event.available_normal_energy_j;
            impact.threshold_speed_m_s = admission.threshold_speed_m_s;
            impact.dent_speed_m_s = admission.yield_speed_m_s;
            impact.would_break = admission.admitted();
            impact.would_dent = admission.yields;
            // Either one needs the lattice, and only the lattice can say which
            // of them actually happens. A trigger that asked about breaking
            // alone never ran below the breaking bar, which is exactly where a
            // dent lives.
            if (admission.worthRunning()) {
                breaking_now.insert(impact.struck);
                // Remember what hit it, for the island a fracture would build.
                // The hardest contact wins: a body resting on the floor and
                // struck by a ball reports both, and the ball is the one that
                // matters.
                double &worst = worst_speed[struck];
                if (impact.closing_speed_m_s >= worst) {
                    worst = impact.closing_speed_m_s;
                    impl_->partner_of[struck] =
                        both && other != struck ? other : static_cast<std::size_t>(-1);
                }
            }
            impl_->last_impacts.push_back(std::move(impact));
        }
    }

    // One body reports several contacts in a step -- a ball on a panel is also
    // resting on something, and most of those are gentle. Deciding "has this
    // already been tried" inside the event loop made the answer depend on the
    // order the events happened to arrive in: a gentle contact cleared the flag
    // that a hard one then set again, and the world stayed wedged even though
    // every part of the rule looked right. Decide it once, after all of them.
    // Keep them where the host can still find them after the batch.
    for (const LiveImpact &impact : impl_->last_impacts) {
        auto same = std::find_if(impl_->reported.begin(), impl_->reported.end(),
                                 [&](const LiveImpact &seen) {
                                     return seen.struck == impact.struck && seen.by == impact.by;
                                 });
        if (same == impl_->reported.end()) impl_->reported.push_back(impact);
        else if (impact.closing_speed_m_s > same->closing_speed_m_s) *same = impact;
    }

    // A body whose answer is already being worked out, or already captured and
    // waiting for a worker, is accounted for: stopping the world over it a
    // second time achieves nothing, because nobody can answer for it twice.
    //
    // `held_through` alone was not enough. It is cleared for any body that is
    // not in contact this step, and a captured body whose contact lapses for a
    // step and resumes was then treated as brand new -- it stopped the clock,
    // and queueBreaks skipped it because it was already in the queue, so
    // nothing cleared it and nothing could. Measured, that stalled the world for
    // 106 steps in a row with the capture working perfectly.
    const auto accounted = [&](const std::string &name) {
        if (impl_->pending && impl_->pending->name == name) return true;
        for (const auto &waiting : impl_->queued)
            if (waiting->name == name) return true;
        return false;
    };
    for (const std::string &name : breaking_now)
        if (impl_->held_through.count(name) == 0 && !accounted(name)) any_would_break = true;
    // A body that is no longer in danger from anything gets a fresh hearing the
    // next time something hits it hard.
    for (auto it = impl_->held_through.begin(); it != impl_->held_through.end();)
        it = breaking_now.count(*it) ? std::next(it) : impl_->held_through.erase(it);
    return any_would_break;
}

void LiveWorld::step(double dt_s) {
    if (!(dt_s > 0.0)) throw std::invalid_argument("a live step needs a positive dt");

    // A held object goes back where the hand put it after the step. This is a
    // kinematic hold rather than a constraint: a world-fixed constraint
    // auto-detects its anchor from wherever the body was when it was made, so
    // it drags a moved body straight back, while re-asserting the pose has no
    // such memory and still lets a dragged object push what it runs into.
    // Whatever is waiting on a fracture stays put. The same kinematic hold the
    // hand uses: the pose is re-asserted after the step, so the body does not
    // move and does not accumulate speed, but still pushes what runs into it.
    // Everything waiting on an answer, running or queued. A queued body must be
    // pinned for the same reason a running one is: its pieces will be put back
    // where it was when it broke, so if it is allowed to bounce away first it
    // visibly springs back to the impact before it comes apart.
    const auto holdPending = [&]() {
        for (const std::size_t body : impl_->held_for_fracture) {
            if (body >= impl_->body_of.size()) continue;
            const MatterBodyId id = impl_->body_of[body];
            if (!impl_->world->contains(id)) continue;
            RigidSnapshot state = impl_->world->snapshot(id);
            state.linear_velocity_m_s = {};
            state.angular_velocity_rad_s = {};
            impl_->world->applyRigidState(id, state);
            impl_->world->wake(id);
        }
    };

    const auto holdStill = [&]() { carryOrHaul(dt_s); };

    // A step that would break something is taken back.

    //
    // Jolt resolves a contact within the step, so by the time the contact is
    // reported the energy has already gone into bouncing the two bodies apart.
    // Handing THAT state to the lattice is handing it a ball that has already
    // bounced: the island flies off with a uniform velocity, carries no stress
    // anywhere in it, and breaks nothing however hard it was hit -- measured,
    // as 171 ms of lattice that produced one piece. Rolling the step back
    // leaves the world one step short of the impact with the closing speed
    // intact, which is the state fracture() has to start from.
    //
    // runReversibleTrial caps out at 2,048 bodies. Past that the step is taken
    // straight; impacts are still reported, but they describe a collision that
    // has already been resolved, so fracture() will find nothing left to break.
    // That is a silent failure -- the room keeps running and simply stops
    // shattering -- so the ceiling is set where a room has to work to reach it
    // rather than where two broken panes reach it.
    impl_->stepped_back = false;
    impl_->last_dt_s = dt_s;
    ++impl_->steps_taken;

    // Heat, chemistry and gas step with the rigid world and on its clock.
    //
    // A pressure boundary pushes on its body INSIDE the trial, so a step that
    // is taken back takes the push back with it -- Jolt's recorded state holds
    // the force accumulator, and a push made outside would survive the rewind
    // and be applied again on the retry. After the rigid step the network is
    // advanced with how far each pushed body actually went, and charges the gas
    // exactly that force times that displacement. And if the step is refused,
    // the network is put back to where it was: the fuel the step would have
    // burned, the gas it would have made, the heat it would have moved.
    thermo::ThermoWorld *const network =
        impl_->thermo && impl_->thermo->active() ? impl_->thermo.get() : nullptr;
    std::optional<thermo::ThermoState> network_before;
    if (network != nullptr) network_before = network->state();
    struct Driven {
        std::string body;
        MatterBodyId id{};
        Vec3 from{};
    };
    std::vector<Driven> driven;
    const auto pushGas = [&]() {
        driven.clear();
        if (network == nullptr) return;
        for (const thermo::Push &push : network->pushes()) {
            const auto found = impl_->index_of.find(push.body);
            if (found == impl_->index_of.end()) continue;
            const MatterBodyId id = impl_->body_of[found->second];
            if (!impl_->world->contains(id)) continue;
            impl_->world->pushBody(id, push.force_n);
            driven.push_back({push.body, id, impl_->world->snapshot(id).center_of_mass_world_m});
        }
    };
    const auto advanceGas = [&]() {
        if (network == nullptr) return;
        std::vector<thermo::Moved> moved;
        moved.reserve(driven.size());
        for (const Driven &d : driven)
            moved.push_back({d.body, impl_->world->snapshot(d.id).center_of_mass_world_m - d.from});
        network->advance(dt_s, moved);
    };
    // Terrain and water, the same way round: the water's pressure and drag are
    // pushed inside the trial, so a refused step takes them back; the water,
    // the ground and its colliders move on only once the step is accepted.
    terrain::Environment *const environment = impl_->environment.get();
    const auto pushWater = [&]() {
        if (environment != nullptr) environment->push(*impl_->world, waterBodies());
    };
    const auto settleEnvironment = [&]() {
        if (environment != nullptr) environment->commit(*impl_->world, waterBodies(), dt_s);
    };

    if (impl_->body_of.size() + 8 <= 2000) {
        bool committed = false;
        try {
            committed = impl_->world->runReversibleTrial([&]() {
                pushGas();
                pushWater();
                impl_->world->step(dt_s);
                holdStill();
                holdPending();
                if (judgeStep()) return false;
                advanceGas();
                return true;
            });
        } catch (...) {
            if (network != nullptr) network->restore(*network_before);
            throw;
        }
        if (!committed && network != nullptr) network->restore(*network_before);
        impl_->stepped_back = !committed;
        // A step that was taken back did not happen, so the clock does not move
        // and the hold does not need re-asserting -- the world is as it was.
        //
        // That is the handshake, and it is right when the host can answer. It is
        // NOT right when something is already being worked out: the host asking
        // for a second fracture gets nothing back, so nobody can resolve this
        // break and the world sits at one instant for as long as the first run
        // takes. Measured in the owner's own session: 756 ms of wall clock in
        // which the world advanced 0 ms, and again 750 ms for 10 ms, in a
        // cascade that came out at 40% of real time with nothing "blocked".
        //
        // So take the break now instead of waiting to be asked. Right here the
        // world is one step short of the impact with the closing speed intact,
        // which is exactly the state the host would have handed back, and
        // preparing is a copy -- it is the RUN that costs a third of a second.
        // Preparing also records the name as heard, so the next step commits
        // and the clock moves again.
        if (!committed) {
            if (impl_->pending) queueBreaks();
            return;
        }
        impl_->time_s += dt_s;
        impl_->rememberJointAngles(*impl_->world);
        partOverloadedLinks();
        // Load does not change in a quarter of a second, and the survey is
        // O(bodies squared). Sixty times a second would be waste; four is not.
        if (impl_->steps_taken % 60 == 0) surveyLoads();
        foresee();
        settleThermo();
        settleEnvironment();
        return;
    }
    pushGas();
    pushWater();
    impl_->world->step(dt_s);
    holdStill();
    holdPending();
    (void)judgeStep();
    advanceGas();
    impl_->time_s += dt_s;
    impl_->rememberJointAngles(*impl_->world);
    partOverloadedLinks();
    if (impl_->steps_taken % 60 == 0) surveyLoads();
    foresee();
    settleThermo();
    settleEnvironment();
}

// Part every link carrying more than it can take.
//
// A rope that cannot fail is a rope that will hold a cathedral up, and the
// whole point of a hoist is that you have to think about what you hang on it.
// So a link with a breaking tension is checked against what the solver actually
// applied on the step just taken -- not against a guess from the load, which
// would miss the shock of something being dropped on the end of it.
//
// The link goes, and says so: `attached` turns false and stays in the list for
// one report, the same as a gate coming off its hinges, because a host that drew
// a rope has to be told to stop drawing it. What was hanging on it falls.
void LiveWorld::partOverloadedLinks() {
    for (Impl::SceneJoint &joint : impl_->joints) {
        const bool a_link = joint.kind == JoltWorld::JointKind::Link;
        const bool a_fixing = joint.kind == JoltWorld::JointKind::Fixing;
        if (!a_link && !a_fixing) continue;
        if (!joint.attached || joint.rigid == 0) continue;
        if (!impl_->world->hasJoint(joint.rigid)) continue;

        double carrying = 0.0, bar = 0.0;
        if (a_fixing) {
            // Two bounds, checked separately, because a peg pulled straight out
            // and a peg sheared sideways fail at different loads. Whichever is
            // the nearer to giving is the one that decides.
            if (!(joint.holds_tension_n > 0.0) && !(joint.holds_shear_n > 0.0)) continue;
            const auto found = impl_->index_of.find(joint.a);
            const Vec3 along =
                found != impl_->index_of.end()
                    ? impl_->world->snapshot(impl_->body_of[found->second])
                          .orientation_world.rotate(joint.axis_local_a)
                    : joint.axis_local_a;
            const JoltWorld::JointLoad load = impl_->world->jointLoad(joint.rigid, along);
            const bool pulled_apart = joint.holds_tension_n > 0.0 &&
                                      load.tension_n > joint.holds_tension_n;
            const bool sheared = joint.holds_shear_n > 0.0 &&
                                 load.shear_n > joint.holds_shear_n;
            if (!pulled_apart && !sheared) continue;
            carrying = pulled_apart ? load.tension_n : load.shear_n;
            bar = pulled_apart ? joint.holds_tension_n : joint.holds_shear_n;
        } else {
            if (!(joint.breaks_at_n > 0.0)) continue;
            carrying = impl_->world->jointTension(joint.rigid);
            if (carrying <= joint.breaks_at_n) continue;
            bar = joint.breaks_at_n;
        }
        impl_->world->removeJoint(joint.rigid);
        joint.rigid = 0;
        joint.attached = false;
        impl_->delays.push_back({impl_->time_s, joint.a + " to " + joint.b,
                                 a_fixing ? "gave way" : "parted", carrying, bar});
        // Both ends have to wake or what was hanging there stays hanging in the
        // air until something else disturbs it.
        for (const std::string &side : {joint.a, joint.b}) {
            const auto found = impl_->index_of.find(side);
            if (found != impl_->index_of.end())
                impl_->world->wake(impl_->body_of[found->second]);
        }
    }
}

double LiveWorld::time_s() const { return impl_->time_s; }
std::size_t LiveWorld::bodies() const { return impl_->described.size(); }

double LiveWorld::cellSize() const { return impl_->request.cell_size_m; }

std::vector<LiveBodyPose> LiveWorld::poses(bool with_geometry) const {
    std::vector<LiveBodyPose> out = impl_->described;
    for (std::size_t i = 0; i < out.size(); ++i) {
        if (with_geometry && out[i].shape == "hull") {
            out[i].cells_local_m.reserve(impl_->nodes_of[i].size());
            for (const std::uint32_t node : impl_->nodes_of[i])
                out[i].cells_local_m.push_back(impl_->cell_offset_m[node]);
        }
        if (!impl_->world->contains(impl_->body_of[i])) continue;
        const RigidSnapshot snap = impl_->world->snapshot(impl_->body_of[i]);
        out[i].position_m = snap.center_of_mass_world_m;
        out[i].orientation_wxyz[0] = snap.orientation_world.w;
        out[i].orientation_wxyz[1] = snap.orientation_world.x;
        out[i].orientation_wxyz[2] = snap.orientation_world.y;
        out[i].orientation_wxyz[3] = snap.orientation_world.z;
        out[i].velocity_m_s = snap.linear_velocity_m_s;
        out[i].held = i == impl_->holding;
    }
    return out;
}

namespace {
// A quaternion's conjugate, which is its inverse for the unit quaternions a
// rigid body carries. Quat has rotate() but no inverse, and taking a world
// vector into a body's own frame needs one on every call below.
[[nodiscard]] Quat conjugateOf(const Quat &q) { return Quat{q.w, -q.x, -q.y, -q.z}; }
} // namespace

unsigned LiveWorld::hinge(const std::string &a, const std::string &b,
                          const Vec3 &point_world_m, const Vec3 &axis_world,
                          double lower_deg, double upper_deg,
                          double friction_torque_n_m) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return 0;

    constexpr double kPi = 3.14159265358979323846;
    const double lower = std::max(-kPi, std::min(0.0, lower_deg * kPi / 180.0));
    const double upper = std::min(kPi, std::max(0.0, upper_deg * kPi / 180.0));

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Hinge;
    joint.lower = lower;
    joint.upper = upper;
    joint.friction = std::max(0.0, friction_torque_n_m);

    // Write the pin down in each body's own frame. Where they are standing at
    // this moment is the only thing that ties the two together, and after this
    // it never matters again.
    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_world_m - one.center_of_mass_world_m);
    joint.point_local_b = conjugateOf(two.orientation_world)
                              .rotate(point_world_m - two.center_of_mass_world_m);
    joint.axis_local_a = conjugateOf(one.orientation_world).rotate((1.0 / reach) * axis_world);

    try {
        JoltWorld::HingeDescription pin{};
        pin.a = impl_->body_of[first->second];
        pin.b = impl_->body_of[second->second];
        pin.point_world_m = point_world_m;
        pin.axis_world = (1.0 / reach) * axis_world;
        pin.lower_rad = lower;
        pin.upper_rad = upper;
        pin.friction_torque_n_m = joint.friction;
        joint.rigid = impl_->world->addHinge(pin);
    } catch (const std::exception &) {
        return 0;
    }
    // Two things hung on a pin are touching by definition -- that is what being
    // hinged IS -- and a body that has been asleep does not notice a push.
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

unsigned LiveWorld::slide(const std::string &a, const std::string &b,
                          const Vec3 &point_world_m, const Vec3 &axis_world,
                          double lower_m, double upper_m, double friction_n) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return 0;
    if (!(lower_m <= 0.0) || !(upper_m >= 0.0)) return 0;

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Slider;
    joint.lower = lower_m;
    joint.upper = upper_m;
    joint.friction = std::max(0.0, friction_n);

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_world_m - one.center_of_mass_world_m);
    joint.point_local_b = conjugateOf(two.orientation_world)
                              .rotate(point_world_m - two.center_of_mass_world_m);
    joint.axis_local_a = conjugateOf(one.orientation_world).rotate((1.0 / reach) * axis_world);

    try {
        JoltWorld::SliderDescription groove{};
        groove.a = impl_->body_of[first->second];
        groove.b = impl_->body_of[second->second];
        groove.point_world_m = point_world_m;
        groove.axis_world = (1.0 / reach) * axis_world;
        groove.lower_m = lower_m;
        groove.upper_m = upper_m;
        groove.friction_n = joint.friction;
        joint.rigid = impl_->world->addSlider(groove);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

unsigned LiveWorld::tie(const std::string &a, const std::string &b,
                        const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                        double length_m, double breaking_tension_n) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;

    // "As they stand" is the ordinary case: a rope laid out and then tied does
    // not want to be told its own length, and getting it wrong by a millimetre
    // either way is either a rope under tension at rest or one that sags.
    const double apart = length(point_b_world_m - point_a_world_m);
    const double ties_at = length_m > 0.0 ? length_m : std::max(apart, 1e-4);

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Link;
    joint.lower = 0.0;
    joint.upper = ties_at;
    joint.friction = 0.0;
    joint.breaks_at_n = std::max(0.0, breaking_tension_n);

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_a_world_m - one.center_of_mass_world_m);
    joint.point_local_b_tie = conjugateOf(two.orientation_world)
                                  .rotate(point_b_world_m - two.center_of_mass_world_m);
    // A link has no axis. The end that follows its material still needs the
    // other body's local point, and point_local_b is what rehangJoints reads.
    joint.point_local_b = joint.point_local_b_tie;
    joint.axis_local_a = Vec3{0.0, 1.0, 0.0};

    try {
        JoltWorld::LinkDescription rope{};
        rope.a = impl_->body_of[first->second];
        rope.b = impl_->body_of[second->second];
        rope.point_a_world_m = point_a_world_m;
        rope.point_b_world_m = point_b_world_m;
        rope.length_m = ties_at;
        rope.breaking_tension_n = joint.breaks_at_n;
        joint.rigid = impl_->world->addLink(rope);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

unsigned LiveWorld::spring(const std::string &a, const std::string &b,
                           const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                           double rest_m, double stiffness_n_m, double damping_n_s_m) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    if (!(stiffness_n_m > 0.0) || !(damping_n_s_m >= 0.0) || !(rest_m >= 0.0)) return 0;

    const double apart = length(point_b_world_m - point_a_world_m);

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Elastic;
    joint.rest_m = rest_m > 0.0 ? rest_m : std::max(apart, 1e-4);
    joint.stiffness_n_m = stiffness_n_m;
    joint.damping_n_s_m = damping_n_s_m;
    joint.lower = joint.rest_m;
    joint.upper = joint.rest_m;

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_a_world_m - one.center_of_mass_world_m);
    joint.point_local_b_tie = conjugateOf(two.orientation_world)
                                  .rotate(point_b_world_m - two.center_of_mass_world_m);
    joint.point_local_b = joint.point_local_b_tie;
    joint.axis_local_a = Vec3{0.0, 1.0, 0.0};

    try {
        JoltWorld::ElasticDescription limb{};
        limb.a = impl_->body_of[first->second];
        limb.b = impl_->body_of[second->second];
        limb.point_a_world_m = point_a_world_m;
        limb.point_b_world_m = point_b_world_m;
        limb.rest_m = joint.rest_m;
        limb.stiffness_n_m = stiffness_n_m;
        limb.damping_n_s_m = damping_n_s_m;
        joint.rigid = impl_->world->addElastic(limb);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

unsigned LiveWorld::fix(const std::string &a, const std::string &b,
                        const Vec3 &point_world_m, const Vec3 &axis_world,
                        double holds_tension_n, double holds_shear_n) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return 0;
    if (!(holds_tension_n >= 0.0) || !(holds_shear_n >= 0.0)) return 0;

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Fixing;
    joint.holds_tension_n = holds_tension_n;
    joint.holds_shear_n = holds_shear_n;

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_world_m - one.center_of_mass_world_m);
    joint.point_local_b = conjugateOf(two.orientation_world)
                              .rotate(point_world_m - two.center_of_mass_world_m);
    joint.point_local_b_tie = joint.point_local_b;
    joint.axis_local_a = conjugateOf(one.orientation_world).rotate((1.0 / reach) * axis_world);

    try {
        JoltWorld::FixingDescription peg{};
        peg.a = impl_->body_of[first->second];
        peg.b = impl_->body_of[second->second];
        peg.point_world_m = point_world_m;
        peg.axis_world = (1.0 / reach) * axis_world;
        peg.holds_tension_n = holds_tension_n;
        peg.holds_shear_n = holds_shear_n;
        joint.rigid = impl_->world->addFixing(peg);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

unsigned LiveWorld::reeve(const std::string &a, const std::string &b,
                          const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                          const Vec3 &over_a_world_m, const Vec3 &over_b_world_m,
                          double ratio, double length_m) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    if (!(ratio > 0.0) || !(length_m >= 0.0)) return 0;

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Pulley;
    joint.over_a = over_a_world_m;
    joint.over_b = over_b_world_m;
    joint.ratio = ratio;
    joint.lower = 0.0;
    joint.upper = length_m > 0.0
                      ? length_m
                      : length(point_a_world_m - over_a_world_m) +
                            ratio * length(point_b_world_m - over_b_world_m);
    joint.friction = 0.0;

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_a_world_m - one.center_of_mass_world_m);
    joint.point_local_b_tie = conjugateOf(two.orientation_world)
                                  .rotate(point_b_world_m - two.center_of_mass_world_m);
    joint.point_local_b = joint.point_local_b_tie;
    joint.axis_local_a = Vec3{0.0, 1.0, 0.0};

    try {
        JoltWorld::PulleyDescription rove{};
        rove.a = impl_->body_of[first->second];
        rove.b = impl_->body_of[second->second];
        rove.point_a_world_m = point_a_world_m;
        rove.point_b_world_m = point_b_world_m;
        rove.over_a_world_m = over_a_world_m;
        rove.over_b_world_m = over_b_world_m;
        rove.ratio = ratio;
        rove.length_m = length_m;
        joint.rigid = impl_->world->addPulley(rove);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

std::vector<LiveJoint> LiveWorld::joints() const {
    std::vector<LiveJoint> out;
    out.reserve(impl_->joints.size());
    for (const Impl::SceneJoint &joint : impl_->joints) {
        LiveJoint said{};
        said.id = joint.id;
        said.kind = joint.kind == JoltWorld::JointKind::Slider   ? "slider"
                    : joint.kind == JoltWorld::JointKind::Link   ? "link"
                    : joint.kind == JoltWorld::JointKind::Pulley ? "pulley"
                    : joint.kind == JoltWorld::JointKind::Fixing ? "fixing"
                    : joint.kind == JoltWorld::JointKind::Elastic ? "elastic"
                                                                 : "hinge";
        said.rest_m = joint.rest_m;
        said.stiffness_n_m = joint.stiffness_n_m;
        said.damping_n_s_m = joint.damping_n_s_m;
        said.holds_tension_n = joint.holds_tension_n;
        said.holds_shear_n = joint.holds_shear_n;
        said.breaks_at_n = joint.breaks_at_n;
        said.ratio = joint.ratio;
        said.over_a_m = joint.over_a;
        said.over_b_m = joint.over_b;
        said.a = joint.a;
        said.b = joint.b;
        said.lower = joint.lower;
        said.upper = joint.upper;
        said.friction = joint.friction;
        said.attached = joint.attached && joint.rigid != 0;
        if (joint.rigid != 0 && impl_->world->hasJoint(joint.rigid)) {
            const JoltWorld::JointReport now = impl_->world->jointState(joint.rigid);
            said.at = now.at;
            said.lower = now.lower;
            said.upper = now.upper;
            said.friction = now.friction;
            said.tension_n = impl_->world->jointTension(joint.rigid);
            if (joint.kind == JoltWorld::JointKind::Elastic) {
                // How far apart the two ATTACHMENT POINTS are, worked out from
                // where the bodies now stand. Not their centres: a bow limb
                // pulls on the end of the limb, and using the centres would be
                // a different machine reporting the same name.
                const auto at_a = impl_->index_of.find(joint.a);
                const auto at_b = impl_->index_of.find(joint.b);
                if (at_a != impl_->index_of.end() && at_b != impl_->index_of.end()) {
                    const RigidSnapshot one =
                        impl_->world->snapshot(impl_->body_of[at_a->second]);
                    const RigidSnapshot two =
                        impl_->world->snapshot(impl_->body_of[at_b->second]);
                    const Vec3 here = one.center_of_mass_world_m +
                                      one.orientation_world.rotate(joint.point_local_a);
                    const Vec3 there = two.center_of_mass_world_m +
                                       two.orientation_world.rotate(joint.point_local_b_tie);
                    said.at = length(there - here);
                }
                const double stretched = said.at - joint.rest_m;
                said.force_n = joint.stiffness_n_m * stretched;
                said.stored_j = 0.5 * joint.stiffness_n_m * stretched * stretched;
                said.tension_n = std::abs(said.force_n);
            }
            if (joint.kind == JoltWorld::JointKind::Fixing) {
                const auto found = impl_->index_of.find(joint.a);
                const Vec3 along =
                    found != impl_->index_of.end()
                        ? impl_->world->snapshot(impl_->body_of[found->second])
                              .orientation_world.rotate(joint.axis_local_a)
                        : joint.axis_local_a;
                const JoltWorld::JointLoad carrying =
                    impl_->world->jointLoad(joint.rigid, along);
                said.tension_n_now = carrying.tension_n;
                said.shear_n_now = carrying.shear_n;
                // One number for a host that only wants "how hard is this
                // working": whichever of the two is nearer its own limit.
                said.tension_n = std::max(carrying.tension_n, carrying.shear_n);
            }
        }
        // Where the pin has got to, worked out from the body it is in rather
        // than remembered, so a gate that has been carried across the room
        // reports its hinge where the gate is.
        const auto found = impl_->index_of.find(joint.a);
        if (found != impl_->index_of.end()) {
            const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[found->second]);
            said.point_world_m = at.center_of_mass_world_m +
                                 at.orientation_world.rotate(joint.point_local_a);
            said.axis_world = at.orientation_world.rotate(joint.axis_local_a);
        }
        out.push_back(std::move(said));
    }
    return out;
}

void LiveWorld::setJointFriction(unsigned joint, double friction_torque_n_m) {
    for (Impl::SceneJoint &held : impl_->joints) {
        if (held.id != joint) continue;
        held.friction = std::max(0.0, friction_torque_n_m);
        if (held.rigid != 0 && impl_->world->hasJoint(held.rigid))
            impl_->world->setJointFriction(held.rigid, held.friction);
        return;
    }
}

void LiveWorld::unhinge(unsigned joint) {
    for (std::size_t i = 0; i < impl_->joints.size(); ++i) {
        if (impl_->joints[i].id != joint) continue;
        if (impl_->joints[i].rigid != 0) impl_->world->removeJoint(impl_->joints[i].rigid);
        // What was hanging on it is about to fall, and a body asleep on its pin
        // would hang in the air until something else woke it.
        for (const std::string &side : {impl_->joints[i].a, impl_->joints[i].b}) {
            const auto found = impl_->index_of.find(side);
            if (found != impl_->index_of.end()) impl_->world->wake(impl_->body_of[found->second]);
        }
        impl_->joints.erase(impl_->joints.begin() + static_cast<std::ptrdiff_t>(i));
        return;
    }
}

// Which body has this point in its matter.
//
// Asked of the cells rather than of the bounding box, because the pieces this
// is chasing are hulls and a hull's box is mostly not the hull. Restricted to
// bodies descended from the name the pin used to be in: a pin that loses its
// wood should come out, not grab whatever happens to be lying against it.
std::size_t LiveWorld::bodyHolding(const Vec3 &point_world_m,
                                   const std::string &was_called) const {
    const double near_enough = impl_->request.cell_size_m;
    std::size_t best = static_cast<std::size_t>(-1);
    double closest = near_enough;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const std::string &name = impl_->described[i].name;
        const bool descended = name == was_called ||
                               name.rfind(was_called + " piece ", 0) == 0;
        if (!descended) continue;
        const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[i]);
        const Quat inverse = conjugateOf(at.orientation_world);
        const Vec3 local = inverse.rotate(point_world_m - at.center_of_mass_world_m);
        for (const std::uint32_t node : impl_->nodes_of[i]) {
            if (node >= impl_->cell_offset_m.size()) continue;
            const double gap = length(impl_->cell_offset_m[node] - local);
            if (gap < closest) { closest = gap; best = i; }
        }
    }
    return best;
}

// Put the pins back after the body table has been rearranged.
//
// Every body in an island is destroyed and rebuilt when anything in it breaks,
// so every engine-level constraint touching it is gone -- including the ones on
// bodies that came through the collision untouched. This is what puts them
// back, and it is also where a pin decides what to do when its wood is no
// longer there: it follows the piece it is inside, and if there is no such
// piece, it comes out and what hung on it falls.
void LiveWorld::rehangJoints() {
    for (Impl::SceneJoint &joint : impl_->joints) {
        if (!joint.attached) continue;
        if (joint.rigid != 0 && impl_->world->hasJoint(joint.rigid)) continue;
        joint.rigid = 0;

        // Find each end again. By name if the name is still there -- which it is
        // whenever a body came through whole -- and otherwise by following the
        // pin into whichever piece of the old body now surrounds it.
        std::size_t side[2] = {static_cast<std::size_t>(-1), static_cast<std::size_t>(-1)};
        std::string *names[2] = {&joint.a, &joint.b};
        Vec3 *locals[2] = {&joint.point_local_a, &joint.point_local_b};
        // The pin's last known place in the world, taken from whichever end is
        // still standing. Both ends cannot have moved without one of them being
        // findable, because a joint with neither end left is simply gone.
        bool have_point = false;
        Vec3 point{};
        for (int end = 0; end < 2 && !have_point; ++end) {
            const auto found = impl_->index_of.find(*names[end]);
            if (found == impl_->index_of.end()) continue;
            const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[found->second]);
            point = at.center_of_mass_world_m + at.orientation_world.rotate(*locals[end]);
            have_point = true;
        }
        for (int end = 0; end < 2; ++end) {
            const auto found = impl_->index_of.find(*names[end]);
            if (found != impl_->index_of.end()) { side[end] = found->second; continue; }
            if (!have_point) break;
            const std::size_t heir = bodyHolding(point, *names[end]);
            if (heir == static_cast<std::size_t>(-1)) break;
            // The pin is in this piece now. Re-write where it sits in the new
            // body's frame -- the piece has its own centre of mass, nowhere near
            // the one the parent had -- and rename the end to match, so the next
            // break follows the piece's own pieces.
            const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[heir]);
            *locals[end] = conjugateOf(at.orientation_world).rotate(point - at.center_of_mass_world_m);
            *names[end] = impl_->described[heir].name;
            side[end] = heir;
            impl_->delays.push_back({impl_->time_s, *names[end], "rehung", 0.0, 0.0});
        }
        if (side[0] == static_cast<std::size_t>(-1) || side[1] == static_cast<std::size_t>(-1) ||
            side[0] == side[1] || !have_point) {
            // Nothing left to hang it on. The gate is off its hinges, which is
            // the honest outcome -- and it is reported rather than dropped, so a
            // host that drew a pin knows to stop drawing it.
            joint.attached = false;
            continue;
        }
        try {
            const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[side[0]]);
            const Vec3 along = one.orientation_world.rotate(joint.axis_local_a);
            // The limits were measured from where the thing was standing when
            // the joint was made, and it is not standing there now. Jolt
            // measures a fresh constraint from where it finds the bodies, so
            // what can be asked for is the travel that is LEFT: a door that has
            // swung 30 of its 90 degrees has 60 to go and 30 to come back, and
            // a portcullis hauled 1 m of its 2 has 1 m either way.
            const double got = std::max(joint.lower, std::min(joint.upper,
                                                              joint.at_when_hung));
            if (joint.kind == JoltWorld::JointKind::Pulley) {
                JoltWorld::PulleyDescription rove{};
                rove.a = impl_->body_of[side[0]];
                rove.b = impl_->body_of[side[1]];
                rove.point_a_world_m = point;
                const RigidSnapshot far = impl_->world->snapshot(impl_->body_of[side[1]]);
                rove.point_b_world_m = far.center_of_mass_world_m +
                                       far.orientation_world.rotate(joint.point_local_b_tie);
                // The sheaves do not move with anything. They are points in the
                // world, and re-making the constraint must not quietly relocate
                // them onto whichever piece of beam survived.
                rove.over_a_world_m = joint.over_a;
                rove.over_b_world_m = joint.over_b;
                rove.ratio = joint.ratio;
                rove.length_m = joint.upper;
                joint.rigid = impl_->world->addPulley(rove);
            } else if (joint.kind == JoltWorld::JointKind::Link) {
                JoltWorld::LinkDescription rope{};
                rope.a = impl_->body_of[side[0]];
                rope.b = impl_->body_of[side[1]];
                rope.point_a_world_m = point;
                // The far end is tied somewhere else on the other body, so it
                // has to be worked out from that body rather than shared. This
                // is the one place a link differs from a pin: two points, not
                // one.
                const RigidSnapshot other = impl_->world->snapshot(impl_->body_of[side[1]]);
                rope.point_b_world_m = other.center_of_mass_world_m +
                                       other.orientation_world.rotate(joint.point_local_b_tie);
                rope.length_m = joint.upper;
                rope.breaking_tension_n = joint.breaks_at_n;
                joint.rigid = impl_->world->addLink(rope);
            } else if (joint.kind == JoltWorld::JointKind::Elastic) {
                JoltWorld::ElasticDescription limb{};
                limb.a = impl_->body_of[side[0]];
                limb.b = impl_->body_of[side[1]];
                limb.point_a_world_m = point;
                const RigidSnapshot far = impl_->world->snapshot(impl_->body_of[side[1]]);
                limb.point_b_world_m = far.center_of_mass_world_m +
                                       far.orientation_world.rotate(joint.point_local_b_tie);
                limb.rest_m = joint.rest_m;
                limb.stiffness_n_m = joint.stiffness_n_m;
                limb.damping_n_s_m = joint.damping_n_s_m;
                joint.rigid = impl_->world->addElastic(limb);
            } else if (joint.kind == JoltWorld::JointKind::Fixing) {
                JoltWorld::FixingDescription peg{};
                peg.a = impl_->body_of[side[0]];
                peg.b = impl_->body_of[side[1]];
                peg.point_world_m = point;
                peg.axis_world = along;
                peg.holds_tension_n = joint.holds_tension_n;
                peg.holds_shear_n = joint.holds_shear_n;
                joint.rigid = impl_->world->addFixing(peg);
            } else if (joint.kind == JoltWorld::JointKind::Slider) {
                JoltWorld::SliderDescription groove{};
                groove.a = impl_->body_of[side[0]];
                groove.b = impl_->body_of[side[1]];
                groove.point_world_m = point;
                groove.axis_world = along;
                groove.lower_m = joint.lower - got;
                groove.upper_m = joint.upper - got;
                groove.friction_n = joint.friction;
                joint.rigid = impl_->world->addSlider(groove);
            } else {
                JoltWorld::HingeDescription pin{};
                pin.a = impl_->body_of[side[0]];
                pin.b = impl_->body_of[side[1]];
                pin.point_world_m = point;
                pin.axis_world = along;
                pin.lower_rad = joint.lower - got;
                pin.upper_rad = joint.upper - got;
                pin.friction_torque_n_m = joint.friction;
                joint.rigid = impl_->world->addHinge(pin);
            }
        } catch (const std::exception &) {
            joint.attached = false;
        }
    }
}

bool LiveWorld::grab(const std::string &name) {
    const auto found = impl_->index_of.find(name);
    if (found == impl_->index_of.end()) return false;
    // Anchored scenery is the world, not a prop. Letting it be dragged would
    // move the floor out from under everything standing on it.
    if (impl_->described[found->second].anchored) return false;
    if (impl_->holding != static_cast<std::size_t>(-1)) release();
    impl_->holding = found->second;
    // The world it is being taken out of has probably been still for a while,
    // and a body that has been still is not being simulated. Everything below
    // -- carrying it, and gravity when it is let go -- needs it back in the
    // step, and writing a pose does not do that.
    impl_->world->wake(impl_->body_of[found->second]);
    const RigidSnapshot now = impl_->world->snapshot(impl_->body_of[impl_->holding]);
    impl_->held_at = now.center_of_mass_world_m;
    impl_->held_facing = now.orientation_world;
    return true;
}

void LiveWorld::moveHeld(const Vec3 &to_world_m) {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    impl_->held_at = to_world_m;
    // And put it there now, rather than waiting for the next step: a host that
    // moves the hand and then reads the world back expects the thing to have
    // moved. Which of the two things below that means is carryOrHaul's
    // business, and the whole reason it is a function rather than a lambda
    // inside step() -- the hand writes the world in two places, and the first
    // version of hauling only fixed one of them. A portcullis with 800 mm of
    // travel went 1.57 m up, because this line here was still a teleport.
    carryOrHaul(impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 240.0);
}

// Where the hand puts what it is holding.
//
// Two different things, and which one depends on whether the thing is attached
// to anything.
//
// A LOOSE body is carried: put exactly where the hand is, every step, at zero
// velocity. That is what makes dragging feel like holding rather than pushing,
// and it is right, because nothing else has an opinion about where it should be.
//
// A body on a JOINT is hauled instead. Carrying it would override everything it
// is attached to -- writing a pose is the last word, and a portcullis with
// 800 mm of travel dragged two metres went two metres, with its grooves
// reporting `upper = 0.8` the whole way and working perfectly. So the hand
// pulls, by velocity, and the mechanism decides what that does: a grate goes up
// its grooves and no further, a gate goes round its pin, and nothing comes off
// its mountings because somebody dragged hard.
//
// For a slide the pull is resolved along the groove and clamped to the travel
// that is actually left, rather than left for the limit to fight. A hard
// constraint against a velocity written in from outside on every step is a tug
// of war, and position correction does not win it -- that is where the 1.57 m
// came from even after the pull became a velocity.
void LiveWorld::setHandStrength(double newtons) {
    impl_->hand_strength_n = std::max(0.0, newtons);
}
double LiveWorld::handStrength() const { return impl_->hand_strength_n; }

void LiveWorld::carryOrHaul(double dt_s) {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    if (!(dt_s > 0.0)) dt_s = 1.0 / 240.0;
    const MatterBodyId id = impl_->body_of[impl_->holding];
    RigidSnapshot state = impl_->world->snapshot(id);

    const std::string carrying = impl_->described[impl_->holding].name;
    const Impl::SceneJoint *on = nullptr;
    for (const Impl::SceneJoint &joint : impl_->joints) {
        if (!joint.attached || joint.rigid == 0) continue;
        if (joint.a != carrying && joint.b != carrying) continue;
        // A SLIDER wins over anything else on the same body, because a slider
        // is the joint that says where the thing may go at all -- and the hand
        // can then ask for exactly the travel it has left, which is the one
        // case that can be answered exactly rather than pulled towards.
        //
        // The courtyard's portcullis is on a slider AND on the winch's rope,
        // and taking whichever came last in the list meant the hand treated it
        // as a rope-and-pulley problem: a person heaving with 800 N against
        // 14.2 kN of iron, which is honest arithmetic and is not what hauling a
        // grate up its own grooves is.
        if (on == nullptr || joint.kind == JoltWorld::JointKind::Slider) on = &joint;
        if (joint.kind == JoltWorld::JointKind::Slider) break;
    }

    if (on != nullptr) {
        constexpr double kFastestHaul = 6.0;   // a hard haul, not a teleport
        const Vec3 gap = impl_->held_at - state.center_of_mass_world_m;
        Vec3 pull{};
        if (on->kind == JoltWorld::JointKind::Slider) {
            const auto found = impl_->index_of.find(on->a);
            const RigidSnapshot anchor =
                found != impl_->index_of.end()
                    ? impl_->world->snapshot(impl_->body_of[found->second])
                    : RigidSnapshot{};
            const Vec3 along = anchor.orientation_world.rotate(on->axis_local_a);
            const double got = impl_->world->hasJoint(on->rigid)
                                   ? impl_->world->jointState(on->rigid).at
                                   : 0.0;
            double wanted = dot(gap, along);
            wanted = std::max(on->lower - got, std::min(on->upper - got, wanted));
            const double speed =
                std::max(-kFastestHaul, std::min(kFastestHaul, wanted / dt_s));
            pull = speed * along;
            state.linear_velocity_m_s = pull;
            impl_->world->applyRigidState(id, state);
            impl_->world->wake(id);
            return;
        }

        // Everything else is PULLED, with a bounded force, and that is not the
        // same as being moved and does not reduce to it.
        //
        // Setting a velocity towards the hand looks like it should work and
        // does not, because a hard constraint cancels it inside the same step:
        // the hand gets one step of authority, never accumulates any, and so
        // can never win against anything stiff. Measured on a bow -- the hand
        // asked for a 300 mm draw, the string went taut, and the nocking point
        // moved 1.6 mm in fifty steps while the limbs stored a ten-thousandth
        // of a joule. From the outside that is a bow that cannot be drawn.
        //
        // A force accumulates. An archer pulls with however many newtons they
        // have and the bow yields until the two balance, which is what a draw
        // IS -- and the same bound is why a hand can heave a gate open and
        // cannot tear it off its hinges.
        const double far = length(gap);
        if (far > 1e-9) {
            // Full strength towards where the hand wants it, and that is the
            // whole of the rule.
            //
            // NOT "the force needed to close the gap this step, given this
            // body's mass", which was the first version and is wrong for the
            // reason a bowstring makes obvious: the thing in your fingers is a
            // nocking point weighing 87 grams, and the force required to move
            // IT is nothing like the force required to move what it is attached
            // to. Measured, that formula asked for 1,512 N however strong the
            // hand was declared to be, and a 16 kN/m bow would not draw with a
            // 6 kN hand.
            //
            // A hand does not know what it is pulling on. It pulls with what it
            // has, and the assembly yields or it does not.
            // Pull towards the target, brake against the speed, and clamp the
            // whole thing to what the hand has got. A hand that is not damped
            // does not hold anything: it slams its target, overshoots, hauls
            // back, and whatever it is attached to rings. Measured on a bow, an
            // undamped 6 kN hand read a different stored energy every time it
            // was asked, because the draw never settled.
            //
            // Full strength at 50 mm of error, and full braking at 8 m/s. Both
            // are a hand's own scale rather than the held body's, which is the
            // point: what the hand can do should not depend on the mass of the
            // thing in its fingers.
            //
            // 8 m/s and not 2. At 2 the braking term reached full strength
            // whenever the held thing was jostled at walking pace, cancelling
            // the pull outright -- a bow that stored 170 J with a plain capped
            // pull stored 7 with that hand, and drawing it further stored less.
            // A hand that stops everything is not a steadier hand.
            const RigidSnapshot now = impl_->world->snapshot(id);
            const double strength = impl_->hand_strength_n;
            Vec3 force = (strength / 0.05) * gap -
                         (strength / 8.0) * now.linear_velocity_m_s;
            const double push = length(force);
            if (push > strength) force = (strength / push) * force;
            impl_->world->pushBody(id, force);
        }
        impl_->world->wake(id);
        return;
    }

    state.center_of_mass_world_m = impl_->held_at;
    state.orientation_world = impl_->held_facing;
    // A carried object does not accumulate speed from being carried; letting go
    // is what hands it back to gravity.
    state.linear_velocity_m_s = {};
    state.angular_velocity_rad_s = {};
    impl_->world->applyRigidState(id, state);
    // Held still at zero velocity is exactly what "has come to rest" looks like,
    // so a carried object puts itself to sleep within half a second of being
    // picked up unless this keeps saying otherwise. Asleep, it stops pushing
    // what it is carried into, and it does not fall when it is let go.
    impl_->world->wake(id);
}

void LiveWorld::release() {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    // The hold was only the pose being re-asserted, so there is nothing to undo
    // -- but the object has spent the whole hold perfectly still, which is the
    // one thing a rigid solver reads as "stop simulating this". Letting go has
    // to put it back in the step, or it hangs in the air where it was released.
    // Watched: let go a metre up, still a metre up two seconds later.
    impl_->world->wake(impl_->body_of[impl_->holding]);
    impl_->holding = static_cast<std::size_t>(-1);
}

void LiveWorld::forgetImpacts() { impl_->reported.clear(); }

std::vector<LiveImpact> LiveWorld::impacts(double quiet_speed_m_s) const {
    std::vector<LiveImpact> out;
    for (const LiveImpact &impact : impl_->reported)
        if (impact.closing_speed_m_s >= quiet_speed_m_s) out.push_back(impact);
    std::sort(out.begin(), out.end(), [](const LiveImpact &lhs, const LiveImpact &rhs) {
        return lhs.closing_speed_m_s > rhs.closing_speed_m_s;
    });
    return out;
}

// Everything waiting on an answer stays where it is. Rebuilt rather than
// patched, because there are five places that change what is waiting and a
// pinned body that nobody unpins never moves again.
// What everything is carrying, and whether it can hold it.
//
// Statics, not dynamics. Nothing here looks at a contact, because a thing at
// rest reports none: a plank bridging two piers with an iron block on it comes
// back with an empty contact ledger once it has settled, which is correct -- a
// ledger of impacts has no impacts to report -- and is why a shelf could be
// loaded until it should snap without anything ever asking.
//
// So it is asked from geometry. A sits on B when A's underside is within a
// whisker of B's top and they overlap from above. That gives what is stacked on
// what, and the weight follows from the cells and the density. O(bodies squared)
// on axis-aligned boxes, which is nothing for a room -- and is why it runs at a
// stride rather than every step.
void LiveWorld::surveyLoads() {
    impl_->overloaded.clear();
    impl_->bearing_on.clear();
    const std::size_t count = impl_->described.size();
    if (count == 0) return;

    const auto standing = poses();
    std::vector<Vec3> middle(count), half(count);
    std::vector<double> weight(count, 0.0);
    for (std::size_t i = 0; i < count && i < standing.size(); ++i) {
        middle[i] = standing[i].position_m;
        half[i] = 0.5 * standing[i].dimensions_m;
        const double cell = impl_->request.cell_size_m;
        const double volume = static_cast<double>(impl_->nodes_of[i].size()) *
                              cell * cell * cell;
        const double density = i < impl_->density_of.size() ? impl_->density_of[i] : 0.0;
        weight[i] = volume * density * 9.81;
    }

    // Who is sitting on whom. A whisker of slack because a body at rest sinks
    // into its support by the solver's penetration allowance -- exactly zero
    // would find nothing at all.
    constexpr double kWhisker = 0.02;
    const auto overlapsFromAbove = [&](std::size_t upper, std::size_t lower) {
        return std::abs(middle[upper].x - middle[lower].x) <
                   half[upper].x + half[lower].x &&
               std::abs(middle[upper].z - middle[lower].z) <
                   half[upper].z + half[lower].z;
    };
    const auto restsOn = [&](std::size_t upper, std::size_t lower) {
        if (upper == lower) return false;
        const double underside = middle[upper].y - half[upper].y;
        const double top = middle[lower].y + half[lower].y;
        return underside > top - kWhisker && underside < top + kWhisker &&
               overlapsFromAbove(upper, lower);
    };

    // What each body carries: everything stacked above it, however deep. Walked
    // upwards from each body rather than summed downwards, because a stack can
    // fork and the same crate must not be counted twice on one shelf.
    std::vector<double> carrying(count, 0.0);
    for (std::size_t base = 0; base < count; ++base) {
        if (impl_->described[base].anchored) continue;
        std::vector<bool> counted(count, false);
        std::vector<std::size_t> above;
        for (std::size_t i = 0; i < count; ++i)
            if (restsOn(i, base)) { above.push_back(i); counted[i] = true; }
        for (std::size_t at = 0; at < above.size(); ++at) {
            const std::size_t here = above[at];
            carrying[base] += weight[here];
            for (std::size_t i = 0; i < count; ++i)
                if (!counted[i] && restsOn(i, here)) { above.push_back(i); counted[i] = true; }
        }
    }

    for (std::size_t i = 0; i < count; ++i) {
        if (impl_->described[i].anchored) continue;
        if (i == impl_->holding) continue;             // in a hand, not on anything
        if (!(carrying[i] > 0.0)) continue;            // nothing on it: nothing to do

        // What is holding it up, and how far apart. A beam supported all along
        // its length has no span and cannot be bent -- which is the honest
        // reason a plate lying flat on the floor will not break however much is
        // piled on it.
        double leftmost = 1e30, rightmost = -1e30;
        bool held = false;
        for (std::size_t under = 0; under < count; ++under) {
            if (!restsOn(i, under)) continue;
            held = true;
            leftmost = std::min(leftmost, middle[under].x - half[under].x);
            rightmost = std::max(rightmost, middle[under].x + half[under].x);
        }
        if (!held) continue;                            // falling, not carrying
        // The clear span: from the inner edge of one support to the inner edge
        // of the other, capped at the beam itself.
        double span = std::min(rightmost - leftmost, 2.0 * half[i].x);
        // Supports that touch along the whole length leave no clear span.
        double supported_length = 0.0;
        for (std::size_t under = 0; under < count; ++under) {
            if (!restsOn(i, under)) continue;
            supported_length += std::min(2.0 * half[under].x, 2.0 * half[i].x);
        }
        span = std::max(0.0, span - supported_length);
        if (!(span > 1e-3)) continue;                   // held everywhere: no bending

        // Section: breadth across the span, depth in the direction it bends.
        const double breadth = 2.0 * half[i].z;
        const double depth = 2.0 * half[i].y;
        if (!(breadth > 1e-6) || !(depth > 1e-6)) continue;

        // Simply supported, point load in the middle, plus its own weight as a
        // uniform load. The worst case for both, on purpose: this decides
        // whether the lattice is worth running, and it is meant to err towards
        // asking rather than towards silence.
        const double own_per_m = weight[i] / std::max(span, 1e-6);
        const double stress = 3.0 * carrying[i] * span / (2.0 * breadth * depth * depth) +
                              3.0 * own_per_m * span * span / (4.0 * breadth * depth * depth);
        const double strength = i < impl_->tensile_of.size() ? impl_->tensile_of[i] : 0.0;
        if (!(strength > 0.0)) continue;
        if (!(stress > strength)) continue;

        impl_->overloaded.push_back(LiveOverload{impl_->described[i].name,
                                                 carrying[i], span, stress, strength});
        // And remember the heaviest thing sitting directly on it, so the
        // fracture has something to press with. Directly on it rather than the
        // heaviest in the whole stack: the lattice needs a body that is really
        // touching, and what is above THAT presses on it in turn.
        std::size_t heaviest = static_cast<std::size_t>(-1);
        double most = 0.0;
        for (std::size_t on_top = 0; on_top < count; ++on_top) {
            if (!restsOn(on_top, i)) continue;
            if (weight[on_top] <= most) continue;
            most = weight[on_top];
            heaviest = on_top;
        }
        if (heaviest != static_cast<std::size_t>(-1)) impl_->bearing_on[i] = heaviest;
    }
}

std::vector<LiveOverload> LiveWorld::overloaded() const { return impl_->overloaded; }

void LiveWorld::repin() {
    impl_->held_for_fracture.clear();
    const auto pin = [&](const Pending &job) {
        for (const std::size_t body : job.island_bodies)
            if (body < impl_->described.size() && !impl_->described[body].anchored)
                impl_->held_for_fracture.push_back(body);
    };
    if (impl_->pending && !impl_->pending->settled) pin(*impl_->pending);
    for (const auto &job : impl_->queued) pin(*job);
}

// Start the run for a collision that has not happened yet.
//
// The run costs about as long as a two-metre fall takes, and it used to start
// when the two things touched -- so you dropped something, it landed, and then
// it sat there for most of a second before coming apart. Measured on an iron
// ball onto a 20 mm pane: 856 ms between the contact and the pieces, with the
// world running at 99% of real time throughout. The clock was never the
// problem. The EVENT was late.
//
// So it starts on the way down instead, from where the two things are going to
// be. Nothing is pinned and nothing is told: the world carries on exactly as it
// would have, and if the collision turns up as expected the answer is already
// waiting. If it does not, the work is thrown away -- which costs a worker
// thread and nothing else.
void LiveWorld::guessAhead(const Foresight &guess, const std::string &name) {
    if (impl_->pending || impl_->guessing || !impl_->queued.empty()) return;
    if (guess.struck >= impl_->described.size()) return;
    // The hand is not a collision anybody is waiting on.
    // The thing in the hand can be the thing that DOES the breaking -- that is
    // what a hold guess is -- but not the thing broken.
    if (guess.struck == impl_->holding) return;
    std::unique_ptr<Pending> job = prepared(name, 0.003, &guess);
    if (job->settled) return;                    // nothing to run
    impl_->guess = guess;
    impl_->guess_unseen = 0;
    impl_->guessing = std::move(job);
    // Said out loud. A run that starts early and is never heard from again is
    // indistinguishable from one that never started, which cost an afternoon.
    // `lead_ms` carries the speed it is expecting, so the log can be read
    // against what actually turned up.
    impl_->delays.push_back({impl_->time_s, name, "guessing",
                             guess.arrival_speed_m_s, 0.0});
    Pending *running = impl_->guessing.get();
    running->started = std::chrono::steady_clock::now();
    impl_->guess_worker = std::async(std::launch::async, [running] { work(*running); });
}

void LiveWorld::dropGuess(const char *why) {
    if (!impl_->guessing) return;
    if (impl_->guess_worker.valid()) impl_->guess_worker.get();   // let it finish, then bin it
    impl_->delays.push_back({impl_->time_s, impl_->guessing->name, why, 0.0,
                             impl_->guessing->cost_ms});
    impl_->guessing.reset();
}

// Is the run that is already going the run for THIS collision?
//
// A guess is built from where things were going to be, and what actually turned
// up has to match it or the answer describes a different impact. Three things
// are checked: the same thing struck, by the same thing, arriving at close to
// the speed that was expected. The speed is the one that matters -- it sets how
// much energy goes into the lattice, and the whole answer turns on it.
bool LiveWorld::adoptGuess(const std::string &name) {
    if (!impl_->guessing) return false;
    if (impl_->guessing->name != name) { dropGuess("guess-wasted"); return false; }

    // What actually hit it, and how hard.
    double came_in = 0.0;
    std::string by;
    for (const LiveImpact &impact : impl_->last_impacts) {
        if (impact.struck != name) continue;
        if (impact.closing_speed_m_s >= came_in) { came_in = impact.closing_speed_m_s; by = impact.by; }
    }
    const double expected = impl_->guessing->guessed_speed;
    const bool same_striker = impl_->guessing->guessed_striker.empty()
                                  ? by == "the ground"
                                  : by == impl_->guessing->guessed_striker;
    // Five per cent of the speed, because the energy handed to the lattice goes
    // as the square of it: five per cent of speed is ten of energy, and fifteen
    // would have been a third. Measured on clean drops the prediction is out by
    // 0.18%, so this is a bar against a DIFFERENT collision turning up, not
    // against the arithmetic.
    const bool same_speed = expected > 0.0 &&
                            std::abs(came_in - expected) <= 0.05 * expected;
    if (!same_striker || !same_speed) {
        // Worth knowing WHY, or a guess that is never adopted looks like a
        // guess that is never made.
        impl_->delays.push_back({impl_->time_s, name, "guess-missed",
                                 expected, came_in});
        dropGuess("guess-wasted");
        return false;
    }

    if (impl_->guess_worker.valid()) impl_->guess_worker.get();
    // NOW it has had its chance at this contact. prepare() records that for a
    // run it starts itself, and a guess deliberately does not -- a prediction
    // about a later collision must not stop the world reporting a different
    // impact in the meantime. But adopting one IS the body having its chance,
    // and without this a thing that held was never written down as having held:
    // the world went on offering the same break, the step went on being taken
    // back, and it deadlocked exactly as the handshake is designed not to.
    impl_->held_through.insert(name);
    // How far out the prediction was, as a percentage of the speed it expected.
    // This is the one number that says whether looking ahead is sound: the
    // arrival speed is what sets the energy going into the lattice, and the
    // whole answer turns on it.
    impl_->guess_error_pct = 100.0 * std::abs(came_in - expected) / expected;
    impl_->pending = std::move(impl_->guessing);
    impl_->worker = std::future<void>{};          // already run
    return true;
}

// Capture every break the world is refusing to step past, so it can step.
void LiveWorld::queueBreaks() {
    for (const std::string &name : breakable()) {
        if (impl_->pending && impl_->pending->name == name) continue;
        bool already = false;
        for (const auto &waiting : impl_->queued)
            already = already || waiting->name == name;
        if (already) continue;
        // Capacity: a cascade can want dozens at once, and each one holds an
        // island's worth of lattice. Past this the world goes back to stopping,
        // which is slow but bounded -- unlike memory.
        if (impl_->queued.size() >= 16) {
            impl_->delays.push_back({impl_->time_s, name, "blocked", 0.0, 0.0});
            continue;
        }
        std::unique_ptr<Pending> job = prepared(name, impl_->pending->window_s);
        if (job->settled) continue;          // nothing to run; it will be re-heard
        impl_->delays.push_back({impl_->time_s, name, "queued", 0.0, 0.0});
        impl_->queued.push_back(std::move(job));
        repin();
    }
}

// Take the next one waiting and put it on the worker.
void LiveWorld::startNextQueued() {
    // One lattice run at a time. A guess is speculative and the queue is not.
    if (!impl_->queued.empty()) dropGuess("guess-wasted");
    while (!impl_->queued.empty()) {
        impl_->pending = std::move(impl_->queued.front());
        impl_->queued.pop_front();
        if (impl_->pending->settled) {       // nothing to run; apply it and move on
            applyPending();
            impl_->pending.reset();
            continue;
        }
        Pending *job = impl_->pending.get();
        job->started = std::chrono::steady_clock::now();
        job->waited_ms = 1000.0 * std::chrono::duration<double>(
            job->started - job->began).count();
        impl_->worker = std::async(std::launch::async, [job] { work(*job); });
        repin();
        return;
    }
    repin();
}

// The queue's indices are into the body table, and applying a fracture erases
// the island it broke from that table. Everything above those slots shifts
// down -- the same fixup `holding` already gets a few lines below the drop.
//
// A queued job whose island shared a body with the one just applied is not
// fixable and must go: the thing it was going to break has itself just come
// apart, and its pieces are new and untried. They will be heard on their own.
// Where everything ended up, given where it was.
//
// `before` is the body table's names in index order, taken just before whatever
// rearranged it. Names are unique and a body keeps its name across a rebuild, so
// they are what survives an operation that indices do not.
//
// Counting how many slots below an index were erased is NOT enough, and getting
// that wrong is what this is written the long way to prevent. A body that came
// through a fracture whole keeps its name and is erased and RE-APPENDED at the
// end: it has not gone, so nothing counts it as gone, and yet every index above
// its old slot has moved down by one. Queued jobs then held indices one too
// high, and the next apply erased the body next door -- measured, an iron ball
// dropped on a plate quietly destroyed two anchored piers, one of them across
// the room, and the only sign was scenery missing afterwards.
void LiveWorld::restackQueue(const std::vector<std::string> &before) {
    std::unordered_map<std::string, std::size_t> now;
    for (std::size_t i = 0; i < impl_->described.size(); ++i)
        now.emplace(impl_->described[i].name, i);

    constexpr std::size_t kGone = static_cast<std::size_t>(-1);
    std::vector<std::size_t> moved(before.size(), kGone);
    for (std::size_t i = 0; i < before.size(); ++i) {
        const auto found = now.find(before[i]);
        if (found != now.end()) moved[i] = found->second;
    }
    const auto follow = [&](std::size_t was) {
        return was < moved.size() ? moved[was] : kGone;
    };

    std::deque<std::unique_ptr<Pending>> keeping;
    for (auto &job : impl_->queued) {
        // A job whose subject or island no longer exists cannot be applied: the
        // thing it was going to break has itself come apart, and its pieces are
        // new and untried.
        bool lost = follow(job->which) == kGone;
        for (const std::size_t body : job->island_bodies)
            lost = lost || follow(body) == kGone;
        if (lost) continue;

        job->which = follow(job->which);
        if (job->anvil != kGone) {
            const std::size_t anvil = follow(job->anvil);
            job->anvil = anvil;            // kGone here simply means "no anvil"
        }
        for (std::size_t &body : job->island_bodies) body = follow(body);
        std::unordered_map<std::size_t, RigidSnapshot> poses;
        for (auto &entry : job->poses_before) poses.emplace(follow(entry.first), entry.second);
        job->poses_before = std::move(poses);
        for (auto &entry : job->body_of_node) entry.second = follow(entry.second);
        keeping.push_back(std::move(job));
    }
    impl_->queued = std::move(keeping);
}

// Take the loose pieces near a point out of the world, and say what they were.
//
// A room that shatters fills up: every pane is dozens of shards that will lie
// where they fell for as long as the world is open, and past a couple of
// thousand bodies the reversible trial cannot run, which is what breaking
// depends on. Sweeping them up is the natural answer -- they are debris, and
// somebody walking through the room is the obvious thing to sweep with.
//
// What is taken is deliberately narrow. Only a piece -- a "hull", which is what
// something that broke or bent becomes, never an authored object, so walking
// past a bowl does not pocket it. Never anchored scenery, never what is in a
// hand, and never anything an unfinished fracture is holding an index to.
//
// What comes back is what the pieces were MADE of, added up by material, which
// is the useful form: nobody wants forty entries called "glass plate 20mm
// piece 31", they want to know they now have 400 grams of glass.
std::vector<LiveCollected> LiveWorld::collect(const Vec3 &at, double radius_m,
                                              std::size_t largest_cells) {
    std::vector<LiveCollected> haul;
    if (!(radius_m > 0.0)) return haul;
    const double reach = radius_m * radius_m;
    const double cell_volume = impl_->request.cell_size_m * impl_->request.cell_size_m *
                               impl_->request.cell_size_m;

    // Anything a fracture still has an index into stays. Its job holds body
    // numbers, and taking one out from under it would either resurrect a body
    // that is gone or write a piece back onto somebody else's slot.
    std::set<std::size_t> spoken_for;
    const auto reserve = [&](const Pending &job) {
        for (const std::size_t body : job.island_bodies) spoken_for.insert(body);
    };
    if (impl_->pending) reserve(*impl_->pending);
    for (const auto &job : impl_->queued) reserve(*job);

    std::vector<std::size_t> taking;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const LiveBodyPose &body = impl_->described[i];
        // A hull is not enough: a dented whole object is a hull too, and it is
        // still the object it was. Only what came off something is debris.
        if (body.anchored || !body.fragment) continue;
        if (i == impl_->holding || spoken_for.count(i)) continue;
        if (i >= impl_->nodes_of.size() || impl_->nodes_of[i].size() > largest_cells) continue;
        if (!impl_->world->contains(impl_->body_of[i])) continue;
        // From where the body IS, not from where `described` remembers it.
        // `described` carries the pose a body was built with and poses() is
        // what refreshes it from the world -- so reading it here found every
        // piece sitting at the origin, a fixed 3.06 m from the plate they came
        // off. A sweep of 3 m collected nothing and a sweep of 50 m collected
        // the room, which is the shape of a bug that looks like a tuning problem.
        const Vec3 gap = impl_->world->snapshot(impl_->body_of[i]).center_of_mass_world_m - at;
        if (dot(gap, gap) > reach) continue;
        taking.push_back(i);
    }
    if (taking.empty()) return haul;

    // Added up by what it is, not by which shard it was.
    std::map<std::string, LiveCollected> by_material;
    for (const std::size_t i : taking) {
        const std::size_t cells = impl_->nodes_of[i].size();
        const double density = i < impl_->density_of.size() ? impl_->density_of[i] : 0.0;
        LiveCollected &into = by_material[impl_->described[i].material];
        into.material = impl_->described[i].material;
        into.cells += cells;
        into.pieces += 1;
        into.kilograms += static_cast<double>(cells) * cell_volume * density;
        into.took.push_back(impl_->described[i].name);
    }
    for (auto &entry : by_material) haul.push_back(std::move(entry.second));

    dropBodies(taking);
    return haul;
}

// Take bodies out of the world and out of every table that is parallel to it.
//
// The tables are indexed in step, so an erase shifts everything above it -- and
// three other things hold indices into them: the hand, the fracture being
// worked out, and anything queued behind it. Missing one of those does not
// crash, it silently moves somebody else's body, which is far worse.
void LiveWorld::dropBodies(const std::vector<std::size_t> &which) {
    // Whatever a body held leaves the world with it, and the ledger says so.
    if (impl_->thermo)
        for (const std::size_t body : which)
            if (body < impl_->described.size()) impl_->thermo->remove(impl_->described[body].name);
    // What was where, so anything still holding an index can follow it.
    std::vector<std::string> before;
    before.reserve(impl_->described.size());
    for (const LiveBodyPose &pose : impl_->described) before.push_back(pose.name);
    std::vector<std::size_t> going = which;
    std::sort(going.begin(), going.end(), std::greater<std::size_t>());
    going.erase(std::unique(going.begin(), going.end()), going.end());
    for (const std::size_t body : going) {
        if (body >= impl_->body_of.size()) continue;
        if (impl_->world->contains(impl_->body_of[body]))
            impl_->world->removeAndDestroy(impl_->body_of[body]);
        const auto drop = [&](auto &vector) {
            if (body < vector.size())
                vector.erase(vector.begin() + static_cast<std::ptrdiff_t>(body));
        };
        drop(impl_->described); drop(impl_->body_of); drop(impl_->nodes_of);
        drop(impl_->limits_of); drop(impl_->impedance_of); drop(impl_->density_of);
        drop(impl_->tensile_of);
        if (impl_->holding != static_cast<std::size_t>(-1) && impl_->holding > body)
            --impl_->holding;
    }
    // A guess holds indices into these tables as well, and unlike a queued job
    // it is speculative -- so it is thrown away rather than carefully followed.
    // It cost a worker thread and nothing else.
    dropGuess("guess-wasted");
    restackQueue(before);
    impl_->index_of.clear();
    for (std::size_t i = 0; i < impl_->described.size(); ++i)
        impl_->index_of.emplace(impl_->described[i].name, i);
    rehangJoints();
    repin();
}

bool LiveWorld::steppedBack() const { return impl_->stepped_back; }

LiveOutcome LiveWorld::lastOutcome() const { return impl_->last_outcome; }

std::vector<LiveDelay> LiveWorld::delays() const { return impl_->delays; }
void LiveWorld::forgetDelays() { impl_->delays.clear(); }
void LiveWorld::foreseeCollisions(double horizon_s) {
    impl_->foresee_horizon_s = std::max(0.0, horizon_s);
}

// Look ahead for a collision that is going to need the lattice.
//
// A ray along each moving body's own path says what is in front of it and how
// far; its speed says how long until it gets there. The same admission test the
// step uses then says whether that arrival would need the lattice at all. What
// comes out is a name and an amount of warning -- and warning is the whole
// point, because the run costs about as long as a two-metre fall takes.
//
// Cheap, but not free: a ray is 0.02 ms and there can be a hundred bodies. So
// it is asked at a stride, and only of things actually going somewhere.
void LiveWorld::foresee() {
    if (!(impl_->foresee_horizon_s > 0.0)) return;
    constexpr std::uint64_t kStride = 8;   // ~30 times a second at a live rate
    if (impl_->steps_taken % kStride != 0) return;

    std::set<std::string> still_coming;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const LiveBodyPose &body = impl_->described[i];
        if (body.anchored || i == impl_->holding) continue;
        const RigidSnapshot now = impl_->world->snapshot(impl_->body_of[i]);
        const double speed = length(now.linear_velocity_m_s);
        // Below this nothing can be admitted anywhere in the catalogue, so
        // there is nothing to look for.
        if (speed < 0.5) continue;
        // From the leading surface, not the centre, or the ray starts inside
        // the body and meets it.
        const Vec3 heading = (1.0 / speed) * now.linear_velocity_m_s;
        const double clear = 0.5 * std::max({body.dimensions_m.x, body.dimensions_m.y,
                                             body.dimensions_m.z}) + 0.005;
        const double reach = speed * impl_->foresee_horizon_s;
        const RayHit ahead = impl_->world->castRay(
            now.center_of_mass_world_m + clear * heading, heading, reach);
        if (!ahead.hit) continue;
        // How fast it will be going when it gets there, not how fast it is
        // going now. This is the whole difference between foresight and a
        // running commentary: a ball a metre up is barely moving and would fail
        // every admission test, and by the time its present speed clears the
        // bar it is nine milliseconds from the thing it is about to break.
        //
        // Falling accelerates it, so the arrival speed comes from the drop
        // still to go: v^2 = u^2 + 2*g*h. Rising or level, the drop is negative
        // and it arrives no faster than it is going.
        constexpr double kGravity = 9.80665;
        const double falling = -ahead.distance_m * heading.y;   // metres of drop left
        const double arrival =
            std::sqrt(std::max(0.0, speed * speed + 2.0 * kGravity * std::max(0.0, falling)));
        // Time to contact at the average of the two speeds, which is exact for
        // constant acceleration along the path and near enough otherwise.
        const double lead_s = 2.0 * ahead.distance_m / std::max(0.1, speed + arrival);

        // Would that arrival need the lattice? The same question the step asks,
        // asked early. Impedance from whatever is in the way, or the ground's
        // when the ray stopped on something with no id of ours.
        // The limits are the STRUCK body's, and the impedance is the striker's
        // -- that is the way round admitRefracture reads them, and it matters:
        // a glass pane hit by iron and an iron ball hit by glass have very
        // different answers from the same contact.
        FragmentFractureLimits struck = impl_->limits_of[i];
        double other = impl_->impedance_of[i];
        if (ahead.named) {
            for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
                if (impl_->body_of[k] == ahead.body_id) { struck = impl_->limits_of[k]; break; }
        } else {
            // The floor. Nothing of ours is struck, so ask about the mover --
            // against the ground that is actually there: sand where the ray
            // came down on sand, rock on rock.
            struck = impl_->limits_of[i];
            other = impl_->environment ? impl_->environment->contactImpedanceAt(ahead.point_world_m)
                                       : impl_->ground_impedance;
        }
        const RefractureAdmission would = admitRefracture(struck, other, arrival,
                                                          std::numeric_limits<double>::max());
        if (!would.worthRunning()) continue;

        // Name what is about to be HIT, where there is one. That is what the
        // lattice will be run on, and what the warning is for. A ray that
        // stopped on the floor has no name, so the mover is named instead.
        std::string about = body.name;
        if (ahead.named)
            for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
                if (impl_->body_of[k] == ahead.body_id) { about = impl_->described[k].name; break; }
        still_coming.insert(about);
        // Start it now, from where the two of them are going to be. Everything
        // this needs has just been worked out to decide whether to warn at all.
        if (!impl_->guessing && !impl_->pending && impl_->queued.empty()) {
            Foresight guess{};
            guess.striker = i;
            guess.arrival_speed_m_s = arrival;
            guess.struck = i;
            if (ahead.named)
                for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
                    if (impl_->body_of[k] == ahead.body_id) { guess.struck = k; break; }
            // Where it will be when it gets there, going as fast as it will be
            // going. The rest of its state -- how it is turned, how it is
            // spinning -- carries over unchanged, which is right for the short
            // flight that is left.
            guess.striker_state = now;
            guess.striker_state.center_of_mass_world_m =
                now.center_of_mass_world_m + ahead.distance_m * heading;
            guess.striker_state.linear_velocity_m_s = arrival * heading;
            if (guess.struck != guess.striker) guessAhead(guess, about);
        }
        if (impl_->foreseen.count(about)) continue;   // already said
        impl_->delays.push_back({impl_->time_s, about, "foreseen", lead_s * 1000.0, 0.0});
    }
    guessWhatIsHeld(still_coming);
    // A guess whose collision has stopped being expected for a while is not
    // going to be adopted. For a WHILE: see guess_unseen above.
    if (impl_->guessing) {
        impl_->guess_unseen = still_coming.count(impl_->guessing->name)
                                  ? 0 : impl_->guess_unseen + 1;
        if (impl_->guess_unseen >= 4) dropGuess("guess-wasted");
    } else {
        impl_->guess_unseen = 0;
    }
    impl_->foreseen.swap(still_coming);
}

// What would happen if the thing in the hand were let go right now.
//
// The warning a fall gives can never be longer than the fall. Measured on a
// concrete pane, whose run costs about 810 ms: a 4 m drop gives 702 ms of
// warning and the pieces are 147 ms late; a 0.6 m drop gives 268 ms and they are
// 573 ms late. Below about three and a half metres there is simply not enough
// air to work in, and no amount of looking further ahead creates any.
//
// But somebody holding a ball over a pane has already given us all the warning
// anyone could want -- seconds of it -- and nothing was being done with it. So
// the run for the drop they are lining up starts while they are still lining it
// up. If they move, the guess is thrown away and made again; if they throw it
// instead of dropping it the arrival speed will not match and it is refused.
// Being wrong costs a worker thread.
void LiveWorld::guessWhatIsHeld(std::set<std::string> &still_coming) {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    if (impl_->pending || !impl_->queued.empty()) return;
    const std::size_t held = impl_->holding;
    if (held >= impl_->described.size()) return;
    const RigidSnapshot now = impl_->world->snapshot(impl_->body_of[held]);

    // Straight down, from underneath it.
    const LiveBodyPose &body = impl_->described[held];
    const double clear = 0.5 * std::max({body.dimensions_m.x, body.dimensions_m.y,
                                         body.dimensions_m.z}) + 0.005;
    const Vec3 down{0.0, -1.0, 0.0};
    const RayHit below = impl_->world->castRay(
        now.center_of_mass_world_m + clear * down, down, 40.0);
    if (!below.hit || !below.named) return;

    std::size_t struck = static_cast<std::size_t>(-1);
    for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
        if (impl_->body_of[k] == below.body_id) { struck = k; break; }
    if (struck == static_cast<std::size_t>(-1) || struck == held) return;
    if (impl_->described[struck].anchored) return;

    constexpr double kGravity = 9.80665;
    const double arrival = std::sqrt(2.0 * kGravity * std::max(0.0, below.distance_m));
    if (arrival < 0.5) return;
    const RefractureAdmission would = admitRefracture(
        impl_->limits_of[struck], impl_->impedance_of[held], arrival,
        std::numeric_limits<double>::max());
    if (!would.worthRunning()) return;

    const std::string about = impl_->described[struck].name;
    still_coming.insert(about);
    // Already working on this exact drop? Then leave it alone. Re-making the
    // guess every time the hand wobbles a millimetre would mean never finishing
    // one.
    if (impl_->guessing) {
        const bool same = impl_->guessing->name == about &&
                          std::abs(impl_->guessing->guessed_speed - arrival) <=
                              0.02 * std::max(0.5, arrival);
        if (same) return;
        dropGuess("guess-wasted");
    }
    if (impl_->pending) return;

    Foresight guess{};
    guess.striker = held;
    guess.struck = struck;
    guess.arrival_speed_m_s = arrival;
    guess.striker_state = now;
    guess.striker_state.center_of_mass_world_m =
        now.center_of_mass_world_m + below.distance_m * down;
    guess.striker_state.linear_velocity_m_s = arrival * down;
    guessAhead(guess, about);
}

std::vector<std::string> LiveWorld::breakable() const {
    std::vector<std::string> out;
    for (const LiveImpact &impact : impl_->last_impacts) {
        // Either bound. The name is a hangover from when breaking was the only
        // thing the lattice was ever run for; what it means is "the lattice has
        // something to say about this one", and a dent is one of the things it
        // can say.
        if (!impact.would_break && !impact.would_dent) continue;
        if (impl_->held_through.count(impact.struck)) continue;
        // Gone: it broke, and what it became carries different names.
        if (impl_->index_of.find(impact.struck) == impl_->index_of.end()) continue;
        if (std::find(out.begin(), out.end(), impact.struck) == out.end())
            out.push_back(impact.struck);
    }
    // And anything carrying more than it can hold up. From the outside these
    // are the same question -- this thing may come apart, do you want to know --
    // and a host that only handled blows would never be offered a shelf.
    //
    // declineBreak silences them the same way it silences a contact, which
    // matters more here than there: a load does not go away by itself, so an
    // overloaded shelf would otherwise be offered on every survey for ever.
    for (const LiveOverload &sagging : impl_->overloaded) {
        if (impl_->held_through.count(sagging.name)) continue;
        if (impl_->index_of.find(sagging.name) == impl_->index_of.end()) continue;
        if (std::find(out.begin(), out.end(), sagging.name) == out.end())
            out.push_back(sagging.name);
    }
    return out;
}

void LiveWorld::declineBreak(const std::string &name) {
    // The same record fracture() keeps, without the lattice run: this body has
    // had its chance at this contact.
    impl_->held_through.insert(name);
}

void LiveWorld::prepare(const std::string &name, double window_s) {
    impl_->pending = prepared(name, window_s);
}

std::unique_ptr<LiveWorld::Pending> LiveWorld::prepared(const std::string &name,
                                                        double window_s,
                                                        const Foresight *guess) {
    auto held = std::make_unique<Pending>();
    Pending &job = *held;
    job.name = name;
    job.window_s = window_s;
    // Whatever happens below, this object has now had its chance at this
    // contact. Recording that here rather than at each of the five ways out is
    // what stops one of them being forgotten and deadlocking the world.
    //
    // Not for a guess. A guess is about a collision that has not happened, so
    // the body has had no chance at anything yet -- and marking it would stop
    // the world reporting a DIFFERENT impact on it in the meantime, which is a
    // real break quietly suppressed by a prediction about a later one.
    if (!guess) impl_->held_through.insert(name);
    impl_->last_outcome = LiveOutcome::Nothing;
    const auto found = impl_->index_of.find(name);
    if (found == impl_->index_of.end()) { job.settled = true; job.answer = 0; return held; }
    const std::size_t which = found->second;
    // Anchored scenery is the world. Breaking the floor is a different feature.
    impl_->last_outcome = LiveOutcome::Held;
    if (impl_->described[which].anchored) { job.settled = true; job.answer = 1; return held; }
    if (impl_->holding == which) { job.settled = true; job.answer = 1; return held; }   // it is in a hand, not in a collision
    const TileImpactSetup &setup = *impl_->setup;
    // Whatever struck it goes into the island too. A body on its own, entered
    // after the contact, is a free-flying object with a uniform velocity and no
    // stress anywhere in it: it cannot break however hard it was hit. Both
    // bodies are cut from the same parent lattice, so the island is simply the
    // union of their cells, and running it resolves the collision through the
    // failure criterion rather than through Jolt's contact solver.
    std::vector<std::size_t> island_bodies{which};
    // Scenery that was struck, kept aside. It does not go INTO the island --
    // it is immovable, and putting immovable matter into a lattice run is
    // paying to solve something whose answer is "it did not move". But it must
    // not simply be dropped either, which is what used to happen: a ball that
    // hit an anchored anvil was re-entered on its own, a free-flying object
    // with a uniform velocity and nothing to press against, and came away a
    // perfect sphere however hard it was driven in. Below, it becomes what it
    // physically is -- a surface that does not give.
    std::size_t anvil = static_cast<std::size_t>(-1);
    {
        // A guess names its own striker: partner_of is written by the step that
        // saw the contact, and for a collision that has not happened there is
        // no such step yet.
        std::size_t with = static_cast<std::size_t>(-1);
        if (guess) {
            with = guess->striker;
        } else {
            const auto partner = impl_->partner_of.find(which);
            if (partner != impl_->partner_of.end()) {
                with = partner->second;
            } else {
                // No contact caused this, so it is a load rather than a blow:
                // the thing sitting on it is what it has to be run against. See
                // Impl::bearing_on -- without this an overloaded shelf goes into
                // the lattice with nothing on it and comes out whole.
                const auto bearing = impl_->bearing_on.find(which);
                if (bearing != impl_->bearing_on.end()) with = bearing->second;
            }
        }
        // A held body is normally kept out of an island: it is in a hand, not in
        // a collision. A guess that names it is saying what will happen when it
        // is let go, and its state is overridden to the moment it lands, so it
        // belongs in the island exactly like anything else that is falling.
        const bool in_a_hand = with == impl_->holding && !(guess && guess->striker == with);
        if (with != static_cast<std::size_t>(-1) && with < impl_->described.size() &&
            !in_a_hand) {
            if (impl_->described[with].anchored) anvil = with;
            else island_bodies.push_back(with);
        }
    }
    for (const std::size_t body : island_bodies)
        if (!impl_->world->contains(impl_->body_of[body])) { job.settled = true; job.answer = 0; return held; }
    // Where a body is, or -- for the one thing that has not arrived yet -- where
    // it is going to be. Everything below asks through this, so a run started
    // early is built from the collision as it is expected to happen.
    const auto stateOf = [&](std::size_t body) {
        if (guess && body == guess->striker) return guess->striker_state;
        return impl_->world->snapshot(impl_->body_of[body]);
    };
    const MatterBodyId old_body = impl_->body_of[which];
    const RigidSnapshot snap = stateOf(which);

    // Every cell of every body in the island, in parent numbering. Each body's
    // cells are placed by ITS own rigid pose, which is what buildFragmentLattice
    // does for one body -- so the offsets are rewritten here into the frame the
    // island will be built in, one body at a time.
    std::vector<std::uint32_t> island_nodes;
    std::unordered_map<std::uint32_t, std::size_t> body_of_node;
    std::unordered_map<std::size_t, RigidSnapshot> poses_before;
    for (const std::size_t body : island_bodies) {
        const RigidSnapshot pose = stateOf(body);
        poses_before.emplace(body, pose);
        for (const std::uint32_t node : impl_->nodes_of[body]) {
            island_nodes.push_back(node);
            body_of_node.emplace(node, body);
            // Where this cell is in the STRUCK body's frame, so that one pose
            // places the whole island correctly.
            const Vec3 world = pose.center_of_mass_world_m +
                               pose.orientation_world.rotate(impl_->cell_offset_m[node]);
            // Into the struck body's frame. A unit quaternion's inverse is its
            // conjugate, and Quat carries no operation for it.
            const Quat inverse{snap.orientation_world.w, -snap.orientation_world.x,
                               -snap.orientation_world.y, -snap.orientation_world.z};
            impl_->cell_offset_m[node] = inverse.rotate(world - snap.center_of_mass_world_m);
        }
    }

    // The rigid solver tolerates a penetration the lattice's support projection
    // does not: a cell centre below the floor is pushed back up THROUGH its
    // bonds, which injects energy that has nothing to do with the impact. Lift
    // the island clear first -- a rigid translation, so no momentum and no
    // kinetic energy change -- and refuse outright if it is buried deeper than
    // half a cell, rather than hand the lattice a state it will explode on.
    double lift = 0.0;
    {
        const SupportSet<double> &support = setup.settings_world.support;
        for (const std::uint32_t node : island_nodes) {
            const Vec3 position = snap.center_of_mass_world_m +
                snap.orientation_world.rotate(impl_->cell_offset_m[node]);
            for (std::uint32_t p = 0; p < support.plane_count; ++p) {
                const SupportPlane<double> &plane = support.planes[p];
                if (plane.normal.y < 0.999) continue;
                if (!insideFootprints(plane, toV3(position))) continue;
                const double depth =
                    dot(toV3(position) - plane.point, plane.normal) - plane.node_radius;
                lift = std::max(lift, -depth);
            }
        }
    }
    if (lift > 0.5 * impl_->request.cell_size_m) { job.settled = true; job.answer = 1; return held; }

    const FragmentPose pose{snap.center_of_mass_world_m + Vec3{0.0, lift, 0.0},
                            snap.orientation_world, snap.linear_velocity_m_s,
                            snap.angular_velocity_rad_s};
    FragmentLattice island = buildFragmentLattice(
        setup.matter, island_nodes, impl_->cell_offset_m, pose,
        impl_->plastic_extension_m, impl_->plastic_strain_m);
    // buildFragmentLattice places every cell with ONE rigid pose, because it was
    // written for one fragment: position, orientation AND velocity all come from
    // that pose. An island of two bodies therefore arrives with the struck
    // body's velocity on both of them -- the ball sits in exactly the right
    // place with exactly the wrong speed, the closing speed is zero, and 2,174
    // substeps later nothing has broken. Give every cell back the velocity of
    // the body it actually belongs to.
    for (std::size_t local = 0; local < island.parent_node.size(); ++local) {
        const std::uint32_t node = island.parent_node[local];
        const auto owner = body_of_node.find(node);
        if (owner == body_of_node.end() || owner->second == which) continue;
        const RigidSnapshot pose = poses_before[owner->second];
        const Vec3 arm = island.matter.nodes[local].position_world_m - pose.center_of_mass_world_m;
        island.matter.nodes[local].velocity_m_s =
            pose.linear_velocity_m_s + cross(pose.angular_velocity_rad_s, arm);
    }
    LatticeState island_state = buildLatticeState(island.matter, island.schedule, island.origin);
    for (std::size_t k = 0; k < island_state.bond_count; ++k) {
        const std::uint32_t o = island.schedule.bond_order[k];
        island_state.plastic_extension[k] = island.plastic_extension_m[o];
        island_state.plastic_strain[k] = island.plastic_strain_m[o];
    }

    // The island alone: no striker, the same support planes the scene uses.
    StepSettings<double> settings = buildSettings(setup, island.origin);
    // Yield from the struck body's OWN material.
    //
    // buildSettings takes it from the scene's default matter, because there is
    // one plastic_yield_stretch for the whole solve and the single-tile lane
    // has one material to put in it. In a scene of objects that default is
    // glass, which has no yield point at all -- so an iron ball being hammered
    // into an anvil was solved with a yield stretch of zero and could not take
    // a permanent set however hard it was hit. An island is one body, or a body
    // and the thing that struck it, so the struck body's material is the one
    // that belongs here.
    const MaterialDefinition *struck_material = &setup.tile_material;
    if (setup.multi_body && !setup.part_of_node.empty() && !impl_->nodes_of[which].empty()) {
        const std::uint32_t part = setup.part_of_node[impl_->nodes_of[which].front()];
        if (part < setup.part_definitions.size()) {
            const MaterialDefinition &own = setup.part_definitions[part];
            struck_material = &own;
            const bool yields = own.yield_strength_pa > 0.0 && own.young_modulus_pa > 0.0;
            settings.plastic_yield_stretch =
                yields ? own.yield_strength_pa / own.young_modulus_pa : 0.0;
            settings.plastic_hardening = yields ? std::max(0.0, own.hardening_ratio) : 0.0;
        }
    }
    // The scenery it was driven into, as the surface it is.
    //
    // A support plane is exactly "a thing that does not give", which is what
    // anchored matter is, and the lattice already has the ground as one. The
    // footprint is the body's own extent, so the island is stopped where the
    // scenery actually is and passes beside it where it is not.
    //
    // Horizontal only: the plane's normal is +Y. So this is a table top, an
    // anvil, a floor -- the cases where something is driven DOWN into
    // something. A wall or a tilted ramp is not covered, and would need a
    // plane that can face any direction.
    if (anvil != static_cast<std::size_t>(-1) &&
        settings.support.plane_count < kMaxSupportPlanes) {
        const RigidSnapshot on = impl_->world->snapshot(impl_->body_of[anvil]);
        const Vec3 half = 0.5 * impl_->described[anvil].dimensions_m;
        const double top = on.center_of_mass_world_m.y + half.y;
        // How the struck body meets the scenery, from the two materials.
        const MaterialDefinition &anvil_material =
            setup.multi_body && !impl_->nodes_of[anvil].empty() &&
                    setup.part_of_node[impl_->nodes_of[anvil].front()] <
                        setup.part_definitions.size()
                ? setup.part_definitions[setup.part_of_node[impl_->nodes_of[anvil].front()]]
                : setup.ground_material;
        const CombinedContactMaterial against = combineContactMaterials(
            compileContactMaterial(*struck_material), compileContactMaterial(anvil_material));
        SupportPlane<double> plane{};
        const SupportPlaneFrame frame = makeSupportPlane(
            Vec3{on.center_of_mass_world_m.x, top, on.center_of_mass_world_m.z} - island.origin,
            Vec3{0.0, 1.0, 0.0});
        plane.point = toV3(frame.point_world_m);
        plane.normal = toV3(frame.normal_world);
        plane.tangent = toV3(frame.tangent_world);
        plane.bitangent = toV3(frame.bitangent_world);
        plane.restitution = against.restitution;
        plane.static_friction = against.static_friction;
        plane.dynamic_friction = against.dynamic_friction;
        plane.node_radius = impl_->request.node_contact_radius_factor * impl_->request.cell_size_m;
        plane.reach_capped = 1;
        plane.footprint_count = 1;
        plane.footprints[0] = {0.0, 0.0, half.x, half.z};
        settings.support.planes[settings.support.plane_count++] = plane;
    }
    settings.node_contact.bucket_mask =
        latticeContactBucketMask(static_cast<std::uint32_t>(island.matter.nodes.size()));
    settings.sphere_enabled = 0U;
    SphereState<double> parked = setup.sphere_world;
    parked.center = {0.0, 1.0e4, 0.0};
    parked.velocity = {0.0, 0.0, 0.0};
    parked.angular_velocity = {0.0, 0.0, 0.0};

    const auto stepsFor = [&](double seconds) {
        return static_cast<std::uint64_t>(
            std::max<long long>(0, std::llround(seconds / setup.dt_s)));
    };
    std::unique_ptr<LatticeBackend> backend = makeBackend(impl_->request, island.schedule);
    backend->upload(island_state, settings, parked);
    RunControl control{};
    // The window has to cover the rigid step that was taken back BEFORE it can
    // cover the impact: the world is one step short of contact, so a ball at
    // 5 m/s is still up to a step's travel away when the lattice starts. A 3 ms
    // window on its own runs out while the ball is still in the air.
    control.max_steps =
        std::max<std::uint64_t>(1, stepsFor(window_s + impl_->last_dt_s));
    // The energy plateau still applies -- it only fires after something has
    // failed, and stopping once the removed energy is flat is the whole reason
    // this window can be short.
    control.min_steps = stepsFor(impl_->request.min_ms / 1000.0);
    control.energy_flat_steps = stepsFor(impl_->request.energy_flat_ms / 1000.0);
    control.energy_flat_fraction = impl_->request.energy_flat_fraction;
    // The calm exit does NOT apply here. It stops a run once nothing is near
    // failing, which is exactly the state a re-entry starts in while the two
    // bodies are still closing -- it would fire a millisecond in and end the
    // run before the impact it was opened for.
    control.calm_steps = 0;
    job.island = std::move(island);
    job.state = std::move(island_state);
    job.backend = std::move(backend);
    job.control = control;
    job.parked = parked;
    job.which = which;
    job.anvil = anvil;
    job.island_bodies = std::move(island_bodies);
    job.poses_before = std::move(poses_before);
    job.body_of_node = std::move(body_of_node);
    job.snap = snap;
    job.struck_material = struck_material;
    job.yield_extension = settings.plastic_yield_stretch * impl_->request.cell_size_m;
    // Who is allowed to come apart in this run. The body asked about, always;
    // anything else in the island only if this contact cleared its own bar.
    for (const std::size_t body : job.island_bodies) {
        bool admitted = body == which;
        if (!admitted)
            for (const LiveImpact &impact : impl_->last_impacts)
                admitted = admitted || (impact.struck == impl_->described[body].name &&
                                        (impact.would_break || impact.would_dent));
        if (!admitted) continue;
        if (body < impl_->nodes_of.size())
            for (const std::uint32_t node : impl_->nodes_of[body]) job.may_break.insert(node);
    }
    job.began = std::chrono::steady_clock::now();
    job.started = job.began;
    if (guess) {
        job.guessed = true;
        job.guessed_speed = guess->arrival_speed_m_s;
        job.guessed_at = guess->striker_state.center_of_mass_world_m;
        if (guess->striker < impl_->described.size())
            job.guessed_striker = impl_->described[guess->striker].name;
    }
    return held;
}

// The only part that takes any time, and the only part that touches nothing
// shared. Safe to call from a worker.
void LiveWorld::work(Pending &job) {
    job.status = job.backend->run(job.control);
    job.backend->download(job.state, job.parked);
    job.cost_ms = 1000.0 * std::chrono::duration<double>(
        std::chrono::steady_clock::now() - job.started).count();
    job.worked = true;
}

std::size_t LiveWorld::applyPending() {
    Pending &job = *impl_->pending;
    if (job.settled) return job.answer;
    const std::string &name = job.name;
    const RunStatus &status = job.status;
    FragmentLattice &island = job.island;
    LatticeState &island_state = job.state;
    const std::size_t which = job.which;
    const std::vector<std::size_t> &island_bodies = job.island_bodies;
    const auto &poses_before = job.poses_before;
    const auto &body_of_node = job.body_of_node;
    const RigidSnapshot &snap = job.snap;
    const TileImpactSetup &setup = *impl_->setup;
    writeBackLatticeState(island_state, island.schedule, island.matter);
    // Put back every bond that belongs to a body which was never admitted for
    // breaking at this contact. See Pending::may_break: the island must hold the
    // striker for the collision to have any stress in it, and holding it must
    // not be the same as condemning it.
    if (!job.may_break.empty() && island.matter.asset != nullptr) {
        std::size_t revived = 0;
        for (std::size_t o = 0; o < island.matter.bonds.size() &&
                                o < island.matter.asset->bonds.size(); ++o) {
            if (island.matter.bonds[o].alive) continue;
            const BondRest &rest = island.matter.asset->bonds[o];
            if (rest.node_a >= island.parent_node.size() ||
                rest.node_b >= island.parent_node.size()) continue;
            const std::uint32_t a = island.parent_node[rest.node_a];
            const std::uint32_t b = island.parent_node[rest.node_b];
            // A bond inside a body that was allowed to break stays broken.
            if (job.may_break.count(a) && job.may_break.count(b)) continue;
            island.matter.bonds[o].alive = true;
            island.matter.bonds[o].damage = 0.0;
            island.matter.bonds[o].failure_mode = BondFailureMode::None;
            ++revived;
        }
        if (revived > 0)
            impl_->delays.push_back({impl_->time_s, name, "spared",
                                     static_cast<double>(revived), 0.0});
    }
    // The permanent set the run left behind: bond lengths the material will not
    // give back. This is a dent. It is carried out of the island and into the
    // parent's own record, so the next hit starts from the shape this one left
    // rather than from the shape it was authored as.
    double dent_m = 0.0;
    Vec3 dent_at{};
    for (std::size_t k = 0; k < island_state.bond_count; ++k) {
        const std::uint32_t o = island.schedule.bond_order[k];
        const std::uint32_t parent_bond = island.parent_bond.empty()
                                              ? static_cast<std::uint32_t>(o)
                                              : island.parent_bond[o];
        if (parent_bond < impl_->plastic_extension_m.size()) {
            impl_->plastic_extension_m[parent_bond] = island_state.plastic_extension[k];
            impl_->plastic_strain_m[parent_bond] = island_state.plastic_strain[k];
        }
        const double set_here = std::abs(island_state.plastic_extension[k]);
        if (set_here > dent_m) {
            dent_m = set_here;
            // Where it happened: the middle of the bond that took the set. In
            // the island's frame, which is the frame the cells are already in.
            // Which two cells the bond joins lives on the asset the island was
            // cut from; the state alongside it carries only how it is doing.
            if (island.matter.asset != nullptr && o < island.matter.asset->bonds.size()) {
                const BondRest &bond = island.matter.asset->bonds[o];
                if (bond.node_a < island.matter.nodes.size() &&
                    bond.node_b < island.matter.nodes.size())
                    dent_at = 0.5 * (island.matter.nodes[bond.node_a].position_world_m +
                                     island.matter.nodes[bond.node_b].position_world_m);
            }
        }
    }

    const auto island_components = findConnectedComponents(island.matter);
    // Nothing came apart. Usually that is the end of it -- the body held, and
    // it keeps the shape it was authored with.
    //
    // Unless it took a permanent set. A dent is not a break: the object is one
    // piece still, but it is not the shape it was, and an engine that throws
    // that away can only ever show things intact or in bits. So a body that
    // has yielded is rebuilt from where its matter actually ended up, which
    // makes it a hull -- because that IS its surface now, and no box or sphere
    // describes a dented thing.
    //
    // The bar is in the material's own units, not the grid's.
    //
    // It was a tenth of a cell -- 2 mm on a 20 mm cell -- which is a tenth of
    // permanent strain on one bond. Nothing reaches that without coming apart
    // first, so the test could never fire: an iron ball hammered into the floor
    // flowed 173 micrometres per bond, nine times what it took to start
    // flowing, and was still called unchanged.
    //
    // What "permanently deformed" means is set by where the material stops
    // springing back, so that is what it is measured against. Twice the yield
    // extension is past the point where the flow could be one substep's
    // overshoot rather than a set.
    const double yield_extension = job.yield_extension;
    const bool dented = yield_extension > 0.0 && dent_m > 2.0 * yield_extension;

    if (status.broken_bonds == 0 && island_components.size() <= 1 && !dented) return 1;
    if (island_components.empty()) return 1;


    // It broke, or it bent. Either way it is not what it was, so replace it.
    FragmentBuildResult rebuilt = buildFragmentRepresentations(island.matter, island_components, {
        .first_body_id = impl_->next_body_id,
        .maximum_rigid_fragments = std::max<std::size_t>(1, island_components.size()),
        .minimum_nodes_per_rigid_fragment = 1,
        .maximum_collision_points = 192,
        .friction = setup.tile_ground.dynamic_friction,
        .restitution = setup.tile_ground.restitution,
    });
    for (const std::size_t body : island_bodies)
        impl_->world->removeAndDestroy(impl_->body_of[body]);

    // A cell's part is what names its piece, so a ball that came through intact
    // is still the ball and the pane's shards are the pane's.
    std::vector<LiveBodyPose> parent_of_part(setup.part_bodies.size());
    std::vector<std::size_t> counted(setup.part_bodies.size(), 0);
    // Every part a body covers, not just the part of its first cell.
    //
    // A body used to be filed under its first cell alone, and a piece that is
    // itself made of pieces can span several parts. Any component whose
    // dominant part was not the first cell of anything found an empty slot and
    // took an empty name and an empty material out of it: the room filled with
    // things called " piece 1 piece 1" made of nothing, and sweeping the floor
    // up reported "2,833 g of ".
    for (const std::size_t body : island_bodies)
        for (const std::uint32_t node : impl_->nodes_of[body]) {
            const std::uint32_t part = setup.part_of_node[node];
            if (part < parent_of_part.size() && parent_of_part[part].name.empty())
                parent_of_part[part] = impl_->described[body];
        }
    // And if a part still has nobody -- it was not in the island at all -- the
    // thing that was struck is the honest answer for whose piece this is.
    const LiveBodyPose fell_from = impl_->described[which];
    // Read now, while the struck body is still in nodes_of. The drop loop below
    // erases it, and reading afterwards indexed off the end of the shortened
    // vector: the answer matched no piece, so a plate that had just come apart
    // into eight was reported as having held.
    const std::uint32_t asked_part =
        impl_->nodes_of[which].empty() ? 0 : setup.part_of_node[impl_->nodes_of[which].front()];
    // Which body each cell came from, so that what a body HELD is shared out
    // among its pieces by the cells each one took: a burning log that breaks
    // gives every piece its share of the fuel, the moisture and the heat, and
    // no piece gets any that was not there.
    const bool thermal = impl_->thermo && impl_->thermo->active();
    std::unordered_map<std::uint32_t, std::string> source_of_cell;
    std::unordered_map<std::string, std::size_t> source_cells;
    std::map<std::string, std::vector<std::pair<std::string, double>>> shares;
    if (thermal)
        for (const std::size_t body : island_bodies) {
            const std::string &source = impl_->described[body].name;
            if (!impl_->thermo->holds(source)) continue;
            source_cells[source] = impl_->nodes_of[body].size();
            for (const std::uint32_t node : impl_->nodes_of[body]) source_of_cell[node] = source;
        }

    // Drop every body in the island and append what they became. A piece is a
    // hull: its cells ARE its surface now, so no authored primitive fits.
    std::vector<std::size_t> going = island_bodies;
    std::sort(going.begin(), going.end(), std::greater<std::size_t>());
    for (const std::size_t body : going) {
        const auto drop = [&](auto &vector) {
            vector.erase(vector.begin() + static_cast<std::ptrdiff_t>(body));
        };
        drop(impl_->described); drop(impl_->body_of); drop(impl_->nodes_of);
        drop(impl_->limits_of); drop(impl_->impedance_of); drop(impl_->density_of);
        drop(impl_->tensile_of);
        if (impl_->holding != static_cast<std::size_t>(-1) && impl_->holding > body) --impl_->holding;
    }

    // What was asked about is `asked_part`, taken above. The island may hold the
    // thing that struck it, and that thing may have come apart too, so counting
    // every component would answer a question nobody asked.
    std::size_t made = 0, of_asked = 0, fragment_index = 0;
    for (const auto &component : island_components) {
        if (fragment_index >= rebuilt.rigid_fragments.size()) break;
        // Not const: a piece that came through whole has its authored collision
        // shape put back below, and the fragments are handed to the world after
        // this loop rather than during it.
        RigidFragmentDescription &fragment = rebuilt.rigid_fragments[fragment_index];
        if (fragment.source_node_count != component.node_indices.size()) continue;
        ++fragment_index;
        std::vector<std::uint32_t> parent_nodes;
        parent_nodes.reserve(component.node_indices.size());
        std::fill(counted.begin(), counted.end(), 0);
        for (const std::uint32_t local : component.node_indices) {
            const std::uint32_t node = island.parent_node[local];
            parent_nodes.push_back(node);
            const std::uint32_t part = setup.part_of_node[node];
            if (part < counted.size()) ++counted[part];
            impl_->cell_offset_m[node] = island.matter.nodes[local].position_world_m -
                                         fragment.mass_properties.center_of_mass_world_m;
        }
        const std::size_t dominant = static_cast<std::size_t>(
            std::max_element(counted.begin(), counted.end()) - counted.begin());
        const LiveBodyPose &parent = parent_of_part[dominant].name.empty()
                                         ? fell_from
                                         : parent_of_part[dominant];
        const MaterialDefinition &material = dominant < setup.part_definitions.size()
                                                 ? setup.part_definitions[dominant]
                                                 : setup.tile_material;
        LiveBodyPose piece{};
        // A piece that is still all of its parent kept its parent; only a piece
        // that is part of one is numbered.
        const bool whole_parent = counted[dominant] == component.node_indices.size() &&
                                  !parent_of_part[dominant].name.empty() &&
                                  component.node_indices.size() ==
                                      impl_->cellsOfPart(dominant);
        piece.name = whole_parent ? parent.name
                                  : parent.name + " piece " + std::to_string(++made);
        if (!source_of_cell.empty()) {
            std::unordered_map<std::string, std::size_t> from;
            for (const std::uint32_t node : parent_nodes) {
                const auto found = source_of_cell.find(node);
                if (found != source_of_cell.end()) ++from[found->second];
            }
            for (const auto &[source, cells] : from)
                shares[source].emplace_back(piece.name, static_cast<double>(cells));
        }
        // A piece that is still all of its parent is that parent, bent. Only
        // something that actually came off is debris.
        piece.fragment = !whole_parent || parent.fragment;
        // The deepest set it carries, and where. A piece keeps what its parent
        // had unless this run went deeper.
        piece.dent_m = parent.dent_m;
        piece.dent_at_m = parent.dent_at_m;
        if (whole_parent && dent_m > piece.dent_m) {
            piece.dent_m = dent_m;
            piece.dent_at_m = dent_at - fragment.mass_properties.center_of_mass_world_m;
        }
        // What it is made of is a property of the PART, not of whichever body
        // happened to be standing in as its parent. Asked of the scene, which
        // has known the answer since it opened. (The material definition has a
        // name too -- "soda_lime_glass" -- but the bodies say "glass", and an
        // inventory holding both has two entries for one substance.)
        piece.material = dominant < impl_->material_of_part.size() &&
                                 !impl_->material_of_part[dominant].empty()
                             ? impl_->material_of_part[dominant]
                             : parent.material;
        if (dominant == asked_part) ++of_asked;

        // Something that came through whole is still the shape it was.
        //
        // Every piece used to be made a hull, including the ones nothing had
        // happened to. An island is the struck body AND the thing that struck
        // it, so a ball that cracked a pane was rebuilt too -- and came out of
        // the collision as a lump of cubes, having not been damaged at all.
        // From the outside that reads as the whole scene turning to voxels the
        // moment anything breaks, which is what it looked like because it is
        // what it was.
        //
        // A hull is the honest surface of a piece that BROKE: its boundary is
        // where the material failed and there is no smooth original to keep.
        // For a body still in one piece there is, and it is the shape it was
        // authored as. The collision primitive goes back with it, or a ball
        // with a flat-bottomed hull slides where it should roll.
        // "Whole" is not the same as "unchanged". A body that yielded still has
        // all of its cells and is still one piece -- that is what a dent IS --
        // and giving it back its authored sphere would hide the very thing that
        // just happened to it. So the permanent set decides too.
        // Whether the SHAPE changed enough to be worth drawing differently,
        // which is a different question from whether the body was dented.
        //
        // Everything that yielded used to be rebuilt out of its cells. That is
        // right when something has really been squashed and wrong when it has
        // not: measured on an iron ball dropped twelve metres onto an anvil, the
        // permanent set is a tenth of a millimetre, the cells end up within
        // ninety micrometres of where they started, and a 120 mm sphere was
        // redrawn as a 136-cube staircase showing no dent whatever -- strictly
        // worse than the sphere it replaced, and it cost the rolling too,
        // because a hull of cells has a flat bottom.
        //
        // The deepest single bond does not answer this: many bonds each giving
        // a little adds up along a chain, and the same ball driven at 16 m/s
        // loses more than a centimetre off its width with no single bond
        // anywhere near that.
        //
        // Nor does the outline against the size it was AUTHORED at, which was
        // the first answer here and was wrong for a reason worth writing down:
        // a sphere's cells never fill its sphere. A 140 mm ball voxelised at
        // 20 mm has its outermost cell centres at 52 mm, so its cell extent is
        // 124 mm before anything happens to it -- a 16 mm "change" that is
        // nothing but the grid. Every ball that so much as entered an island
        // was therefore redrawn as a blob: measured on an aluminium ball that
        // struck an ice plate at 8.75 m/s against a bending threshold of 58.2,
        // took a permanent set of exactly zero, and came out a 168-cell hull.
        //
        // What answers it is the cells against THEMSELVES: how far the furthest
        // one reaches from the middle of them, now, against how far it reached
        // when the body was made. Same measure, same cells, so the grid cancels
        // -- and it does not care how the body is turned, which an axis-aligned
        // box would.
        const auto reachOf = [&](auto &&placeOf) {
            Vec3 middle{};
            for (const std::uint32_t node : parent_nodes) middle = middle + placeOf(node);
            const double count = static_cast<double>(parent_nodes.size());
            if (count > 0.0) middle = (1.0 / count) * middle;
            double far = 0.0;
            for (const std::uint32_t node : parent_nodes)
                far = std::max(far, length(placeOf(node) - middle));
            return far;
        };
        const double reaches_now =
            reachOf([&](std::uint32_t node) { return impl_->cell_offset_m[node]; });
        const double reached_when_made =
            reachOf([&](std::uint32_t node) { return setup.matter.nodes[node].position_world_m; });
        const double moved = std::abs(reaches_now - reached_when_made);
        // A quarter of a cell. Measured, an undeformed body comes out at a few
        // micrometres and a genuinely squashed one at about half a cell, so the
        // two are nowhere near each other and the bar only has to sit between.
        const bool reshaped = moved > 0.25 * impl_->request.cell_size_m;
        const bool untouched = whole_parent && !reshaped && parent.shape != "hull";
        if (untouched) {
            piece.shape = parent.shape;
            piece.dimensions_m = parent.dimensions_m;
            fragment.primitive = parent.shape == "sphere" ? FragmentPrimitive::Sphere
                                                          : FragmentPrimitive::Box;
            fragment.primitive_dimensions_m = parent.dimensions_m;
        } else {
            piece.shape = "hull";
        }
        piece.color_rgba = parent.color_rgba;
        impl_->limits_of.push_back(fragmentFractureLimits(
            setup.matter, parent_nodes, material.density_kg_m3, material.young_modulus_pa,
            material.yield_strength_pa));
        impl_->impedance_of.push_back(
            acousticImpedance(material.density_kg_m3, material.young_modulus_pa));
        impl_->density_of.push_back(material.density_kg_m3);
        impl_->tensile_of.push_back(material.tensile_strength_pa);
        impl_->nodes_of.push_back(std::move(parent_nodes));
        if (piece.shape == "hull")
            piece.dimensions_m = cellBounds(impl_->nodes_of.back(), impl_->cell_offset_m,
                                            impl_->request.cell_size_m);
        impl_->described.push_back(std::move(piece));
        impl_->body_of.push_back(fragment.body_id);
        impl_->next_body_id = std::max(impl_->next_body_id, fragment.body_id + 1);
    }
    impl_->world->addFragments(rebuilt.rigid_fragments);
    impl_->index_of.clear();
    for (std::size_t i = 0; i < impl_->described.size(); ++i)
        impl_->index_of.emplace(impl_->described[i].name, i);
    if (thermal) {
        for (auto &[source, pieces] : shares) {
            const double cells = static_cast<double>(source_cells[source]);
            for (auto &piece : pieces) piece.second /= cells;
            impl_->thermo->split(source, pieces);
        }
        impl_->thermo->refresh(thermoShapes(), setup.ground_y);
    }
    // Every body in the island was destroyed and rebuilt above, so every pin
    // touching any of them is holding nothing. This is where they find their
    // wood again -- or find there is none left, and let go.
    rehangJoints();
    // What happened to the body that was ASKED about, which is not the same as
    // what happened to the island. An island can come apart while the thing in
    // question survives whole -- a ball that cracked the pane it hit is one
    // piece still -- and reporting the island's fate as the body's says a thing
    // broke when it did not.
    impl_->last_outcome = of_asked > 1 ? LiveOutcome::Broke
                        : dented       ? LiveOutcome::Dented
                                       : LiveOutcome::Held;
    // It broke, so the name it held under is gone and its pieces are new ones
    // that have never been tried. A body that only BENT keeps its name, and
    // must keep its place in the already-answered set with it -- otherwise the
    // same contact is offered again on the next step, dents it again, and the
    // world spends itself deforming one object for ever.
    if (impl_->index_of.find(name) == impl_->index_of.end()) impl_->held_through.erase(name);
    return of_asked;
}


bool LiveWorld::beginFracture(const std::string &name, double window_s) {
    // One at a time, and a second one waits for the first.
    //
    // Dropping it instead is not an option: the step that turned it up was
    // taken back, and it stays taken back until somebody answers, so ignoring
    // it stops the clock -- the very thing this is here to prevent. So the
    // first is collected, waiting for it if it is not ready yet, and that wait
    // is written down as a block because that is what it is.
    //
    // Two that share no matter could run side by side; that is a real
    // improvement and not this one. Until then a queue is correct, and honest
    // about what it costs.
    // If the run for exactly this impact was started on the way down, it is
    // finished or nearly so, and there is nothing left to wait for. This is the
    // whole point of looking ahead: the pieces appear when the thing lands
    // rather than most of a second later.
    if (!impl_->pending && adoptGuess(name)) {
        impl_->delays.push_back({impl_->time_s, name, "foreseen",
                                 impl_->guess_error_pct, impl_->pending->cost_ms});
        repin();
        return true;
    }
    if (impl_->pending) {
        const bool ready = fractureReady();
        const auto waited_from = std::chrono::steady_clock::now();
        const std::string first = impl_->pending->name;
        finishFracture();
        if (!ready)
            impl_->delays.push_back({impl_->time_s, first, "blocked", 0.0,
                1000.0 * std::chrono::duration<double>(
                    std::chrono::steady_clock::now() - waited_from).count()});
    }
    prepare(name, window_s);
    if (impl_->pending->settled) {
        // Nothing to run. Apply it here and now -- there is no cost to hide.
        applyPending();
        impl_->pending.reset();
        return false;
    }
    // Pin what is about to happen to something. Letting it carry on means it
    // bounces off a thing that is in fact breaking, and has to be put back when
    // the answer lands: measured, an iron ball arcs half a metre into the air
    // and comes back down in the time the run takes.
    repin();
    impl_->delays.push_back({impl_->time_s, name, "held", 0.0, 0.0});
    Pending *job = impl_->pending.get();
    job->started = std::chrono::steady_clock::now();
    impl_->worker = std::async(std::launch::async, [job] { work(*job); });
    return true;
}

bool LiveWorld::fracturePending() const { return impl_->pending != nullptr; }

bool LiveWorld::fractureReady() const {
    if (!impl_->pending) return false;
    if (!impl_->worker.valid()) return true;
    return impl_->worker.wait_for(std::chrono::seconds(0)) == std::future_status::ready;
}

std::string LiveWorld::fractureSubject() const {
    return impl_->pending ? impl_->pending->name : std::string{};
}

std::size_t LiveWorld::finishFracture() {
    if (!impl_->pending) return 0;
    if (impl_->worker.valid()) impl_->worker.get();   // waits only if it has to
    // `lead_ms` here is how long it sat in the queue before a worker took it;
    // `cost_ms` is what the run itself cost. Neither was paid by the caller.
    impl_->delays.push_back({impl_->time_s, impl_->pending->name, "precomputed",
                             impl_->pending->waited_ms, impl_->pending->cost_ms});
    // Which slots the apply is about to empty, read by name rather than by
    // trusting what the island said it would drop: a body that held drops
    // nothing, and a body that came apart drops its whole island. Names are
    // unique and survive the apply, indices do not.
    std::vector<std::string> before;
    before.reserve(impl_->described.size());
    for (const LiveBodyPose &pose : impl_->described) before.push_back(pose.name);

    const std::size_t pieces = applyPending();
    impl_->pending.reset();

    // A guess holds indices into the table that has just changed shape, and
    // unlike a queued job it is speculative, so it is thrown away rather than
    // carefully followed.
    dropGuess("guess-wasted");
    restackQueue(before);

    // Whatever was waiting behind it starts now, on the same worker.
    startNextQueued();
    return pieces;
}

// The whole thing at once, which is what a caller that does not mind waiting
// wants. Identical to what this always did.
std::size_t LiveWorld::fracture(const std::string &name, double window_s) {
    // A run may already be going for this very impact, started on the way down.
    // Take it if it fits, and if it does not, wait for it and bin it -- because
    // starting a second lattice run beside it is two at once, which nothing
    // here was built for. That was a real deadlock: the guess and the real run
    // went side by side, the answer came back wrong, and the world sat refusing
    // the same step for ever.
    if (adoptGuess(name)) {
        impl_->delays.push_back({impl_->time_s, name, "foreseen",
                                 impl_->guess_error_pct, impl_->pending->cost_ms});
        impl_->held_through.insert(name);
        const std::size_t early = applyPending();
        impl_->pending.reset();
        return early;
    }
    dropGuess("guess-wasted");
    prepare(name, window_s);
    if (!impl_->pending->settled) {
        work(*impl_->pending);
        impl_->delays.push_back({impl_->time_s, name, "blocked", 0.0,
                                 impl_->pending->cost_ms});
    }
    const std::size_t pieces = applyPending();
    impl_->pending.reset();
    return pieces;
}

LivePick LiveWorld::pick(const Vec3 &from_world_m, const Vec3 &direction,
                         double max_distance_m) const {
    LivePick out{};
    const RayHit hit = impl_->world->castRay(from_world_m, direction, max_distance_m);
    if (!hit.hit) return out;
    out.hit = true;
    out.distance_m = hit.distance_m;
    out.point_world_m = hit.point_world_m;
    if (!hit.named) return out;   // the ground: hit, but not one of the scene's
    for (std::size_t i = 0; i < impl_->body_of.size(); ++i)
        if (impl_->body_of[i] == hit.body_id) { out.name = impl_->described[i].name; break; }
    return out;
}

std::string LiveWorld::held() const {
    return impl_->holding == static_cast<std::size_t>(-1)
               ? std::string{}
               : impl_->described[impl_->holding].name;
}

// ---- heat, chemistry and gas ------------------------------------------------

double LiveWorld::hullArea(std::size_t body) const {
    const double cell = impl_->request.cell_size_m;
    const std::vector<std::uint32_t> &nodes = impl_->nodes_of[body];
    if (nodes.empty()) return 6.0 * cell * cell;
    const std::string &name = impl_->described[body].name;
    const auto cached = impl_->hull_area_of.find(name);
    if (cached != impl_->hull_area_of.end() && cached->second.first == nodes.size())
        return cached->second.second;
    // A face is open when no cell of the same body sits against it. Cells lie
    // on one grid, so their offsets differ by whole cells; rounding from the
    // first one puts a bent body back on it too.
    std::set<std::tuple<long, long, long>> at;
    const Vec3 origin = impl_->cell_offset_m[nodes.front()];
    for (const std::uint32_t node : nodes) {
        const Vec3 o = (impl_->cell_offset_m[node] - origin) / cell;
        at.insert({std::lround(o.x), std::lround(o.y), std::lround(o.z)});
    }
    std::size_t faces = 0;
    for (const auto &[x, y, z] : at)
        for (const auto &[dx, dy, dz] : {std::tuple{1L, 0L, 0L}, std::tuple{-1L, 0L, 0L},
                                         std::tuple{0L, 1L, 0L}, std::tuple{0L, -1L, 0L},
                                         std::tuple{0L, 0L, 1L}, std::tuple{0L, 0L, -1L}})
            if (!at.count({x + dx, y + dy, z + dz})) ++faces;
    const double area = static_cast<double>(faces) * cell * cell;
    impl_->hull_area_of[name] = {nodes.size(), area};
    return area;
}

std::vector<thermo::BodyShape> LiveWorld::thermoShapes() const {
    constexpr double kPi = 3.14159265358979323846;
    const double cell = impl_->request.cell_size_m;
    std::vector<thermo::BodyShape> shapes;
    shapes.reserve(impl_->described.size());
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const LiveBodyPose &body = impl_->described[i];
        const MatterBodyId id = impl_->body_of[i];
        if (!impl_->world->contains(id)) continue;
        const RigidMechanicalState state = impl_->world->mechanicalState(id);
        thermo::BodyShape shape;
        shape.name = body.name;
        shape.material = body.material;
        shape.anchored = body.anchored;
        shape.center_m = state.motion.center_of_mass_world_m;
        const Vec3 d = body.dimensions_m;
        const std::size_t cells = i < impl_->nodes_of.size() ? impl_->nodes_of[i].size() : 0;
        const double matter = static_cast<double>(cells) * cell * cell * cell;
        if (body.shape == "sphere") {
            shape.area_m2 = kPi * d.x * d.x;
            shape.volume_m3 = kPi * d.x * d.x * d.x / 6.0;
        } else if (body.shape == "box") {
            shape.area_m2 = 2.0 * (d.x * d.y + d.y * d.z + d.x * d.z);
            shape.volume_m3 = d.x * d.y * d.z;
        } else {
            shape.area_m2 = hullArea(i);
            shape.volume_m3 = matter > 0.0 ? matter : d.x * d.y * d.z;
        }
        // What it weighs now, which the network may itself have changed.
        // Scenery is static to the solver and has no mass there, so its matter
        // is counted from its cells.
        const double density = i < impl_->density_of.size() ? impl_->density_of[i] : 0.0;
        shape.mass_kg = state.mass_kg > 0.0 ? state.mass_kg : matter * density;
        const Quat q = state.motion.orientation_world;
        const Vec3 h = d * 0.5;
        const Vec3 ax = q.rotate({1.0, 0.0, 0.0}), ay = q.rotate({0.0, 1.0, 0.0}),
                   az = q.rotate({0.0, 0.0, 1.0});
        shape.half_extent_m = {std::abs(ax.x) * h.x + std::abs(ay.x) * h.y + std::abs(az.x) * h.z,
                               std::abs(ax.y) * h.x + std::abs(ay.y) * h.y + std::abs(az.y) * h.z,
                               std::abs(ax.z) * h.x + std::abs(ay.z) * h.y + std::abs(az.z) * h.z};
        shapes.push_back(std::move(shape));
    }
    return shapes;
}

thermo::ThermoWorld &LiveWorld::ensureThermo() {
    if (!impl_->thermo) impl_->thermo = std::make_unique<thermo::ThermoWorld>();
    impl_->thermo->refresh(thermoShapes(), impl_->setup->ground_y);
    return *impl_->thermo;
}

void LiveWorld::settleThermo() {
    thermo::ThermoWorld *network = impl_->thermo.get();
    if (network == nullptr || !network->active()) return;
    // Where things are changes slowly next to a step, so the heat paths are
    // worked out again every eighth accepted step -- thirty times a second at
    // the room's rate -- and whenever the body table changes.
    if (impl_->steps_taken % 8 == 0) network->refresh(thermoShapes(), impl_->setup->ground_y);
    // A body whose matter has been used up or given off weighs less, and the
    // rigid body is told, so momentum and energy are about what is really there.
    for (const auto &[name, kg] : network->massesToMirror(1.0e-3)) {
        const auto found = impl_->index_of.find(name);
        if (found == impl_->index_of.end() || impl_->described[found->second].anchored) continue;
        const MatterBodyId id = impl_->body_of[found->second];
        if (impl_->world->contains(id)) impl_->world->setMass(id, kg);
    }
}

const thermo::ThermoWorld *LiveWorld::thermo() const { return impl_->thermo.get(); }

void LiveWorld::declareThermo(const std::string &json) {
    thermo::Declarations declared = thermo::readDeclarations(json);
    thermo::ThermoWorld &network = ensureThermo();
    // A heater declared into a running world starts from now.
    for (thermo::HeaterDeclaration &heater : declared.heaters) heater.start_s += network.timeS();
    thermo::apply(network, declared);
}

unsigned LiveWorld::heat(const std::string &target, double power_w, double seconds) {
    thermo::ThermoWorld &network = ensureThermo();
    return network.heat({target, power_w, network.timeS(), seconds, "heater"});
}

void LiveWorld::setVent(const std::string &region, bool open) { ensureThermo().setVent(region, open); }

std::string LiveWorld::thermoReport(bool with_model) const {
    if (impl_->thermo) return thermo::reportJson(*impl_->thermo, with_model);
    const thermo::ThermoWorld nothing;
    return thermo::reportJson(nothing, with_model);
}

double LiveWorld::mechanicalEnergyJ() const {
    return impl_->world->mechanicalTotals(impl_->request.gravity_m_s2).mechanicalEnergy();
}

// ---- terrain and water --------------------------------------------------------

std::vector<water::BodyInWater> LiveWorld::waterBodies() {
    constexpr double kPi = 3.14159265358979323846;
    std::vector<water::BodyInWater> out;
    out.reserve(impl_->described.size());
    const double cell = impl_->request.cell_size_m;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const MatterBodyId id = impl_->body_of[i];
        if (!impl_->world->contains(id)) continue;
        const LiveBodyPose &pose = impl_->described[i];
        const RigidSnapshot snap = impl_->world->snapshot(id);
        water::BodyInWater b;
        b.index = out.size();
        b.body_id = id;
        b.name = pose.name;
        b.com_m = snap.center_of_mass_world_m;
        b.orientation = snap.orientation_world;
        b.velocity_m_s = snap.linear_velocity_m_s;
        b.angular_velocity_rad_s = snap.angular_velocity_rad_s;
        b.density_kg_m3 = i < impl_->density_of.size() ? impl_->density_of[i] : 1000.0;
        b.anchored = pose.anchored;
        b.held = i == impl_->holding;
        b.awake = impl_->world->isAwake(id);
        b.cell_m = cell;
        b.dimensions_m = pose.dimensions_m;
        const std::size_t cells = i < impl_->nodes_of.size() ? impl_->nodes_of[i].size() : 0;
        if (pose.shape == "sphere") {
            b.shape = water::BodyInWater::Shape::Sphere;
            b.volume_m3 = kPi / 6.0 * pose.dimensions_m.x * pose.dimensions_m.x * pose.dimensions_m.x;
        } else if (pose.shape == "box") {
            b.shape = water::BodyInWater::Shape::Box;
            b.volume_m3 = pose.dimensions_m.x * pose.dimensions_m.y * pose.dimensions_m.z;
            // A box authored tilted carries its tilt in its shape, not in its
            // pose: the box the water meets is the pose turned by the tilt.
            if (const auto tilt = impl_->tilt_of.find(pose.name); tilt != impl_->tilt_of.end()) {
                const Quat &p = b.orientation, &q = tilt->second;
                b.orientation = Quat{p.w * q.w - p.x * q.x - p.y * q.y - p.z * q.z,
                                     p.w * q.x + p.x * q.w + p.y * q.z - p.z * q.y,
                                     p.w * q.y - p.x * q.z + p.y * q.w + p.z * q.x,
                                     p.w * q.z + p.x * q.y - p.y * q.x + p.z * q.w};
            }
        } else {
            // A piece, a join or a cone: its cells are its matter and its
            // surface.
            b.shape = water::BodyInWater::Shape::Cells;
            auto &cached = impl_->water_cells_of[pose.name];
            if (cached.first != cells || cached.second.size() != cells) {
                cached.first = cells;
                cached.second.clear();
                cached.second.reserve(cells);
                for (const std::uint32_t node : impl_->nodes_of[i]) cached.second.push_back(impl_->cell_offset_m[node]);
            }
            b.cells_local_m = &cached.second;
            b.volume_m3 = static_cast<double>(cells) * cell * cell * cell;
        }
        b.mass_kg = b.density_kg_m3 * b.volume_m3;
        out.push_back(std::move(b));
    }
    return out;
}

const terrain::Environment *LiveWorld::environment() const { return impl_->environment.get(); }

namespace {
terrain::Environment &requireEnvironment(const std::unique_ptr<terrain::Environment> &environment) {
    if (!environment) throw std::invalid_argument("this world has no terrain: its scene declares none");
    return *environment;
}
} // namespace

terrain::EditEffect LiveWorld::dig(double ax, double az, double bx, double bz, double width_m,
                                   double depth_m) {
    return requireEnvironment(impl_->environment).dig(*impl_->world, ax, az, bx, bz, width_m, depth_m);
}

terrain::EditEffect LiveWorld::deposit(double x, double z, double radius_m, double sand_m3, double soil_m3) {
    return requireEnvironment(impl_->environment).deposit(*impl_->world, x, z, radius_m, sand_m3, soil_m3);
}

std::optional<terrain::CutBlock> LiveWorld::cut(double x, double z, int cells_x, int cells_z,
                                                double height_m, std::string *why) {
    terrain::Environment &environment = requireEnvironment(impl_->environment);
    // The block has to be something the world can build: matter here is cubic
    // cells, so every side of it is a whole number of them. Said with the
    // nearest sizes that are, rather than refused bare.
    const double cell = impl_->request.cell_size_m;
    const double column = environment.terrain().grid().dx;
    const auto whole = [&](double length) {
        const double n = length / cell;
        return std::abs(n - std::round(n)) < 1.0e-6;
    };
    if (!whole(cells_x * column) || !whole(cells_z * column)) {
        int fits = 1;
        while (fits < 64 && !whole(fits * column)) ++fits;
        if (why) {
            char text[240];
            std::snprintf(text, sizeof text,
                          "a block is a whole number of %.3g m cells on every side, and the ground's "
                          "columns are %.3g m: cut %d columns at a time (%.3g m) each way",
                          cell, column, fits, fits * column);
            *why = text;
        }
        return std::nullopt;
    }
    const double cells_tall = std::max(1.0, std::round(height_m / cell));
    return environment.cut(*impl_->world, x, z, cells_x, cells_z, cells_tall * cell, why);
}

bool LiveWorld::setDischarge(const std::string &river, double discharge_m3_s) {
    return requireEnvironment(impl_->environment).setDischarge(river, discharge_m3_s);
}

std::string LiveWorld::environmentReport(bool full) const {
    if (!impl_->environment) return "{}";
    return impl_->environment->reportJson(full);
}

std::string LiveWorld::environmentState() const {
    if (!impl_->environment) return "{}";
    return impl_->environment->stateJson();
}

std::string LiveWorld::survey(double x, double z) const {
    if (!impl_->environment) return R"({"on_the_ground":false})";
    return impl_->environment->surveyJson(x, z);
}

unsigned LiveWorld::awakeBodies() const { return impl_->world->awakeBodies(); }

} // namespace banjo::fastlattice
