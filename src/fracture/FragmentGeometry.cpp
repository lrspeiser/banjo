#include "fracture/FragmentGeometry.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <numbers>
#include <stdexcept>
#include <unordered_set>
#include <utility>
#include <vector>

namespace banjo {
namespace {

struct GridCoordHash {
    [[nodiscard]] std::size_t operator()(const GridCoord &coord) const noexcept {
        std::uint64_t value = static_cast<std::uint32_t>(coord.x);
        value = (value * 0x9e3779b185ebca87ULL) ^ static_cast<std::uint32_t>(coord.y);
        value = (value * 0xc2b2ae3d27d4eb4fULL) ^ static_cast<std::uint32_t>(coord.z);
        value ^= value >> 33U;
        value *= 0xff51afd7ed558ccdULL;
        value ^= value >> 33U;
        return static_cast<std::size_t>(value);
    }
};

struct FaceDefinition {
    GridCoord neighbor_offset{};
    Vec3 normal{};
    std::array<Vec3, 4> corners{};
};

[[nodiscard]] const std::array<FaceDefinition, 6> &faceDefinitions() {
    static const std::array<FaceDefinition, 6> faces{{
        {{1, 0, 0}, {1.0, 0.0, 0.0},
         {{{0.5, -0.5, -0.5}, {0.5, 0.5, -0.5}, {0.5, 0.5, 0.5}, {0.5, -0.5, 0.5}}}},
        {{-1, 0, 0}, {-1.0, 0.0, 0.0},
         {{{-0.5, -0.5, 0.5}, {-0.5, 0.5, 0.5}, {-0.5, 0.5, -0.5}, {-0.5, -0.5, -0.5}}}},
        {{0, 1, 0}, {0.0, 1.0, 0.0},
         {{{-0.5, 0.5, -0.5}, {-0.5, 0.5, 0.5}, {0.5, 0.5, 0.5}, {0.5, 0.5, -0.5}}}},
        {{0, -1, 0}, {0.0, -1.0, 0.0},
         {{{-0.5, -0.5, 0.5}, {-0.5, -0.5, -0.5}, {0.5, -0.5, -0.5}, {0.5, -0.5, 0.5}}}},
        {{0, 0, 1}, {0.0, 0.0, 1.0},
         {{{-0.5, -0.5, 0.5}, {0.5, -0.5, 0.5}, {0.5, 0.5, 0.5}, {-0.5, 0.5, 0.5}}}},
        {{0, 0, -1}, {0.0, 0.0, -1.0},
         {{{0.5, -0.5, -0.5}, {-0.5, -0.5, -0.5}, {-0.5, 0.5, -0.5}, {0.5, 0.5, -0.5}}}},
    }};
    return faces;
}

[[nodiscard]] std::vector<Vec3> sampleCollisionPoints(
    const FragmentSurfaceMesh &mesh,
    std::span<const Vec3> voxel_centers_local_m,
    double voxel_size_m,
    std::size_t maximum_points) {
    if (voxel_centers_local_m.empty() || mesh.vertices.empty()) {
        throw std::invalid_argument("collision proxy requires surface geometry");
    }
    maximum_points = std::max<std::size_t>(maximum_points, 8U);

    std::vector<Vec3> points;
    points.reserve(maximum_points);

    const auto appendUnique = [&points](const Vec3 &candidate) {
        constexpr double kDuplicateToleranceSquared = 1.0e-16;
        for (const Vec3 &existing : points) {
            if (lengthSquared(existing - candidate) <= kDuplicateToleranceSquared) {
                return;
            }
        }
        points.push_back(candidate);
    };

    // Preserve extrema in many directions before taking an even sample. This keeps
    // the convex proxy close to the fractured voxel surface without introducing the
    // oversized global AABB that a simple bounding-box fallback would create.
    for (int dz = -1; dz <= 1 && points.size() < maximum_points; ++dz) {
        for (int dy = -1; dy <= 1 && points.size() < maximum_points; ++dy) {
            for (int dx = -1; dx <= 1 && points.size() < maximum_points; ++dx) {
                if (dx == 0 && dy == 0 && dz == 0) {
                    continue;
                }
                const Vec3 direction = normalized({
                    static_cast<double>(dx),
                    static_cast<double>(dy),
                    static_cast<double>(dz),
                });
                const SurfaceVertex *best = &mesh.vertices.front();
                double best_projection = dot(best->position_local_m, direction);
                for (const SurfaceVertex &vertex : mesh.vertices) {
                    const double projection = dot(vertex.position_local_m, direction);
                    if (projection > best_projection) {
                        best = &vertex;
                        best_projection = projection;
                    }
                }
                appendUnique(best->position_local_m);
            }
        }
    }

    const std::size_t remaining = maximum_points - points.size();
    if (remaining > 0U) {
        const std::size_t stride = std::max<std::size_t>(
            1U, (mesh.vertices.size() + remaining - 1U) / remaining);
        for (std::size_t index = 0;
             index < mesh.vertices.size() && points.size() < maximum_points;
             index += stride) {
            appendUnique(mesh.vertices[index].position_local_m);
        }
    }

    // Extremely small components still have a cube surface, but retain this guarded
    // fallback in case future mesh simplification removes too many distinct points.
    if (points.size() < 4U) {
        const double half = 0.5 * voxel_size_m;
        const Vec3 center = voxel_centers_local_m.front();
        for (int z = -1; z <= 1; z += 2) {
            for (int y = -1; y <= 1; y += 2) {
                for (int x = -1; x <= 1; x += 2) {
                    appendUnique(center + Vec3{
                        static_cast<double>(x) * half,
                        static_cast<double>(y) * half,
                        static_cast<double>(z) * half,
                    });
                }
            }
        }
    }
    return points;
}

[[nodiscard]] double equivalentSphereRadius(double mass_kg, double density_kg_m3) {
    if (mass_kg <= 0.0 || density_kg_m3 <= 0.0) {
        return 0.0;
    }
    const double volume_m3 = mass_kg / density_kg_m3;
    return std::cbrt(3.0 * volume_m3 / (4.0 * std::numbers::pi));
}

} // namespace

FragmentSurfaceMesh buildExposedVoxelSurface(
    const ActiveMatter &matter,
    std::span<const std::uint32_t> node_indices,
    const Vec3 &center_of_mass_world_m) {
    if (matter.asset == nullptr || node_indices.empty()) {
        throw std::invalid_argument("surface mesh requires an active material component");
    }

    std::unordered_set<GridCoord, GridCoordHash> component_grid;
    component_grid.reserve(node_indices.size() * 2U);
    for (const std::uint32_t index : node_indices) {
        if (index >= matter.nodes.size() || index >= matter.asset->nodes.size()) {
            throw std::out_of_range("surface mesh node index is invalid");
        }
        component_grid.insert(matter.asset->nodes[index].grid);
    }

    FragmentSurfaceMesh mesh;
    mesh.vertices.reserve(node_indices.size() * 12U);
    mesh.indices.reserve(node_indices.size() * 18U);
    const double voxel_size = matter.asset->recipe.voxel_size_m;

    for (const std::uint32_t node_index : node_indices) {
        const GridCoord grid = matter.asset->nodes[node_index].grid;
        const Vec3 center_local =
            matter.nodes[node_index].position_world_m - center_of_mass_world_m;

        for (const FaceDefinition &face : faceDefinitions()) {
            const GridCoord neighbor{
                grid.x + face.neighbor_offset.x,
                grid.y + face.neighbor_offset.y,
                grid.z + face.neighbor_offset.z,
            };
            if (component_grid.contains(neighbor)) {
                continue;
            }

            const std::uint32_t base = static_cast<std::uint32_t>(mesh.vertices.size());
            for (const Vec3 &corner : face.corners) {
                mesh.vertices.push_back({center_local + voxel_size * corner, face.normal});
            }
            mesh.indices.insert(mesh.indices.end(), {
                base,
                base + 1U,
                base + 2U,
                base,
                base + 2U,
                base + 3U,
            });
            ++mesh.exposed_face_count;
        }
    }

    return mesh;
}

FragmentBuildResult buildFragmentRepresentations(
    const ActiveMatter &matter,
    std::span<const FragmentComponent> components,
    const FragmentBuildSettings &settings) {
    if (matter.asset == nullptr || components.empty()) {
        throw std::invalid_argument("fragment build requires active material components");
    }
    if (settings.first_body_id == kInvalidMatterBodyId ||
        settings.maximum_rigid_fragments == 0U ||
        settings.maximum_collision_points < 8U) {
        throw std::invalid_argument("fragment build settings are invalid");
    }

    std::vector<const FragmentComponent *> sorted;
    sorted.reserve(components.size());
    for (const FragmentComponent &component : components) {
        if (!component.node_indices.empty()) {
            sorted.push_back(&component);
        }
    }
    std::sort(sorted.begin(), sorted.end(), [](const auto *left, const auto *right) {
        if (left->node_indices.size() != right->node_indices.size()) {
            return left->node_indices.size() > right->node_indices.size();
        }
        return left->node_indices.front() < right->node_indices.front();
    });

    FragmentBuildResult result;
    MatterBodyId next_body_id = settings.first_body_id;
    std::size_t rigid_count = 0U;

    for (const FragmentComponent *component : sorted) {
        const FragmentMassProperties properties =
            calculateFragmentMassProperties(matter, component->node_indices);
        result.total_mass_kg += properties.mass_kg;
        result.coarsening_kinetic_loss_j += properties.coarsening_kinetic_loss_j;
        const Vec3 linear_momentum = properties.mass_kg * properties.linear_velocity_m_s;
        result.total_linear_momentum_kg_m_s += linear_momentum;
        result.total_angular_momentum_about_origin_kg_m2_s +=
            properties.angular_momentum_kg_m2_s +
            cross(properties.center_of_mass_world_m, linear_momentum);

        const bool make_rigid =
            rigid_count < settings.maximum_rigid_fragments &&
            (component->node_indices.size() >= settings.minimum_nodes_per_rigid_fragment ||
             rigid_count == 0U);
        if (!make_rigid) {
            const double equivalent_radius = equivalentSphereRadius(
                properties.mass_kg, matter.material.density_kg_m3);
            result.debris_particles.push_back({
                properties.center_of_mass_world_m,
                properties.linear_velocity_m_s,
                properties.angular_velocity_rad_s,
                properties.mass_kg,
                std::max(0.2 * matter.asset->recipe.voxel_size_m, equivalent_radius),
                properties.inertia_world_kg_m2,
            });
            result.debris_mass_kg += properties.mass_kg;
            continue;
        }

        RigidFragmentDescription fragment;
        fragment.body_id = next_body_id++;
        fragment.mass_properties = properties;
        fragment.voxel_size_m = matter.asset->recipe.voxel_size_m;
        fragment.friction = settings.friction;
        fragment.restitution = settings.restitution;
        fragment.source_node_count = component->node_indices.size();
        fragment.voxel_centers_local_m.reserve(component->node_indices.size());
        for (const std::uint32_t node_index : component->node_indices) {
            fragment.voxel_centers_local_m.push_back(
                matter.nodes[node_index].position_world_m - properties.center_of_mass_world_m);
        }
        fragment.surface_mesh = buildExposedVoxelSurface(
            matter, component->node_indices, properties.center_of_mass_world_m);
        fragment.collision_points_local_m = sampleCollisionPoints(
            fragment.surface_mesh,
            fragment.voxel_centers_local_m,
            fragment.voxel_size_m,
            settings.maximum_collision_points);

        result.rigid_fragment_mass_kg += properties.mass_kg;
        result.rigid_fragments.push_back(std::move(fragment));
        ++rigid_count;
    }

    return result;
}

} // namespace banjo
