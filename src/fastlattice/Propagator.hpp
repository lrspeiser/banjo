#pragma once

// Algorithm 3: multi-step propagators for the fast explicit lattice.
//
// For a FIXED topology and with the ball contact disabled, one substep of the
// lattice integrator is a map f on the state x = (u, v) of 6N doubles. This
// header probes that map with the engine's own backend -- never a rederivation
// of the physics -- and, when the probe says the map is affine, builds the
// dense matrix P and its powers so that m substeps cost one matrix-vector
// product instead of m sweeps.
//
// Whether f really is affine is a question about the engine, not an
// assumption: probeLinearity() measures it and the lane reports what it found.
// See docs/algo3-propagator-cones-checkpoint.md.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeSchedule.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace banjo::fastlattice {

// One substep of the engine's own integrator as a map on x = (u, v).
// Every apply() re-uploads a pristine state, so the map depends on nothing but
// x: u_prev is rewritten by the gravity kick, accumulated_lambda is reset on
// the single constraint iteration, engaged is cleared and approach is recorded
// inside the step. Bond aliveness and damage are restored from the pristine
// copy, so the topology is frozen.
class SubstepMap {
public:
    SubstepMap(const LatticeState &state, const LatticeSchedule &schedule,
               const StepSettings<double> &settings, Precision precision);

    [[nodiscard]] std::size_t dimension() const { return 6U * static_cast<std::size_t>(pristine_.node_count); }
    [[nodiscard]] std::uint32_t nodeCount() const { return pristine_.node_count; }
    [[nodiscard]] std::uint64_t applications() const { return applications_; }

    // y = f(x). Both are dimension() doubles: the first 3N are u, the last 3N v.
    void apply(const double *x, double *y);

    // Pack / unpack a LatticeState's (u, v) into a state vector.
    static void pack(const LatticeState &state, double *x);
    static void unpack(const double *x, LatticeState &state);

    // Reference positions, for the cone measurement's distances.
    [[nodiscard]] const LatticeState &referenceState() const { return pristine_; }

private:
    LatticeState pristine_;
    LatticeState scratch_;
    LatticeSchedule schedule_;
    StepSettings<double> settings_;
    SphereState<double> sphere_{};
    std::unique_ptr<LatticeBackend> backend_;
    std::uint64_t applications_{};
};

// What probeLinearity() found. All figures are in metres / metres per second
// on the state vector; "rel" divides by the norm of the tested increment's
// image, so it is the relative error a linear propagator would make.
struct DensePropagator;

struct LinearityReport {
    double amplitude_m{};        // amplitude of the probe increment
    // The displacement and velocity blocks are reported apart: the substep
    // carries u into v through a factor 1/dt, so one norm over both blocks
    // would say nothing about the displacements.
    double u_image{}, v_image{};          // ||g(a)||_inf per block, g(d) = f(x0+d) - f(x0)
    double u_additivity{}, v_additivity{}; // ||g(a+b) - g(a) - g(b)||_inf
    double u_homogeneity{}, v_homogeneity{};
    double additivity_rel{};     // worst of the two blocks, relative to its image
    double homogeneity_rel{};
    std::uint64_t substeps{};
};

// Probe the map around x0 with random increments of the given amplitude.
// samples random directions are drawn from seed. displacement_only perturbs
// the u block alone (a velocity perturbation of the same size is a far larger
// physical disturbance, because a substep turns u into v through 1/dt).
[[nodiscard]] LinearityReport probeLinearity(SubstepMap &map, const double *x0, double amplitude,
                                             unsigned samples, std::uint64_t seed,
                                             bool displacement_only = true);

// How well the dense propagator reproduces the engine's own substep on random
// increments of the given amplitude around p.base.
struct PropagatorCheck {
    double amplitude_m{};
    double u_image{}, v_image{};
    double u_error{}, v_error{};
    double rel_error{};   // worst block, relative to its image
};

[[nodiscard]] PropagatorCheck checkPropagator(SubstepMap &map, const DensePropagator &p, double amplitude,
                                              unsigned samples, std::uint64_t seed,
                                              bool displacement_only = true);

// A dense propagator: y = P (x - x0) + f(x0), stored column-major so that
// column j is contiguous. n = dimension.
struct DensePropagator {
    std::size_t n{};
    std::vector<double> columns; // n * n, column-major
    std::vector<double> offset;  // f(x0) for the affine part
    std::vector<double> base;    // x0
    std::uint32_t power{1};      // how many substeps this propagator advances

    [[nodiscard]] std::size_t bytes() const {
        return columns.size() * sizeof(double) + offset.size() * sizeof(double) + base.size() * sizeof(double);
    }
    // y = P (x - base) + offset.
    void apply(const double *x, double *y) const;
};

// Build P around x0 by applying the engine's substep to x0 + eps e_j for every
// j. Costs dimension() + 1 substeps.
[[nodiscard]] DensePropagator buildPropagator(SubstepMap &map, const double *x0, double eps);

// Q = A^m by repeated squaring of the affine map (both the matrix and the
// offset are squared, so Q advances m substeps of the affine map exactly).
[[nodiscard]] DensePropagator propagatorPower(const DensePropagator &base, std::uint32_t m,
                                              unsigned threads, double *gemm_seconds);

// How far one node's displacement has spread after a number of substeps. The
// support is exact: a node counts as touched when any component of its (u, v)
// differs at all from the unperturbed trajectory, which is what exactness
// demands of a causal cone -- a difference of one ulp still flips a threshold.
struct ConeGrowth {
    std::uint64_t substeps{};
    std::uint32_t touched_nodes{};
    double touched_fraction{};
    double max_cell_distance{};  // from the seeded node, in cell widths
    double max_du_m{};
};

// Perturb node `seed_node` by `delta` in x and step both trajectories, with the
// ball contact disabled, reporting the support at each checkpoint.
[[nodiscard]] std::vector<ConeGrowth> measureCone(SubstepMap &map, const double *x0,
                                                  std::uint32_t seed_node, double delta,
                                                  const std::vector<std::uint64_t> &checkpoints,
                                                  double cell_size_m);

// Wall seconds of one dense n x n multiply in the given precision: the unit
// cost of a repeated squaring, measured rather than assumed.
[[nodiscard]] double measureGemmSeconds(std::size_t n, unsigned threads, bool single_precision);

// Cache. The key is the scene: plate, cell, support, material, substep, power.
struct PropagatorCacheKey {
    std::string scene;   // canonical scene description
    std::uint32_t power{};
    [[nodiscard]] std::string fileName() const;
};

[[nodiscard]] bool loadPropagator(const std::filesystem::path &dir, const PropagatorCacheKey &key,
                                  DensePropagator &out);
bool storePropagator(const std::filesystem::path &dir, const PropagatorCacheKey &key,
                     const DensePropagator &p);

} // namespace banjo::fastlattice
