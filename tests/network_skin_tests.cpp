#include "platform/PlatformWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using banjo::CellSkinTriangle;
using banjo::PlatformInstance;
using banjo::PlatformSkin;
using banjo::PlatformWorld;
using banjo::Vec3;
using nlohmann::json;

struct TestFailure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, std::string_view message) {
    if (!condition) {
        throw TestFailure(std::string(message));
    }
}

json fixture(std::string_view name) {
    const auto path = std::filesystem::path(BANJO_SOURCE_DIR) / "assets" / "runtime-v2" / name;
    std::ifstream input(path);
    require(input.good(), "network skin fixture must be readable");
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
                "network skin step must complete without a fault");
    }
}

json report(PlatformWorld &world) {
    return json::parse(world.reportJson());
}

json physicsState(json value) {
    value.erase("skin");
    value.erase("performance");
    return value;
}

void requireSameCellStates(const std::vector<PlatformInstance> &queried,
                           const std::vector<PlatformInstance> &control) {
    require(queried.size() == control.size(), "skin queries must retain cell count");
    for (std::size_t i = 0; i < queried.size(); ++i) {
        const auto &a = queried[i];
        const auto &b = control[i];
        require(a.object_id == b.object_id && a.element_id == b.element_id,
                "skin queries must retain cell identity");
        require(a.state.center_of_mass_world_m.x == b.state.center_of_mass_world_m.x &&
                    a.state.center_of_mass_world_m.y == b.state.center_of_mass_world_m.y &&
                    a.state.center_of_mass_world_m.z == b.state.center_of_mass_world_m.z &&
                    a.state.orientation_world.w == b.state.orientation_world.w &&
                    a.state.orientation_world.x == b.state.orientation_world.x &&
                    a.state.orientation_world.y == b.state.orientation_world.y &&
                    a.state.orientation_world.z == b.state.orientation_world.z &&
                    a.state.linear_velocity_m_s.x == b.state.linear_velocity_m_s.x &&
                    a.state.linear_velocity_m_s.y == b.state.linear_velocity_m_s.y &&
                    a.state.linear_velocity_m_s.z == b.state.linear_velocity_m_s.z &&
                    a.state.angular_velocity_rad_s.x == b.state.angular_velocity_rad_s.x &&
                    a.state.angular_velocity_rad_s.y == b.state.angular_velocity_rad_s.y &&
                    a.state.angular_velocity_rad_s.z == b.state.angular_velocity_rad_s.z,
                "skin queries must not change cell positions, rotations, or velocities");
    }
}

const PlatformInstance &instanceFor(const std::vector<PlatformInstance> &instances,
                                     unsigned element_id) {
    for (const auto &instance : instances)
        if (instance.element_id == element_id) return instance;
    throw TestFailure("skin source cell is missing from renderInstances");
}

const PlatformSkin &skinFor(const std::vector<PlatformSkin> &skins, unsigned object_id) {
    for (const auto &skin : skins)
        if (skin.object_id == object_id) return skin;
    throw TestFailure("network object is missing from renderSkins");
}

void requireSameMeshGeometry(const PlatformSkin &a, const PlatformSkin &b) {
    require(a.object_id == b.object_id, "renamed skin must retain object ID");
    require(a.mesh.revision == b.mesh.revision, "renamed skin must retain topology revision");
    require(a.mesh.exposed_faces == b.mesh.exposed_faces &&
                a.mesh.fracture_faces == b.mesh.fracture_faces &&
                a.mesh.triangles.size() == b.mesh.triangles.size(),
            "renamed skin must retain mesh counts");
    for (std::size_t i = 0; i < a.mesh.triangles.size(); ++i) {
        const auto &left = a.mesh.triangles[i];
        const auto &right = b.mesh.triangles[i];
        require(left.component == right.component && left.source_cell == right.source_cell &&
                    left.fracture_surface == right.fracture_surface,
                "renamed skin must retain triangle identity and fracture flags");
        for (unsigned corner = 0; corner < 3U; ++corner) {
            require(banjo::length(left.positions_world_m[corner] -
                                  right.positions_world_m[corner]) < 1.0e-12,
                    "renamed material IDs must preserve skin geometry");
        }
    }
}

void restControlHasStableFourMaterialSkins() {
    auto world = load(fixture("06-rest-control.json"));
    const auto instances = world->renderInstances();
    const auto skins = world->renderSkins();
    require(!instances.empty() && skins.size() == 4U,
            "rest control should expose cell instances and four material skins");

    for (const auto &instance : instances) {
        const auto &skin = skinFor(skins, instance.object_id);
        require(instance.deformable_cell, "network-v2 instances must identify deformable cells");
        require(skin.material_id == instance.material_id && skin.color_rgba == instance.color_rgba,
                "skin identity and color must match its render instance");
        require(!skin.mesh.triangles.empty(), "each material object must have a skin mesh");
    }
    const auto first = report(*world);
    const auto secondSkins = world->renderSkins();
    const auto second = report(*world);
    require(secondSkins.size() == skins.size(), "repeated skin query must retain object count");
    require(physicsState(first) == physicsState(second),
            "skin queries must not change physics report fields");
    require(first.at("skin").at("object_topology_rebuilds") ==
                second.at("skin").at("object_topology_rebuilds"),
            "repeated skin query must not rebuild unchanged topology");
}

void skinQueriesDoNotChangePhysicsStateBetweenWorlds() {
    auto queried = load(fixture("04-soft-tissue-offset-cut.json"));
    auto control = load(fixture("04-soft-tissue-offset-cut.json"));
    for (unsigned done = 0; done < 480; done += 60) {
        const auto queriedStep = queried->step(60);
        const auto controlStep = control->step(60);
        require(queriedStep.completed_steps == 60U && queriedStep.error.empty() &&
                    controlStep.completed_steps == 60U && controlStep.error.empty(),
                "paired skin-query steps must complete");
        (void)queried->renderSkins();
    }
    require(physicsState(report(*queried)) == physicsState(report(*control)),
            "interleaved skin queries must preserve exact final physics state");
    require(queried->fractureCount()>0,"skin isolation comparison must exercise actual fracture");
    requireSameCellStates(queried->renderInstances(), control->renderInstances());
}

void freeFlightSkinTranslationFollowsCellMotion() {
    auto world = load(fixture("08-free-flight.json"));
    const auto initialInstances = world->renderInstances();
    const auto initialSkins = world->renderSkins();
    const auto step = world->step(1);
    require(step.completed_steps == 1U && step.error.empty(), "free-flight skin step must complete");
    const auto finalInstances = world->renderInstances();
    const auto finalSkins = world->renderSkins();
    require(initialSkins.size() == finalSkins.size(), "free flight must retain skin objects");

    for (const auto &initialSkin : initialSkins) {
        const auto &after = skinFor(finalSkins, initialSkin.object_id);
        require(initialSkin.mesh.triangles.size() == after.mesh.triangles.size(),
                "free flight must retain skin topology");
        for (std::size_t i = 0; i < initialSkin.mesh.triangles.size(); ++i) {
            const auto &beforeTriangle = initialSkin.mesh.triangles[i];
            const auto &afterTriangle = after.mesh.triangles[i];
            const auto &beforeCell = instanceFor(initialInstances, beforeTriangle.source_cell);
            const auto &afterCell = instanceFor(finalInstances, beforeTriangle.source_cell);
            const Vec3 translation = afterCell.state.center_of_mass_world_m -
                                     beforeCell.state.center_of_mass_world_m;
            for (unsigned corner = 0; corner < 3U; ++corner) {
                // This is a geometry-following tolerance, not a trajectory tolerance:
                // the spring fit introduces small relative-deformation roundoff.
                require(banjo::length(afterTriangle.positions_world_m[corner] -
                                      beforeTriangle.positions_world_m[corner] - translation) < 1.0e-7,
                        "free-flight skin vertices must follow cell translation within mesh tolerance");
            }
        }
    }
}

void sharpBreakProducesFractureSkinsWithStableIdentity() {
    auto world = load(fixture("01-sharp-four-materials.json"));
    const auto before = world->renderSkins();
    const auto beforeReport = report(*world);
    runSteps(*world, 720);
    const auto instances = world->renderInstances();
    const auto skins = world->renderSkins();
    const auto afterReport = report(*world);
    require(afterReport.at("broken_links") > 0 && afterReport.at("skin").at("fracture_faces") > 0,
            "real failed bonds must produce fracture skin surfaces");
    require(afterReport.at("skin").at("object_topology_rebuilds") >
                beforeReport.at("skin").at("object_topology_rebuilds"),
            "a break must trigger a skin topology rebuild");

    for (const auto &skin : skins) {
        for (const CellSkinTriangle &triangle : skin.mesh.triangles) {
            const auto &instance = instanceFor(instances, triangle.source_cell);
            require(instance.object_id == skin.object_id && instance.component_id == triangle.component,
                    "skin triangle component and source cell must match renderInstances");
        }
    }
    require(skins.size() == before.size(), "fracture must preserve network skin object identities");
}

void materialRenamingPreservesSkinGeometry() {
    const auto source = fixture("01-sharp-four-materials.json");
    auto renamed = source;
    for (auto &material : renamed["materials"]) {
        const auto old = material.at("id").get<std::string>();
        const auto fresh = "skin-renamed-" + old;
        material["id"] = fresh;
        for (auto &object : renamed["objects"])
            if (object.at("material").get<std::string>() == old) object["material"] = fresh;
    }
    auto originalWorld = load(source);
    auto renamedWorld = load(renamed);
    const auto originalInitial = originalWorld->renderSkins();
    const auto renamedInitial = renamedWorld->renderSkins();
    require(originalInitial.size() == renamedInitial.size(),
            "material renaming must retain skin object count");
    for (const auto &original : originalInitial)
        requireSameMeshGeometry(original, skinFor(renamedInitial, original.object_id));

    runSteps(*originalWorld, 240);
    runSteps(*renamedWorld, 240);
    const auto originalFinal = originalWorld->renderSkins();
    const auto renamedFinal = renamedWorld->renderSkins();
    for (const auto &original : originalFinal)
        requireSameMeshGeometry(original, skinFor(renamedFinal, original.object_id));
}

} // namespace

int main() {
    try {
        restControlHasStableFourMaterialSkins();
        skinQueriesDoNotChangePhysicsStateBetweenWorlds();
        freeFlightSkinTranslationFollowsCellMotion();
        sharpBreakProducesFractureSkinsWithStableIdentity();
        materialRenamingPreservesSkinGeometry();
        std::cout << "[PASS] network skins preserve identity, geometry, topology and physics state\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
