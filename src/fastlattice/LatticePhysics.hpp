#pragma once

// Shared device/host physics for the fast explicit lattice lane.
//
// Every function here is the CPU lane's physics re-expressed one element at a
// time, so that the CPU fallback (CpuLatticeBackend.cpp) and the CUDA kernel
// (CudaLatticeBackend.cu) execute the same code and can be compared bit for
// bit. Sources, statement by statement:
//   - fracture/BondFailure.cpp:     nonlocal Green-Lagrange node strain, its
//                                   resolution along the bond, the damage ramp,
//                                   the removal rule and the removed energy.
//   - fracture/BrittleBondSolver.cpp: XPBD bond solve, support projection and
//                                   velocity response, radial bond damping.
//   - physics/SphereMaterialContact.cpp: node/sphere impulses and corrections.
// Nothing here changes a law or a tolerance. What differs from the CPU lane is
// scheduling only: bonds are swept in a graph-colouring order instead of index
// order (a different Gauss-Seidel permutation, see docs/fast-gpu-checkpoint.md).
//
// Real = double reproduces the CPU arithmetic (absolute positions, same
// operation order). Real = float is the fast path: positions are carried as
// displacements from the reference configuration and the strain is formed from
// F - I directly, so the criterion keeps ~1e-7 relative precision where a naive
// float port would lose it to cancellation.

#include <cmath>
#include <cstdint>

#if defined(__CUDACC__)
#define BANJO_HD __host__ __device__ __forceinline__
#else
#define BANJO_HD inline
#endif

namespace banjo::fastlattice {

// ---------------------------------------------------------------------------
// Small vector algebra (same expression order as core/Math.hpp).
// ---------------------------------------------------------------------------
template <typename Real>
struct V3 {
    Real x, y, z;
};

template <typename Real> BANJO_HD V3<Real> v3(Real x, Real y, Real z) { return {x, y, z}; }
template <typename Real> BANJO_HD V3<Real> operator+(V3<Real> a, V3<Real> b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
template <typename Real> BANJO_HD V3<Real> operator-(V3<Real> a, V3<Real> b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
template <typename Real> BANJO_HD V3<Real> operator-(V3<Real> a) { return {-a.x, -a.y, -a.z}; }
template <typename Real> BANJO_HD V3<Real> operator*(V3<Real> a, Real s) { return {a.x * s, a.y * s, a.z * s}; }
template <typename Real> BANJO_HD V3<Real> operator*(Real s, V3<Real> a) { return {a.x * s, a.y * s, a.z * s}; }
template <typename Real> BANJO_HD V3<Real> operator/(V3<Real> a, Real s) { return {a.x / s, a.y / s, a.z / s}; }
template <typename Real> BANJO_HD Real dot(V3<Real> a, V3<Real> b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
template <typename Real> BANJO_HD V3<Real> cross(V3<Real> a, V3<Real> b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
template <typename Real> BANJO_HD Real length2(V3<Real> a) { return dot(a, a); }

template <typename Real> BANJO_HD Real sqrtR(Real x) {
#if defined(__CUDA_ARCH__)
    return sqrt(x);
#else
    return std::sqrt(x);
#endif
}
template <typename Real> BANJO_HD Real absR(Real x) { return x < Real(0) ? -x : x; }
template <typename Real> BANJO_HD Real maxR(Real a, Real b) { return (a < b) ? b : a; }
template <typename Real> BANJO_HD Real minR(Real a, Real b) { return (b < a) ? b : a; }
template <typename Real> BANJO_HD bool finiteR(Real x) {
#if defined(__CUDA_ARCH__)
    return isfinite(x);
#else
    return std::isfinite(x);
#endif
}
template <typename Real> BANJO_HD Real length(V3<Real> a) { return sqrtR(length2(a)); }
// core/Math.hpp normalized(): fallback (1,0,0) below 1e-12.
template <typename Real> BANJO_HD V3<Real> normalized(V3<Real> a) {
    const Real magnitude = length(a);
    return magnitude > Real(1.0e-12) ? a / magnitude : v3<Real>(1, 0, 0);
}
template <typename Real> BANJO_HD V3<Real> load3(const Real *p, std::uint32_t i) {
    return {p[3 * i], p[3 * i + 1], p[3 * i + 2]};
}
template <typename Real> BANJO_HD void store3(Real *p, std::uint32_t i, V3<Real> v) {
    p[3 * i] = v.x;
    p[3 * i + 1] = v.y;
    p[3 * i + 2] = v.z;
}

// ---------------------------------------------------------------------------
// Scene description carried into every step.
// ---------------------------------------------------------------------------
constexpr unsigned kMaxSupportPlanes = 2;
constexpr unsigned kMaxFootprints = 4;
constexpr unsigned kMaxCandidatesPerBlock = 1024;
constexpr std::uint32_t kNoBond = 0xffffffffU;

#if defined(__CUDACC__)
#define BANJO_UNROLL _Pragma("unroll 4")
#else
#define BANJO_UNROLL
#endif

template <typename Real>
struct Footprint {
    // Rectangle on the plane, offset from the plane point along tangent and
    // bitangent. center 0 / half infinity reproduces core/Plane.hpp's
    // insideSupportFootprint exactly.
    Real center_t, center_b, half_t, half_b;
};

template <typename Real>
struct SupportPlane {
    V3<Real> point, normal, tangent, bitangent;
    Real restitution, static_friction, dynamic_friction;
    // Nodes are cell centres; a node is held this far above the physical
    // surface (half a cell), which is the same as BrittleBondSolver seeing a
    // plane raised by node_radius. The rigid ball uses the physical plane.
    Real node_radius;
    std::uint32_t footprint_count;
    Footprint<Real> footprints[kMaxFootprints];
};

template <typename Real>
struct SupportSet {
    std::uint32_t plane_count;
    SupportPlane<Real> planes[kMaxSupportPlanes];
};

template <typename Real>
struct SphereState {
    V3<Real> center, velocity, angular_velocity;
    Real radius, mass, inertia;
};

template <typename Real>
struct ContactSettings {
    Real static_friction, dynamic_friction, restitution, restitution_speed_threshold;
    Real node_contact_radius, contact_margin;
    // Nodes within this extra distance of the sphere are handed to the serial
    // contact pass, which then applies the exact CPU test in node order. It only
    // has to exceed how far the sphere centre can move inside one pass.
    Real prefilter_slack;
};

template <typename Real>
struct StepSettings {
    Real dt;
    V3<Real> gravity;
    std::uint32_t constraint_iterations;
    // 1 - exp(-bond_damping * dt); zero disables the radial damping sweep.
    Real damping_fraction;
    std::uint8_t sphere_enabled;
    // 1: absolute-position arithmetic in the CPU's operation order (double
    // reference). 0: displacement arithmetic (float fast path).
    std::uint8_t direct_arithmetic;
    ContactSettings<Real> contact;
    SupportSet<Real> support;
};

// All state as raw pointers; the CPU backend points into host vectors and the
// CUDA backend into device buffers. Bonds are stored in schedule order.
template <typename Real>
struct LatticeArrays {
    std::uint32_t node_count, bond_count, block_count, color_count;
    // Nodes.
    const Real *x0;             // 3N reference positions (scene frame)
    Real *u;                    // 3N displacement
    Real *u_prev;               // 3N displacement at the substep start
    Real *v;                    // 3N velocity
    const Real *inv_mass;       // N
    const Real *mass;           // N
    Real *rinv;                 // 9N cached inverse rest covariance
    std::uint8_t *node_valid;   // N  nonlocal strain is defined
    std::uint8_t *node_dirty;   // N  live neighbour set changed
    Real *strain;               // 6N E (xx, yy, zz, xy, xz, yz)
    Real *approach;             // kMaxSupportPlanes * N approach normal speeds
    std::uint8_t *engaged;      // kMaxSupportPlanes * N support engaged flags
    std::uint8_t *candidate;    // N sphere contact candidate this step
    const std::uint32_t *adj_offsets;  // N + 1
    const std::uint32_t *adj_bonds;    // schedule-order bond indices
    const std::uint32_t *node_block_begin; // block_count + 1 node ranges
    // Padded neighbour lists, k-major (index k * N + i) so a warp of
    // consecutive nodes reads consecutive addresses, in the asset's adjacency
    // order so sums accumulate in the CPU lane's order. Entries past a node's
    // degree hold kNoBond.
    std::uint32_t max_degree;
    const std::uint32_t *nbr_bond;   // max_degree * N
    const std::uint32_t *nbr_other;  // max_degree * N
    const Real *nbr_rest;            // 3 * max_degree * N, other - node
    const Real *nbr_weight;          // max_degree * N
    // Aliveness per neighbour slot, kept in step with alive[] when a bond is
    // removed, so the strain loop reads it coalesced instead of gathering.
    std::uint8_t *nbr_alive;         // max_degree * N
    const std::uint32_t *bond_slot_a; // B: slot of the bond in node a's list
    const std::uint32_t *bond_slot_b; // B: slot of the bond in node b's list
    // Diagnostic: nodes whose rest covariance the CPU's absolute determinant
    // rule accepts but the relative rule rejects (or vice versa), counted at
    // every recomputation. Written by many threads; the count is approximate
    // on the GPU (plain increments), exact on the CPU.
    std::uint32_t *degenerate_disagreements;
    // Bonds.
    const std::uint32_t *bond_a;
    const std::uint32_t *bond_b;
    const Real *rest_edge;      // 3B  x0[b] - x0[a]
    const Real *rest_length;    // B   rest_length_m of the asset
    const Real *rest_length_sq_minus; // B  |rest_edge|^2 - rest_length^2 (double-computed)
    const Real *weight;         // B   1 / |rest_edge|^2
    const Real *compliance;     // B
    const Real *threshold;      // 6B  ds, de, cs, ce, ss, se
    std::uint8_t *alive;
    Real *damage;
    std::uint8_t *failure_mode; // 0 none, 1 tension, 2 compression, 3 shear
    Real *accumulated_lambda;   // B
    Real *prev_tensile;         // B   values at the substep start
    Real *prev_compressive;
    Real *prev_shear;
    // Sweep ranges: index ((block * 2 + boundary) * color_count + color).
    const std::uint32_t *range_begin;
    const std::uint32_t *range_end;
    const std::uint32_t *bond_block_begin; // block_count + 1 bond ranges by owner
    // Sphere contact candidate lists, one ordered list per block.
    std::uint32_t *candidate_list;   // block_count * kMaxCandidatesPerBlock
    std::uint32_t *candidate_count;  // block_count
};

// Serial contact bookkeeping, written by the one thread that runs the pass.
struct ContactAccumulators {
    unsigned long long impulse_contacts;
    double impulse_to_material_x, impulse_to_material_y, impulse_to_material_z;
    double dissipated_kinetic_energy_j;
    double maximum_penetration_m;
    double maximum_position_correction_m;
    double maximum_center_shift_m; // largest sphere centre shift inside one pass
    unsigned long long candidate_overflow;
    unsigned long long ball_support_events;
};

BANJO_HD void clearContactAccumulators(ContactAccumulators &c) {
    c.impulse_contacts = 0;
    c.impulse_to_material_x = c.impulse_to_material_y = c.impulse_to_material_z = 0.0;
    c.dissipated_kinetic_energy_j = 0.0;
    c.maximum_penetration_m = 0.0;
    c.maximum_position_correction_m = 0.0;
    c.maximum_center_shift_m = 0.0;
    c.candidate_overflow = 0;
    c.ball_support_events = 0;
}

// ---------------------------------------------------------------------------
// Position helpers. Absolute positions are x0 + u; the two arithmetic modes
// differ only in where the rounding happens.
// ---------------------------------------------------------------------------
template <typename Real>
BANJO_HD V3<Real> position(const LatticeArrays<Real> &L, std::uint32_t i) {
    return load3(L.x0, i) + load3(L.u, i);
}

// Current bond vector b - a.
template <typename Real>
BANJO_HD V3<Real> bondVector(const LatticeArrays<Real> &L, std::uint32_t j, bool direct) {
    const std::uint32_t a = L.bond_a[j], b = L.bond_b[j];
    if (direct) return position(L, b) - position(L, a);
    return load3(L.rest_edge, j) + (load3(L.u, b) - load3(L.u, a));
}

// ---------------------------------------------------------------------------
// core/Math.hpp Mat3::inverse, row-major m[r*3+c].
// ---------------------------------------------------------------------------
template <typename Real>
BANJO_HD bool inverse3(const Real m[9], Real epsilon, Real out[9]) {
    const Real det = m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) +
                     m[2] * (m[3] * m[7] - m[4] * m[6]);
    if (absR(det) <= epsilon) return false;
    out[0] = (m[4] * m[8] - m[5] * m[7]) / det;
    out[1] = (m[2] * m[7] - m[1] * m[8]) / det;
    out[2] = (m[1] * m[5] - m[2] * m[4]) / det;
    out[3] = (m[5] * m[6] - m[3] * m[8]) / det;
    out[4] = (m[0] * m[8] - m[2] * m[6]) / det;
    out[5] = (m[2] * m[3] - m[0] * m[5]) / det;
    out[6] = (m[3] * m[7] - m[4] * m[6]) / det;
    out[7] = (m[1] * m[6] - m[0] * m[7]) / det;
    out[8] = (m[0] * m[4] - m[1] * m[3]) / det;
    return true;
}

// Degeneracy threshold for the rest covariance determinant. The CPU uses an
// absolute 1e-16 in double. In float the rounding noise of a coplanar
// neighbourhood is far above that, so the float path scales the threshold by
// the isotropic determinant (trace/3)^3; trace(R) equals the live neighbour
// count because the weights are 1/|rest edge|^2.
template <typename Real>
BANJO_HD Real inverseEpsilon(const Real r[9]) {
    if constexpr (sizeof(Real) == 8) {
        (void)r;
        return Real(1.0e-16);
    } else {
        const Real third = (r[0] + r[4] + r[8]) * Real(1.0 / 3.0);
        return Real(1.0e-5) * third * third * third;
    }
}

// ---------------------------------------------------------------------------
// Nonlocal node strain (BondFailure.cpp calculateNodeStrains).
// Recomputes the cached inverse rest covariance when the node is dirty, then
// stores E for this node. Returns nothing; node_valid says whether E exists.
// ---------------------------------------------------------------------------
template <typename Real>
BANJO_HD void nodeStrain(const LatticeArrays<Real> &L, std::uint32_t i, bool direct) {
    const std::uint32_t N = L.node_count, D = L.max_degree;
    if (L.node_dirty[i]) {
        Real rest_cov[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
        std::uint32_t live = 0;
        for (std::uint32_t k = 0; k < D; ++k) {
            const std::uint32_t slot = k * N + i;
            const std::uint32_t j = L.nbr_bond[slot];
            if (j == kNoBond) break;
            if (!L.nbr_alive[slot]) continue;
            const Real w = L.nbr_weight[slot];
            if (w <= Real(0)) continue; // rest length squared <= 1e-18 in the CPU
            const V3<Real> r = load3(L.nbr_rest, slot);
            const Real rr[3] = {r.x, r.y, r.z};
            for (int row = 0; row < 3; ++row)
                for (int col = 0; col < 3; ++col)
                    rest_cov[row * 3 + col] += w * rr[row] * rr[col];
            ++live;
        }
        std::uint8_t valid = 0;
        if (live >= 3U) {
            Real inv[9];
            if (inverse3(rest_cov, inverseEpsilon(rest_cov), inv)) {
                for (int k = 0; k < 9; ++k) L.rinv[9 * i + k] = inv[k];
                valid = 1;
            }
            // Would the other rule have decided differently?
            const Real det = rest_cov[0] * (rest_cov[4] * rest_cov[8] - rest_cov[5] * rest_cov[7]) -
                             rest_cov[1] * (rest_cov[3] * rest_cov[8] - rest_cov[5] * rest_cov[6]) +
                             rest_cov[2] * (rest_cov[3] * rest_cov[7] - rest_cov[4] * rest_cov[6]);
            const Real third = (rest_cov[0] + rest_cov[4] + rest_cov[8]) * Real(1.0 / 3.0);
            const bool absolute_rule = absR(det) > Real(1.0e-16);
            const bool relative_rule = absR(det) > Real(1.0e-5) * third * third * third;
            if (absolute_rule != relative_rule && L.degenerate_disagreements != nullptr)
                *L.degenerate_disagreements += 1U;
        }
        L.node_valid[i] = valid;
        L.node_dirty[i] = 0;
    }
    if (!L.node_valid[i]) return;

    // A = sum w * current (x) rest (direct) or dA = sum w * du (x) rest. Dead
    // and padded neighbours contribute an exact zero, which leaves the
    // accumulator unchanged, so the loop has no data-dependent branch and
    // its independent loads can be issued together.
    Real acc[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
    const V3<Real> xi = direct ? position(L, i) : load3(L.u, i);
    BANJO_UNROLL
    for (std::uint32_t k = 0; k < D; ++k) {
        const std::uint32_t slot = k * N + i;
        const std::uint32_t j = L.nbr_bond[slot];
        const bool present = j != kNoBond;
        const std::uint32_t other = present ? L.nbr_other[slot] : i;
        const Real w = (present && L.nbr_alive[slot]) ? L.nbr_weight[slot] : Real(0);
        const V3<Real> rest = present ? load3(L.nbr_rest, slot) : v3<Real>(0, 0, 0);
        const V3<Real> xo = direct ? position(L, other) : load3(L.u, other);
        const V3<Real> cur = xo - xi;
        const Real cc[3] = {cur.x, cur.y, cur.z};
        const Real rr[3] = {rest.x, rest.y, rest.z};
        for (int row = 0; row < 3; ++row)
            for (int col = 0; col < 3; ++col)
                acc[row * 3 + col] += w * cc[row] * rr[col];
    }
    const Real *inv = L.rinv + 9 * i;
    Real f[9];
    for (int row = 0; row < 3; ++row)
        for (int col = 0; col < 3; ++col) {
            Real s = Real(0);
            for (int k = 0; k < 3; ++k) s += acc[row * 3 + k] * inv[k * 3 + col];
            f[row * 3 + col] = s;
        }
    Real e[6];
    if (direct) {
        // F = A R^-1, C = F^T F, E = (C - I) / 2.
        const int rows[6] = {0, 1, 2, 0, 0, 1};
        const int cols[6] = {0, 1, 2, 1, 2, 2};
        for (int q = 0; q < 6; ++q) {
            Real c = Real(0);
            for (int k = 0; k < 3; ++k) c += f[k * 3 + rows[q]] * f[k * 3 + cols[q]];
            const Real identity = rows[q] == cols[q] ? Real(1) : Real(0);
            e[q] = Real(0.5) * (c - identity);
        }
    } else {
        // G = F - I = dA R^-1, E = (G + G^T + G^T G) / 2: no cancellation.
        const int rows[6] = {0, 1, 2, 0, 0, 1};
        const int cols[6] = {0, 1, 2, 1, 2, 2};
        for (int q = 0; q < 6; ++q) {
            Real c = Real(0);
            for (int k = 0; k < 3; ++k) c += f[k * 3 + rows[q]] * f[k * 3 + cols[q]];
            e[q] = Real(0.5) * (f[rows[q] * 3 + cols[q]] + f[cols[q] * 3 + rows[q]] + c);
        }
    }
    for (int q = 0; q < 6; ++q) L.strain[6 * i + q] = e[q];
}

// BondFailure.cpp resolveAlongBond on the stored symmetric strain.
template <typename Real>
BANJO_HD void resolveAlongBond(const Real *e, V3<Real> d, Real &normal, Real &shear) {
    const V3<Real> traction{
        e[0] * d.x + e[3] * d.y + e[4] * d.z,
        e[3] * d.x + e[1] * d.y + e[5] * d.z,
        e[4] * d.x + e[5] * d.y + e[2] * d.z,
    };
    normal = dot(d, traction);
    shear = length(traction - normal * d);
}

// The bond's own stretch |x_ab| / rest_length - 1 (BondFailure.cpp
// accumulateBondStrainPeaks), cancellation-free in the displacement mode.
template <typename Real>
BANJO_HD Real bondStretch(const LatticeArrays<Real> &L, std::uint32_t j, bool direct) {
    const V3<Real> delta = bondVector(L, j, direct);
    const Real len = length(delta);
    const Real rest = L.rest_length[j];
    if (direct) return len / rest - Real(1);
    const std::uint32_t a = L.bond_a[j], b = L.bond_b[j];
    const V3<Real> du = load3(L.u, b) - load3(L.u, a);
    const V3<Real> r = load3(L.rest_edge, j);
    const Real len2_minus_rest2 = L.rest_length_sq_minus[j] + Real(2) * dot(r, du) + dot(du, du);
    return len2_minus_rest2 / ((len + rest) * rest);
}

// One bond's resolved strain sample at the current configuration.
template <typename Real>
BANJO_HD void bondStrainSample(const LatticeArrays<Real> &L, std::uint32_t j, bool direct,
                               Real &tensile, Real &compressive, Real &shear) {
    const Real stretch = bondStretch(L, j, direct);
    tensile = stretch;
    compressive = -stretch;
    shear = Real(0);
    const V3<Real> rest_edge = load3(L.rest_edge, j);
    const Real rest_len = length(rest_edge);
    if (rest_len > Real(1.0e-9)) {
        const V3<Real> direction = rest_edge * (Real(1) / rest_len);
        const std::uint32_t ends[2] = {L.bond_a[j], L.bond_b[j]};
        for (int q = 0; q < 2; ++q) {
            const std::uint32_t n = ends[q];
            if (!L.node_valid[n]) continue;
            Real normal, sh;
            resolveAlongBond(L.strain + 6 * n, direction, normal, sh);
            tensile = maxR(tensile, normal);
            compressive = maxR(compressive, -normal);
            shear = maxR(shear, sh);
        }
    }
}

// BondFailure.cpp bondDamageProgress.
template <typename Real>
BANJO_HD Real damageProgress(Real value, Real start, Real end) {
    if (!finiteR(start) || value <= start) return Real(0);
    if (!finiteR(end) || end <= start) return value > start ? Real(1) : Real(0);
    const Real p = (value - start) / (end - start);
    return p < Real(0) ? Real(0) : (p > Real(1) ? Real(1) : p);
}

// BondFailure.cpp storedBondEnergy at the current configuration.
template <typename Real>
BANJO_HD Real storedBondEnergy(const LatticeArrays<Real> &L, std::uint32_t j, bool direct) {
    const Real c = L.compliance[j];
    if (c <= Real(0)) return Real(0);
    const Real extension = length(bondVector(L, j, direct)) - L.rest_length[j];
    return Real(0.5) * extension * extension / c;
}

struct FailureOutcome {
    bool broke;
    double removed_energy_j;
    std::uint8_t mode;
    // The substep's peaks for this bond, for diagnostics.
    float peak_tensile, peak_compressive, peak_shear;
};

// End-of-substep evaluation for one bond: peaks are the maximum of the start
// sample (prev_*) and the sample at the current configuration; then
// evaluateBondDamage and the removal rule of applyBondFailure.
template <typename Real>
BANJO_HD FailureOutcome bondEndSampleAndFailure(const LatticeArrays<Real> &L, std::uint32_t j, bool direct) {
    FailureOutcome out{false, 0.0, 0, 0.0F, 0.0F, 0.0F};
    Real tensile, compressive, shear;
    bondStrainSample(L, j, direct, tensile, compressive, shear);
    // resetBondStrainPeaks zeroes the peaks before the start sample, so the
    // reset value takes part in the maximum: a negative sample never shows.
    const Real peak_t = maxR(Real(0), maxR(L.prev_tensile[j], tensile));
    const Real peak_c = maxR(Real(0), maxR(L.prev_compressive[j], compressive));
    const Real peak_s = maxR(Real(0), maxR(L.prev_shear[j], shear));
    out.peak_tensile = static_cast<float>(peak_t);
    out.peak_compressive = static_cast<float>(peak_c);
    out.peak_shear = static_cast<float>(peak_s);
    // The end sample becomes the next substep's start sample unless topology
    // changes (the scheduler recomputes it then).
    L.prev_tensile[j] = maxR(Real(0), tensile);
    L.prev_compressive[j] = maxR(Real(0), compressive);
    L.prev_shear[j] = maxR(Real(0), shear);

    const Real *t = L.threshold + 6 * j;
    const Real tensile_damage = damageProgress(peak_t, t[0], t[1]);
    const Real compressive_damage = damageProgress(peak_c, t[2], t[3]);
    const Real shear_damage = damageProgress(peak_s, t[4], t[5]);
    Real damage = tensile_damage;
    std::uint8_t mode = 1;
    if (compressive_damage > damage) { damage = compressive_damage; mode = 2; }
    if (shear_damage > damage) { damage = shear_damage; mode = 3; }
    if (damage > L.damage[j]) {
        L.damage[j] = damage;
        L.failure_mode[j] = mode;
    }
    if (L.damage[j] >= Real(1)) {
        out.removed_energy_j = static_cast<double>(storedBondEnergy(L, j, direct));
        out.broke = true;
        out.mode = L.failure_mode[j];
        L.alive[j] = 0;
        L.nbr_alive[L.bond_slot_a[j]] = 0;
        L.nbr_alive[L.bond_slot_b[j]] = 0;
    }
    return out;
}

// Start-of-substep sample (after resetBondStrainPeaks); only needed when the
// topology changed since the last end sample.
template <typename Real>
BANJO_HD void bondStartSample(const LatticeArrays<Real> &L, std::uint32_t j, bool direct) {
    Real tensile, compressive, shear;
    bondStrainSample(L, j, direct, tensile, compressive, shear);
    // Stored as the CPU stores them: peaks after reset, i.e. never negative.
    L.prev_tensile[j] = maxR(Real(0), tensile);
    L.prev_compressive[j] = maxR(Real(0), compressive);
    L.prev_shear[j] = maxR(Real(0), shear);
}

// ---------------------------------------------------------------------------
// XPBD bond solve (BrittleBondSolver.cpp solveBond).
// ---------------------------------------------------------------------------
// first_iteration reproduces the per-substep accumulated_lambda reset.
template <typename Real>
BANJO_HD void bondSolve(const LatticeArrays<Real> &L, std::uint32_t j, Real dt, bool direct,
                        bool first_iteration) {
    if (!L.alive[j]) return;
    const std::uint32_t a = L.bond_a[j], b = L.bond_b[j];
    const V3<Real> delta = bondVector(L, j, direct);
    const Real current_length = length(delta);
    if (current_length <= Real(1.0e-12)) return;
    const Real rest = L.rest_length[j];
    Real constraint;
    if (direct) {
        constraint = current_length - rest;
    } else {
        const V3<Real> du = load3(L.u, b) - load3(L.u, a);
        const V3<Real> r = load3(L.rest_edge, j);
        constraint = (L.rest_length_sq_minus[j] + Real(2) * dot(r, du) + dot(du, du)) /
                     (current_length + rest);
    }
    const V3<Real> direction = delta / current_length;
    const Real wa = L.inv_mass[a], wb = L.inv_mass[b];
    const Real alpha = L.compliance[j] / (dt * dt);
    const Real lambda = first_iteration ? Real(0) : L.accumulated_lambda[j];
    const Real delta_lambda = (-constraint - alpha * lambda) / (wa + wb + alpha);
    L.accumulated_lambda[j] = lambda + delta_lambda;
    store3(L.u, a, load3(L.u, a) - wa * delta_lambda * direction);
    store3(L.u, b, load3(L.u, b) + wb * delta_lambda * direction);
}

// Radial pair damping (BrittleBondSolver.cpp dampInternalBonds), one bond.
template <typename Real>
BANJO_HD void bondDamp(const LatticeArrays<Real> &L, std::uint32_t j, Real fraction, bool direct) {
    if (!L.alive[j]) return;
    const std::uint32_t a = L.bond_a[j], b = L.bond_b[j];
    const Real ma = L.mass[a], mb = L.mass[b];
    if (ma <= Real(0) || mb <= Real(0)) return;
    const V3<Real> normal = normalized(bondVector(L, j, direct));
    const V3<Real> va = load3(L.v, a), vb = load3(L.v, b);
    const Real relative_speed = dot(vb - va, normal);
    const Real inverse_mass = Real(1) / ma + Real(1) / mb;
    const Real impulse = -fraction * relative_speed / inverse_mass;
    store3(L.v, a, va - (impulse / ma) * normal);
    store3(L.v, b, vb + (impulse / mb) * normal);
}

// ---------------------------------------------------------------------------
// Support plane (BrittleBondSolver.cpp constrained support path).
// ---------------------------------------------------------------------------
template <typename Real>
BANJO_HD bool insideFootprints(const SupportPlane<Real> &plane, V3<Real> p) {
    const V3<Real> relative = p - plane.point;
    const Real t = dot(relative, plane.tangent), b = dot(relative, plane.bitangent);
    for (std::uint32_t k = 0; k < plane.footprint_count; ++k) {
        const Footprint<Real> &f = plane.footprints[k];
        if (absR(t - f.center_t) <= f.half_t && absR(b - f.center_b) <= f.half_b) return true;
    }
    return false;
}

// projectSupportPosition: returns the depth removed (positive when engaged).
// approach_normal_speed is the node's normal velocity recorded before the
// sweep and dt the substep, which bound how deep a node arriving from above
// can be.
template <typename Real>
BANJO_HD Real projectSupportPosition(const LatticeArrays<Real> &L, const SupportPlane<Real> &plane, std::uint32_t i,
                                     Real approach_normal_speed, Real dt) {
    const V3<Real> p = position(L, i);
    if (!insideFootprints(plane, p)) return Real(0);
    const Real distance = dot(p - plane.point, plane.normal) - plane.node_radius;
    if (distance > Real(1.0e-8)) return Real(0);
    // A finite footprint has edges. A node that already passed the surface
    // (fell through the gap beside a ledge) and then drifts under the
    // footprint must not be teleported back up through its bonds: a surface
    // only stops what arrives from above, and such a node can be at most a
    // few approach steps deep. A bond teleported by millimetres carries
    // kilojoules, which is what an uncapped projection injected here. Inert
    // for an infinite footprint, where every engaged node arrives from above.
    const Real reach = Real(8) * maxR(Real(0), -approach_normal_speed) * dt + Real(1.0e-5);
    if (-distance > reach) return Real(0);
    store3(L.u, i, load3(L.u, i) - distance * plane.normal);
    return -distance;
}

// applySupportVelocity for a node whose position was constrained this substep.
template <typename Real>
BANJO_HD void applySupportVelocity(const LatticeArrays<Real> &L, const SupportPlane<Real> &plane,
                                   std::uint32_t i, Real approach_normal_speed) {
    V3<Real> vel = load3(L.v, i);
    const Real restitution = -approach_normal_speed > Real(0.5)
        ? (plane.restitution < Real(0) ? Real(0) : (plane.restitution > Real(1) ? Real(1) : plane.restitution))
        : Real(0);
    const Real target = approach_normal_speed < Real(0) ? -restitution * approach_normal_speed : Real(0);
    const Real normal_speed = dot(vel, plane.normal);
    Real corrected = normal_speed;
    if (normal_speed > target) corrected = target;
    else if (normal_speed < Real(0)) corrected = Real(0);
    vel = vel + (corrected - normal_speed) * plane.normal;
    const Real normal_delta = corrected - minR(Real(0), approach_normal_speed);
    if (normal_delta <= Real(0)) { store3(L.v, i, vel); return; }
    const V3<Real> tangent = vel - dot(vel, plane.normal) * plane.normal;
    const Real speed = length(tangent);
    if (speed <= Real(1.0e-12)) { store3(L.v, i, vel); return; }
    const Real friction_delta = speed <= plane.static_friction * normal_delta
        ? speed : minR(speed, plane.dynamic_friction * normal_delta);
    vel = vel - (friction_delta / speed) * tangent;
    store3(L.v, i, vel);
}

// Support handling of one node after the constraint sweep of one iteration.
template <typename Real>
BANJO_HD void nodeSupportProject(const LatticeArrays<Real> &L, const StepSettings<Real> &S, std::uint32_t i) {
    for (std::uint32_t p = 0; p < S.support.plane_count; ++p) {
        const Real depth = projectSupportPosition(L, S.support.planes[p], i, L.approach[p * L.node_count + i], S.dt);
        if (depth > Real(0)) L.engaged[p * L.node_count + i] = 1;
    }
}

template <typename Real>
BANJO_HD void nodeSupportVelocity(const LatticeArrays<Real> &L, const StepSettings<Real> &S, std::uint32_t i) {
    for (std::uint32_t p = 0; p < S.support.plane_count; ++p) {
        if (!L.engaged[p * L.node_count + i]) continue;
        applySupportVelocity(L, S.support.planes[p], i, L.approach[p * L.node_count + i]);
    }
}

template <typename Real>
BANJO_HD void nodeRecordApproach(const LatticeArrays<Real> &L, const StepSettings<Real> &S, std::uint32_t i) {
    const V3<Real> vel = load3(L.v, i);
    for (std::uint32_t p = 0; p < S.support.plane_count; ++p)
        L.approach[p * L.node_count + i] = dot(vel, S.support.planes[p].normal);
}

// ---------------------------------------------------------------------------
// Sphere contact (SphereMaterialContact.cpp), sequential in node order.
// ---------------------------------------------------------------------------

// Conservative prefilter evaluated in parallel: a node that could pass the CPU
// test for any sphere velocity reachable inside this step is a candidate.
template <typename Real>
BANJO_HD bool sphereCandidate(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                              const SphereState<Real> &sphere, std::uint32_t i) {
    if (L.mass[i] <= Real(0)) return false;
    const V3<Real> r = position(L, i) - sphere.center;
    const Real distance = length(r);
    const Real gap = distance - (sphere.radius + S.contact.node_contact_radius);
    const Real speed_bound = length(load3(L.v, i) - sphere.velocity) +
                             length(sphere.angular_velocity) * distance;
    const Real reach = maxR(S.contact.contact_margin, speed_bound * S.dt) + S.contact.prefilter_slack;
    return gap <= reach;
}

template <typename Real>
BANJO_HD Real kineticEnergy(const LatticeArrays<Real> &L, std::uint32_t i, const SphereState<Real> &s) {
    return Real(0.5) * L.mass[i] * length2(load3(L.v, i)) +
           Real(0.5) * s.mass * length2(s.velocity) +
           Real(0.5) * s.inertia * length2(s.angular_velocity);
}

// One node against the sphere, exactly the loop body of
// solveSphereMaterialContacts. Returns true when an impulse was applied.
template <typename Real>
BANJO_HD void sphereContactNode(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                                SphereState<Real> &sphere, std::uint32_t i, bool correct_positions,
                                ContactAccumulators &acc) {
    if (L.mass[i] <= Real(0)) return;
    const ContactSettings<Real> &c = S.contact;
    const Real dt = S.dt;
    const Real inverse_sphere_mass = Real(1) / sphere.mass;
    const Real inverse_inertia = Real(1) / sphere.inertia;
    const Real contact_radius = sphere.radius + c.node_contact_radius;
    const V3<Real> r = position(L, i) - sphere.center;
    const Real distance = length(r);
    const V3<Real> normal = normalized(r);
    const Real gap = distance - contact_radius;
    V3<Real> node_v = load3(L.v, i);
    const V3<Real> relative = node_v - sphere.velocity - cross(sphere.angular_velocity, r);
    const Real vn = dot(relative, normal);
    if (gap > maxR(c.contact_margin, -vn * dt)) return;
    if (-gap > Real(acc.maximum_penetration_m)) acc.maximum_penetration_m = static_cast<double>(-gap);
    const Real inverse_node_mass = Real(1) / L.mass[i];
    const auto effective_inverse_mass = [&](V3<Real> direction) {
        return inverse_node_mass + inverse_sphere_mass + inverse_inertia * length2(cross(r, direction));
    };
    const Real restitution = -vn > c.restitution_speed_threshold ? c.restitution : Real(0);
    const Real desired_vn = gap > c.contact_margin ? -gap / dt : -restitution * minR(vn, Real(0));
    const Real normal_impulse = maxR(Real(0), (desired_vn - vn) / effective_inverse_mass(normal));
    if (normal_impulse > Real(0)) {
        const Real before = kineticEnergy(L, i, sphere);
        const auto apply = [&](V3<Real> impulse) {
            node_v = node_v + inverse_node_mass * impulse;
            store3(L.v, i, node_v);
            sphere.velocity = sphere.velocity - inverse_sphere_mass * impulse;
            const V3<Real> torque_impulse = -cross(r, impulse);
            sphere.angular_velocity = sphere.angular_velocity + inverse_inertia * torque_impulse;
            acc.impulse_to_material_x += static_cast<double>(impulse.x);
            acc.impulse_to_material_y += static_cast<double>(impulse.y);
            acc.impulse_to_material_z += static_cast<double>(impulse.z);
        };
        apply(normal_impulse * normal);
        const V3<Real> after_normal_relative = node_v - sphere.velocity - cross(sphere.angular_velocity, r);
        const V3<Real> tangent = after_normal_relative - dot(after_normal_relative, normal) * normal;
        const Real tangent_speed = length(tangent);
        if (tangent_speed > Real(1.0e-12)) {
            const V3<Real> direction = tangent / tangent_speed;
            const Real sticking_impulse = tangent_speed / effective_inverse_mass(direction);
            const Real friction_impulse = sticking_impulse <= c.static_friction * normal_impulse
                ? sticking_impulse : minR(sticking_impulse, c.dynamic_friction * normal_impulse);
            apply(-friction_impulse * direction);
        }
        acc.dissipated_kinetic_energy_j += static_cast<double>(before - kineticEnergy(L, i, sphere));
        ++acc.impulse_contacts;
    }
    if (correct_positions && gap < -c.contact_margin) {
        const Real correction = minR(-gap - c.contact_margin,
            Real(0.2) * maxR(c.node_contact_radius, sphere.radius * Real(0.01)));
        const Real sum_inverse_mass = inverse_node_mass + inverse_sphere_mass;
        const V3<Real> node_shift = (correction * inverse_node_mass / sum_inverse_mass) * normal;
        const V3<Real> sphere_shift = -(correction * inverse_sphere_mass / sum_inverse_mass) * normal;
        store3(L.u, i, load3(L.u, i) + node_shift);
        sphere.center = sphere.center + sphere_shift;
        if (correction > Real(acc.maximum_position_correction_m))
            acc.maximum_position_correction_m = static_cast<double>(correction);
    }
}

// The whole sequential pass over the ordered candidate lists. pass 1 follows
// the gravity kick (velocity impulses only) and then records the support
// approach speeds and predicts the candidates' positions; pass 2 follows the
// velocity update (impulses and position corrections) and then applies the
// support velocity response to engaged candidates when no damping sweep will
// follow.
template <typename Real>
BANJO_HD void sphereContactPass(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                                SphereState<Real> &sphere, int pass, ContactAccumulators &acc) {
    const V3<Real> center_before = sphere.center;
    for (std::uint32_t block = 0; block < L.block_count; ++block) {
        const std::uint32_t count = L.candidate_count[block];
        const std::uint32_t *list = L.candidate_list + block * kMaxCandidatesPerBlock;
        for (std::uint32_t k = 0; k < count; ++k) {
            const std::uint32_t i = list[k];
            sphereContactNode(L, S, sphere, i, pass == 2, acc);
            if (pass == 1) {
                nodeRecordApproach(L, S, i);
                store3(L.u, i, load3(L.u, i) + S.dt * load3(L.v, i));
            }
        }
    }
    // Candidates always take their support velocity response here: on the CPU
    // it follows damping and the second contact pass, both of which are done
    // for them by the time this pass ends.
    if (pass == 2) {
        for (std::uint32_t block = 0; block < L.block_count; ++block) {
            const std::uint32_t count = L.candidate_count[block];
            const std::uint32_t *list = L.candidate_list + block * kMaxCandidatesPerBlock;
            for (std::uint32_t k = 0; k < count; ++k) nodeSupportVelocity(L, S, list[k]);
        }
    }
    const Real shift = length(sphere.center - center_before);
    if (shift > Real(acc.maximum_center_shift_m)) acc.maximum_center_shift_m = static_cast<double>(shift);
}

// ---------------------------------------------------------------------------
// Node phases.
// ---------------------------------------------------------------------------

// Gravity kick, previous position, candidate test. Non-candidates also record
// their support approach speed and take their prediction here; candidates get
// both from the serial contact pass after their impulses.
template <typename Real>
BANJO_HD bool nodeKickAndClassify(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                                  const SphereState<Real> &sphere, std::uint32_t i) {
    V3<Real> vel = load3(L.v, i) + S.dt * S.gravity;
    store3(L.v, i, vel);
    store3(L.u_prev, i, load3(L.u, i));
    for (std::uint32_t p = 0; p < kMaxSupportPlanes; ++p) L.engaged[p * L.node_count + i] = 0;
    const bool candidate = S.sphere_enabled && sphereCandidate(L, S, sphere, i);
    L.candidate[i] = candidate ? 1 : 0;
    if (!candidate) {
        nodeRecordApproach(L, S, i);
        store3(L.u, i, load3(L.u, i) + S.dt * vel);
    }
    return candidate;
}

// After the last constraint iteration's support projection: velocity from the
// accepted positions. Non-candidates apply the support velocity response here
// when no damping sweep follows (the sweep would otherwise change velocities
// first, as it does on the CPU).
template <typename Real>
BANJO_HD void nodeVelocityUpdate(const LatticeArrays<Real> &L, const StepSettings<Real> &S, std::uint32_t i) {
    const V3<Real> vel = (load3(L.u, i) - load3(L.u_prev, i)) / S.dt;
    store3(L.v, i, vel);
    if (S.damping_fraction <= Real(0) && !L.candidate[i]) nodeSupportVelocity(L, S, i);
}

// When the lattice phase may stop, shared by both backends. 0 continue,
// 1 cascade quiet (no failure for quiet_steps after at least one failure and
// min_steps in total), 2 nothing has failed by no_failure_steps.
BANJO_HD unsigned latticeExitReason(unsigned long long completed, unsigned broken,
                                    unsigned long long last_failure_step,
                                    unsigned long long quiet_steps,
                                    unsigned long long min_steps,
                                    unsigned long long no_failure_steps) {
    if (broken > 0U && quiet_steps > 0ULL && completed >= min_steps &&
        completed > last_failure_step && completed - last_failure_step > quiet_steps)
        return 1U;
    if (broken == 0U && no_failure_steps > 0ULL && completed >= no_failure_steps) return 2U;
    return 0U;
}

// Rigid ball against the support planes during the lattice phase: not part of
// the CPU material solver (there Jolt does it). Same restitution/friction rule
// as a node, applied to the sphere as a whole.
template <typename Real>
BANJO_HD void sphereSupportContact(const StepSettings<Real> &S, SphereState<Real> &sphere,
                                   ContactAccumulators &acc) {
    for (std::uint32_t p = 0; p < S.support.plane_count; ++p) {
        const SupportPlane<Real> &plane = S.support.planes[p];
        const V3<Real> foot = sphere.center - sphere.radius * plane.normal;
        if (!insideFootprints(plane, foot)) continue;
        const Real distance = dot(foot - plane.point, plane.normal);
        if (distance > Real(0)) continue;
        // Same rule as for nodes: only a ball arriving from above is stopped.
        const Real vn0 = dot(sphere.velocity, plane.normal);
        if (-distance > Real(8) * maxR(Real(0), -vn0) * S.dt + Real(1.0e-5)) continue;

        const Real vn = dot(sphere.velocity, plane.normal);
        if (vn < Real(0)) {
            const Real restitution = -vn > Real(0.5) ? plane.restitution : Real(0);
            const Real normal_delta = -(Real(1) + restitution) * vn;
            sphere.velocity = sphere.velocity + normal_delta * plane.normal;
            const V3<Real> tangent = sphere.velocity - dot(sphere.velocity, plane.normal) * plane.normal;
            const Real speed = length(tangent);
            if (speed > Real(1.0e-12)) {
                const Real friction_delta = speed <= plane.static_friction * normal_delta
                    ? speed : minR(speed, plane.dynamic_friction * normal_delta);
                sphere.velocity = sphere.velocity - (friction_delta / speed) * tangent;
            }
            ++acc.ball_support_events;
        }
        sphere.center = sphere.center - distance * plane.normal;
    }
}

} // namespace banjo::fastlattice
