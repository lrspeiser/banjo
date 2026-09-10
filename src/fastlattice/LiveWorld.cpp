#include "fastlattice/LiveWorld.hpp"

#include "core/Plane.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fastlattice/Refracture.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "rigid/JoltWorld.hpp"

#include <algorithm>
#include <stdexcept>
#include <thread>
#include <unordered_map>

namespace banjo::fastlattice {
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
};

LiveWorld::LiveWorld() : impl_(std::make_unique<Impl>()) {}
LiveWorld::~LiveWorld() = default;

std::unique_ptr<LiveWorld> LiveWorld::open(const TileImpactRequest &request) {
    std::unique_ptr<LiveWorld> live(new LiveWorld());
    Impl &impl = *live->impl_;
    impl.request = request;
    impl.setup = buildTileImpactSetup(request);
    const TileImpactSetup &setup = *impl.setup;
    const TileImpactRequest &r = impl.request;

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
        impl.nodes_of.emplace_back(component.node_indices.begin(), component.node_indices.end());
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
    impl.world->addSupportSurface({
        .frame = makeSupportPlane({0.0, setup.ground_y, 0.0}, {0.0, 1.0, 0.0}),
        .material = setup.ground_material,
        .half_length_tangent_m = 4.0,
        .half_length_bitangent_m = 4.0,
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

void LiveWorld::step(double dt_s) {
    if (!(dt_s > 0.0)) throw std::invalid_argument("a live step needs a positive dt");
    impl_->world->step(dt_s);
    // Re-assert the hold after the step rather than pinning with a constraint.
    // A world-fixed constraint auto-detects its anchor from where the body is
    // when it is made, so it drags a moved body straight back; a kinematic hold
    // has no such memory and lets a dragged object still push what it meets.
    if (impl_->holding != static_cast<std::size_t>(-1)) {
        const MatterBodyId id = impl_->body_of[impl_->holding];
        RigidSnapshot state = impl_->world->snapshot(id);
        state.center_of_mass_world_m = impl_->held_at;
        state.orientation_world = impl_->held_facing;
        state.linear_velocity_m_s = {};
        state.angular_velocity_rad_s = {};
        impl_->world->applyRigidState(id, state);
    }
    // Every contact of the step just taken, judged against what the struck
    // object can take. Draining also keeps the collector's queue from growing
    // for the life of the world.
    impl_->last_impacts.clear();
    std::unordered_map<MatterBodyId, std::size_t> index_of_body;
    for (std::size_t i = 0; i < impl_->body_of.size(); ++i)
        index_of_body.emplace(impl_->body_of[i], i);
    for (const ImpactEvent &event : impl_->world->drainImpacts()) {
        const auto a = index_of_body.find(event.body_a);
        const auto b = index_of_body.find(event.body_b);
        const bool a_known = a != index_of_body.end();
        const bool b_known = b != index_of_body.end();
        if (!a_known && !b_known) continue;
        // Judge both sides: a glass pin struck by an iron ball and the ball
        // struck by the pin are two different questions with two answers.
        const std::size_t pair[2] = {a_known ? a->second : b->second,
                                     b_known ? b->second : a->second};
        for (int which = 0; which < 2; ++which) {
            const std::size_t struck = pair[which];
            const std::size_t other = pair[1 - which];
            const bool other_known = which == 0 ? b_known : a_known;
            if (which == 1 && !(a_known && b_known)) break;
            if (impl_->described[struck].anchored) continue;
            const double other_impedance =
                other_known && other != struck ? impl_->impedance_of[other]
                                               : impl_->ground_impedance;
            const RefractureAdmission admission = admitRefracture(
                impl_->limits_of[struck], other_impedance,
                event.closing_speed_m_s, event.available_normal_energy_j);
            LiveImpact impact{};
            impact.struck = impl_->described[struck].name;
            impact.by = other_known && other != struck ? impl_->described[other].name
                                                       : std::string("the ground");
            impact.closing_speed_m_s = event.closing_speed_m_s;
            impact.threshold_speed_m_s = admission.threshold_speed_m_s;
            impact.energy_j = event.available_normal_energy_j;
            impact.would_break = admission.admitted();
            impl_->last_impacts.push_back(std::move(impact));
        }
    }
    impl_->time_s += dt_s;
}

double LiveWorld::time_s() const { return impl_->time_s; }
std::size_t LiveWorld::bodies() const { return impl_->described.size(); }

std::vector<LiveBodyPose> LiveWorld::poses() const {
    std::vector<LiveBodyPose> out = impl_->described;
    for (std::size_t i = 0; i < out.size(); ++i) {
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
}

void LiveWorld::release() {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    // Nothing to undo: the hold was only the pose being re-asserted, so simply
    // not asserting it hands the object back to gravity, from rest.
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

std::string LiveWorld::held() const {
    return impl_->holding == static_cast<std::size_t>(-1)
               ? std::string{}
               : impl_->described[impl_->holding].name;
}

} // namespace banjo::fastlattice
