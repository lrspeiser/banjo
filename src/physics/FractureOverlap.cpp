#include "physics/FractureOverlap.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

void require(bool condition, const char *message) {
    if (!condition)
        throw std::invalid_argument(message);
}

bool finite(Vec3 p) {
    return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
}

struct Tet {
    std::array<Vec3, 4> p;
    Vec3 minimum;
    Vec3 maximum;
};

double component(Vec3 p, unsigned axis) {
    return axis == 0 ? p.x : (axis == 1 ? p.y : p.z);
}

double aabbGap(const Tet &a, const Tet &b) {
    double result = -std::numeric_limits<double>::infinity();
    for (unsigned i = 0; i < 3; ++i) {
        result = std::max(result, std::max(component(b.minimum, i) - component(a.maximum, i),
                                           component(a.minimum, i) - component(b.maximum, i)));
    }
    return result;
}

bool testAxis(const Tet &a, const Tet &b, Vec3 raw, double relative_scale,
              FractureOverlapResult &result, const FractureOverlapLimits &limits,
              double &pair_measure) {
    const double magnitude = length(raw);
    require(std::isfinite(magnitude), "Nonfinite SAT axis");
    if (magnitude <= relative_scale * 1.e-12)
        return true;
    if (result.sat_axes >= limits.maximum_sat_axes) {
        result.resolved = false;
        return false;
    }
    ++result.sat_axes;
    const Vec3 axis = raw / magnitude;
    double amin = dot(a.p[0], axis), amax = amin;
    double bmin = dot(b.p[0], axis), bmax = bmin;
    for (unsigned i = 1; i < 4; ++i) {
        const double ap = dot(a.p[i], axis);
        const double bp = dot(b.p[i], axis);
        require(std::isfinite(ap) && std::isfinite(bp), "Nonfinite SAT projection");
        amin = std::min(amin, ap);
        amax = std::max(amax, ap);
        bmin = std::min(bmin, bp);
        bmax = std::max(bmax, bp);
    }
    pair_measure = std::max(pair_measure, std::max(bmin - amax, amin - bmax));
    return true;
}

bool sat(const Tet &a, const Tet &b, FractureOverlapResult &result,
         const FractureOverlapLimits &limits, double &measure) {
    static constexpr std::array<std::array<unsigned, 3>, 4> faces = {
        {{{1, 2, 3}}, {{0, 3, 2}}, {{0, 1, 3}}, {{0, 2, 1}}}};
    static constexpr std::array<std::array<unsigned, 2>, 6> edges = {
        {{{0, 1}}, {{0, 2}}, {{0, 3}}, {{1, 2}}, {{1, 3}}, {{2, 3}}}};
    measure = -std::numeric_limits<double>::infinity();
    for (const Tet *tet : {&a, &b}) {
        for (const auto &f : faces) {
            const Vec3 e0 = tet->p[f[1]] - tet->p[f[0]];
            const Vec3 e1 = tet->p[f[2]] - tet->p[f[0]];
            if (!testAxis(a, b, cross(e0, e1), length(e0) * length(e1), result, limits,
                          measure))
                return false;
        }
    }
    for (const auto &ea : edges) {
        const Vec3 av = a.p[ea[1]] - a.p[ea[0]];
        for (const auto &eb : edges) {
            const Vec3 bv = b.p[eb[1]] - b.p[eb[0]];
            if (!testAxis(a, b, cross(av, bv), length(av) * length(bv), result, limits,
                          measure))
                return false;
        }
    }
    require(std::isfinite(measure), "Tetrahedra have no valid SAT axis");
    return true;
}

} // namespace

FractureOverlapResult detectFractureOverlap(const FractureTopology &topology,
                                            const std::vector<Vec3> &positions,
                                            const FractureSeparation &separation,
                                            const FractureOverlapLimits &limits) {
    require(std::isfinite(limits.penetration_tolerance_m) &&
                limits.penetration_tolerance_m >= 0. && limits.penetration_tolerance_m <= 1.,
            "Invalid fracture overlap tolerance");
    require(limits.maximum_tetrahedron_pairs > 0 &&
                limits.maximum_tetrahedron_pairs <= 100000000 && limits.maximum_sat_axes > 0 &&
                limits.maximum_sat_axes <= 4000000000ULL,
            "Invalid fracture overlap work cap");
    const auto &definition = topology.duplicated_definition;
    const std::size_t count = topology.tetrahedra.size();
    require(count > 0 && count <= 16384 && definition.elements.size() == count &&
                definition.reference_positions_m.size() <= 65536 &&
                positions.size() == definition.reference_positions_m.size(),
            "Fracture overlap geometry size mismatch");
    require(!separation.components.empty() && separation.components.size() <= 16384,
            "Fracture separation component count exceeds bound");
    require(separation.component_by_tetrahedron.size() == count,
            "Fracture separation component map size mismatch");

    std::vector<unsigned> membership(count, std::numeric_limits<unsigned>::max());
    for (unsigned component_id = 0; component_id < separation.components.size(); ++component_id) {
        for (unsigned tet_id : separation.components[component_id]) {
            require(tet_id < count && membership[tet_id] == std::numeric_limits<unsigned>::max(),
                    "Invalid fracture separation component membership");
            membership[tet_id] = component_id;
        }
    }
    for (std::size_t i = 0; i < count; ++i)
        require(membership[i] != std::numeric_limits<unsigned>::max() &&
                    membership[i] == separation.component_by_tetrahedron[i],
                "Inconsistent fracture separation component map");

    std::vector<Tet> tets;
    tets.reserve(count);
    for (const auto &element : definition.elements) {
        Tet tet;
        for (unsigned i = 0; i < 4; ++i) {
            require(element.nodes[i] < positions.size(), "Invalid tetrahedron node index");
            tet.p[i] = positions[element.nodes[i]];
            require(finite(tet.p[i]) && length(tet.p[i]) <= 1000.,
                    "Invalid current fracture position");
        }
        const Vec3 e1 = tet.p[1] - tet.p[0];
        const Vec3 e2 = tet.p[2] - tet.p[0];
        const Vec3 e3 = tet.p[3] - tet.p[0];
        const double determinant = dot(e1, cross(e2, e3));
        const double scale = length(e1) * length(e2) * length(e3);
        require(std::isfinite(determinant) && determinant > std::max(1.e-24, scale * 1.e-12),
                "Current tetrahedron must have positive nondegenerate volume");
        tet.minimum = tet.maximum = tet.p[0];
        for (unsigned i = 1; i < 4; ++i) {
            tet.minimum.x = std::min(tet.minimum.x, tet.p[i].x);
            tet.minimum.y = std::min(tet.minimum.y, tet.p[i].y);
            tet.minimum.z = std::min(tet.minimum.z, tet.p[i].z);
            tet.maximum.x = std::max(tet.maximum.x, tet.p[i].x);
            tet.maximum.y = std::max(tet.maximum.y, tet.p[i].y);
            tet.maximum.z = std::max(tet.maximum.z, tet.p[i].z);
        }
        tets.push_back(tet);
    }

    FractureOverlapResult out;
    auto record = [&](double measure, unsigned a, unsigned b) {
        if (measure < out.minimum_signed_separation_m) {
            out.minimum_signed_separation_m = measure;
            out.tetrahedron_a = a;
            out.tetrahedron_b = b;
        }
        if (measure < -limits.penetration_tolerance_m)
            out.interpenetrating = true;
    };
    for (std::size_t component_a = 0; component_a < separation.components.size(); ++component_a) {
        for (std::size_t component_b = component_a + 1;
             component_b < separation.components.size(); ++component_b) {
            for (unsigned first : separation.components[component_a]) {
                for (unsigned second : separation.components[component_b]) {
                    const unsigned a = std::min(first, second);
                    const unsigned b = std::max(first, second);
                    if (out.tetrahedron_pairs >= limits.maximum_tetrahedron_pairs) {
                        out.resolved = false;
                        return out;
                    }
                    ++out.tetrahedron_pairs;
                    const double broad_gap = aabbGap(tets[a], tets[b]);
                    require(std::isfinite(broad_gap), "Nonfinite fracture overlap AABB gap");
                    if (broad_gap > 0.) {
                        record(broad_gap, a, b);
                        continue;
                    }
                    ++out.broad_phase_candidates;
                    double measure = 0.;
                    if (!sat(tets[a], tets[b], out, limits, measure))
                        return out;
                    record(measure, a, b);
                }
            }
        }
    }
    return out;
}

} // namespace banjo
