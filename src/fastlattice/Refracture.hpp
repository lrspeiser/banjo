#pragma once

// Re-entering the lattice phase after the rigid handoff.
//
// The lane's fracture used to be a one-way street: cells bond into a lattice,
// the lattice breaks, the surviving connected components become Jolt rigid
// bodies, and from that moment nothing could break again at any speed
// (docs/fast-gpu-checkpoint.md section 8, limit 6). This module supplies the
// two pieces that were missing -- a trigger and a return path -- so a fragment
// that is struck hard enough goes back into the lattice, is judged by the same
// criterion at every substep, and hands back whatever it has become.
//
// Nothing here is a new failure law. The criterion, the thresholds, the contact
// rule and the solver are the ones already in LatticePhysics.hpp; this module
// only decides WHEN to run them again and builds the state they run on.

#include "core/Math.hpp"
#include "core/Types.hpp"
#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeSchedule.hpp"
#include "fracture/ActiveMatter.hpp"
#include "material/Material.hpp"
#include "matter/Lattice.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <vector>

namespace banjo::fastlattice {

// ---------------------------------------------------------------------------
// 1. The trigger
// ---------------------------------------------------------------------------
//
// THE DERIVATION. A rigid fragment carries its material and its geometry, and a
// contact hands us a closing speed and a reduced mass. Two independent
// NECESSARY conditions follow for "some bond inside this fragment could reach
// its removal threshold during this contact"; a contact that fails either
// cannot break anything and is rejected without building a lattice.
//
// (a) STRESS. In the acoustic limit (the first microseconds of a contact,
//     before any boundary reflects) two bodies meeting at closing speed v along
//     the contact normal reach a common interface velocity, and the interface
//     carries the stress
//
//         sigma = v * z_o * z_f / (z_o + z_f),   z = rho * c,   c = sqrt(E/rho),
//
//     with z the acoustic impedance of each side (o = the other body, f = the
//     fragment). The pulse that enters the fragment therefore carries the
//     uniaxial strain
//
//         eps_0 = sigma / E_f = v * [z_o / (z_o + z_f)] / c_f.
//
//     A plane wave is a state of uniaxial STRAIN, so a bond aligned with the
//     propagation direction is stretched by eps_0 and every other orientation
//     by less: eps_0 bounds the axial stretch the incident pulse can produce.
//     The pulse then reflects. At a traction-free surface a compressive pulse
//     returns as a tensile pulse of the same magnitude, and where incident and
//     reflected pulses superpose the magnitude reaches at most 2 * eps_0 -- the
//     classical spall bound. No other linear-elastic mechanism inside a free
//     fragment amplifies one pulse further within one contact, so
//
//         eps_max <= 2 * v * [z_o / (z_o + z_f)] / c_f.
//
//     The lattice removes a bond when its resolved stretch reaches that bond's
//     own removal threshold (LatticePhysics.hpp bondEndSampleAndFailure, the
//     `threshold` array `BondFailure.cpp` fills). Taking the SMALLEST removal
//     threshold over the fragment's live bonds and over the three modes gives
//     the admission test
//
//         v >= v* = s_min * c_f * (z_o + z_f) / (2 * z_o),
//
//     one multiply and one compare against a number precomputed per fragment.
//     A static partner (the ground, a ledge) still has a finite impedance --
//     it is concrete, not a rigid abstraction -- and uses the same formula.
//
// (b) ENERGY. Removing a bond costs at least the energy that bond stores at its
//     removal stretch, 0.5 * (s_end * L)^2 / compliance, which is exactly what
//     `storedBondEnergy` reports when the bond goes. The contact cannot deposit
//     more than the kinetic energy available in the pair's centre-of-mass frame
//     along the normal, 0.5 * mu * v^2 with mu the reduced mass (Jolt's
//     `ImpactEvent::available_normal_energy_j`; ignoring the rotational part of
//     the effective mass makes it an upper bound). So
//
//         0.5 * mu * v^2 >= U_min = min over live bonds of 0.5 (s_end L)^2 / c
//
//     is necessary as well. It is what rejects a chip: a light fragment can
//     arrive at any speed and still not carry one bond's worth of energy.
//
// Both are bounds, not predictions. The trigger never decides that a fragment
// breaks; it decides whether the fragment is worth asking the lattice about,
// and the lattice -- the same criterion, at every substep -- decides the rest.
// Erring towards admission is therefore the correct direction, which is why the
// free-surface factor 2 is kept in (a).

// Everything about one fragment the trigger needs, computed once when the
// fragment is created (O(live bonds), never per contact).
struct FragmentFractureLimits {
    double minimum_removal_stretch{};      // s_min over live bonds and modes
    double minimum_removal_energy_j{};     // U_min over live bonds
    double bar_wave_speed_m_s{};           // c = sqrt(E/rho)
    double acoustic_impedance_pa_s_m{};    // z = rho * c = sqrt(rho * E)
    std::size_t live_bonds{};
    std::size_t cells{};
};

enum class RefractureVerdict : std::uint8_t {
    Admitted = 0,
    NoLiveBond = 1,       // a single cell, or a fragment whose bonds are all gone
    BelowStressBound = 2, // (a) fails: no bond can reach its threshold
    BelowEnergyBound = 3, // (b) fails: the pair cannot pay for one bond
};

struct RefractureAdmission {
    RefractureVerdict verdict{RefractureVerdict::NoLiveBond};
    double threshold_speed_m_s{};    // v*
    double estimated_peak_stretch{}; // 2 * eps_0
    double available_energy_j{};
    [[nodiscard]] bool admitted() const { return verdict == RefractureVerdict::Admitted; }
};

// z = sqrt(rho * E) for a declared material.
[[nodiscard]] double acousticImpedance(double density_kg_m3, double young_modulus_pa);

// The whole trigger: no allocation, no lattice, four multiplies.
[[nodiscard]] RefractureAdmission admitRefracture(
    const FragmentFractureLimits &fragment, double other_impedance_pa_s_m,
    double closing_speed_m_s, double available_normal_energy_j);

// The per-fragment limits, read from the parent lattice state so that the
// per-bond strength variation and any bond already removed are accounted for:
// `bonds` are indices into the parent's ORIGINAL bond order.
[[nodiscard]] FragmentFractureLimits fragmentFractureLimits(
    const ActiveMatter &matter, std::span<const std::uint32_t> node_indices,
    double density_kg_m3, double young_modulus_pa);

// ---------------------------------------------------------------------------
// 2. The return path
// ---------------------------------------------------------------------------
//
// A fragment goes back into the lattice with everything it learned the first
// time: the bonds it lost, the damage its surviving bonds carry, and their
// permanent (plastic) extension. Its rigid pose supplies the geometry and its
// rigid velocity the initial condition.
//
// The reference configuration is the ORIGINAL rest lattice, rigidly rotated and
// translated onto the fragment's current pose. That is exact -- a rigid motion
// of the reference frame leaves the nonlocal Green-Lagrange strain, the bond
// rest lengths and every threshold unchanged -- and it keeps the displacement
// field small, which is what the float path needs (LatticePhysics.hpp
// bondVector forms the bond from the exact rest edge plus a displacement
// difference).
//
// The cells' offsets inside the rigid body were taken from the DEFORMED lattice
// at handoff, so the displacement the fragment re-enters with is exactly the
// deformation it was frozen in: a piece that was bent when it was handed over
// comes back bent, and a piece that was half-cracked comes back half-cracked.
struct FragmentLattice {
    // Owned sub-lattice: the fragment's cells, and the parent bonds with both
    // ends inside it -- dead ones included, so that a broken bond stays broken
    // and stays reportable in the parent's numbering.
    std::unique_ptr<LatticeAsset> asset;
    ActiveMatter matter;
    LatticeSchedule schedule;
    Vec3 origin{}; // the fragment's centre of mass now
    // local index -> parent index.
    std::vector<std::uint32_t> parent_node;
    std::vector<std::uint32_t> parent_bond;
    // Per local bond, in the sub-asset's own bond order.
    std::vector<double> plastic_extension_m;
    std::vector<double> plastic_strain_m;
    // Rigid spin carried through untouched: the lattice applies no nodal torque,
    // so a cell's own spin is a constant of this window and putting it back is
    // what makes the round trip conserve angular momentum and energy exactly.
    Vec3 carried_spin_rad_s{};
};

// Build the sub-lattice for one fragment. `node_indices` are parent node
// indices (any order; the sub-lattice sorts them, so the result never depends
// on the order a component was discovered in). `pose` places it: cells are
// centre_of_mass + orientation * offset, velocities are v + omega x r.
struct FragmentPose {
    Vec3 center_of_mass_world_m{};
    Quat orientation_world{};
    Vec3 linear_velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
};

[[nodiscard]] FragmentLattice buildFragmentLattice(
    const ActiveMatter &parent, std::span<const std::uint32_t> node_indices,
    std::span<const Vec3> parent_cell_offset_m, const FragmentPose &pose,
    std::span<const double> parent_plastic_extension_m,
    std::span<const double> parent_plastic_strain_m);

// ---------------------------------------------------------------------------
// 3. The ledger
// ---------------------------------------------------------------------------
//
// Mass, linear momentum, angular momentum about the fragment's centre of mass
// and kinetic energy, measured the same way on both sides of a conversion so
// that the conversion itself can be shown to close.
struct MechanicalLedger {
    double mass_kg{};
    Vec3 linear_momentum_kg_m_s{};
    Vec3 angular_momentum_kg_m2_s{}; // about `about_m`
    Vec3 about_m{};
    double kinetic_energy_j{};
};

// From a lattice state (point masses plus the carried cell spin).
[[nodiscard]] MechanicalLedger latticeLedger(
    const LatticeState &state, const Vec3 &about_m, const Vec3 &cell_spin_rad_s,
    double cell_size_m);

// From a rigid body: mass, v, omega and the inertia tensor about its centre.
[[nodiscard]] MechanicalLedger rigidLedger(
    double mass_kg, const Vec3 &center_of_mass_world_m, const Vec3 &linear_velocity_m_s,
    const Mat3 &inertia_world_kg_m2, const Vec3 &angular_velocity_rad_s, const Vec3 &about_m);

} // namespace banjo::fastlattice
