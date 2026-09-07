#pragma once

#include "fracture/ActiveMatter.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace banjo {

// The brittle bond failure criterion, shared by every solver that can break a
// bond. It was file-local inside the explicit XPBD solver; two lanes copying it
// could silently disagree about when a material breaks, so the criterion lives
// here and both lanes call it. Nothing here integrates motion: these functions
// read positions that a solver has already accepted and update bond history.
//
// The criterion is a strain-based lattice rule, not a Gc-calibrated cohesive
// law. Damage is a monotone counter that removes the bond at 1; it does not
// soften the bond beforehand, so a partially damaged bond is mechanically
// identical to an undamaged one.

// Clear the recorded per-bond strain peaks, including dead bonds. A solver
// calls this at the start of an interval so the peaks describe that interval.
void resetBondStrainPeaks(ActiveMatter &matter);

// Raise each live bond's recorded peaks to the strain implied by the current
// positions. The bond is judged by the nonlocal node strain resolved along its
// own rest axis, falling back to its own length change where a node has fewer
// than three live neighbours and no nonlocal strain can be formed.
//
// Only accepted states carry physical strain history. Predictor positions and
// Gauss-Seidel iterates are numerical guesses, not intermediate physical time.
void accumulateBondStrainPeaks(ActiveMatter &matter);

// Linear ramp from an undamaged start threshold to full damage at end.
[[nodiscard]] double bondDamageProgress(double value, double start, double end);

struct BondDamageEvaluation {
    double damage{};
    BondFailureMode mode{BondFailureMode::None};
};

// Damage implied by one bond's recorded peaks against its own thresholds. The
// driving mode is the largest of the three, resolved tension first on a tie.
[[nodiscard]] BondDamageEvaluation evaluateBondDamage(
    const ActiveBondState &state, const BondRest &rest);

struct BondFailureSummary {
    std::size_t newly_broken{};
    // Stored elastic energy carried by the removed bonds at the instant of
    // removal. This is energy leaving the mechanical ledger through a topology
    // change; it is not a calibrated crack-work law and must stay named.
    double removed_elastic_energy_j{};
    double maximum_tensile_stretch{};
    double maximum_compressive_strain{};
    double maximum_shear_strain{};
};

// Advance every live bond's damage from its recorded peaks and remove the bonds
// that reach full damage. Reported maxima cover the bonds that were live on
// entry, measured before any removal. When removed_bond_indices is supplied it
// receives the indices removed by this call, in increasing order.
BondFailureSummary applyBondFailure(
    ActiveMatter &matter,
    std::vector<std::uint32_t> *removed_bond_indices = nullptr);

// Remove named bonds at the current configuration without consulting strain.
// The caller has already decided they failed; this exists so a solver that
// rejects an interval can apply that decision at the interval's start, where
// the removed stored energy is the energy the bond held at that instant.
BondFailureSummary removeBondsAtCurrentState(
    ActiveMatter &matter,
    const std::vector<std::uint32_t> &bond_indices,
    const std::vector<BondFailureMode> &modes);

[[nodiscard]] std::size_t countBrokenBonds(const ActiveMatter &matter);

struct BondFailureModeCounts {
    std::size_t tensile{};
    std::size_t compressive{};
    std::size_t shear{};
};

[[nodiscard]] BondFailureModeCounts countBondFailureModes(const ActiveMatter &matter);

} // namespace banjo
