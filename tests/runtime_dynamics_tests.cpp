#include "core/Plane.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "rigid/JoltWorld.hpp"
#include "sim/RollingBallExperiment.hpp"
#include "physics/RollingKinematics.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <optional>
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

banjo::MaterialDefinition controlledMaterial(
    std::string_view name,
    double density_kg_m3,
    double rolling_resistance = 0.0) {
    banjo::MaterialDefinition material;
    material.name = std::string(name);
    material.model = banjo::MaterialModel::RigidOnly;
    material.density_kg_m3 = density_kg_m3;
    material.young_modulus_pa = 70.0e9;
    material.poisson_ratio = 0.25;
    material.yield_strength_pa = 100.0e6;
    material.tensile_strength_pa = 100.0e6;
    material.compressive_strength_pa = 200.0e6;
    material.fracture_energy_j_m2 = 1000.0;
    material.static_friction = 0.80;
    material.dynamic_friction = 0.65;
    material.friction = material.dynamic_friction;
    material.rolling_resistance = rolling_resistance;
    material.contact_damping_ratio = 0.10;
    material.derive_restitution_from_damping = true;
    material.damping_ratio = 0.0;
    return material;
}

void tiltedSurfaceAcceleratesDownhillAndSupportsBall() {
    const banjo::SupportPlaneFrame plane =
        banjo::makeSupportPlaneFromSlopeDegrees(15.0);
    const banjo::MaterialDefinition ball =
        controlledMaterial("test_ball", 2500.0, 0.002);
    const banjo::MaterialDefinition surface =
        controlledMaterial("test_surface", 2400.0, 0.010);

    banjo::JoltWorld world;
    world.setGravity({0.0, -9.81, 0.0});
    world.addSupportSurface({
        .frame = plane,
        .material = surface,
    });
    constexpr double radius = 0.25;
    world.addBall({
        .body_id = 1,
        .radius_m = radius,
        .material = ball,
        .position_world_m =
            banjo::pointInPlaneFrame(plane, -1.0, 0.0, radius + 0.001),
    });

    for (unsigned step = 0; step < 240U; ++step) {
        world.step(1.0 / 240.0);
    }
    const banjo::RigidSnapshot snapshot = world.snapshot(1);
    const double downhill_speed =
        banjo::dot(snapshot.linear_velocity_m_s, plane.tangent_world);
    const double support_distance =
        banjo::signedDistanceToPlane(plane, snapshot.center_of_mass_world_m);

    require(downhill_speed > 0.20,
            "gravity should accelerate a supported sphere down a tilted plane");
    require(std::abs(support_distance - radius) < 0.06,
            "sphere center should remain approximately one radius above its support plane");
    require(banjo::length(snapshot.angular_velocity_rad_s) > 0.2,
            "static friction should generate rolling rotation on the incline");
}

void zeroGravityLeavesSupportedBallAtRest() {
    const banjo::SupportPlaneFrame plane =
        banjo::makeSupportPlaneFromSlopeDegrees(20.0);
    const banjo::MaterialDefinition material =
        controlledMaterial("rest_test", 2500.0, 0.02);

    banjo::JoltWorld world;
    world.setGravity({});
    world.addSupportSurface({
        .frame = plane,
        .material = material,
    });
    world.addBall({
        .body_id = 1,
        .radius_m = 0.25,
        .material = material,
        .position_world_m =
            banjo::pointInPlaneFrame(plane, 0.0, 0.0, 0.251),
    });
    for (unsigned step = 0; step < 120U; ++step) {
        world.step(1.0 / 120.0);
    }
    require(banjo::length(world.snapshot(1).linear_velocity_m_s) < 0.02,
            "tilting geometry alone must not create acceleration without a field");
}

void densityDoesNotChangeVacuumFreeFall() {
    banjo::MaterialDefinition light = controlledMaterial("light", 500.0);
    banjo::MaterialDefinition heavy = controlledMaterial("heavy", 8000.0);

    banjo::JoltWorld world;
    world.setGravity({0.0, -9.81, 0.0});
    world.addBall({
        .body_id = 1,
        .radius_m = 0.20,
        .material = light,
        .position_world_m = {-1.0, 5.0, 0.0},
    });
    world.addBall({
        .body_id = 2,
        .radius_m = 0.20,
        .material = heavy,
        .position_world_m = {1.0, 5.0, 0.0},
    });
    for (unsigned step = 0; step < 120U; ++step) {
        world.step(1.0 / 120.0);
    }

    const banjo::RigidSnapshot light_state = world.snapshot(1);
    const banjo::RigidSnapshot heavy_state = world.snapshot(2);
    require(std::abs(
                light_state.linear_velocity_m_s.y -
                heavy_state.linear_velocity_m_s.y) < 1.0e-5,
            "uniform gravitational acceleration should be independent of density");
    require(std::abs(
                light_state.center_of_mass_world_m.y -
                heavy_state.center_of_mass_world_m.y) < 1.0e-5,
            "equal initial states should follow equal vacuum trajectories in uniform gravity");
}

std::optional<banjo::ImpactEvent> firstBallImpact(
    const banjo::MaterialDefinition &first,
    const banjo::MaterialDefinition &second) {
    banjo::JoltWorld world;
    world.setGravity({});
    world.addBall({
        .body_id = 1,
        .radius_m = 0.25,
        .material = first,
        .position_world_m = {-0.8, 0.0, 0.0},
        .linear_velocity_m_s = {4.0, 0.0, 0.0},
    });
    world.addBall({
        .body_id = 2,
        .radius_m = 0.25,
        .material = second,
        .position_world_m = {0.0, 0.0, 0.0},
    });

    for (unsigned step = 0; step < 120U; ++step) {
        world.step(1.0 / 240.0);
        std::vector<banjo::ImpactEvent> impacts = world.drainImpacts();
        for (const banjo::ImpactEvent &impact : impacts) {
            if (impact.involves(1) && impact.involves(2)) {
                return impact;
            }
        }
    }
    return std::nullopt;
}

void runtimeContactUsesCompiledMaterialPair() {
    const banjo::MaterialDefinition iron =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Iron, 971);
    const banjo::MaterialDefinition glass =
        banjo::makeReferenceMaterial(banjo::MaterialPreset::Glass, 971);
    const banjo::CombinedContactMaterial expected =
        banjo::combineContactMaterials(
            banjo::compileContactMaterial(iron),
            banjo::compileContactMaterial(glass));
    const std::optional<banjo::ImpactEvent> impact =
        firstBallImpact(iron, glass);

    require(impact.has_value(), "runtime should report the ball-to-ball impact");
    require(std::abs(
                impact->combined_restitution - expected.restitution) < 1.0e-5,
            "Jolt contact callback should receive the compiled pair restitution");
    require(std::abs(
                impact->effective_contact_modulus_pa -
                expected.effective_modulus_pa) /
                expected.effective_modulus_pa < 1.0e-5,
            "impact event should expose the compiled effective contact modulus");
    require(impact->applied_friction == impact->combined_static_friction ||
                impact->applied_friction == impact->combined_dynamic_friction,
            "runtime contact should select one of the pair friction regimes");
}

double simulateTargetSpeed(double striker_density_kg_m3) {
    banjo::MaterialDefinition striker =
        controlledMaterial("striker", striker_density_kg_m3);
    banjo::MaterialDefinition target =
        controlledMaterial("target", 2500.0);
    striker.static_friction = 0.0;
    striker.dynamic_friction = 0.0;
    striker.friction = 0.0;
    target.static_friction = 0.0;
    target.dynamic_friction = 0.0;
    target.friction = 0.0;

    banjo::JoltWorld world;
    world.setGravity({});
    world.addBall({
        .body_id = 1,
        .radius_m = 0.25,
        .material = striker,
        .position_world_m = {-0.8, 0.0, 0.0},
        .linear_velocity_m_s = {4.0, 0.0, 0.0},
    });
    world.addBall({
        .body_id = 2,
        .radius_m = 0.25,
        .material = target,
        .position_world_m = {0.0, 0.0, 0.0},
    });
    for (unsigned step = 0; step < 180U; ++step) {
        world.step(1.0 / 240.0);
        (void)world.drainImpacts();
    }
    return world.snapshot(2).linear_velocity_m_s.x;
}

void massDistributionChangesCollisionTransfer() {
    const double light_striker_target_speed = simulateTargetSpeed(500.0);
    const double heavy_striker_target_speed = simulateTargetSpeed(8000.0);
    require(heavy_striker_target_speed > light_striker_target_speed + 0.5,
            "a denser equal-size striker should transfer more momentum to the target");
}

double simulateRollingSpeed(double surface_rolling_resistance) {
    banjo::MaterialDefinition ball =
        controlledMaterial("rolling_ball", 2500.0, 0.0);
    banjo::MaterialDefinition surface =
        controlledMaterial(
            "rolling_surface", 2400.0, surface_rolling_resistance);
    const banjo::SupportPlaneFrame plane =
        banjo::makeSupportPlaneFromSlopeDegrees(0.0);

    banjo::JoltWorld world;
    world.setGravity({0.0, -9.81, 0.0});
    world.addSupportSurface({
        .frame = plane,
        .material = surface,
    });
    const banjo::Vec3 velocity = 2.0 * plane.tangent_world;
    world.addBall({
        .body_id = 1,
        .radius_m = 0.25,
        .material = ball,
        .position_world_m =
            banjo::pointInPlaneFrame(plane, -2.0, 0.0, 0.251),
        .linear_velocity_m_s = velocity,
        .angular_velocity_rad_s =
            banjo::cross(plane.normal_world, velocity) / 0.25,
    });
    for (unsigned step = 0; step < 480U; ++step) {
        world.step(1.0 / 240.0);
    }
    return banjo::dot(
        world.snapshot(1).linear_velocity_m_s,
        plane.tangent_world);
}

void rollingResistanceChangesCoastingSpeed() {
    const double low_resistance_speed = simulateRollingSpeed(0.001);
    const double high_resistance_speed = simulateRollingSpeed(0.100);
    require(high_resistance_speed + 0.30 < low_resistance_speed,
            "higher rolling resistance should dissipate more coasting speed");
}

void slidingSpinsUpToAnalyticalRollingSpeed() {
    auto material = controlledMaterial("friction_test", 2500.0);
    material.derive_restitution_from_damping = false;
    material.restitution = 0.0;
    const auto plane = banjo::makeSupportPlaneFromSlopeDegrees(0.0);
    banjo::JoltWorld world;
    world.addSupportSurface({.frame=plane, .material=material});
    world.addBall({.body_id=1, .radius_m=.25, .material=material,
        .position_world_m={0,.25,0}, .linear_velocity_m_s={2,0,0}});
    for (unsigned i=0;i<240;++i) world.step(1.0/480.0);
    const auto body=world.snapshot(1);
    const auto motion=banjo::measureRollingKinematics(body,.25,plane);
    std::cout << "Measured slide-to-roll: v=" << body.linear_velocity_m_s.x
              << " slip=" << motion.contact_slip_speed_m_s << " m/s\n";
    require(std::abs(body.linear_velocity_m_s.x-2.0/1.4)<.02,
        "solid sphere launched without spin should reach v=5/7 v0 under friction");
    require(motion.contact_slip_speed_m_s<.02, "friction should spin up the initially sliding ball");
}
void frictionlessSurfaceCannotSpinUpBall() {
    auto material=controlledMaterial("frictionless",2500.0);
    material.static_friction=material.dynamic_friction=material.friction=0;
    banjo::JoltWorld world;
    world.addSupportSurface({.material=material});
    world.addBall({.body_id=1,.radius_m=.25,.material=material,
        .position_world_m={0,.25,0},.linear_velocity_m_s={2,0,0}});
    for(unsigned i=0;i<120;++i)world.step(1.0/240.0);
    const auto body=world.snapshot(1);
    require(std::abs(body.linear_velocity_m_s.x-2.0)<1e-5,
        "frictionless translation must not lose speed");
    std::cout << "Frictionless angular drift=" << banjo::length(body.angular_velocity_rad_s) << " rad/s\n";
    // Jolt uses single-precision contact geometry; measure the tiny spin drift
    // in surface-speed units. This permits <10 micrometers/s, not macroscopic rolling.
    require(.25 * banjo::length(body.angular_velocity_rad_s)<1e-5,
        "surface without friction must not manufacture rolling spin");
}
void rollingResistanceIsTorqueNotSpinSnap() {
    auto material=controlledMaterial("torque_test",2500.0,.03);
    material.static_friction=material.dynamic_friction=material.friction=0;
    banjo::JoltWorld world;
    world.addSupportSurface({.material=material});
    world.addBall({.body_id=1,.radius_m=.25,.material=material,
        .position_world_m={0,.25,0},.linear_velocity_m_s={2,0,0},
        .angular_velocity_rad_s={0,0,-7.2}});
    for(unsigned i=0;i<24;++i)world.step(1.0/240.0);
    const auto body=world.snapshot(1);
    require(std::abs(body.linear_velocity_m_s.x-2.0)<1e-5,
        "rolling-resistance torque without friction cannot change COM velocity");
    require(std::abs(body.angular_velocity_rad_s.z)<7.2,
        "resisting torque should reduce angular speed, not snap it to v/r");
}
void materialDampingIsNotVacuumDrag() {
    auto material=controlledMaterial("damped_interior",2500.0);
    material.damping_ratio=.9;
    banjo::JoltWorld world;world.setGravity({});
    world.addBall({.body_id=1,.radius_m=.25,.material=material,
        .linear_velocity_m_s={2,0,0},.angular_velocity_rad_s={0,0,3}});
    for(unsigned i=0;i<240;++i)world.step(1.0/240.0);
    const auto body=world.snapshot(1);
    require(std::abs(body.linear_velocity_m_s.x-2.0)<1e-5,
        "internal damping must not slow rigid translation in vacuum");
    require(std::abs(body.angular_velocity_rad_s.z-3.0)<1e-5,
        "internal damping must not slow undistorted rigid rotation");
}
void sensorHandoffDoesNotDoubleApplyImpact() {
    auto iron=banjo::makeReferenceMaterial(banjo::MaterialPreset::Iron,971);
    auto glass=banjo::makeReferenceMaterial(banjo::MaterialPreset::Glass,971);
    banjo::JoltWorld world;world.setGravity({});
    world.addBall({.body_id=1,.radius_m=.25,.material=iron,
        .position_world_m={-.8,0,0},.linear_velocity_m_s={4,0,0}});
    world.addBall({.body_id=2,.radius_m=.25,.material=glass,
        .position_world_m={0,0,0},.defer_brittle_contacts_to_material=true});
    bool deferred=false;
    for(unsigned i=0;i<240 && !deferred;++i){
        world.step(1.0/480.0);
        for(const auto &impact:world.drainImpacts())deferred|=impact.response_deferred_to_material;
    }
    require(deferred,"activating contact should be handed to material solver");
    require(std::abs(world.snapshot(1).linear_velocity_m_s.x-4)<1e-5,
        "Jolt must not also resolve an activating impact");
    require(banjo::length(world.snapshot(2).linear_velocity_m_s)<1e-5,
        "target must receive its impulse from material contacts, not twice");
}
void defaultExperimentUsesRealContactWithoutPulse() {
    banjo::ExperimentSettings settings;
    settings.minimum_material_steps=20;
    settings.stable_material_steps_before_handoff=10;
    settings.maximum_material_steps=120;
    banjo::RollingBallExperiment experiment(settings);
    require(experiment.stats().striker_motion.state==banjo::RollingState::Rolling,
        "default ball should start rolling");
    for(unsigned i=0;i<240 && experiment.phase()!=banjo::ExperimentPhase::RigidFragments;++i)
        experiment.stepFixed();
    const auto &stats=experiment.stats();
    require(stats.activation_response_deferred,"initial rigid response must be suppressed");
    require(stats.impact_speed_m_s>7.0,"default activation must originate in the ball collision");
    require(stats.coupled_contact_points>0 && stats.coupled_impulse_n_s>0,
        "active nodes must actually exchange impulses with rigid striker");
    require(stats.coupled_contact_dissipation_j>=-1e-6,"contact must not manufacture energy");
    require(stats.broken_bonds>0 && stats.rigid_fragments>0,
        "contact alone must drive fracture and generated-fragment handoff");
    require(std::abs(stats.mass_error_kg)<1e-8,"contact-driven handoff must conserve represented mass");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"tilted support accelerates downhill",
         tiltedSurfaceAcceleratesDownhillAndSupportsBall},
        {"zero gravity leaves ball at rest", zeroGravityLeavesSupportedBallAtRest},
        {"free fall is density independent", densityDoesNotChangeVacuumFreeFall},
        {"runtime uses compiled contact pair", runtimeContactUsesCompiledMaterialPair},
        {"mass controls momentum transfer", massDistributionChangesCollisionTransfer},
        {"rolling resistance changes coasting", rollingResistanceChangesCoastingSpeed},
        {"slide to analytical rolling speed", slidingSpinsUpToAnalyticalRollingSpeed},
        {"frictionless slide stays sliding", frictionlessSurfaceCannotSpinUpBall},
        {"rolling resistance is torque", rollingResistanceIsTorqueNotSpinSnap},
        {"no material damping as vacuum drag", materialDampingIsNotVacuumDrag},
        {"sensor prevents double impulse", sensorHandoffDoesNotDoubleApplyImpact},
        {"runtime contact drives fracture", defaultExperimentUsesRealContactWithoutPulse},
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
