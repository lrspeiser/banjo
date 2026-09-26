#include "material/MaterialCatalog.hpp"

#include <cstddef>
#include <stdexcept>
#include <string>

namespace banjo {
namespace {

MaterialDefinition baseMaterial(
    std::string_view name,
    MaterialModel model,
    double density_kg_m3,
    double young_modulus_pa,
    double poisson_ratio) {
    MaterialDefinition material;
    material.name = std::string(name);
    material.model = model;
    material.density_kg_m3 = density_kg_m3;
    material.young_modulus_pa = young_modulus_pa;
    material.poisson_ratio = poisson_ratio;
    return material;
}

// rolling_resistance is the material's OWN share of the coefficient c in the
// rolling-resistance couple M = c N r: a ball of this material rolling on a
// surface of that one is resisted with c = own + surface's, because both are
// deformed at the contact. Each value, its source and its uncertainty are in
// docs/rolling-resistance.md; the pair values in the tables there (steel on
// steel about 0.001, a rubber tyre on concrete 0.010-0.015) are what these
// add up to.
void setContact(
    MaterialDefinition &material,
    double static_friction,
    double dynamic_friction,
    double rolling_resistance,
    double contact_damping_ratio) {
    material.static_friction = static_friction;
    material.dynamic_friction = dynamic_friction;
    material.friction = dynamic_friction;
    material.rolling_resistance = rolling_resistance;
    material.contact_damping_ratio = contact_damping_ratio;
    material.derive_restitution_from_damping = true;
}

} // namespace

std::string_view materialPresetName(MaterialPreset preset) {
    switch (preset) {
    case MaterialPreset::Iron:
        return "iron";
    case MaterialPreset::Aluminum:
        return "aluminum";
    case MaterialPreset::Glass:
        return "glass";
    case MaterialPreset::Ceramic:
        return "alumina ceramic";
    case MaterialPreset::Oak:
        return "oak";
    case MaterialPreset::Rubber:
        return "rubber";
    case MaterialPreset::Ice:
        return "ice";
    case MaterialPreset::Concrete:
        return "concrete";
    }
    return "unknown";
}

MaterialDefinition makeReferenceMaterial(MaterialPreset preset, std::uint64_t seed) {
    MaterialDefinition material;
    switch (preset) {
    case MaterialPreset::Iron:
        material = baseMaterial("iron", MaterialModel::RigidOnly, 7870.0, 211.0e9, 0.29);
        material.yield_strength_pa = 200.0e6;
        material.tensile_strength_pa = 250.0e6;
        material.compressive_strength_pa = 600.0e6;
        material.shear_strength_pa = 170.0e6;
        material.hardness_pa = 1.5e9;
        material.fracture_energy_j_m2 = 100000.0;
        material.damping_ratio = 0.015;
        // Half of steel on steel: 0.0010-0.0015 for hardened ball bearings,
        // 0.0010-0.0024 for a rail wheel on its rail.
        setContact(material, 0.60, 0.45, 0.0005, 0.18);
        break;
    case MaterialPreset::Aluminum:
        material = baseMaterial(
            "aluminum_6061_t6", MaterialModel::RigidOnly, 2700.0, 68.9e9, 0.33);
        material.yield_strength_pa = 276.0e6;
        material.tensile_strength_pa = 310.0e6;
        material.compressive_strength_pa = 250.0e6;
        material.shear_strength_pa = 207.0e6;
        material.hardness_pa = 950.0e6;
        material.fracture_energy_j_m2 = 25000.0;
        material.damping_ratio = 0.02;
        // No table value: iron's, scaled by elastic hysteresis for a third of
        // the stiffness and a little more internal loss (about twice).
        setContact(material, 0.61, 0.47, 0.001, 0.16);
        break;
    case MaterialPreset::Glass:
        material = baseMaterial(
            "soda_lime_glass", MaterialModel::BrittleBond, 2500.0, 70.0e9, 0.22);
        material.tensile_strength_pa = 45.0e6;
        material.compressive_strength_pa = 1000.0e6;
        material.shear_strength_pa = 35.0e6;
        material.hardness_pa = 5.5e9;
        material.fracture_energy_j_m2 = 8.0;
        material.damping_ratio = 0.015;
        material.strength_variation = 0.12;
        material.calibration.activation_energy_scale = 1.0;
        // Failure follows the declared 45 MPa tensile / 35 MPa shear strengths.
        // The previous 8x/16x strain multipliers put bond failure at
        // 360-720 MPa, so a resolved impact five times over glass strength
        // produced no damage at all; the fragmentation in earlier runs came
        // from the unbounded support projection instead.
        //
        // A BREAK MULTIPLIER OF 2 WAS STILL A DIFFERENT GLASS. The multiplier
        // says how far past its strength a bond stretches before it is
        // removed, which for a material with a yield plateau is a real
        // reserve; glass has none. 45 MPa is not a yield point glass carries
        // on past. It is the characteristic bending strength of annealed
        // soda lime silicate float glass in EN 572-1: quasi-static loading,
        // 5% breakage probability at the 95% lower confidence limit. Against
        // the same family of standards, EN 1863-1 puts heat strengthened
        // glass at 70 N/mm^2 and EN 12150-1 puts thermally toughened at 120.
        // Twice 45 is 90, so a multiplier of 2 quietly made every pane in
        // this world stronger than heat strengthened while the catalogue
        // said annealed.
        //
        // 45 being a 5% fractile rather than a mean makes breaking AT it
        // conservative, which is the right way round for an answer somebody
        // leans on, and strength_variation above scatters around it.
        //
        // Measured before the change: a 20 kg iron block dropped on the
        // Workshop's 40 mm glass table needed 4 to 5 m to break it (785-981 J)
        // where the declared strength puts it at 0.25 m (49 J). The break
        // strain is now the strength strain: a bond goes when its stretch
        // reaches 45 MPa / E, and damage starts a tenth before it, which is
        // the softening band a brittle bond gets rather than a reserve of
        // strength it does not have.
        //
        // Still a strength-based lattice criterion and not a Gc-calibrated
        // one: the declared 8 J/m^2 does not enter here, and the energy per
        // unit crack area therefore still moves with the cell size.
        material.calibration.damage_strain_multiplier = 0.9;
        material.calibration.break_strain_multiplier = 1.0;
        // Hard, elastic and smooth: as iron.
        setContact(material, 0.45, 0.35, 0.0005, 0.08);
        break;
    case MaterialPreset::Ceramic:
        material = baseMaterial(
            "alumina_ceramic", MaterialModel::BrittleBond, 3900.0, 300.0e9, 0.22);
        material.tensile_strength_pa = 300.0e6;
        material.compressive_strength_pa = 2200.0e6;
        material.shear_strength_pa = 240.0e6;
        material.hardness_pa = 15.0e9;
        material.fracture_energy_j_m2 = 25.0;
        material.damping_ratio = 0.01;
        material.strength_variation = 0.08;
        material.calibration.activation_energy_scale = 2.0;
        material.calibration.damage_strain_multiplier = 6.0;
        material.calibration.break_strain_multiplier = 12.0;
        // Stiffer than steel and less lossy: below iron.
        setContact(material, 0.50, 0.38, 0.0003, 0.06);
        break;
    case MaterialPreset::Oak:
        material = baseMaterial("oak", MaterialModel::RigidOnly, 700.0, 12.0e9, 0.35);
        material.yield_strength_pa = 45.0e6;
        material.tensile_strength_pa = 90.0e6;
        material.compressive_strength_pa = 52.0e6;
        material.shear_strength_pa = 11.0e6;
        material.hardness_pa = 35.0e6;
        material.fracture_energy_j_m2 = 1000.0;
        material.damping_ratio = 0.04;
        material.anisotropy_ratio = 8.0;
        // A smooth wooden track adds at most 0.001 under a bicycle tyre; a
        // seventeenth of steel's stiffness and more internal loss put oak
        // above iron.
        setContact(material, 0.62, 0.42, 0.002, 0.24);
        break;
    case MaterialPreset::Rubber:
        material = baseMaterial(
            "natural_rubber", MaterialModel::RigidOnly, 1100.0, 10.0e6, 0.49);
        material.yield_strength_pa = 6.0e6;
        material.tensile_strength_pa = 20.0e6;
        material.compressive_strength_pa = 15.0e6;
        material.shear_strength_pa = 3.5e6;
        material.hardness_pa = 6.0e6;
        material.fracture_energy_j_m2 = 5000.0;
        material.damping_ratio = 0.18;
        // A rubber tyre on concrete is 0.010-0.015, nearly all of it the
        // rubber's own hysteresis.
        setContact(material, 1.00, 0.80, 0.010, 0.05);
        break;
    case MaterialPreset::Ice:
        material = baseMaterial("freshwater_ice", MaterialModel::BrittleBond, 917.0, 9.0e9, 0.33);
        material.tensile_strength_pa = 1.0e6;
        material.compressive_strength_pa = 5.0e6;
        material.shear_strength_pa = 1.0e6;
        material.hardness_pa = 10.0e6;
        material.fracture_energy_j_m2 = 1.5;
        material.damping_ratio = 0.025;
        material.strength_variation = 0.18;
        material.calibration.activation_energy_scale = 1.5;
        material.calibration.damage_strain_multiplier = 5.0;
        material.calibration.break_strain_multiplier = 10.0;
        // No measurement found: iron's, scaled by elastic hysteresis for ice's
        // stiffness and loss (about four to five times).
        setContact(material, 0.10, 0.03, 0.002, 0.12);
        break;
    case MaterialPreset::Concrete:
        material = baseMaterial("concrete", MaterialModel::RigidOnly, 2400.0, 30.0e9, 0.20);
        material.tensile_strength_pa = 3.0e6;
        material.compressive_strength_pa = 35.0e6;
        material.shear_strength_pa = 5.0e6;
        material.hardness_pa = 100.0e6;
        material.fracture_energy_j_m2 = 100.0;
        material.damping_ratio = 0.04;
        // Stone. A bicycle tyre on concrete is 0.002 in all, so concrete's own
        // share is at most that. The floor of every room is this, and so is
        // the valley's rock.
        setContact(material, 0.75, 0.62, 0.001, 0.30);
        break;
    }
    material.seed = seed;
    return material;
}

RollingResistanceSource rollingResistanceSource(MaterialPreset preset) {
    switch (preset) {
    case MaterialPreset::Iron:
        return {true, "half of steel on steel: hardened steel ball bearings 0.0010-0.0015 "
                      "(Hibbeler 2007), a rail wheel on its rail 0.0010-0.0024 (Hay 1982)"};
    case MaterialPreset::Aluminum:
        return {false, "demonstration: no table value; iron's, scaled by elastic hysteresis "
                       "(Johnson 1985) for 69 GPa against 211 and a little more internal loss"};
    case MaterialPreset::Glass:
        return {false, "demonstration: no table value for a glass ball; hard, elastic and "
                       "smooth, so taken as iron"};
    case MaterialPreset::Ceramic:
        return {false, "demonstration: no table value; iron's, scaled by elastic hysteresis "
                       "for alumina's 300 GPa and lower internal loss"};
    case MaterialPreset::Oak:
        return {false, "demonstration: no table value for oak; a smooth wooden track adds at "
                       "most 0.001 under a bicycle tyre (Engineering ToolBox), and iron's "
                       "scaled by elastic hysteresis gives 0.0035; taken between"};
    case MaterialPreset::Rubber:
        return {true, "a rubber tyre on concrete 0.010-0.015 (Gillespie 1992, p. 117; "
                      "Engineering ToolBox), nearly all of it the rubber's own hysteresis"};
    case MaterialPreset::Ice:
        return {false, "demonstration: no measurement found; iron's, scaled by elastic "
                       "hysteresis for ice's 9 GPa and loss"};
    case MaterialPreset::Concrete:
        return {true, "a bicycle tyre on concrete is 0.002 in all (Engineering ToolBox), so "
                      "concrete's own share is at most that"};
    }
    return {false, "unknown material"};
}

MaterialPreset materialPresetFromOrdinal(unsigned ordinal) {
    if (ordinal >= kMaterialPresets.size()) {
        throw std::out_of_range("material preset ordinal is invalid");
    }
    return kMaterialPresets[ordinal];
}

MaterialPreset nextMaterialPreset(MaterialPreset preset) {
    for (std::size_t index = 0; index < kMaterialPresets.size(); ++index) {
        if (kMaterialPresets[index] == preset) {
            return kMaterialPresets[(index + 1U) % kMaterialPresets.size()];
        }
    }
    throw std::invalid_argument("unknown material preset");
}

} // namespace banjo
