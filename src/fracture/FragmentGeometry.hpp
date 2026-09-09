#pragma once

#include "core/Math.hpp"
#include "core/Types.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentMassProperties.hpp"

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace banjo {

struct SurfaceVertex {
    Vec3 position_local_m{};
    Vec3 normal_local{};
};

struct FragmentSurfaceMesh {
    std::vector<SurfaceVertex> vertices;
    std::vector<std::uint32_t> indices;
    std::size_t exposed_face_count{};
};

// The collision shape a fragment gets. None means the convex hull of its cells,
// which is the honest surface of a broken piece. Sphere and Box are the shape
// the object was authored as, used only while it is still whole: a ball made of
// five cells across hulls into a lump with a flat bottom, and a flat-bottomed
// lump slides where a ball would roll. Measured: the same 100 mm ball turns 0.0
// degrees at five cells across and 24.4 at ten, because of the hull and not
// because of anything about torque.
enum class FragmentPrimitive : std::uint8_t { None, Sphere, Box };

struct RigidFragmentDescription {
    MatterBodyId body_id{kInvalidMatterBodyId};
    FragmentMassProperties mass_properties{};
    FragmentSurfaceMesh surface_mesh{};
    std::vector<Vec3> collision_points_local_m;
    std::vector<Vec3> voxel_centers_local_m;
    double voxel_size_m{};
    double friction{0.35};
    double restitution{0.08};
    std::size_t source_node_count{};
    // Set only where the fragment is exactly one whole authored object. Box
    // uses all three extents; Sphere uses x as the diameter.
    FragmentPrimitive primitive{FragmentPrimitive::None};
    Vec3 primitive_dimensions_m{};
};

struct DebrisParticleDescription {
    Vec3 position_world_m{};
    Vec3 velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
    double mass_kg{};
    double radius_m{};
    Mat3 inertia_world_kg_m2{};
};

struct FragmentBuildSettings {
    MatterBodyId first_body_id{1000};
    std::size_t maximum_rigid_fragments{96};
    std::size_t minimum_nodes_per_rigid_fragment{3};
    std::size_t maximum_collision_points{192};
    double friction{0.35};
    double restitution{0.08};
};

struct FragmentBuildResult {
    std::vector<RigidFragmentDescription> rigid_fragments;
    std::vector<DebrisParticleDescription> debris_particles;
    double total_mass_kg{};
    double rigid_fragment_mass_kg{};
    double debris_mass_kg{};
    Vec3 total_linear_momentum_kg_m_s{};
    Vec3 total_angular_momentum_about_origin_kg_m2_s{};
    double coarsening_kinetic_loss_j{};
};

[[nodiscard]] FragmentSurfaceMesh buildExposedVoxelSurface(
    const ActiveMatter &matter,
    std::span<const std::uint32_t> node_indices,
    const Vec3 &center_of_mass_world_m);

[[nodiscard]] FragmentBuildResult buildFragmentRepresentations(
    const ActiveMatter &matter,
    std::span<const FragmentComponent> components,
    const FragmentBuildSettings &settings = {});

} // namespace banjo
