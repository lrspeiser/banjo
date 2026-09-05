#pragma once
#include "fracture/ActiveMatter.hpp"
#include "physics/ConservativeStep.hpp"
#include "physics/CompliantStep.hpp"
#include <span>
namespace banjo {
// Explicit ideal tensile rupture of a central elastic connector. Interface area
// is supplied by geometry; a lattice edge is NOT automatically a fracture face.
// Gc is per unit newly separated interface area (both faces counted once).
struct RuptureInterface {
    double area_m2{};
    double fracture_energy_j_m2{};
    double minimum_tensile_strength_pa{};
};
struct RuptureThreshold {
    double work_j{},extension_m{},stress_pa{};
};
// The energy-derived failure stress must meet the declared strength lower bound.
// Incompatible compliance/area/Gc/strength rejects; no silent recalibration.
RuptureThreshold compileRuptureThreshold(const BondRest &bond,const RuptureInterface &law);
// Material-gated adapter. RigidOnly presets remain unsupported; no name dispatch.
std::vector<RuptureInterface> compileMaterialRuptureInterfaces(const MaterialDefinition &material,
    const LatticeAsset &asset,std::span<const double> interface_areas_m2);
struct RuptureResult {
    bool accepted{};
    std::vector<std::uint32_t> broken_bonds;
    double removed_elastic_energy_j{},fracture_work_j{},event_overshoot_loss_j{};
    // Overshoot is unresolved numerical energy removal, never fracture work/heat.
    double balance_residual_j{};
};
// Between accepted motion steps, all interfaces checked before any mutation.
// Only current tensile extension can break a live connector. Compression, old
// peak strain and predicted contact energy cannot pay for fracture. No velocity,
// node mass, pose or spin edits. Caller retains the returned cumulative ledger.
// Budget failure leaves ALL state unchanged and requires replay/refinement of
// the preceding elastic step. At most 4096 bonds / 2048 nodes.
RuptureResult tryEnergyRupture(ActiveMatter &matter,std::span<const RuptureInterface> interfaces,double maximum_event_overshoot_j);
struct RuptureStepResult {
    bool accepted{};
    ConservativeStepResult elastic;
    RuptureResult rupture;
};
// Transactional elastic advance + endpoint rupture. Failed event/elastic solve
// publishes neither motion nor topology. This is not an adaptive event finder;
// callers must bound/refine time and compare paths, including missed crossings.
// Static support and finite-sphere coupling remain outside this first contract.
RuptureStepResult tryEnergyRuptureStep(ActiveMatter &matter,double dt_s,std::span<const RuptureInterface> interfaces,
    double maximum_event_overshoot_j,const ConservativeStepSettings &settings={},Vec3 gravity_m_s2={});
struct CompliantRuptureStepResult {
    bool accepted{};
    CompliantStepResult contact;
    RuptureResult rupture;
};
// One finite sphere and a deformable connector network, one common clock and
// compliant contact owner. Both bodies and topology roll back together. This
// reference has no Jolt contact, friction, curved support or live-world handoff.
CompliantRuptureStepResult tryCompliantRuptureStep(ActiveMatter &matter,CoupledSphereState &sphere,double dt_s,
    std::span<const RuptureInterface> interfaces,double maximum_event_overshoot_j,
    const CompliantStepSettings &settings,Vec3 gravity_m_s2={});
}
