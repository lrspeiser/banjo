#pragma once

#include "core/Plane.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/BondFailure.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace banjo {

// Quasi-static fracture: the crack pattern of an impact without the wave.
//
// The dynamic lanes obtain the strain field the failure criterion reads by
// integrating the elastic wave at sub-microsecond steps. The whole fracture
// event is sub-frame (a crack crosses a 240 mm plate in ~140 us), so nobody
// sees the transient; what has to be right is the outcome. This lane therefore
// solves static equilibrium of the intact lattice under the impact load,
// applies the ONE shared failure criterion (fracture/BondFailure.hpp,
// unchanged), removes what fails, re-solves, and repeats until nothing more
// fails. Pieces are the connected components that remain. Nothing here precuts
// geometry, animates a shatter, adds an impulse or assigns a fragment velocity.
//
// The load is the ball's kinetic energy. The ball is a rigid sphere pushed
// along its direction of travel; every contacted node is held on its surface
// (frictionless, unilateral). The work the ball does on the lattice is
// integrated along its travel and the ball stops when that work equals its
// kinetic energy, or goes through when nothing statically supported is left
// in its path. That is an energy budget from the impact, which AGENTS.md
// allows; a hand-drawn crack pattern is not.
//
// What the static picture cannot know, it pins and reports: the rigid-body
// modes a frictionless unilateral support leaves free (sliding and spinning in
// its plane) are deflated from the solve and the net force that pin carries is
// reported against the normal force, a piece that loses its static support is
// frozen where it is (its stored energy is reported as released, not silently
// kept), and a node whose live bonds no longer span three dimensions has its
// mechanism direction pinned and counted. None of these is a tolerance.

// ---------------------------------------------------------------------------
// Static equilibrium of the live bond lattice, linearised about the reference
// configuration: K u = f with K = sum over live bonds of k (d d^T) on the
// [a,b] pair, d the rest direction of the bond. Strains here are ~1e-3, so the
// linearisation error is of that order relative and the shared criterion is
// still evaluated on the actual positions X + u.

struct StaticConstraint {
    std::uint32_t node{};
    Vec3 direction{}; // unit
    double value{};   // direction . u = value
    // Whether this constraint counts as anchoring a component's rigid modes.
    // Support and frozen constraints do; a ball contact does not, because the
    // frame's friction, not the ball, is what keeps a tile from sliding.
    bool anchors_rigid_modes{true};
};

struct StaticSolveSettings {
    double relative_tolerance{1.0e-10};
    unsigned maximum_iterations{200000};
    // A free direction at a node whose stiffness is below this fraction of the
    // stiffest bond in the lattice is a mechanism (a dangling node, a hinge).
    // Statics has no answer for it, so it is pinned and counted.
    double mechanism_stiffness_ratio{1.0e-8};
    // Pin mechanism directions at zero rather than at the current displacement
    // (used for rate problems, whose unknown is a displacement per unit travel).
    bool pin_mechanisms_at_zero{};
};

struct StaticSolveResult {
    bool converged{};
    unsigned iterations{};
    double relative_residual{};
    // Why a solve did not converge, and what the constraint set looked like.
    const char *failure{};
    std::size_t dependent_constraints{};
    double maximum_prescribed_m{};
    // Per input constraint: the force the constraint exerts on its node along
    // its direction. For a unilateral contact this must be >= 0.
    std::vector<double> reactions_n;
    std::size_t pinned_mechanism_directions{};
    double pinned_mechanism_force_n{};
    // Rigid modes a component could still perform under its constraints
    // (in-plane sliding and spinning on a frictionless support, every mode of
    // a free piece). They are deflated from the solve; the net force and torque
    // the deflation removed is what the pins carry.
    std::size_t deflated_modes{};
    double pinned_rigid_force_n{};
    double pinned_rigid_torque_n_m{};
    // Zero-stiffness directions the iteration ran into and pinned (a flap on a
    // hinge, invisible to the per-node check); their load joins
    // pinned_mechanism_force_n.
    std::size_t deflated_mechanism_modes{};
};

class StaticLatticeSolver {
public:
    explicit StaticLatticeSolver(const ActiveMatter &matter);
    // Re-read the live bond set after a topology change.
    void rebuild();
    // Preconditioned conjugate gradients on the constrained subspace. The
    // displacement is the warm start on entry and the solution on exit; a
    // failed solve leaves it as it was.
    // component_of_node, when given, enables rigid-mode deflation per connected
    // component (see StaticSolveResult); without it a floating component makes
    // the operator singular and the solve reports failure.
    [[nodiscard]] StaticSolveResult solve(const std::vector<Vec3> &loads_n,
        const std::vector<StaticConstraint> &constraints, std::vector<Vec3> &displacement_m,
        const StaticSolveSettings &settings = {}, const std::vector<std::uint32_t> *component_of_node = nullptr) const;
    void applyStiffness(const std::vector<Vec3> &displacement_m, std::vector<Vec3> &force_n) const;
    [[nodiscard]] double elasticEnergy(const std::vector<Vec3> &displacement_m) const;
    // Linearised stored energy of one bond (live or not) at this displacement.
    [[nodiscard]] double bondElasticEnergy(std::uint32_t bond, const std::vector<Vec3> &displacement_m) const;
    [[nodiscard]] double referenceStiffness() const { return reference_stiffness_; }
    // Per node, how many directions its live bonds stiffen above the given
    // fraction of the stiffest bond (3 = fully stiffened, less = a mechanism).
    [[nodiscard]] std::vector<unsigned> nodeStiffnessRanks(double stiffness_ratio) const;
    [[nodiscard]] std::size_t liveBonds() const { return edges_.size(); }

private:
    struct Edge {
        std::uint32_t a{}, b{}, bond{};
        Vec3 direction{};
        double stiffness{};
    };
    const ActiveMatter *matter_;
    std::vector<Edge> edges_;
    std::vector<Mat3> diagonal_;
    double reference_stiffness_{};
};

// ---------------------------------------------------------------------------
// The impact.

struct QuasiStaticImpactScene {
    Vec3 gravity_m_s2{};
    // The plane the support-eligible nodes may rest on (unilateral, with the
    // in-plane friction lock described above). Nodes not listed pass through
    // it: a tile on a frame has a hole under it.
    SupportPlaneFrame support{};
    std::vector<std::uint32_t> support_nodes;
    // Ball at the instant of first contact, travelling along ball_direction.
    Vec3 ball_center_m{};
    Vec3 ball_direction{0.0, -1.0, 0.0};
    double ball_radius_m{};
    double ball_mass_kg{};
    double ball_speed_m_s{};
    // The ball is not followed further than this along its travel.
    double maximum_travel_m{};
};

struct QuasiStaticImpactSettings {
    StaticSolveSettings solver{};
    unsigned maximum_events{100000};
    unsigned maximum_rounds{200000};
    unsigned maximum_active_set_iterations{500};
    // Relative overshoot of the failure ratio an event lands at, so that the
    // shared criterion, evaluated at the event state, removes the bond.
    double event_overshoot{1.0e-9};
    // Print every solve, event and round to stderr.
    bool trace{};
    // A component needs this many non-collinear active support nodes to have a
    // static answer; below it, it is frozen and handed on as a rigid piece.
    unsigned minimum_support_nodes{3};
};

enum class QuasiStaticStop : std::uint8_t {
    None,
    // The ball's kinetic energy is exhausted; the lattice held it.
    BallStopped,
    // Nothing statically supported is left in the ball's path.
    BallThrough,
    // The ball reached maximum_travel_m while still loading the lattice.
    TravelLimit,
    EventBudget,
    RoundBudget,
    SolverFailed,
    ActiveSetFailed,
};

[[nodiscard]] const char *quasiStaticStopName(QuasiStaticStop stop);

struct QuasiStaticImpactEvent {
    double travel_m{};
    unsigned rounds{};
    std::size_t bonds_removed{};
    double contact_force_n{};
    double ball_work_j{};
    double stored_elastic_j{};
    std::size_t components{};
    std::size_t frozen_components{};
};

struct QuasiStaticImpactResult {
    bool converged{};
    QuasiStaticStop stop{QuasiStaticStop::None};

    unsigned events{};
    unsigned rounds{};
    unsigned static_solves{};
    unsigned linear_iterations{};
    unsigned active_set_iterations{};

    double travel_m{};
    Vec3 ball_center_m{};
    // Ball velocity implied by the energy balance at the stop: the remaining
    // kinetic energy along the travel direction when it went through, or the
    // stored elastic energy returned against it when the lattice held.
    Vec3 ball_velocity_m_s{};

    // Ledger. kinetic_in = ball_work + kinetic_out, and
    // ball_work = (potential_end - potential_start) + removed_linear
    //           + released + relaxation, every term named.
    double kinetic_energy_in_j{};
    double ball_work_j{};
    double kinetic_energy_out_j{};
    double potential_start_j{};
    double potential_end_j{};
    double stored_elastic_j{};
    // Stored energy of removed bonds as the shared criterion reports it (from
    // actual positions) and as this lane's linear model carries it.
    double removed_bond_energy_j{};
    double removed_bond_energy_linear_j{};
    double released_energy_j{};
    double relaxation_energy_j{};
    // Largest disagreement, over all segments, between the ball's work and the
    // change of the lattice potential. Zero up to rounding if the reactions
    // are right; it is the ledger's independent check.
    double segment_work_mismatch_j{};

    // The support is frictionless; the rigid in-plane modes it leaves free are
    // pinned (deflated) and the net force that pin carried, over the total
    // normal force, is the friction coefficient the frame would need.
    double maximum_support_normal_force_n{};
    double total_support_normal_force_n{};
    double required_friction_coefficient{};
    double pinned_rigid_force_n{};
    double pinned_rigid_torque_n_m{};
    std::size_t pinned_mechanism_directions{};
    std::size_t pinned_mechanism_modes{};
    double pinned_mechanism_force_n{};

    std::size_t broken_bonds{};
    std::size_t components{};
    std::size_t frozen_components{};
    BondFailureModeCounts failure_modes{};
    std::vector<std::uint32_t> first_failure_bonds;
    double first_failure_travel_m{};
    double first_failure_force_n{};
    // Indexed like findConnectedComponents(matter) at the end of the run.
    std::vector<bool> component_frozen;
    std::vector<QuasiStaticImpactEvent> log;

    double solve_wall_s{};
    double criterion_wall_s{};
    double topology_wall_s{};
};

// Runs the cascade on the lattice. On return the node positions are the
// static configuration at the stop (frozen pieces at their rest shape), node
// velocities are untouched (they are not a static quantity), and bond damage
// and aliveness carry the criterion's decisions. Node masses must be positive
// and reference_positions_world_m must be set.
[[nodiscard]] QuasiStaticImpactResult runQuasiStaticImpact(ActiveMatter &matter,
    const QuasiStaticImpactScene &scene, const QuasiStaticImpactSettings &settings = {});

} // namespace banjo
