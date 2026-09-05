#include "platform/PlatformWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
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

int main() {
    try {
        freeFlightPreservesMomentum();
        restingFourMaterialControl();
        sharpLocalDamageAndBluntControl();
        ductileCouponHasPlasticWorkWithoutFracture();
        packageValidationAndMaterialRenaming();
        temporalAdmissionIsSeparateFromValidation();
        std::cout << "[PASS] network runtime controls, local damage, plastic work, validation and ID invariance\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
