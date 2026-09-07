#pragma once

#include "fracture/BondFailure.hpp"
#include "modal/ModalBasis.hpp"
#include "physics/SphereMaterialContact.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace banjo::modal {

// The precomputed-basis fracture lane.
//
// The intact body is a linear elastic lattice; its response to an impact lies
// in the span of its eigenmodes, and each mode is an independent harmonic
// oscillator with a closed-form solution. So the lane never integrates the
// elastic wave. It advances the modal amplitudes exactly over a sampling
// interval, evaluates the strain field at the sample, and hands that field to
// the *same* failure criterion the stepped lanes use (fracture/BondFailure).
// When bonds fail, the interval is discarded, the bonds are removed at its
// start (StepRestart semantics, as in physics/FractureStep), and the basis is
// downdated by one rank-one update per removed bond instead of being
// recomputed. Pieces are connected components. Nothing here precuts, animates
// or assigns fragment velocities.
//
// The rigid iron ball is coupled through frictionless normal contact against
// the free nodes, resolved once per sampling interval: an impulse applied at
// the interval start, with the basis's own impulse response over the interval,
// puts each penetrating node on the sphere surface at the interval end. This
// mirrors the implicit reference's sphere contact, with the elastic solve
// replaced by the closed form.

enum class BasisMode : std::uint8_t {
    // Rank-one downdate per removed bond (the method under test).
    Update,
    // Full re-decomposition after every round (validation baseline only).
    Recompute,
    // Downdate when a round removes few bonds, re-decompose when it removes
    // many; both are exact, this only chooses the cheaper of two exact paths.
    Auto,
};

struct ModalFractureSettings {
    // Failure-criterion sampling interval and contact substep. Not a
    // stability limit: the elastic evolution between samples is exact. A
    // strain excursion shorter than this can be missed, exactly as the
    // stepped lanes miss one shorter than their step.
    double sample_dt_s{1.0e-6};
    // Simulated duration of the modal phase.
    double window_s{2.0e-3};
    // Gravity applied to nodes and ball.
    Vec3 gravity_m_s2{0.0, -9.81, 0.0};
    // Trials allowed for one interval, counting discarded ones.
    unsigned maximum_trials_per_interval{256};
    unsigned maximum_contact_sweeps{200};
    // Outer passes that admit nodes pushed into the sphere by other impulses.
    unsigned maximum_contact_passes{32};
    double contact_impulse_tolerance{1.0e-12};
    BasisMode basis_mode{BasisMode::Update};
    // Auto mode re-decomposes when a round removes at least this many bonds.
    unsigned rebuild_at_bonds_per_round{6};
    // Fraction of modes kept (lowest frequencies). 1 is the exact basis.
    double retained_mode_fraction{1.0};
    // After every round, compare the updated basis against a fresh
    // decomposition (O(n^3) per round; validation only).
    bool check_basis{false};
    // Record a frame at least this often, plus one per round.
    double frame_interval_s{1.0e-4};
    // Start from the static sag under gravity instead of the undeformed rest.
    bool start_from_static_sag{true};
    // Where in the interval the contact impulse acts. The implicit reference's
    // midpoint rule moves a node by (dt/2) * dv for an end-velocity change dv,
    // so a captured node leaves with twice the closing speed (an elastic
    // capture). An impulse at the interval start moves it by dt * dv and the
    // capture is inelastic. Midpoint reproduces the reference's contact
    // semantics; start is the alternative kept for comparison.
    bool contact_impulse_at_midpoint{true};
};

// The ball as the lane sees it. `contact_radius_m` is the radius at which a
// lattice node (a cell centre) is held: for a cubic cell of size h that is
// the true radius plus h/2, so the ball touches the cell face, not its centre.
struct ModalBall {
    RigidSnapshot motion{};
    double radius_m{};
    double contact_radius_m{};
    double mass_kg{};
    double inertia_kg_m2{};
};

struct ModalRound {
    double time_s{};
    unsigned interval_trial{};
    std::vector<std::uint32_t> bonds;
    std::vector<BondFailureMode> modes;
    // The engine's figure: stored energy of the removed bonds at removal, from
    // the exact bond extension (fracture/BondFailure).
    double removed_bond_energy_j{};
    // The linearised figure the modal ledger uses: 0.5 k (g.u)^2 per bond.
    double removed_linear_energy_j{};
    std::size_t retained_modes_total{};
    std::size_t deflated_total{};
    bool rebuilt{};
    // Largest resolved strain among the removed bonds, as a multiple of the
    // bond's own break threshold. Far above 1 means the nonlocal strain at a
    // node with a degenerate live-neighbour set, not a physical excursion.
    double trigger_over_threshold{};
    // Fewest live neighbours at either end of a removed bond, before removal.
    unsigned fewest_live_neighbours{};
    double update_wall_s{};
    std::size_t components_after{};
    // Only when check_basis: residual and orthogonality after the update, and
    // the largest relative eigenvalue discrepancy against a fresh decomposition.
    double basis_residual{};
    double basis_orthogonality{};
    double basis_value_error{};
};

struct ModalFrame {
    double time_s{};
    std::vector<Vec3> node_positions_m;
    std::vector<std::uint32_t> component_of_node;
    RigidSnapshot ball{};
    std::size_t broken_bonds{};
    std::vector<std::uint8_t> bond_alive;
    std::vector<float> bond_damage;
};

struct ModalTimings {
    double basis_assemble_s{};
    double basis_decompose_s{};
    double evolve_s{};
    double field_s{};
    double contact_s{};
    double criterion_s{};
    double update_s{};
    double components_s{};
    double frames_s{};
    double total_s{};
};

struct ModalLedger {
    double energy_start_j{};
    double energy_end_j{};
    double removed_linear_energy_j{};
    double removed_bond_energy_j{};
    double contact_loss_j{};
    // energy_end - energy_start + removed_linear + contact_loss; exact
    // evolution and exact updates leave only roundoff here.
    double residual_j{};
    double elastic_energy_end_modal_j{};
    double elastic_energy_end_lattice_j{};
};

struct ModalFractureResult {
    std::vector<ModalRound> rounds;
    std::vector<ModalFrame> frames;
    ModalTimings timings{};
    ModalLedger ledger{};
    std::size_t samples{};
    std::size_t trials{};
    std::size_t discarded_trials{};
    std::size_t contact_samples{};
    std::size_t peak_contact_nodes{};
    // Free nodes found inside the contact sphere at an accepted interval end,
    // beyond the impulse tolerance. Must be zero; reported so it cannot hide.
    std::size_t penetration_violations{};
    double maximum_end_penetration_m{};
    // Largest free-node speed seen at any accepted sample.
    double peak_node_speed_m_s{};
    std::size_t contact_passes_exhausted{};
    // The largest single contact impulse applied and its ingredients.
    double largest_impulse_n_s{};
    double largest_impulse_response_w{};
    double largest_impulse_distance_m{};
    double largest_impulse_time_s{};
    std::uint32_t largest_impulse_node{};
    std::size_t largest_impulse_pass{};
    unsigned largest_impulse_sweep{};
    // Ingredients of the response at the largest impulse: the node's own
    // response along the normal, and the spectrum at that time.
    double largest_impulse_node_response{};
    double largest_impulse_omega2_max{};
    double largest_impulse_omega2_min{};
    double largest_impulse_weight_min{};
    double largest_impulse_diag_trace{};
    std::size_t negative_response_events{};
    double most_negative_response{};
    unsigned maximum_sweeps_used{};
    std::size_t sweep_budget_exhausted{};
    std::size_t broken_bonds{};
    std::size_t components{};
    std::size_t largest_component{};
    double first_failure_time_s{-1.0};
    double last_failure_time_s{-1.0};
    double ball_separation_time_s{-1.0};
    bool interval_budget_exhausted{};
    // Largest resolved strains the criterion saw at any sample.
    double maximum_tensile_stretch{};
    double maximum_compressive_strain{};
    double maximum_shear_strain{};
    std::size_t modes{};
    std::size_t rigid_modes_end{};
    double fastest_period_s{};
    double simulated_s{};
};

// Runs the modal phase on `matter`, whose free nodes are named by `free_nodes`
// (every other node is held fixed). On return the lattice's positions,
// velocities, bond aliveness and damage describe the end of the window, and
// the ball's motion is updated in place.
ModalFractureResult runModalImpact(ActiveMatter &matter, const std::vector<std::uint32_t> &free_nodes,
                                   ModalBall &ball, const ModalFractureSettings &settings);

} // namespace banjo::modal
