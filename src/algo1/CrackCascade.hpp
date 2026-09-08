#pragma once

// Algorithm 1, the run-time half: an impact evaluated against the precomputed
// impulse-response library, screened in one matrix-vector product, and cascaded
// with Woodbury crack updates. No eigenvector is ever updated.
//
// Three stages, in order:
//
//   1. Contact. The ball's momentum enters the plate. Two models are offered
//      and both are stated in the report: `impulse` delivers the whole momentum
//      transfer as one impulse at t = 0 over the cells the ball's footprint
//      covers (the literal reading of the algorithm), and `tracked` resolves
//      frictionless normal contact against the intact plate once per substep
//      with the library's own (diagonal-mass) impulse response, which is what
//      an object of this size and speed actually does.
//   2. Screen. |eps_b(t)| is bounded above from the modal envelope, and the
//      nonlocal strain the shared criterion reads is bounded from the same
//      envelope through the node's rest covariance. One (bonds x modes) product
//      says whether anything can break at all and from what time; the samples
//      before that time are never taken.
//   3. Cascade. Each round: the intact modal field, plus the Woodbury
//      correction from the bonds released so far, is written into the lattice
//      and handed to the unchanged shared criterion. Bonds that fail are added
//      to the released set; the k x k inverse is extended by bordering in
//      O(k^2). Cost per round is O(n k) + O(k^2), never O(n k^2).
//
// Exact: the intact response (the modal evolution has no time step), and the
// first failure, which is read from that response by the shared criterion.
// Hypothesis: that each released bond may be treated quasi-statically while the
// impact loading stays dynamic. That is what section "accuracy" of the
// checkpoint measures against the reference; it is not assumed here.

#include "algo1/ImpulseLibrary.hpp"
#include "fracture/ActiveMatter.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace banjo::algo1 {

enum class ContactModel : std::uint8_t { SingleImpulse, Tracked };

struct Ball {
    Vec3 center_m{};
    Vec3 velocity_m_s{};
    double radius_m{};
    double contact_radius_m{};
    double mass_kg{};
};

struct CascadeSettings {
    double sample_dt_s{1.0e-6};
    double window_s{6.0e-3};
    // Modal damping ratio, applied to every elastic mode. The reference lane
    // runs undamped, so this is 0 by default and any non-zero value is a
    // declared model change, not a tuning knob.
    double damping_ratio{0.0};
    ContactModel contact{ContactModel::Tracked};
    // Restitution used by the single-impulse model only.
    double restitution{0.0};
    Vec3 gravity_m_s2{0.0, -9.81, 0.0};
    // Gravity acts on the ball during the window; the plate's own weight is a
    // static pre-load 1e-7 in strain over a window this short and is left out,
    // as the modal lane leaves it out.
    bool plate_gravity{false};
    // Points on the coarse time grid the screen uses to find the earliest
    // instant at which any bond can reach a threshold.
    unsigned screen_grid{16};
    // Stop the cascade this long after the last failure with no new failure.
    double quiet_s{1.5e-3};
    unsigned maximum_rounds{20000};
    // Frames recorded during the window, beyond one per round.
    double frame_interval_s{2.0e-4};
    unsigned maximum_frames{400};
    // Contact solver.
    unsigned contact_sweeps{32};
    // Uniform cell size, used only to place the single-impulse footprint.
    double cell_m{0.01};
    // Fraction of the penetration removed per substep by the contact solve.
    double penetration_recovery{0.8};
    // A released bond whose Schur complement falls below this fraction of the
    // bond's own compliance has detached a mechanism: the quasi-static
    // correction is unbounded there and the bond is left out of it.
    double schur_floor{1.0e-9};
};

struct CascadeRound {
    double time_s{};
    std::vector<std::uint32_t> bonds;
    double removed_energy_j{};
    std::size_t released_total{};
    std::size_t components_after{};
    double update_wall_s{};
    double largest_correction_m{};
    unsigned singular_releases{};
};

struct CascadeFrame {
    double time_s{};
    std::vector<Vec3> positions;
    std::vector<std::uint32_t> component;
    Vec3 ball_center{};
    std::vector<std::uint8_t> bond_alive;
    std::vector<float> bond_damage;
    std::size_t broken{};
};

struct ScreenReport {
    std::size_t candidate_bonds{};
    double wall_s{};
    double earliest_possible_failure_s{-1.0};
    // The largest bound over all bonds, as a multiple of that bond's smallest
    // break threshold, at the end of the window.
    double largest_bound_ratio{};
    bool anything_can_break{};
    std::size_t bonds_screened{};
};

struct ContactReport {
    std::string model;
    double impulse_n_s{};              // |sum of the impulses delivered to the plate|
    double axial_impulse_n_s{};        // along the ball's initial direction
    double total_impulse_magnitude_n_s{};
    std::size_t contact_nodes{};       // distinct cells that ever carried an impulse
    std::size_t events{};
    double duration_s{};
    double maximum_penetration_m{};
    double largest_node_displacement_m{};
    double ball_speed_end_m_s{};
    double wall_s{};
};

struct CascadeTimings {
    double contact_s{}, screen_s{}, sample_s{}, field_s{}, criterion_s{}, woodbury_s{}, frames_s{}, total_s{};
};

struct CascadeResult {
    std::vector<CascadeRound> rounds;
    std::vector<CascadeFrame> frames;
    ScreenReport screen{};
    ContactReport contact{};
    CascadeTimings timings{};
    std::size_t samples{};
    std::size_t skipped_samples{};
    std::size_t broken_bonds{};
    std::size_t components{};
    std::size_t largest_component_cells{};
    double largest_component_mass_kg{};
    double removed_energy_j{};
    double first_failure_time_s{-1.0};
    std::vector<std::uint32_t> first_failure_bonds;
    double last_failure_time_s{-1.0};
    double simulated_s{};
    double maximum_tensile_stretch{}, maximum_compressive_strain{}, maximum_shear_strain{};
    unsigned singular_releases{};
    Ball ball{};
};

// Runs the window on `matter`. On return the lattice's positions, velocities,
// bond aliveness and damage describe the end of the window and `ball` has been
// advanced. `matter` and `library` must describe the same lattice.
CascadeResult runCrackCascade(ActiveMatter &matter, const ImpulseLibrary &library, Ball &ball,
                              const CascadeSettings &settings);

} // namespace banjo::algo1
