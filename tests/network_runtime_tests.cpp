#include "platform/PlatformWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <chrono>
#include <utility>
#include <vector>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string_view>

namespace {
using banjo::PlatformWorld;
using banjo::Vec3;
using nlohmann::json;

struct TestFailure : std::runtime_error { using std::runtime_error::runtime_error; };

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

json fixture(std::string_view name) {
    const auto path = std::filesystem::path(BANJO_SOURCE_DIR) / "assets" / "runtime-v2" / name;
    std::ifstream input(path);
    require(input.good(), "network runtime fixture must be readable");
    return json::parse(input);
}

std::unique_ptr<PlatformWorld> load(const json &source) {
    return PlatformWorld::load(source.dump());
}

void runSteps(PlatformWorld &world, unsigned count) {
    for (unsigned done = 0; done < count; done += 240) {
        const unsigned batch = std::min(240U, count - done);
        const auto result = world.step(batch);
        require(result.completed_steps == batch && result.error.empty(),
                "network runtime step must complete without a fault");
    }
}

json report(PlatformWorld &world) { return json::parse(world.reportJson()); }

const json &objectResult(const json &reportValue, unsigned id) {
    for (const auto &object : reportValue.at("objects"))
        if (object.at("id") == id) return object;
    throw TestFailure("network object result is missing");
}

Vec3 vector(const json &value) {
    return {value.at(0).get<double>(), value.at(1).get<double>(), value.at(2).get<double>()};
}

void rejects(json source, std::string_view message) {
    try {
        auto world = load(source);
        (void)world;
    } catch (const std::exception &) {
        return;
    }
    throw TestFailure(std::string(message));
}

json rigidSphereFixture() {
    auto source = fixture("08-free-flight.json");
    source["name"] = "rigid sphere contact test";
    source["required_capabilities"] =
        json::array({"sphere", "finite-ground", "gravity", "contact", "render-instances"});
    const auto ironMaterial = source.at("materials").at(2);
    source["materials"] = json::array({ironMaterial});
    source["objects"] = json::array();
    source["objects"].push_back({
        {"id", 1},
        {"name", "iron sphere"},
        {"material", "iron"},
        {"shape", "sphere"},
        {"representation", "rigid"},
        {"dimensions_m", {0.1, 0.1, 0.1}},
        {"position_m", {0.0, 0.3, 0.0}},
        {"orientation_wxyz", {0.9238795325112867, 0.0, 0.3826834323650898, 0.0}},
        {"velocity_m_s", {0.0, 0.0, 0.0}},
        {"spin_rad_s", {0.0, 0.0, 4.0}}
    });
    return source;
}

void rigidSphereHasMaterialMassInertiaAndRenderGeometry() {
    auto source = rigidSphereFixture();
    source["gravity_m_s2"] = {0.0, 0.0, 0.0};
    source["ground"] = nullptr;
    auto world = load(source);
    const auto initial = report(*world);
    const double radius = 0.05;
    const double mass = 7870.0 * (4.0 / 3.0) * std::numbers::pi * radius * radius * radius;
    const double rotationalEnergy = 0.5 * (0.4 * mass * radius * radius) * 16.0;
    const auto &object = objectResult(initial, 1);
    require(std::abs(object.at("mass_kg").get<double>() - mass) < 1.0e-12,
            "rigid sphere mass must come from material density and sphere volume");
    require(std::abs(initial.at("mechanical_energy_j").get<double>() - rotationalEnergy) /
                rotationalEnergy < 1.0e-5,
            "rigid sphere report must retain solid-sphere inertia");
    const auto instances = world->renderInstances();
    require(instances.size() == 1 && instances.front().geometry.kind == banjo::PrimitiveKind::Sphere,
            "rigid sphere must expose a sphere render primitive");
    require(std::abs(instances.front().geometry.radius_m - radius) < 1.0e-12 &&
                !instances.front().deformable_cell,
            "rigid sphere render primitive must retain its diameter and rigid representation");
    require(std::abs(instances.front().state.orientation_world.w - 0.9238795325112867) < 1.0e-6 &&
                std::abs(instances.front().state.orientation_world.y - 0.3826834323650898) < 1.0e-6,
            "rigid sphere must preserve its authored orientation state");
}

void rigidSphereRejectsAnisotropyAndNetworkRepresentation() {
    auto source = rigidSphereFixture();
    source["objects"][0]["dimensions_m"] = {0.1, 0.101, 0.1};
    rejects(source, "anisotropic sphere dimensions must be rejected");
    source = rigidSphereFixture();
    source["objects"][0]["representation"] = "network";
    source["objects"][0]["resolution"] = {2, 2, 2};
    rejects(source, "network sphere representation must be rejected");
}

void rigidSphereMovesThroughGroundContact() {
    auto source = rigidSphereFixture();
    source["gravity_m_s2"] = {0.0, -9.81, 0.0};
    source["ground"] = {{"half_length_m", 2.0}, {"half_width_m", 2.0}, {"friction", 0.4}};
    source["objects"][0]["spin_rad_s"] = {0.0, 0.0, 0.0};
    source["objects"][0]["velocity_m_s"] = {0.0, -1.0, 0.0};
    auto world = load(source);
    const auto initial = world->renderInstances().front().state.center_of_mass_world_m;
    double minimum_height = initial.y;
    double maximum_upward_velocity = 0.0;
    for (unsigned i = 0; i < 80; ++i) {
        const auto step = world->step(1);
        require(step.completed_steps == 1U && step.error.empty(),
                "rigid sphere contact step must complete without a fault");
        const auto state = world->renderInstances().front().state;
        minimum_height = std::min(minimum_height, state.center_of_mass_world_m.y);
        maximum_upward_velocity = std::max(maximum_upward_velocity,
                                           state.linear_velocity_m_s.y);
        if (i == 47) {
            require(state.center_of_mass_world_m.y < initial.y - 0.08 &&
                        state.linear_velocity_m_s.y < 0.0,
                    "rigid sphere must show free-fall motion before contact");
        }
    }
    require(minimum_height >= 0.045 && minimum_height < 0.06,
            "rigid sphere must reach the support without tunneling through it");
    require(maximum_upward_velocity > 0.5,
            "rigid sphere ground contact must produce an upward contact response");
}

void freeFlightPreservesMomentum() {
    auto world = load(fixture("08-free-flight.json"));
    const auto initial = report(*world);
    const auto initialMomentum = vector(initial.at("linear_momentum_kg_m_s"));
    const auto initialInstances = world->renderInstances();
    runSteps(*world, 720);
    const auto final = report(*world);
    const auto finalMomentum = vector(final.at("linear_momentum_kg_m_s"));
    require(world->fractureCount() == 0 && final.at("broken_links") == 0 &&
                final.at("damaged_links") == 0,
            "free flight must not damage or break links");
    require(banjo::length(finalMomentum - initialMomentum) < 1e-9,
            "free flight must preserve total linear momentum");
    const auto finalInstances = world->renderInstances();
    require(initialInstances.size() == finalInstances.size(), "free flight retains all cells");
    for (std::size_t i = 0; i < initialInstances.size(); ++i)
        require(banjo::length(finalInstances[i].state.linear_velocity_m_s -
                              initialInstances[i].state.linear_velocity_m_s) < 1e-12,
                "free flight preserves each cell velocity");
}

void restingFourMaterialControl() {
    auto world = load(fixture("06-rest-control.json"));
    runSteps(*world, 480);
    const auto result = report(*world);
    require(result.at("broken_links") == 0 && result.at("damaged_links") == 0 &&
                result.at("fracture_work_j").get<double>() == 0.0 &&
                result.at("plastic_work_j").get<double>() == 0.0,
            "supported four-material rest control must remain undamaged");
    require(result.at("objects").size() == 4, "rest control retains four material objects");
}

void sharpLocalDamageAndBluntControl() {
    auto sharp = load(fixture("01-sharp-four-materials.json"));
    runSteps(*sharp, 720);
    const auto sharpReport = report(*sharp);
    const auto &sharpTissue = objectResult(sharpReport, 7);
    require(sharpTissue.at("broken_links") > 0 && sharpTissue.at("damaged_links") > 0,
            "sharp tool must damage soft tissue locally");
    require(sharpTissue.at("largest_component_cells").get<unsigned>() * 4 >=
                sharpTissue.at("cells").get<unsigned>() * 3,
            "sharp tissue tearing must retain at least a 75 percent connected core");
    require(sharpTissue.at("broken_links") < sharpTissue.at("links"),
            "sharp tissue tearing must retain surviving links");

    auto blunt = load(fixture("02-blunt-four-materials.json"));
    runSteps(*blunt, 720);
    const auto bluntReport = report(*blunt);
    const auto &bluntTissue = objectResult(bluntReport, 7);
    require(bluntTissue.at("broken_links") == 0 && bluntTissue.at("damaged_links") == 0 &&
                bluntTissue.at("components") == 1,
            "equal-volume blunt tool control must retain intact soft tissue");
}

void ductileCouponHasPlasticWorkWithoutFracture() {
    auto world = load(fixture("07-ductile-indentation.json"));
    runSteps(*world, 720);
    const auto result = report(*world);
    const auto &coupon = objectResult(result, 1);
    require(coupon.at("plastic_work_j").get<double>() > 0.0,
            "ductile coupon must record positive plastic work");
    require(coupon.at("broken_links") == 0 && coupon.at("components") == 1,
            "ductile coupon must remain connected without fracture");
}

void packageValidationAndMaterialRenaming() {
    const auto source = fixture("01-sharp-four-materials.json");
    auto bad = source;
    bad["unknown_field"] = 1;
    rejects(bad, "unknown top-level fields must be rejected");
    bad = source;
    bad["materials"][0]["unknown_field"] = 1;
    rejects(bad, "unknown material fields must be rejected");
    bad = source;
    bad["objects"][0]["material"] = "missing-material";
    rejects(bad, "unknown material references must be rejected");

    auto renamed = source;
    for (auto &material : renamed["materials"]) {
        const auto old = material.at("id").get<std::string>();
        const auto fresh = "renamed-" + old;
        material["id"] = fresh;
        for (auto &object : renamed["objects"])
            if (object.at("material").get<std::string>() == old) object["material"] = fresh;
    }
    auto originalWorld = load(source);
    auto renamedWorld = load(renamed);
    runSteps(*originalWorld, 240);
    runSteps(*renamedWorld, 240);
    const auto originalReport = report(*originalWorld);
    const auto renamedReport = report(*renamedWorld);
    require(originalReport.at("damaged_links") > 0,
            "renaming comparison must exercise nonzero damage");
    for (const auto &originalObject : originalReport.at("objects")) {
        const auto &renamedObject = objectResult(renamedReport, originalObject.at("id").get<unsigned>());
        require(originalObject.at("cells") == renamedObject.at("cells") &&
                    originalObject.at("links") == renamedObject.at("links") &&
                    originalObject.at("broken_links") == renamedObject.at("broken_links") &&
                    originalObject.at("damaged_links") == renamedObject.at("damaged_links"),
                "renaming material IDs must preserve network topology outcomes");
        require(std::abs(originalObject.at("plastic_work_j").get<double>() -
                          renamedObject.at("plastic_work_j").get<double>()) < 1e-12,
                "renaming material IDs must preserve plastic work");
        const auto originalPosition = vector(originalObject.at("position_m"));
        const auto renamedPosition = vector(renamedObject.at("position_m"));
        require(banjo::length(originalPosition - renamedPosition) < 1e-12,
                "renaming material IDs must preserve object positions");
        const auto originalVelocity = vector(originalObject.at("velocity_m_s"));
        const auto renamedVelocity = vector(renamedObject.at("velocity_m_s"));
        require(banjo::length(originalVelocity - renamedVelocity) < 1e-12,
                "renaming material IDs must preserve object velocities");
    }
}

void temporalAdmissionIsSeparateFromValidation() {
    auto source=fixture("06-rest-control.json");
    auto diagnostic=load(source);
    const auto unresolved=report(*diagnostic).at("temporal_resolution");
    require(!unresolved.at("resolved").get<bool>()&&unresolved.at("required_substeps")>1,
            "stiff comparative scene must expose unresolved temporal dynamics");
    require(!unresolved.at("material_validation").get<bool>()&&!unresolved.at("includes_contact_stiffness").get<bool>(),
            "spring sampling must not certify material or contact accuracy");
    source["temporal_policy"]="require-resolved";
    rejects(source,"strict policy must reject unresolved scene before simulation");
    source["temporal_policy"]="silent-softening";
    rejects(source,"unknown temporal policy must not silently alter material stiffness");
    source["temporal_policy"]="require-resolved";
    // A deliberately soft numerical coupon exercises successful admission.
    // It is not a replacement glass/wood/iron material calibration.
    for(auto &material:source["materials"]){material["young_modulus_pa"]={100,100,100};material["fracture_enabled"]=false;material["yield_strength_pa"]=0;}
    source["fixed_dt_s"]=1./4800;
    auto soft=load(source);
    require(report(*soft).at("temporal_resolution").at("resolved").get<bool>(),
            "resolved soft numerical coupon passes temporal admission");
}
}

int main(int argc, char **argv) {
    // This suite used to print one line, after every check had passed. Silence
    // therefore meant nothing: a run that produced no output in forty-five
    // minutes could have been stuck in the first check or grinding through the
    // eighth, and there was no way to tell without waiting for an end that never
    // came. It has blocked a merge for days on exactly that ambiguity.
    //
    // Each check now says its name before it runs and its wall clock after, and
    // a name on the command line runs just that one -- so a suspect check can be
    // watched on its own instead of behind the seven in front of it.
    const std::vector<std::pair<std::string, void (*)()>> checks{
        {"rigid-sphere-mass-inertia-geometry", rigidSphereHasMaterialMassInertiaAndRenderGeometry},
        {"rigid-sphere-rejects-anisotropy", rigidSphereRejectsAnisotropyAndNetworkRepresentation},
        {"rigid-sphere-ground-contact", rigidSphereMovesThroughGroundContact},
        {"free-flight-momentum", freeFlightPreservesMomentum},
        {"resting-four-material-control", restingFourMaterialControl},
        {"sharp-local-damage-and-blunt-control", sharpLocalDamageAndBluntControl},
        {"ductile-coupon-plastic-work", ductileCouponHasPlasticWorkWithoutFracture},
        {"package-validation-and-renaming", packageValidationAndMaterialRenaming},
        {"temporal-admission", temporalAdmissionIsSeparateFromValidation},
    };
    const std::string only = argc > 1 ? argv[1] : std::string();
    if (only == "--list") {
        for (const auto &[name, _] : checks) std::cout << name << '\n';
        return 0;
    }
    try {
        bool ran = false;
        for (const auto &[name, check] : checks) {
            if (!only.empty() && only != name) continue;
            ran = true;
            std::cout << "  ... " << name << std::flush;
            const auto began = std::chrono::steady_clock::now();
            check();
            const double seconds = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - began).count();
            std::cout << "  ok (" << seconds << " s)\n" << std::flush;
        }
        if (!ran) {
            std::cerr << "[FAIL] no check called " << only
                      << "; --list shows the names\n";
            return 1;
        }
        std::cout << "[PASS] network runtime controls, local damage, plastic work, validation and ID invariance\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
