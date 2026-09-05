#include "fracture/ActivationPolicy.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/ContactMechanics.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct TestFailure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, std::string_view message) {
    if (!condition) {
        throw TestFailure(std::string(message));
    }
}

void hertzProjectionIsMonotonicWithSpeed() {
    const banjo::HertzSphereImpactResult slow =
        banjo::projectHertzSphereImpact({57.0e9, 0.125, 20.0, 1.0});
    const banjo::HertzSphereImpactResult fast =
        banjo::projectHertzSphereImpact({57.0e9, 0.125, 20.0, 4.0});
    require(fast.available_energy_j > slow.available_energy_j,
            "normal impact energy must increase with speed");
    require(fast.maximum_indent_m > slow.maximum_indent_m,
            "Hertz maximum indentation must increase with speed");
    require(fast.peak_force_n > slow.peak_force_n,
            "Hertz peak force must increase with speed");
    require(fast.peak_pressure_pa > slow.peak_pressure_pa,
            "Hertz peak pressure must increase with speed");
}

void stifferPairProducesHigherPeakForce() {
    const banjo::HertzSphereImpactResult compliant =
        banjo::projectHertzSphereImpact({1.0e9, 0.125, 20.0, 2.0});
    const banjo::HertzSphereImpactResult stiff =
        banjo::projectHertzSphereImpact({100.0e9, 0.125, 20.0, 2.0});
    require(stiff.maximum_indent_m < compliant.maximum_indent_m,
            "stiffer contact should indent less at equal energy");
    require(stiff.peak_force_n > compliant.peak_force_n,
            "stiffer contact should reach a higher peak force at equal energy");
}

void concentratedStressCanActivateBelowGlobalEnergyThreshold() {
    banjo::MaterialDefinition glass =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Glass, 971);
    const banjo::MaterialDefinition iron =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Iron, 971);
    const banjo::CombinedContactMaterial contact =
        banjo::combineContactMaterials(
            banjo::compileContactMaterial(iron),
            banjo::compileContactMaterial(glass));

    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.closing_speed_m_s = 1.0;
    impact.available_normal_energy_j = 0.05;
    impact.effective_contact_modulus_pa = contact.effective_modulus_pa;

    banjo::ActivationPolicy policy;
    const banjo::ActivationDecision decision = policy.evaluate(
        impact,
        {
            .body_id = 2,
            .radius_m = 0.25,
            .material = glass,
            .accumulated_damage = 0.0,
            .reduced_radius_m = 0.125,
        });

    require(decision.normalized_energy < 1.0,
            "test scenario must remain below whole-object fracture energy");
    require(decision.tensile_stress_ratio > 1.0,
            "concentrated Hertz field should exceed glass tensile screening strength");
    require(decision.activate,
            "brittle object should physicalize when local contact stress exceeds strength");
}

void negligibleEnergyDoesNotActivateDespiteIdealizedStress() {
    const banjo::MaterialDefinition glass =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Glass, 971);
    const banjo::MaterialDefinition iron =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Iron, 971);
    const banjo::CombinedContactMaterial contact =
        banjo::combineContactMaterials(
            banjo::compileContactMaterial(iron),
            banjo::compileContactMaterial(glass));

    banjo::ImpactEvent impact;
    impact.body_a = 1;
    impact.body_b = 2;
    impact.closing_speed_m_s = 0.10;
    impact.available_normal_energy_j = 0.001;
    impact.effective_contact_modulus_pa = contact.effective_modulus_pa;

    banjo::ActivationPolicy policy;
    const banjo::ActivationDecision decision = policy.evaluate(
        impact,
        {
            .body_id = 2,
            .radius_m = 0.25,
            .material = glass,
            .reduced_radius_m = 0.125,
        });
    require(!decision.activate,
            "stress screening must retain a finite energy floor to reject numerical taps");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"Hertz response grows with speed", hertzProjectionIsMonotonicWithSpeed},
        {"stiffer pair raises peak force", stifferPairProducesHigherPeakForce},
        {"local stress activates brittle matter",
         concentratedStressCanActivateBelowGlobalEnergyThreshold},
        {"negligible taps stay rigid",
         negligibleEnergyDoesNotActivateDespiteIdealizedStress},
    };

    std::size_t failures = 0U;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
