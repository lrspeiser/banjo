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

// Host: unqualified so that a differentiable Real (Dual.hpp) is found by ADL.
template <typename Real> BANJO_HD Real sqrtR(Real x) {
#if defined(__CUDA_ARCH__)
    return sqrt(x);
#else
    using std::sqrt;
    return sqrt(x);
#endif
}
template <typename Real> BANJO_HD Real absR(Real x) { return x < Real(0) ? -x : x; }
template <typename Real> BANJO_HD Real maxR(Real a, Real b) { return (a < b) ? b : a; }
template <typename Real> BANJO_HD Real minR(Real a, Real b) { return (b < a) ? b : a; }
template <typename Real> BANJO_HD bool finiteR(Real x) {
#if defined(__CUDA_ARCH__)
    return isfinite(x);
#else
    using std::isfinite;
    return isfinite(x);
#endif
}
template <typename Real> BANJO_HD Real floorR(Real x) {
#if defined(__CUDA_ARCH__)
    return floor(x);
#else
    using std::floor;
    return floor(x);
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
    // 1 for a finite footprint (a ledge): the projection only stops what
    // arrives from above, see projectSupportPosition. 0 for an infinite plane,
    // where the CPU lane's unconditional projection applies unchanged.
    std::uint8_t reach_capped;
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

// ---------------------------------------------------------------------------
// Node-to-node contact.
// ---------------------------------------------------------------------------
// A cell is a cube of side `cell`; for contact it is the sphere of radius
// node_contact_radius = cell / 2 inscribed in it, which is the same radius the
// support planes already use to hold a cell centre half a cell above a surface.
// Two such cells touch when their centres are one cell apart, which is exactly
// the lattice spacing, so the rest configuration sits on the contact threshold
// and nothing is pushed at rest.
//
// THE RULE. Contact resolves a pair only where no LIVE bond joins it. A bonded
// pair is already held by its bond; adding contact to it would apply two
// responses to one interaction, stiffen the material in compression and change
// the elastic reference the criterion is calibrated against. A pair whose bond
// has failed is no longer held by anything, and that is precisely the crack
// surface a fragment would otherwise pass through, so contact must act there.
// The rule is enforced twice: unbonded-and-live pairs are never put in the pair
// list, and nodeContactPair re-checks the bond's aliveness where the response
// is applied.
constexpr std::uint32_t kMaxPairsPerNode = 24;

// mode
enum : std::uint8_t {
    kNodeContactOff = 0,     // no broad phase, no narrow phase: af8af80 exactly
    kNodeContactMeasure = 1, // broad + narrow, overlap recorded, no response
    kNodeContactOn = 2,      // broad + narrow with the response
};

template <typename Real>
struct NodeContactSettings {
    std::uint8_t mode;
    // Per-node contact radius; two nodes touch at 2 * radius.
    Real radius;
    // Verlet skin: the pair list holds every pair within 2 * radius + skin, and
    // is rebuilt once any node has moved more than skin / 2 since the build (two
    // nodes each moving skin / 2 towards one another close exactly the skin).
    Real skin;
    Real margin;
    Real restitution, restitution_speed_threshold;
    Real static_friction, dynamic_friction;
    // Power-of-two hash table size minus one; see latticeContactBucketMask.
    std::uint32_t bucket_mask;
};

// Written by the one thread that runs the narrow phase, so every sum is in pair
// order on every backend.
struct NodeContactAccumulators {
    unsigned long long contacts;      // pairs that received an impulse
    unsigned long long pair_tests;    // narrow-phase pair evaluations
    unsigned long long rebuilds;      // broad-phase rebuilds
    unsigned long long pairs_listed;  // pairs in the list, summed over rebuilds
    unsigned long long pair_overflow; // pairs a node could not store
    double dissipated_kinetic_energy_j;
    // Worst overlap between two cells that no live bond joins, over the whole
    // lattice phase. Recorded in the measure mode as well, which is how the
    // before/after numbers are taken on the same scene.
    double maximum_overlap_m;
    double maximum_position_correction_m;
    // Momentum the pair responses added to the lattice. Every impulse is applied
    // equal and opposite, so this is a rounding residual, not a budget.
    double momentum_residual_x, momentum_residual_y, momentum_residual_z;
};

inline void clearNodeContactAccumulators(NodeContactAccumulators &c) {
    c.contacts = 0;
    c.pair_tests = 0;
    c.rebuilds = 0;
    c.pairs_listed = 0;
    c.pair_overflow = 0;
    c.dissipated_kinetic_energy_j = 0.0;
    c.maximum_overlap_m = 0.0;
    c.maximum_position_correction_m = 0.0;
    c.momentum_residual_x = c.momentum_residual_y = c.momentum_residual_z = 0.0;
}

// Hash table size for a lattice of this many nodes: the smallest power of two
// at least twice the node count, so the average bucket holds half a node. Both
// the array allocation and the settings derive the mask from the node count by
// this one rule, so they cannot disagree.
[[nodiscard]] constexpr std::uint32_t latticeContactBucketMask(std::uint32_t node_count) {
    std::uint32_t size = 64U;
    while (size < 2U * node_count && size < (1U << 22)) size <<= 1U;
    return size - 1U;
}

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
    // 1: measure the lattice's kinetic energy across the damping sweep and the
    // contact passes, so the dissipation of each can be reported separately.
    // Two serial passes over the nodes per substep; off by default.
    std::uint8_t audit_energy;
    // Axial plastic flow (bondPlasticReturn). Zero -- the default, and what
    // every material that declares no yield strength compiles to -- disables it:
    // no bond ever takes a permanent extension, plastic_extension stays zero and
    // every expression below reduces to the elastic one, bit for bit.
    // yield_stretch is the declared yield strength over the Young modulus; see
    // material/Material.hpp CompiledBrittleMaterial::yield_stretch.
    Real plastic_yield_stretch;
    Real plastic_hardening;
    ContactSettings<Real> contact;
    NodeContactSettings<Real> node_contact;
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
    std::uint32_t *rank_deficient_nodes;
    // 3N: unit normal of a coplanar neighbourhood, zero where the node spans
    // all three directions. The strain is projected into the plane it defines.
    Real *node_unmeasured;
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
    // Axial plastic state, one bond each. plastic_extension is the signed
    // permanent extension: the bond's rest length is rest_length + this, and the
    // elastic extension it stores energy in is measured from there.
    // plastic_strain is the accumulated magnitude of the flow, which is what
    // linear isotropic hardening raises the yield extension with. Both stay
    // exactly zero unless StepSettings::plastic_yield_stretch is positive.
    Real *plastic_extension;    // B
    Real *plastic_strain;       // B
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
    // Node-node contact broad phase. The hash is a counting sort of the nodes
    // into a uniform grid of side 2 * radius + skin, laid out as a power-of-two
    // hash table so an unbounded domain (fragments leaving the tile) needs no
    // bounding box. Every array below is written in node index order or by one
    // thread, so the pair list is the same on every backend.
    std::int32_t *node_cell;         // 3N grid coordinates at the last build
    Real *build_u;                   // 3N displacement at the last build
    std::uint32_t *bucket_begin;     // buckets + 1, prefix sums
    std::uint32_t *bucket_cursor;    // buckets, scatter cursors
    std::uint32_t *bucket_nodes;     // N, nodes by bucket, ascending within one
    std::uint32_t *pair_other;       // kMaxPairsPerNode * N, partners of node a
    std::uint32_t *pair_bond;        // kMaxPairsPerNode * N, the pair's bond or kNoBond
    std::uint32_t *pair_fill;        // N, pairs owned by node a
    std::uint32_t *pair_node_list;   // N, nodes owning at least one pair, ascending
    std::uint32_t *pair_node_count;  // 1
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

// Relative eigenvalue floor for the rest covariance. A direction the
// neighbourhood does not sample carries no information about the deformation,
// and inverting it amplifies rounding noise without bound: that is what
// produced fabricated strains of 2.3, 4.0 and 127.5 (a deformation gradient
// collapsed to zero reads as a compressive Green-Lagrange strain of exactly
// 0.5). The floor is relative to the largest eigenvalue, so it is a statement
// about conditioning rather than about units; the trace of R equals the live
// neighbour count because the weights are 1/|rest edge|^2.
template <typename Real>
BANJO_HD Real eigenvalueFloor() {
    return sizeof(Real) == 8 ? Real(1.0e-9) : Real(1.0e-5);
}

// Eigendecomposition of a symmetric 3x3 by cyclic Jacobi rotations. Fixed
// sweep count, no allocation, no library call: identical on host and device.
// Returns eigenvalues in d[3] and orthonormal eigenvectors as the columns of
// v[9] (row-major, v[row * 3 + col] is component `row` of eigenvector `col`).
template <typename Real>
BANJO_HD void symmetricEigen3(const Real m[9], Real d[3], Real v[9]) {
    Real a[9];
    for (int k = 0; k < 9; ++k) a[k] = m[k];
    for (int k = 0; k < 9; ++k) v[k] = (k % 4 == 0) ? Real(1) : Real(0);
    for (int sweep = 0; sweep < 12; ++sweep) {
        Real off = absR(a[1]) + absR(a[2]) + absR(a[5]);
        if (!(off > Real(0))) break;
        for (int p = 0; p < 2; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                const Real apq = a[p * 3 + q];
                if (!(absR(apq) > Real(0))) continue;
                const Real app = a[p * 3 + p], aqq = a[q * 3 + q];
                // t = tan(theta) of the rotation that zeroes a[p][q].
                const Real theta = (aqq - app) / (Real(2) * apq);
                const Real sign = theta >= Real(0) ? Real(1) : Real(-1);
                const Real t = sign / (absR(theta) + sqrtR(theta * theta + Real(1)));
                const Real c = Real(1) / sqrtR(t * t + Real(1));
                const Real sn = t * c;
                for (int k = 0; k < 3; ++k) {
                    const Real akp = a[k * 3 + p], akq = a[k * 3 + q];
                    a[k * 3 + p] = c * akp - sn * akq;
                    a[k * 3 + q] = sn * akp + c * akq;
                }
                for (int k = 0; k < 3; ++k) {
                    const Real apk = a[p * 3 + k], aqk = a[q * 3 + k];
                    a[p * 3 + k] = c * apk - sn * aqk;
                    a[q * 3 + k] = sn * apk + c * aqk;
                }
                for (int k = 0; k < 3; ++k) {
                    const Real vkp = v[k * 3 + p], vkq = v[k * 3 + q];
                    v[k * 3 + p] = c * vkp - sn * vkq;
                    v[k * 3 + q] = sn * vkp + c * vkq;
                }
            }
        }
    }
    d[0] = a[0]; d[1] = a[4]; d[2] = a[8];
}

// Moore-Penrose pseudo-inverse of a symmetric positive semi-definite 3x3,
// truncating every eigen-direction below the relative floor. `rank` reports how
// many directions survived: 3 for a solid neighbourhood, 2 for a coplanar one
// (a sheet one cell thick, where every rest edge lies in the plane), less where
// fracture has stripped a node of neighbours.
//
// Truncation rather than inversion is what makes the unsampled direction
// harmless. The strain is formed below as G = F - I = dA R+, so a direction
// killed by R+ contributes G d = 0, i.e. F d = d: the deformation gradient is
// the identity along a direction the neighbourhood never measured, which is the
// plane-stress statement for a thin sheet and the only claim the data supports.
template <typename Real>
BANJO_HD int symmetricPseudoInverse3(const Real m[9], Real out[9], Real unmeasured[3]) {
    Real d[3], v[9];
    symmetricEigen3(m, d, v);
    Real largest = absR(d[0]);
    if (absR(d[1]) > largest) largest = absR(d[1]);
    if (absR(d[2]) > largest) largest = absR(d[2]);
    const Real floor_value = eigenvalueFloor<Real>() * largest;
    for (int k = 0; k < 9; ++k) out[k] = Real(0);
    for (int k = 0; k < 3; ++k) unmeasured[k] = Real(0);
    int rank = 0, dropped = -1;
    for (int c = 0; c < 3; ++c) {
        if (!(d[c] > floor_value)) { dropped = c; continue; }
        ++rank;
        const Real inv = Real(1) / d[c];
        for (int row = 0; row < 3; ++row)
            for (int col = 0; col < 3; ++col)
                out[row * 3 + col] += inv * v[row * 3 + c] * v[col * 3 + c];
    }
    // Exactly one direction dropped -- a coplanar neighbourhood -- is the case
    // the strain can still be stated on: report its normal so the strain can be
    // projected into the plane. Two or more dropped leaves too little to say.
    if (rank == 2 && dropped >= 0)
        for (int k = 0; k < 3; ++k) unmeasured[k] = v[k * 3 + dropped];
    return rank;
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
        if (live >= 1U) {
            Real inv[9], unmeasured[3];
            const int rank = symmetricPseudoInverse3(rest_cov, inv, unmeasured);
            if (rank >= 2) {
                for (int k = 0; k < 9; ++k) L.rinv[9 * i + k] = inv[k];
                for (int k = 0; k < 3; ++k) L.node_unmeasured[3 * i + k] = unmeasured[k];
                valid = 1;
            }
            // A node whose neighbourhood does not span three directions still
            // yields a strain, on the directions it does span. Counting them is
            // what keeps that visible: a sheet one cell thick has every node at
            // rank 2, and reporting zero here used to be the only sign that the
            // nonlocal criterion had quietly become a local stretch test.
            if (rank < 3 && L.rank_deficient_nodes != nullptr)
                *L.rank_deficient_nodes += 1U;
        }
        L.node_valid[i] = valid;
        L.node_dirty[i] = 0;
    }
    if (!L.node_valid[i]) return;

    // dA = sum w * (current - rest) (x) rest in both modes. Accumulating the
    // difference rather than the current edge is what lets a rank-deficient R+
    // mean "identity along the unmeasured direction": at rest dA is exactly
    // zero, so G is zero and F is I whatever R+ drops. It is also the
    // cancellation-free form. Dead and padded neighbours contribute an exact
    // zero, so the loop has no data-dependent branch.
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
        const V3<Real> cur = direct ? (xo - xi) - rest : xo - xi;
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
    // G = F - I = dA R+, E = (G + G^T + G^T G) / 2 in both modes: exact, free of
    // the cancellation that forming F from absolute positions would carry, and
    // it is the form that leaves E zero along a direction R+ dropped.
    Real e[6];
    {
        const int rows[6] = {0, 1, 2, 0, 0, 1};
        const int cols[6] = {0, 1, 2, 1, 2, 2};
        for (int q = 0; q < 6; ++q) {
            Real c = Real(0);
            for (int k = 0; k < 3; ++k) c += f[k * 3 + rows[q]] * f[k * 3 + cols[q]];
            e[q] = Real(0.5) * (f[rows[q] * 3 + cols[q]] + f[cols[q] * 3 + rows[q]] + c);
        }
    }
    // A coplanar neighbourhood measures the deformation of its own plane and
    // nothing else. Leaving the unmeasured direction at rest is not a neutral
    // choice: it is not rotation invariant, so a sheet that merely flexes reads
    // as shear -- measured at 436 bonds broken under gravity alone on a plate
    // that was not struck. Projecting the strain into the plane removes exactly
    // those cross terms and is invariant under rigid motion, because the
    // in-plane block of E is identically zero for a rotation. Every live bond
    // at such a node lies in that plane, so nothing the criterion reads is lost.
    const Real un[3] = {L.node_unmeasured[3 * i], L.node_unmeasured[3 * i + 1],
                        L.node_unmeasured[3 * i + 2]};
    if (un[0] * un[0] + un[1] * un[1] + un[2] * un[2] > Real(0)) {
        const Real a[3] = {e[0] * un[0] + e[3] * un[1] + e[4] * un[2],
                           e[3] * un[0] + e[1] * un[1] + e[5] * un[2],
                           e[4] * un[0] + e[5] * un[1] + e[2] * un[2]};
        const Real s = a[0] * un[0] + a[1] * un[1] + a[2] * un[2];
        const int rows[6] = {0, 1, 2, 0, 0, 1};
        const int cols[6] = {0, 1, 2, 1, 2, 2};
        for (int q = 0; q < 6; ++q)
            e[q] += -un[rows[q]] * a[cols[q]] - a[rows[q]] * un[cols[q]] +
                    s * un[rows[q]] * un[cols[q]];
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

// ---------------------------------------------------------------------------
// Axial plasticity (material/NetworkMaterial.cpp advanceNetworkBond).
// ---------------------------------------------------------------------------
// The bond's recoverable extension: how far it is stretched past the rest
// length it has NOW, which is its original rest length plus whatever permanent
// extension it has taken. With plastic_extension zero this is
// `length - rest_length`, the expression storedBondEnergy has always used, and
// `x - 0` is x for every finite x, so the elastic lane is unchanged bit for bit.
template <typename Real>
BANJO_HD Real bondElasticExtension(const LatticeArrays<Real> &L, std::uint32_t j, bool direct) {
    return length(bondVector(L, j, direct)) - L.rest_length[j] - L.plastic_extension[j];
}

// BondFailure.cpp storedBondEnergy at the current configuration, on the elastic
// extension: plastic work is dissipated, so it is never stored here.
template <typename Real>
BANJO_HD Real storedBondEnergy(const LatticeArrays<Real> &L, std::uint32_t j, bool direct) {
    const Real c = L.compliance[j];
    if (c <= Real(0)) return Real(0);
    const Real extension = bondElasticExtension(L, j, direct);
    return Real(0.5) * extension * extension / c;
}

// One bond's return mapping, run once per substep. This is
// advanceNetworkBond's plasticity block (NetworkMaterial.cpp lines 106-117) on
// this lattice's bond, with two stated departures:
//
//  - the yield extension is `yield_stretch * rest_length` where the network lane
//    divides `yield_force_n` by the bond stiffness. The two are the same number
//    whenever the stiffness is E A / L; this lattice's is not, so the quotient
//    form is the one that gives every bond of the bond family the same yield
//    strain (material/Material.hpp CompiledBrittleMaterial::yield_stretch);
//  - linear isotropic hardening is carried through. The network lane declares
//    `hardening_ratio` and then validates that it is exactly zero, so nothing
//    there exercises it; with `plastic_hardening` zero every line below is the
//    network lane's, including the plastic work, which is then
//    `yield_force * increment` exactly.
//
// The mapping runs once per substep rather than once per constraint iteration,
// so the flow this substep does not depend on how many iterations the solve
// takes. Within one substep the bond can carry more than the yield force -- the
// solve sees the plastic extension it started the substep with -- and the
// overshoot is bounded by how far the load can move in one substep. That is the
// usual explicit-integration statement, and it is why the elastic extension is
// at most the yield extension at every substep boundary.
//
// Returns the plastic work dissipated, which is never stored anywhere as
// elastic energy.
template <typename Real>
BANJO_HD Real bondPlasticReturn(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                                std::uint32_t j, bool direct) {
    if (!(S.plastic_yield_stretch > Real(0))) return Real(0);
    const Real elastic = bondElasticExtension(L, j, direct);
    const Real magnitude = absR(elastic);
    const Real hardening = S.plastic_hardening;
    const Real yield_extension =
        S.plastic_yield_stretch * L.rest_length[j] + hardening * L.plastic_strain[j];
    if (!(magnitude > yield_extension)) return Real(0);
    // |e| - increment = yield + hardening * increment.
    const Real increment = (magnitude - yield_extension) / (Real(1) + hardening);
    L.plastic_extension[j] =
        L.plastic_extension[j] + (elastic < Real(0) ? -increment : increment);
    L.plastic_strain[j] = L.plastic_strain[j] + increment;
    const Real c = L.compliance[j];
    if (!(c > Real(0))) return Real(0);
    // Mean yield force over the increment. With no hardening the two ends are
    // the same number, so this is the network lane's yield_force_n * increment.
    const Real yield_end = yield_extension + hardening * increment;
    return Real(0.5) * (yield_extension + yield_end) * increment / c;
}

struct FailureOutcome {
    bool broke;
    double removed_energy_j;
    std::uint8_t mode;
    // The substep's peaks for this bond, for diagnostics.
    float peak_tensile, peak_compressive, peak_shear;
    // Plastic work dissipated by this bond in this substep, and the permanent
    // extension it now carries as a fraction of its rest length.
    double plastic_increment_j;
    float plastic_stretch;
    // How close this bond now is to failing, 0 to 1, monotone over the run.
    // This is the quantity exit reason 5 watches: it is already computed for
    // the failure test, and unlike a raw strain it is normalised by the bond's
    // own six thresholds, so one number compares across materials.
    float damage;
};

// End-of-substep evaluation for one bond: the plastic return mapping first, as
// advanceNetworkBond does it before its own failure test; then the peaks, which
// are the maximum of the start sample (prev_*) and the sample at the current
// configuration; then evaluateBondDamage and the removal rule of
// applyBondFailure.
//
// The failure surface reads the bond's TOTAL deformation, exactly as before:
// plasticity adds no failure law and changes no threshold. A bond that has flowed
// has spent part of the same stretch budget the criterion measures, which is the
// statement that this lattice's ductile matter ruptures at a total strain.
template <typename Real>
BANJO_HD FailureOutcome bondEndSampleAndFailure(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                                                std::uint32_t j, bool direct) {
    FailureOutcome out{false, 0.0, 0, 0.0F, 0.0F, 0.0F, 0.0, 0.0F, 0.0F};
    if (S.plastic_yield_stretch > Real(0)) {
        out.plastic_increment_j = static_cast<double>(bondPlasticReturn(L, S, j, direct));
        out.plastic_stretch = static_cast<float>(absR(L.plastic_extension[j]) / L.rest_length[j]);
    }
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
    out.damage = static_cast<float>(L.damage[j]);
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
    // The bond pulls towards the rest length it has now: the original one plus
    // whatever permanent extension it has taken (zero for every material that
    // declares no yield strength). Unloading therefore returns it to the new
    // rest length, not the original one, which is what makes a dent stay.
    const Real original_rest = L.rest_length[j];
    const Real plastic = L.plastic_extension[j];
    const Real rest = original_rest + plastic;
    Real constraint;
    if (direct) {
        constraint = current_length - rest;
    } else {
        const V3<Real> du = load3(L.u, b) - load3(L.u, a);
        const V3<Real> r = load3(L.rest_edge, j);
        // |d|^2 - rest^2 = (|d|^2 - original^2) - plastic * (rest + original),
        // keeping the cancellation-free numerator of the displacement path and
        // reducing to it exactly when the plastic extension is zero.
        constraint = (L.rest_length_sq_minus[j] + Real(2) * dot(r, du) + dot(du, du) -
                      plastic * (rest + original_rest)) /
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
    // kilojoules, which is what an uncapped projection injected here. The
    // cap is NOT inert on an infinite plane: under a hard strike the sweep
    // pushes a resting bottom node deeper than its reach in one substep, and
    // the CPU lane projects such a node unconditionally. So the cap applies
    // only to finite footprints, which BrittleBondSolver cannot express.
    if (plane.reach_capped) {
        const Real reach = Real(8) * maxR(Real(0), -approach_normal_speed) * dt + Real(1.0e-5);
        if (-distance > reach) return Real(0);
    }
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

// One node's kinetic energy, and the sphere's. The combined quantity above is
// the right thing to difference across a *single* contact, and the wrong thing
// to sum over a pass: hundreds of nodes touch one sphere in a substep, so
// differencing the combined energy per contact counts the sphere's change once
// per contact. That is how a 111 kg projectile carrying 22 kJ came to report
// 59 kJ of contact dissipation. The pass below differences the sphere once and
// each node once.
template <typename Real>
BANJO_HD Real nodeKineticEnergy(const LatticeArrays<Real> &L, std::uint32_t i) {
    return Real(0.5) * L.mass[i] * length2(load3(L.v, i));
}

template <typename Real>
BANJO_HD Real sphereKineticEnergy(const SphereState<Real> &s) {
    return Real(0.5) * s.mass * length2(s.velocity) +
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
        const Real before = nodeKineticEnergy(L, i);
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
        acc.dissipated_kinetic_energy_j += static_cast<double>(before - nodeKineticEnergy(L, i));
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
    // The sphere is one body meeting many nodes in this pass, so its kinetic
    // energy is differenced once here rather than inside every contact.
    const Real sphere_energy_before = sphereKineticEnergy(sphere);
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
    acc.dissipated_kinetic_energy_j +=
        static_cast<double>(sphere_energy_before - sphereKineticEnergy(sphere));
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
// Node-to-node contact: broad phase.
// ---------------------------------------------------------------------------
// Four steps, in this order. Steps 1 and 3 are per node and independent, so a
// backend may spread them; steps 2 and 4 are one serial scan each and are run by
// one thread on every backend. Nothing in any of them depends on the order the
// threads finish in: step 1 writes only node i's own cell, step 3 writes only
// node i's own pair slots, and the two serial steps walk the nodes in index
// order. The pair list is therefore identical on the serial CPU, the parallel
// CPU and the GPU.

template <typename Real>
BANJO_HD Real nodeContactCutoff(const NodeContactSettings<Real> &c) {
    return Real(2) * c.radius + c.skin;
}

BANJO_HD std::uint32_t nodeContactBucket(std::int32_t ix, std::int32_t iy, std::int32_t iz,
                                         std::uint32_t mask) {
    // Teschner's spatial hash: three large primes, exclusive-or, masked to the
    // table. Collisions are harmless because the gather compares the stored grid
    // coordinates before accepting a node.
    const std::uint32_t h = (static_cast<std::uint32_t>(ix) * 73856093U) ^
                            (static_cast<std::uint32_t>(iy) * 19349663U) ^
                            (static_cast<std::uint32_t>(iz) * 83492791U);
    return h & mask;
}

// Step 1, per node: the node's grid cell, and the displacement the list is
// built at, which the staleness test measures drift against.
template <typename Real>
BANJO_HD void nodeContactStoreCell(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                                   std::uint32_t i) {
    const Real inverse_cell = Real(1) / nodeContactCutoff(S.node_contact);
    const V3<Real> p = position(L, i);
    L.node_cell[3 * i] = static_cast<std::int32_t>(floorR(p.x * inverse_cell));
    L.node_cell[3 * i + 1] = static_cast<std::int32_t>(floorR(p.y * inverse_cell));
    L.node_cell[3 * i + 2] = static_cast<std::int32_t>(floorR(p.z * inverse_cell));
    store3(L.build_u, i, load3(L.u, i));
}

// Step 2, one thread: counting sort of the nodes into the hash buckets.
template <typename Real>
BANJO_HD void nodeContactHashBuild(const LatticeArrays<Real> &L, const StepSettings<Real> &S) {
    const std::uint32_t buckets = S.node_contact.bucket_mask + 1U;
    for (std::uint32_t b = 0; b <= buckets; ++b) L.bucket_begin[b] = 0U;
    for (std::uint32_t i = 0; i < L.node_count; ++i) {
        if (L.mass[i] <= Real(0)) continue;
        const std::uint32_t b = nodeContactBucket(L.node_cell[3 * i], L.node_cell[3 * i + 1],
                                                  L.node_cell[3 * i + 2], S.node_contact.bucket_mask);
        ++L.bucket_begin[b + 1U];
    }
    for (std::uint32_t b = 0; b < buckets; ++b) L.bucket_begin[b + 1U] += L.bucket_begin[b];
    for (std::uint32_t b = 0; b < buckets; ++b) L.bucket_cursor[b] = L.bucket_begin[b];
    for (std::uint32_t i = 0; i < L.node_count; ++i) {
        if (L.mass[i] <= Real(0)) continue;
        const std::uint32_t b = nodeContactBucket(L.node_cell[3 * i], L.node_cell[3 * i + 1],
                                                  L.node_cell[3 * i + 2], S.node_contact.bucket_mask);
        L.bucket_nodes[L.bucket_cursor[b]++] = i;
    }
}

// Step 3, per node: the pairs node i owns. A pair belongs to its lower-index
// end, so every unordered pair is emitted exactly once. Returns the pairs that
// did not fit in the node's slots (a diagnostic; the cap is generous).
template <typename Real>
BANJO_HD std::uint32_t nodeContactGather(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                                         std::uint32_t i) {
    L.pair_fill[i] = 0U;
    if (L.mass[i] <= Real(0)) return 0U;
    const NodeContactSettings<Real> &c = S.node_contact;
    const Real cutoff = nodeContactCutoff(c);
    const Real cutoff_squared = cutoff * cutoff;
    const V3<Real> p = position(L, i);
    const std::int32_t cx = L.node_cell[3 * i], cy = L.node_cell[3 * i + 1], cz = L.node_cell[3 * i + 2];
    std::uint32_t fill = 0U, overflow = 0U;
    for (std::int32_t dz = -1; dz <= 1; ++dz) {
        for (std::int32_t dy = -1; dy <= 1; ++dy) {
            for (std::int32_t dx = -1; dx <= 1; ++dx) {
                const std::int32_t gx = cx + dx, gy = cy + dy, gz = cz + dz;
                const std::uint32_t b = nodeContactBucket(gx, gy, gz, c.bucket_mask);
                for (std::uint32_t k = L.bucket_begin[b]; k < L.bucket_begin[b + 1U]; ++k) {
                    const std::uint32_t j = L.bucket_nodes[k];
                    if (j <= i) continue;
                    // One bucket can hold several grid cells; take only the
                    // nodes of the cell this scan is visiting, so a collision
                    // never emits a pair twice.
                    if (L.node_cell[3 * j] != gx || L.node_cell[3 * j + 1] != gy ||
                        L.node_cell[3 * j + 2] != gz)
                        continue;
                    if (length2(position(L, j) - p) > cutoff_squared) continue;
                    // The rule: a live bond already holds this pair.
                    std::uint32_t bond = kNoBond;
                    bool held_by_a_live_bond = false;
                    for (std::uint32_t s = 0; s < L.max_degree; ++s) {
                        const std::uint32_t slot = s * L.node_count + i;
                        const std::uint32_t bj = L.nbr_bond[slot];
                        if (bj == kNoBond) break;
                        if (L.nbr_other[slot] != j) continue;
                        bond = bj;
                        held_by_a_live_bond = L.nbr_alive[slot] != 0U;
                        break;
                    }
                    if (held_by_a_live_bond) continue;
                    if (fill >= kMaxPairsPerNode) {
                        ++overflow;
                        continue;
                    }
                    L.pair_other[kMaxPairsPerNode * i + fill] = j;
                    L.pair_bond[kMaxPairsPerNode * i + fill] = bond;
                    ++fill;
                }
            }
        }
    }
    L.pair_fill[i] = fill;
    return overflow;
}

// Step 4, one thread: the ascending list of nodes that own at least one pair.
// The narrow phase walks this instead of every node, so an intact lattice --
// where no pair is unbonded and the list is empty -- costs nothing per substep.
template <typename Real>
BANJO_HD std::uint32_t nodeContactActiveList(const LatticeArrays<Real> &L) {
    std::uint32_t count = 0U, pairs = 0U;
    for (std::uint32_t i = 0; i < L.node_count; ++i) {
        if (L.pair_fill[i] == 0U) continue;
        L.pair_node_list[count++] = i;
        pairs += L.pair_fill[i];
    }
    L.pair_node_count[0] = count;
    return pairs;
}

// Whether the list has to be rebuilt before it is used: a node has drifted more
// than half the skin since the build, so a pair that was outside the cutoff then
// could be inside the contact distance now. One serial scan on every backend.
template <typename Real>
BANJO_HD bool nodeContactStale(const LatticeArrays<Real> &L, const StepSettings<Real> &S) {
    const Real half_skin = Real(0.5) * S.node_contact.skin;
    const Real limit = half_skin * half_skin;
    for (std::uint32_t i = 0; i < L.node_count; ++i) {
        const V3<Real> drift = load3(L.u, i) - load3(L.build_u, i);
        if (length2(drift) > limit) return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// Node-to-node contact: narrow phase.
// ---------------------------------------------------------------------------
// One authoritative response per pair: a single normal impulse with the
// restitution rule the striker uses, then one Coulomb friction impulse, then one
// overlap correction, all applied equal and opposite so the pair's momentum is
// unchanged and its centre of mass does not move. It is sphereContactNode with
// the rigid ball replaced by a second node of finite mass.
template <typename Real>
BANJO_HD void nodeContactPair(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                              std::uint32_t a, std::uint32_t b, std::uint32_t bond,
                              NodeContactAccumulators &acc) {
    // The rule, restated where the response is applied.
    if (bond != kNoBond && L.alive[bond]) return;
    const Real ma = L.mass[a], mb = L.mass[b];
    if (ma <= Real(0) || mb <= Real(0)) return;
    const NodeContactSettings<Real> &c = S.node_contact;
    ++acc.pair_tests;
    const V3<Real> r = position(L, b) - position(L, a);
    const Real distance = length(r);
    const V3<Real> normal = normalized(r); // a -> b
    const Real gap = distance - Real(2) * c.radius;
    // Recorded before the engagement test, and in the measure mode too: the
    // deepest interpenetration of a pass-through happens when the two cells are
    // already separating, which the engagement test would skip.
    if (gap < Real(0) && -gap > Real(acc.maximum_overlap_m))
        acc.maximum_overlap_m = static_cast<double>(-gap);
    if (c.mode != kNodeContactOn) return;

    V3<Real> va = load3(L.v, a), vb = load3(L.v, b);
    const Real vn = dot(vb - va, normal); // negative while approaching
    if (gap > maxR(c.margin, -vn * S.dt)) return;
    const Real inverse_a = Real(1) / ma, inverse_b = Real(1) / mb;
    const Real inverse_pair_mass = inverse_a + inverse_b;
    const Real restitution = -vn > c.restitution_speed_threshold ? c.restitution : Real(0);
    const Real desired_vn = gap > c.margin ? -gap / S.dt : -restitution * minR(vn, Real(0));
    const Real normal_impulse = maxR(Real(0), (desired_vn - vn) / inverse_pair_mass);
    if (normal_impulse > Real(0)) {
        const V3<Real> va_before = va, vb_before = vb;
        const Real before = Real(0.5) * ma * length2(va) + Real(0.5) * mb * length2(vb);
        // impulse acts on b, and its negative on a: equal and opposite by
        // construction, so no momentum is created by the pair.
        const auto apply = [&](V3<Real> impulse) {
            vb = vb + inverse_b * impulse;
            va = va - inverse_a * impulse;
        };
        apply(normal_impulse * normal);
        const V3<Real> relative = vb - va;
        const V3<Real> tangent = relative - dot(relative, normal) * normal;
        const Real tangent_speed = length(tangent);
        if (tangent_speed > Real(1.0e-12)) {
            const V3<Real> direction = tangent / tangent_speed;
            const Real sticking_impulse = tangent_speed / inverse_pair_mass;
            const Real friction_impulse = sticking_impulse <= c.static_friction * normal_impulse
                ? sticking_impulse : minR(sticking_impulse, c.dynamic_friction * normal_impulse);
            apply(-friction_impulse * direction);
        }
        store3(L.v, a, va);
        store3(L.v, b, vb);
        acc.dissipated_kinetic_energy_j += static_cast<double>(
            before - (Real(0.5) * ma * length2(va) + Real(0.5) * mb * length2(vb)));
        acc.momentum_residual_x += static_cast<double>(ma * (va.x - va_before.x) + mb * (vb.x - vb_before.x));
        acc.momentum_residual_y += static_cast<double>(ma * (va.y - va_before.y) + mb * (vb.y - vb_before.y));
        acc.momentum_residual_z += static_cast<double>(ma * (va.z - va_before.z) + mb * (vb.z - vb_before.z));
        ++acc.contacts;
    }
    if (gap < -c.margin) {
        const Real correction = minR(-gap - c.margin, Real(0.2) * c.radius);
        const V3<Real> shift = (correction / inverse_pair_mass) * normal;
        store3(L.u, a, load3(L.u, a) - inverse_a * shift);
        store3(L.u, b, load3(L.u, b) + inverse_b * shift);
        if (correction > Real(acc.maximum_position_correction_m))
            acc.maximum_position_correction_m = static_cast<double>(correction);
    }
}

// The whole narrow phase, sequential in pair order: owner node ascending, then
// slot ascending. Like the striker pass it is one thread's work on every
// backend, because the response of one pair changes the state the next pair
// sees, and a fixed order is what makes the parallel backend bit identical to
// the serial one.
template <typename Real>
BANJO_HD void nodeContactPass(const LatticeArrays<Real> &L, const StepSettings<Real> &S,
                              NodeContactAccumulators &acc) {
    const std::uint32_t owners = L.pair_node_count[0];
    for (std::uint32_t k = 0; k < owners; ++k) {
        const std::uint32_t a = L.pair_node_list[k];
        const std::uint32_t fill = L.pair_fill[a];
        for (std::uint32_t p = 0; p < fill; ++p) {
            const std::uint32_t slot = kMaxPairsPerNode * a + p;
            nodeContactPair(L, S, a, L.pair_other[slot], L.pair_bond[slot], acc);
        }
    }
}

// Total kinetic energy of the lattice, serial so the sum is in node order on
// every backend. Used only by the energy audit (StepSettings::audit_energy),
// which brackets the damping sweep and the contact passes to attribute the
// dissipation of each separately.
template <typename Real>
BANJO_HD double latticeKineticEnergy(const LatticeArrays<Real> &L) {
    double total = 0.0;
    for (std::uint32_t i = 0; i < L.node_count; ++i)
        total += static_cast<double>(Real(0.5) * L.mass[i] * length2(load3(L.v, i)));
    return total;
}

// Elastic energy stored in the live bonds, serial so the sum is in bond order
// on every backend. Plastic work is not in it: storedBondEnergy measures the
// recoverable extension only, so a bond that has flowed and then unloaded to its
// new rest length stores nothing. Used by the energy ledger.
template <typename Real>
BANJO_HD double latticeElasticEnergy(const LatticeArrays<Real> &L, bool direct) {
    double total = 0.0;
    for (std::uint32_t j = 0; j < L.bond_count; ++j) {
        if (!L.alive[j]) continue;
        total += static_cast<double>(storedBondEnergy(L, j, direct));
    }
    return total;
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
// min_steps in total), 2 nothing has failed by no_failure_steps, 4 the removed
// energy has stopped growing, 5 nothing is anywhere near failing.
//
// Reason 5 is the cheap exit for a scene that never breaks, and those are most
// of them: a ball rolling down a ramp, a stack standing there. Measured on a
// four-object ski ramp of 9,056 cells, the lattice phase spent 11.46 s of wall
// clock covering 20 ms of simulated time -- 573x realtime, 91% of the whole
// run's compute, for 0.5% of the watched time -- and broke nothing, because the
// worst-stressed bond never got past a tenth of its failure strain. Waiting out
// no_failure_steps to establish that is the most expensive way to learn nothing.
//
// The test is on damage rather than on a strain, because damage is already
// normalised by each bond's own thresholds: below calm_damage_margin, with no
// material rise for calm_steps, means the lattice is not being loaded toward
// failure at all. It is deliberately not a promise about the future -- a later
// impact is a new event, and re-entering the lattice on contact is what the
// refracture lane is for.
//
// Reason 4 exists because the three things this phase produces settle at very
// different times. Measured on a 250 x 200 x 20 mm glass plate, against the same
// run taken to 1,058 wave transits: removed energy is within 0.8% of its final
// value by 106 transits, while the piece count is still 38% short there and 12%
// short at 212. Waiting for the pieces costs five to ten times the wall clock
// and buys a number that does not converge in cell size, time step, sweep order
// or precision either, so it was never a quantity to wait on. Energy is, and it
// is the one quantity every lane in this repository agrees converges.
BANJO_HD unsigned latticeExitReason(unsigned long long completed, unsigned broken,
                                    unsigned long long last_failure_step,
                                    unsigned long long quiet_steps,
                                    unsigned long long min_steps,
                                    unsigned long long no_failure_steps,
                                    unsigned long long energy_flat_steps,
                                    unsigned long long last_energy_gain_step,
                                    unsigned long long calm_steps,
                                    unsigned long long last_damage_gain_step,
                                    double max_damage, double calm_damage_margin) {
    if (broken > 0U && quiet_steps > 0ULL && completed >= min_steps &&
        completed > last_failure_step && completed - last_failure_step > quiet_steps)
        return 1U;
    if (broken == 0U && no_failure_steps > 0ULL && completed >= no_failure_steps) return 2U;
    if (broken == 0U && calm_steps > 0ULL && completed >= calm_steps &&
        max_damage < calm_damage_margin && completed > last_damage_gain_step &&
        completed - last_damage_gain_step > calm_steps)
        return 5U;
    if (broken > 0U && energy_flat_steps > 0ULL && completed >= min_steps &&
        completed > last_energy_gain_step && completed - last_energy_gain_step > energy_flat_steps)
        return 4U;
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
