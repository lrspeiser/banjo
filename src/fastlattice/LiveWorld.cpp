#include "fastlattice/LiveWorld.hpp"

#include "core/Plane.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticePhysics.hpp"
#include "fastlattice/Refracture.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "material/MaterialCompiler.hpp"
#include "rigid/JoltWorld.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <thread>
#include <set>
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
    std::vector<LiveImpact> last_impacts;
    // For each body the last step would have broken, the body that hit it, or
    // npos for the ground. An island built without the thing that struck it is
    // a free-flying object with no stress in it, which breaks nothing.
    std::unordered_map<std::size_t, std::size_t> partner_of;
    bool stepped_back{};
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
            definition->density_kg_m3, definition->young_modulus_pa));
        impl.impedance_of.push_back(
            acousticImpedance(definition->density_kg_m3, definition->young_modulus_pa));
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

    const auto clampCapacity = [](std::size_t value, unsigned low, unsigned high) {
        return static_cast<unsigned>(std::clamp<std::size_t>(value, low, high));
    };
    impl.world = std::make_unique<JoltWorld>(
        std::clamp(std::thread::hardware_concurrency(), 1U, 64U),
        RigidContactCapacity{clampCapacity(64U * components.size(), 16384U, 262144U),
                             clampCapacity(128U * components.size(), 8192U, 65536U)});
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
    constexpr double kLiveGroundHalfSpanM = 200.0;
    impl.world->addSupportSurface({
        .frame = makeSupportPlane({0.0, setup.ground_y, 0.0}, {0.0, 1.0, 0.0}),
        .material = setup.ground_material,
        .half_length_tangent_m = kLiveGroundHalfSpanM,
        .half_length_bitangent_m = kLiveGroundHalfSpanM,
        .thickness_m = 0.5,
    });
    MatterBodyId next_static = 900;
    for (const StaticBox &ledge : setup.ledges)
        impl.world->addBox({.body_id = next_static++, .dimensions_m = ledge.dimensions_m,
                            .material = setup.ground_material,
                            .state = {.center_of_mass_world_m = ledge.center_m}, .fixed = true});
    impl.world->addFragments(build.rigid_fragments);

    for (std::size_t i = 0; i < impl.described.size(); ++i)
        impl.index_of.emplace(impl.described[i].name, i);
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
            const double other_impedance = both && other != struck
                                               ? impl_->impedance_of[other]
                                               : impl_->ground_impedance;
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
            impact.would_break = admission.admitted();
            if (impact.would_break) {
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
    for (const std::string &name : breaking_now)
        if (impl_->held_through.count(name) == 0) any_would_break = true;
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
    const auto holdStill = [&]() {
        if (impl_->holding == static_cast<std::size_t>(-1)) return;
        const MatterBodyId id = impl_->body_of[impl_->holding];
        RigidSnapshot state = impl_->world->snapshot(id);
        state.center_of_mass_world_m = impl_->held_at;
        state.orientation_world = impl_->held_facing;
        state.linear_velocity_m_s = {};
        state.angular_velocity_rad_s = {};
        impl_->world->applyRigidState(id, state);
    };

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
    // runReversibleTrial caps out at 256 bodies. Past that the step is taken
    // straight; impacts are still reported, but they describe a collision that
    // has already been resolved, so fracture() will find nothing left to break.
    impl_->stepped_back = false;
    impl_->last_dt_s = dt_s;
    if (impl_->body_of.size() + 8 <= 250) {
        const bool committed = impl_->world->runReversibleTrial([&]() {
            impl_->world->step(dt_s);
            holdStill();
            return !judgeStep();
        });
        impl_->stepped_back = !committed;
        // A step that was taken back did not happen, so the clock does not move
        // and the hold does not need re-asserting -- the world is as it was.
        if (!committed) return;
        impl_->time_s += dt_s;
        return;
    }
    impl_->world->step(dt_s);
    holdStill();
    (void)judgeStep();
    impl_->time_s += dt_s;
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
    const MatterBodyId id = impl_->body_of[impl_->holding];
    RigidSnapshot state = impl_->world->snapshot(id);
    state.center_of_mass_world_m = to_world_m;
    state.orientation_world = impl_->held_facing;
    // A held object does not accumulate speed from being carried; letting go is
    // what hands it back to gravity.
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

std::vector<LiveImpact> LiveWorld::impacts(double quiet_speed_m_s) const {
    std::vector<LiveImpact> out;
    for (const LiveImpact &impact : impl_->last_impacts)
        if (impact.closing_speed_m_s >= quiet_speed_m_s) out.push_back(impact);
    std::sort(out.begin(), out.end(), [](const LiveImpact &lhs, const LiveImpact &rhs) {
        return lhs.closing_speed_m_s > rhs.closing_speed_m_s;
    });
    return out;
}

bool LiveWorld::steppedBack() const { return impl_->stepped_back; }

std::vector<std::string> LiveWorld::breakable() const {
    std::vector<std::string> out;
    for (const LiveImpact &impact : impl_->last_impacts) {
        if (!impact.would_break) continue;
        if (impl_->held_through.count(impact.struck)) continue;
        // Gone: it broke, and what it became carries different names.
        if (impl_->index_of.find(impact.struck) == impl_->index_of.end()) continue;
        if (std::find(out.begin(), out.end(), impact.struck) == out.end())
            out.push_back(impact.struck);
    }
    return out;
}

void LiveWorld::declineBreak(const std::string &name) {
    // The same record fracture() keeps, without the lattice run: this body has
    // had its chance at this contact.
    impl_->held_through.insert(name);
}

std::size_t LiveWorld::fracture(const std::string &name, double window_s) {
    // Whatever happens below, this object has now had its chance at this
    // contact. Recording that here rather than at each of the five ways out is
    // what stops one of them being forgotten and deadlocking the world.
    impl_->held_through.insert(name);
    const auto found = impl_->index_of.find(name);
    if (found == impl_->index_of.end()) return 0;
    const std::size_t which = found->second;
    // Anchored scenery is the world. Breaking the floor is a different feature.
    if (impl_->described[which].anchored) return 1;
    if (impl_->holding == which) return 1;   // it is in a hand, not in a collision
    const TileImpactSetup &setup = *impl_->setup;
    // Whatever struck it goes into the island too. A body on its own, entered
    // after the contact, is a free-flying object with a uniform velocity and no
    // stress anywhere in it: it cannot break however hard it was hit. Both
    // bodies are cut from the same parent lattice, so the island is simply the
    // union of their cells, and running it resolves the collision through the
    // failure criterion rather than through Jolt's contact solver.
    std::vector<std::size_t> island_bodies{which};
    {
        const auto partner = impl_->partner_of.find(which);
        if (partner != impl_->partner_of.end() &&
            partner->second != static_cast<std::size_t>(-1) &&
            partner->second < impl_->described.size() &&
            !impl_->described[partner->second].anchored &&
            partner->second != impl_->holding)
            island_bodies.push_back(partner->second);
    }
    for (const std::size_t body : island_bodies)
        if (!impl_->world->contains(impl_->body_of[body])) return 0;
    const MatterBodyId old_body = impl_->body_of[which];
    const RigidSnapshot snap = impl_->world->snapshot(old_body);

    // Every cell of every body in the island, in parent numbering. Each body's
    // cells are placed by ITS own rigid pose, which is what buildFragmentLattice
    // does for one body -- so the offsets are rewritten here into the frame the
    // island will be built in, one body at a time.
    std::vector<std::uint32_t> island_nodes;
    std::unordered_map<std::uint32_t, std::size_t> body_of_node;
    std::unordered_map<std::size_t, RigidSnapshot> poses_before;
    for (const std::size_t body : island_bodies) {
        const RigidSnapshot pose = impl_->world->snapshot(impl_->body_of[body]);
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
    if (lift > 0.5 * impl_->request.cell_size_m) return 1;

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
    const RunStatus status = backend->run(control);
    backend->download(island_state, parked);
    writeBackLatticeState(island_state, island.schedule, island.matter);
    // The permanent set the run left behind: bond lengths the material will not
    // give back. This is a dent. It is carried out of the island and into the
    // parent's own record, so the next hit starts from the shape this one left
    // rather than from the shape it was authored as.
    double dent_m = 0.0;
    for (std::size_t k = 0; k < island_state.bond_count; ++k) {
        const std::uint32_t o = island.schedule.bond_order[k];
        const std::uint32_t parent_bond = island.parent_bond.empty()
                                              ? static_cast<std::uint32_t>(o)
                                              : island.parent_bond[o];
        if (parent_bond < impl_->plastic_extension_m.size()) {
            impl_->plastic_extension_m[parent_bond] = island_state.plastic_extension[k];
            impl_->plastic_strain_m[parent_bond] = island_state.plastic_strain[k];
        }
        dent_m = std::max(dent_m, std::abs(island_state.plastic_extension[k]));
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
    // The bar is a tenth of a cell. Below that the deformation is not visible
    // at the resolution the body is drawn at, and rebuilding would turn every
    // authored sphere into a hull the first time it landed hard.
    const bool dented = dent_m > 0.1 * impl_->request.cell_size_m;
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
    for (const std::size_t body : island_bodies)
        if (!impl_->nodes_of[body].empty()) {
            const std::uint32_t part = setup.part_of_node[impl_->nodes_of[body].front()];
            if (part < parent_of_part.size()) parent_of_part[part] = impl_->described[body];
        }
    // Read now, while the struck body is still in nodes_of. The drop loop below
    // erases it, and reading afterwards indexed off the end of the shortened
    // vector: the answer matched no piece, so a plate that had just come apart
    // into eight was reported as having held.
    const std::uint32_t asked_part =
        impl_->nodes_of[which].empty() ? 0 : setup.part_of_node[impl_->nodes_of[which].front()];

    // Drop every body in the island and append what they became. A piece is a
    // hull: its cells ARE its surface now, so no authored primitive fits.
    std::vector<std::size_t> going = island_bodies;
    std::sort(going.begin(), going.end(), std::greater<std::size_t>());
    for (const std::size_t body : going) {
        const auto drop = [&](auto &vector) {
            vector.erase(vector.begin() + static_cast<std::ptrdiff_t>(body));
        };
        drop(impl_->described); drop(impl_->body_of); drop(impl_->nodes_of);
        drop(impl_->limits_of); drop(impl_->impedance_of);
        if (impl_->holding != static_cast<std::size_t>(-1) && impl_->holding > body) --impl_->holding;
    }

    // What was asked about is `asked_part`, taken above. The island may hold the
    // thing that struck it, and that thing may have come apart too, so counting
    // every component would answer a question nobody asked.
    std::size_t made = 0, of_asked = 0, fragment_index = 0;
    for (const auto &component : island_components) {
        if (fragment_index >= rebuilt.rigid_fragments.size()) break;
        const RigidFragmentDescription &fragment = rebuilt.rigid_fragments[fragment_index];
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
        const LiveBodyPose &parent = parent_of_part[dominant];
        const MaterialDefinition &material = dominant < setup.part_definitions.size()
                                                 ? setup.part_definitions[dominant]
                                                 : setup.tile_material;
        LiveBodyPose piece{};
        // A piece that is still all of its parent kept its parent; only a piece
        // that is part of one is numbered.
        const bool whole_parent = counted[dominant] == component.node_indices.size() &&
                                  parent_of_part[dominant].name.size() > 0 &&
                                  component.node_indices.size() ==
                                      impl_->cellsOfPart(dominant);
        piece.name = whole_parent ? parent.name
                                  : parent.name + " piece " + std::to_string(++made);
        piece.material = parent.material;
        if (dominant == asked_part) ++of_asked;
        piece.shape = "hull";
        piece.color_rgba = parent.color_rgba;
        impl_->limits_of.push_back(fragmentFractureLimits(
            setup.matter, parent_nodes, material.density_kg_m3, material.young_modulus_pa));
        impl_->impedance_of.push_back(
            acousticImpedance(material.density_kg_m3, material.young_modulus_pa));
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
    // It broke, so the name it held under is gone and its pieces are new ones
    // that have never been tried. A body that only BENT keeps its name, and
    // must keep its place in the already-answered set with it -- otherwise the
    // same contact is offered again on the next step, dents it again, and the
    // world spends itself deforming one object for ever.
    if (impl_->index_of.find(name) == impl_->index_of.end()) impl_->held_through.erase(name);
    return of_asked;
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

} // namespace banjo::fastlattice
