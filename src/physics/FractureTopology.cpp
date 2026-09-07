#include "physics/FractureTopology.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <queue>
#include <set>
#include <stdexcept>
#include <utility>

namespace banjo {
namespace {

void require(bool condition, const char *message) {
    if (!condition)
        throw std::invalid_argument(message);
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

struct FaceRecord {
    std::vector<FractureFacetSide> sides;
};

FractureFacetSide outwardSide(const PatchDefinition &definition, std::size_t tet_id,
                              unsigned opposite, unsigned local_base) {
    const auto &tet = definition.elements[tet_id];
    FractureFacetSide side;
    side.tetrahedron = static_cast<unsigned>(tet_id);
    side.opposite_local_vertex = opposite;
    unsigned at = 0;
    for (unsigned i = 0; i < 4; ++i) {
        if (i == opposite)
            continue;
        side.original_nodes[at] = tet.nodes[i];
        side.local_nodes[at] = local_base + i;
        ++at;
    }
    const Vec3 a = definition.reference_positions_m[side.original_nodes[0]];
    const Vec3 b = definition.reference_positions_m[side.original_nodes[1]];
    const Vec3 c = definition.reference_positions_m[side.original_nodes[2]];
    const Vec3 inward = definition.reference_positions_m[tet.nodes[opposite]] - a;
    if (dot(cross(b - a, c - a), inward) > 0.) {
        std::swap(side.original_nodes[1], side.original_nodes[2]);
        std::swap(side.local_nodes[1], side.local_nodes[2]);
    }
    return side;
}

std::array<unsigned, 3> faceKey(const FractureFacetSide &side) {
    auto key = side.original_nodes;
    std::sort(key.begin(), key.end());
    return key;
}

} // namespace

FractureTopology compileFractureTopology(const PatchDefinition &definition,
                                         const FractureTopologyLimits &limits) {
    require(limits.maximum_original_nodes >= 4 && limits.maximum_original_nodes <= 4096 &&
                limits.maximum_tetrahedra > 0 && limits.maximum_tetrahedra <= 16384 &&
                limits.maximum_local_nodes >= 4 && limits.maximum_local_nodes <= 65536 &&
                limits.maximum_facets > 0 && limits.maximum_facets <= 65536,
            "Invalid fracture topology count budget");
    const std::size_t node_count = definition.reference_positions_m.size();
    const std::size_t tet_count = definition.elements.size();
    require(node_count >= 4 && node_count <= limits.maximum_original_nodes,
            "Fracture topology original-node budget exceeded");
    require(tet_count > 0 && tet_count <= limits.maximum_tetrahedra,
            "Fracture topology tetrahedron budget exceeded");
    require(tet_count <= limits.maximum_local_nodes / 4,
            "Fracture topology local-node budget exceeded");
    require(definition.fixed_components.size() == node_count,
            "Patch constraint count differs from nodes");
    require(!definition.materials.empty() && definition.materials.size() <= 64,
            "Patch material count must be 1..64");

    std::set<std::array<double, 3>> positions;
    for (const auto p : definition.reference_positions_m) {
        require(finite(p) && length(p) <= 1000., "Invalid patch reference position");
        require(positions.insert({p.x, p.y, p.z}).second,
                "Coincident source patch reference nodes");
    }
    for (const auto &material : definition.materials) {
        validateSmallStrainLaw(material.law);
        require(std::isfinite(material.density_kg_m3) && material.density_kg_m3 > 0. &&
                    material.density_kg_m3 <= 1.e9,
                "Invalid patch density");
    }

    FractureTopology out;
    out.duplicated_definition.materials = definition.materials;
    out.duplicated_definition.reference_positions_m.reserve(tet_count * 4);
    out.duplicated_definition.fixed_components.reserve(tet_count * 4);
    out.duplicated_definition.elements.reserve(tet_count);
    out.local_to_original_node.reserve(tet_count * 4);
    out.local_nodal_masses_kg.reserve(tet_count * 4);
    out.tetrahedra.reserve(tet_count);

    std::map<std::array<unsigned, 3>, FaceRecord> faces;
    std::set<std::array<unsigned, 4>> unique_tets;
    std::vector<bool> used(node_count, false);
    for (std::size_t tet_id = 0; tet_id < tet_count; ++tet_id) {
        const auto &tet = definition.elements[tet_id];
        require(tet.material < definition.materials.size(), "Unknown patch element material");
        auto sorted = tet.nodes;
        for (const unsigned node : sorted)
            require(node < node_count, "Invalid tetrahedron node index");
        std::sort(sorted.begin(), sorted.end());
        require(std::adjacent_find(sorted.begin(), sorted.end()) == sorted.end() &&
                    unique_tets.insert(sorted).second,
                "Duplicate tetrahedron or repeated node");

        const Vec3 p = definition.reference_positions_m[tet.nodes[0]];
        const Vec3 e1 = definition.reference_positions_m[tet.nodes[1]] - p;
        const Vec3 e2 = definition.reference_positions_m[tet.nodes[2]] - p;
        const Vec3 e3 = definition.reference_positions_m[tet.nodes[3]] - p;
        const double determinant = dot(e1, cross(e2, e3));
        const double scale = length(e1) * length(e2) * length(e3);
        require(std::isfinite(determinant) && determinant > std::max(1.e-24, scale * 1.e-12),
                "Tetrahedron must have positive nondegenerate volume");
        const double volume = determinant / 6.;
        const double mass = volume * definition.materials[tet.material].density_kg_m3;
        require(std::isfinite(mass) && mass > 0., "Invalid tetrahedron mass");

        const unsigned local_base = static_cast<unsigned>(out.local_to_original_node.size());
        PatchTet local_tet{{local_base, local_base + 1, local_base + 2, local_base + 3},
                           tet.material};
        out.duplicated_definition.elements.push_back(local_tet);
        for (const unsigned original : tet.nodes) {
            used[original] = true;
            out.duplicated_definition.reference_positions_m.push_back(
                definition.reference_positions_m[original]);
            out.duplicated_definition.fixed_components.push_back(
                definition.fixed_components[original]);
            out.local_to_original_node.push_back(original);
            out.local_nodal_masses_kg.push_back(mass * .25);
        }
        out.tetrahedra.push_back({volume, mass});
        out.reference_volume_m3 += volume;
        out.mass_kg += mass;

        for (unsigned opposite = 0; opposite < 4; ++opposite) {
            auto side = outwardSide(definition, tet_id, opposite, local_base);
            const auto key = faceKey(side);
            auto found = faces.find(key);
            if (found == faces.end()) {
                require(faces.size() < limits.maximum_facets,
                        "Fracture topology facet budget exceeded");
                found = faces.emplace(key, FaceRecord{}).first;
            }
            auto &record = found->second;
            require(record.sides.size() < 2, "Nonmanifold tetrahedral face");
            record.sides.push_back(side);
        }
    }
    require(std::all_of(used.begin(), used.end(), [](bool value) { return value; }),
            "Unused source patch node");
    require(faces.size() <= limits.maximum_facets, "Fracture topology facet budget exceeded");

    out.internal_facets.reserve(faces.size());
    out.original_exterior_faces.reserve(faces.size());
    for (const auto &[key, record] : faces) {
        (void)key;
        if (record.sides.size() == 1) {
            out.original_exterior_faces.push_back(record.sides.front());
            continue;
        }
        const auto &a = record.sides[0];
        const auto &b = record.sides[1];
        const Vec3 p0 = definition.reference_positions_m[a.original_nodes[0]];
        const Vec3 p1 = definition.reference_positions_m[a.original_nodes[1]];
        const Vec3 p2 = definition.reference_positions_m[a.original_nodes[2]];
        const Vec3 twice_area_normal = cross(p1 - p0, p2 - p0);
        const double twice_area = length(twice_area_normal);
        require(std::isfinite(twice_area) && twice_area > 0., "Degenerate tetrahedral face");
        const Vec3 b0 = definition.reference_positions_m[b.original_nodes[0]];
        const Vec3 b1 = definition.reference_positions_m[b.original_nodes[1]];
        const Vec3 b2 = definition.reference_positions_m[b.original_nodes[2]];
        require(dot(twice_area_normal, cross(b1 - b0, b2 - b0)) < 0.,
                "Shared face has tetrahedra on the same side");

        FractureFacetPair pair;
        pair.side_a = a;
        pair.side_b = b;
        pair.reference_normal_a = twice_area_normal / twice_area;
        pair.reference_area_m2 = .5 * twice_area;
        for (unsigned i = 0; i < 3; ++i) {
            const auto found =
                std::find(b.original_nodes.begin(), b.original_nodes.end(), a.original_nodes[i]);
            require(found != b.original_nodes.end(), "Shared facet correspondence mismatch");
            pair.side_b_index_for_side_a[i] =
                static_cast<unsigned>(found - b.original_nodes.begin());
        }
        out.internal_facets.push_back(pair);
    }
    return out;
}

FractureSeparation evaluateAcceptedSeparations(const FractureTopology &topology,
                                               const std::vector<bool> &accepted,
                                               const FractureSeparationLimits &limits) {
    require(limits.maximum_adjacency_visits > 0 && limits.maximum_adjacency_visits <= 100000000 &&
                limits.maximum_components > 0 && limits.maximum_components <= 16384 &&
                limits.maximum_newly_exposed_faces <= 65536,
            "Invalid fracture separation count budget");
    const std::size_t tet_count = topology.tetrahedra.size();
    require(tet_count <= 16384, "Supplied fracture topology tetrahedron count exceeds bound");
    require(topology.internal_facets.size() <= 65536,
            "Supplied fracture topology internal-facet count exceeds bound");
    require(tet_count > 0 && topology.duplicated_definition.elements.size() == tet_count,
            "Invalid fracture topology tetrahedra");
    require(accepted.size() == topology.internal_facets.size(),
            "Accepted separation flags differ from internal facets");

    std::vector<std::vector<unsigned>> neighbors(tet_count);
    FractureSeparation out;
    for (std::size_t i = 0; i < topology.internal_facets.size(); ++i) {
        const auto &facet = topology.internal_facets[i];
        require(facet.side_a.tetrahedron < tet_count && facet.side_b.tetrahedron < tet_count &&
                    facet.side_a.tetrahedron != facet.side_b.tetrahedron,
                "Invalid fracture facet adjacency");
        if (accepted[i]) {
            require(out.newly_exposed_faces.size() + 2 <= limits.maximum_newly_exposed_faces,
                    "Newly exposed face budget exceeded");
            out.newly_exposed_faces.push_back(facet.side_a);
            out.newly_exposed_faces.push_back(facet.side_b);
        } else {
            neighbors[facet.side_a.tetrahedron].push_back(facet.side_b.tetrahedron);
            neighbors[facet.side_b.tetrahedron].push_back(facet.side_a.tetrahedron);
        }
    }
    for (auto &row : neighbors) {
        std::sort(row.begin(), row.end());
        row.erase(std::unique(row.begin(), row.end()), row.end());
    }

    out.component_by_tetrahedron.assign(tet_count, std::numeric_limits<unsigned>::max());
    for (unsigned seed = 0; seed < tet_count; ++seed) {
        if (out.component_by_tetrahedron[seed] != std::numeric_limits<unsigned>::max())
            continue;
        require(out.components.size() < limits.maximum_components,
                "Fracture component budget exceeded");
        const unsigned component = static_cast<unsigned>(out.components.size());
        out.components.emplace_back();
        std::queue<unsigned> pending;
        pending.push(seed);
        out.component_by_tetrahedron[seed] = component;
        while (!pending.empty()) {
            const unsigned tet = pending.front();
            pending.pop();
            out.components.back().push_back(tet);
            for (const unsigned neighbor : neighbors[tet]) {
                require(out.adjacency_visits < limits.maximum_adjacency_visits,
                        "Fracture adjacency-work budget exhausted");
                ++out.adjacency_visits;
                if (out.component_by_tetrahedron[neighbor] ==
                    std::numeric_limits<unsigned>::max()) {
                    out.component_by_tetrahedron[neighbor] = component;
                    pending.push(neighbor);
                }
            }
        }
    }
    return out;
}

} // namespace banjo
