#pragma once

#include <cstdint>
#include <string>

namespace banjo {

enum class MaterialModel : std::uint8_t {
    RigidOnly,
    BrittleBond,
};

// Which rule turns a bond's recorded strain peaks into damage.
//
// StrainThreshold (default): the bond is removed when its peak stretch reaches
// break_strain_multiplier * tensile_strength / E. The energy released per unit
// crack area then grows in proportion to the cell size, so the fracture answer
// does not converge under refinement (docs/engine-options-analysis-2026-09-07.md,
// section 1, Wall 2).
//
// EnergyScaled: the removal stretch is derived from fracture_energy_j_m2, the
// horizon and the cell size so that the stored energy of every bond crossing a
// unit area of a lattice crack plane sums to Gc at every resolution, bounded
// above by the strength stretch (docs/criterion-energy-scaled-checkpoint.md).
enum class BondFailureLaw : std::uint8_t {
    StrainThreshold,
    EnergyScaled,
};

struct SolverCalibration {
    double activation_energy_scale{1.0};
    double stress_activation_energy_floor_ratio{0.02};
    double damage_strain_multiplier{1.0};
    double break_strain_multiplier{2.0};
};

struct MaterialDefinition {
    std::string name;
    MaterialModel model{MaterialModel::RigidOnly};

    double density_kg_m3{};
    double young_modulus_pa{};
    double poisson_ratio{};
    double yield_strength_pa{};
    // Tangent modulus after yield as a fraction of the Young modulus. 0 is
    // perfect plasticity, which is the only value material/NetworkMaterial.cpp
    // admits and the value every catalog preset declares; a caller that wants
    // linear isotropic hardening declares it here.
    double hardening_ratio{};
    double tensile_strength_pa{};
    double compressive_strength_pa{};
    double shear_strength_pa{};
    double hardness_pa{};
    double fracture_energy_j_m2{};

    double friction{0.5};
    double static_friction{-1.0};
    double dynamic_friction{-1.0};
    double rolling_resistance{};
    double restitution{};
    double contact_damping_ratio{0.05};
    bool derive_restitution_from_damping{};

    double damping_ratio{0.01};
    double anisotropy_ratio{1.0};
    double reference_temperature_k{293.15};

    double strength_variation{};
    std::uint64_t seed{};
    SolverCalibration calibration{};
    BondFailureLaw failure_law{BondFailureLaw::StrainThreshold};
};

struct CompiledBrittleMaterial {
    double density_kg_m3{};
    double poisson_ratio{};
    double bond_compliance{};

    double damage_start_stretch{};
    double damage_end_stretch{};
    double compression_damage_start_strain{};
    double compression_damage_end_strain{};
    double shear_damage_start_strain{};
    double shear_damage_end_strain{};

    double bond_damping{};
    double fracture_energy_j_m2{};
    double activation_energy_scale{1.0};
    double strength_variation{};
    std::uint64_t seed{};

    // Which law set the damage thresholds above, and what the energy-scaled
    // derivation produced (zero under the strain-threshold law): the removal
    // stretch that makes a lattice crack plane cost Gc per unit area, before
    // the strength bound; and whether that bound was the smaller of the two.
    BondFailureLaw failure_law{BondFailureLaw::StrainThreshold};
    double energy_scaled_stretch{};
    bool strength_bound_active{};

    // Axial plastic flow, the law of material/NetworkMaterial.cpp
    // advanceNetworkBond expressed on a bond of this lattice. A bond carries a
    // permanent extension p; its elastic extension is (current length - rest
    // length - p) and it yields when that reaches
    //     yield_stretch * rest_length + plastic_hardening_ratio * kappa,
    // where kappa is the plastic extension accumulated so far. Beyond yield the
    // excess becomes permanent and the work it costs is dissipated.
    //
    // yield_stretch is zero unless the caller asks for the plastic law
    // (MaterialCompiler withPlasticFlow), and zero disables every line of it:
    // p stays zero, the XPBD constraint is the elastic one and the lane is what
    // it was, bit for bit. It is a stretch rather than a force because the
    // lattice's bond stiffness is a peridynamic family weight E h / (m |o|^2)
    // rather than E A / L, and only the quotient yield_strength / E gives every
    // bond of the family the same yield strain -- the currency the failure
    // surface above is already stated in. On a bond whose stiffness is E A / L
    // the two forms are identical: yield_stretch * L * (E A / L) = sigma_y * A,
    // which is the network lane's yield_force_n.
    double yield_stretch{};
    double plastic_hardening_ratio{};
};

struct CompiledContactMaterial {
    double static_friction{};
    double dynamic_friction{};
    double rolling_resistance{};
    double restitution{};
    double contact_damping_ratio{};
    double young_modulus_pa{};
    double poisson_ratio{};
};

struct CombinedContactMaterial {
    double static_friction{};
    double dynamic_friction{};
    double rolling_resistance{};
    double restitution{};
    double contact_damping_ratio{};
    double effective_modulus_pa{};
};

} // namespace banjo
