#include "platform/PlatformWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using banjo::PlatformInstance;
using banjo::PlatformWorld;
using banjo::PrimitiveKind;
using banjo::Vec3;
using nlohmann::json;

struct TestFailure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

json fixture(std::string_view name) {
    const auto path = std::filesystem::path(BANJO_SOURCE_DIR) / "assets" /
                      "material-showcase" / name;
    std::ifstream input(path);
    require(input.good(), "material showcase fixture must be readable");
    return json::parse(input);
}

json catalogFixture() {
    const auto path = std::filesystem::path(BANJO_SOURCE_DIR) / "assets" /
                      "runtime-v2" / "04-soft-tissue-offset-cut.json";
    std::ifstream input(path);
    require(input.good(), "runtime-v2 catalog fixture must be readable");
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
                "material showcase step must complete without a fault");
    }
}

json report(PlatformWorld &world) {
    return json::parse(world.reportJson());
}

const json &objectResult(const json &result, unsigned id) {
    for (const auto &object : result.at("objects"))
        if (object.at("id") == id) return object;
    throw TestFailure("material showcase object result is missing");
}

const PlatformInstance &instanceFor(const std::vector<PlatformInstance> &instances,
                                    unsigned objectId, unsigned elementId = ~0U) {
    for (const auto &instance : instances) {
        if (instance.object_id == objectId &&
            (elementId == ~0U || instance.element_id == elementId))
            return instance;
    }
    throw TestFailure("material showcase render instance is missing");
}

void requireNear(double left, double right, double tolerance, std::string_view message) {
    require(std::isfinite(left) && std::isfinite(right) &&
                std::abs(left - right) <= tolerance,
            message);
}

void requireNear(const Vec3 &left, const Vec3 &right, double tolerance,
                 std::string_view message) {
    require(banjo::length(left - right) <= tolerance, message);
}

void requireSameState(const banjo::RigidSnapshot &left, const banjo::RigidSnapshot &right,
                      std::string_view message) {
    requireNear(left.center_of_mass_world_m, right.center_of_mass_world_m, 1.0e-12, message);
    requireNear(left.orientation_world.w, right.orientation_world.w, 1.0e-12, message);
    requireNear(left.orientation_world.x, right.orientation_world.x, 1.0e-12, message);
    requireNear(left.orientation_world.y, right.orientation_world.y, 1.0e-12, message);
    requireNear(left.orientation_world.z, right.orientation_world.z, 1.0e-12, message);
    requireNear(left.linear_velocity_m_s, right.linear_velocity_m_s, 1.0e-12, message);
    requireNear(left.angular_velocity_rad_s, right.angular_velocity_rad_s, 1.0e-12, message);
}

json normalizedSpeedFixture(json source) {
    source.erase("name");
    for (auto &object : source.at("objects")) {
        const unsigned id = object.at("id").get<unsigned>();
        if (id == 2 || id == 4 || id == 6) {
            object.erase("name");
            object.erase("velocity_m_s");
        }
    }
    return source;
}

void propertyCatalogAndSpeedInputsAreBounded() {
    const auto catalog = catalogFixture().at("materials");
    const std::vector<std::string_view> names{
        "01-clamped-panels-02mps.json", "02-clamped-panels-06mps.json",
        "03-clamped-panels-12mps.json"};
    const auto reference = fixture(names.front());
    for (const auto name : names) {
        const auto source = fixture(name);
        require(source.at("materials") == catalog,
                "showcase material property catalog must match runtime-v2 catalog");
        require(normalizedSpeedFixture(source) == normalizedSpeedFixture(reference),
                "speed showcase fixtures must differ only in scene and projectile speed names");
    }
    require(fixture("04-tomato-proxy-knife-cut.json").at("materials") == catalog,
            "tomato showcase material property catalog must match runtime-v2 catalog");
}

void requireSameSupport(const std::vector<std::array<Vec3, 3>> &left,
                        const std::vector<std::array<Vec3, 3>> &right) {
    require(left.size() == right.size(), "showcase panels must use the same support geometry");
    for (std::size_t triangle = 0; triangle < left.size(); ++triangle)
        for (unsigned corner = 0; corner < 3; ++corner)
            requireNear(left[triangle][corner], right[triangle][corner], 1.0e-12,
                        "showcase support geometry must be invariant across speeds");
}

void requireSamePanelGeometry(const std::vector<PlatformInstance> &left,
                              const std::vector<PlatformInstance> &right,
                              unsigned objectId) {
    std::vector<const PlatformInstance *> a, b;
    for (const auto &instance : left)
        if (instance.object_id == objectId) a.push_back(&instance);
    for (const auto &instance : right)
        if (instance.object_id == objectId) b.push_back(&instance);
    require(a.size() == b.size() && !a.empty(),
            "showcase panels must retain the same rendered cell count");
    for (std::size_t i = 0; i < a.size(); ++i) {
        require(a[i]->element_id == b[i]->element_id && a[i]->deformable_cell &&
                    b[i]->deformable_cell && a[i]->material_id == b[i]->material_id,
                "showcase panels must retain cell identity and material");
        require(a[i]->geometry.kind == b[i]->geometry.kind &&
                    a[i]->geometry.kind == PrimitiveKind::Sphere,
                "showcase panels must retain spherical cell geometry");
        requireNear(a[i]->geometry.radius_m, b[i]->geometry.radius_m, 1.0e-12,
                    "showcase panel cell geometry must be invariant across speeds");
        requireSameState(a[i]->state, b[i]->state,
                         "showcase panel initial orientation and state must be invariant");
    }
}

void requireSameProjectileGeometry(const std::vector<PlatformInstance> &left,
                                   const std::vector<PlatformInstance> &right,
                                   const json &leftReport, const json &rightReport,
                                   unsigned objectId) {
    const auto &a = instanceFor(left, objectId);
    const auto &b = instanceFor(right, objectId);
    require(!a.deformable_cell && !b.deformable_cell && a.geometry.kind == PrimitiveKind::Sphere &&
                b.geometry.kind == PrimitiveKind::Sphere,
            "showcase projectile must retain rigid sphere geometry");
    requireNear(a.geometry.radius_m, b.geometry.radius_m, 1.0e-12,
                "showcase projectile radius must be invariant across speeds");
    requireNear(objectResult(leftReport, objectId).at("mass_kg").get<double>(),
                objectResult(rightReport, objectId).at("mass_kg").get<double>(), 1.0e-12,
                "showcase projectile mass must be invariant across speeds");
    requireNear(a.state.center_of_mass_world_m, b.state.center_of_mass_world_m, 1.0e-12,
                "showcase projectile initial position must be invariant across speeds");
    requireSameState(
        {a.state.center_of_mass_world_m, a.state.orientation_world, {}, a.state.angular_velocity_rad_s},
        {b.state.center_of_mass_world_m, b.state.orientation_world, {}, b.state.angular_velocity_rad_s},
        "showcase projectile initial orientation must be invariant across speeds");
    requireNear(a.state.angular_velocity_rad_s, b.state.angular_velocity_rad_s, 1.0e-12,
                "showcase projectile initial spin must be invariant across speeds");
}

void initialShowcaseGeometryIsInvariant() {
    const std::vector<std::string_view> names{
        "01-clamped-panels-02mps.json", "02-clamped-panels-06mps.json",
        "03-clamped-panels-12mps.json"};
    auto referenceWorld = load(fixture(names.front()));
    const auto referenceInstances = referenceWorld->renderInstances();
    const auto referenceReport = report(*referenceWorld);
    for (const auto name : names) {
        auto world = load(fixture(name));
        const auto instances = world->renderInstances();
        const auto result = report(*world);
        requireSameSupport(referenceWorld->supportMesh(), world->supportMesh());
        for (const unsigned panelId : {1U, 3U, 5U})
            requireSamePanelGeometry(referenceInstances, instances, panelId);
        for (const auto &[leftPanel, rightPanel] :
             std::vector<std::pair<unsigned, unsigned>>{{1U, 3U}, {1U, 5U}}) {
            const auto &left = instanceFor(instances, leftPanel);
            const auto &right = instanceFor(instances, rightPanel);
            require(left.geometry.kind == right.geometry.kind &&
                        left.geometry.radius_m == right.geometry.radius_m,
                    "all clamped panel materials must use the same cell geometry");
        }
        for (const unsigned ballId : {2U, 4U, 6U})
            requireSameProjectileGeometry(referenceInstances, instances, referenceReport, result,
                                           ballId);
    }
}

void ballsSlowOnClampedPanelContact() {
    const std::vector<std::pair<std::string_view, double>> cases{
        {"01-clamped-panels-02mps.json", 2.0},
        {"02-clamped-panels-06mps.json", 6.0},
        {"03-clamped-panels-12mps.json", 12.0}};
    constexpr unsigned steps = 96; // 0.2 s at the authored 480 Hz fixed step.
    for (const auto &[name, speed] : cases) {
        const auto source = fixture(name);
        auto world = load(source);
        const auto initial = world->renderInstances();
        runSteps(*world, steps);
        const auto final = world->renderInstances();
        const double elapsed = world->fixedStep() * steps;
        for (const unsigned ballId : {2U, 4U, 6U}) {
            const auto &start = instanceFor(initial, ballId);
            const auto &after = instanceFor(final, ballId);
            const Vec3 gravity{source.at("gravity_m_s2").at(0).get<double>(),
                               source.at("gravity_m_s2").at(1).get<double>(),
                               source.at("gravity_m_s2").at(2).get<double>()};
            const auto freePosition = start.state.center_of_mass_world_m +
                                      start.state.linear_velocity_m_s * elapsed +
                                      gravity * (0.5 * elapsed * elapsed);
            const auto freeVelocity = start.state.linear_velocity_m_s + gravity * elapsed;
            require(after.state.center_of_mass_world_m.z > freePosition.z + 0.01,
                    "each iron ball must move less than gravity-only free flight after contact");
            require(after.state.linear_velocity_m_s.z > freeVelocity.z + 0.1,
                    "each iron ball must slow along its impact direction on contact");
            require(std::abs(start.state.linear_velocity_m_s.z + speed) < 1.0e-12,
                    "showcase projectile speed must match its fixture");
        }
        if (speed == 12.0) {
            const auto result = report(*world);
            const auto &oak = objectResult(result, 3);
            require(oak.at("broken_links") > 0,
                    "12 m/s oak panel impact must break local links");
            require(oak.at("largest_component_cells").get<unsigned>() * 4 >=
                        oak.at("cells").get<unsigned>() * 3,
                    "12 m/s oak panel impact must retain a connected core");
        }
    }
}

void zeroVelocityProjectilesStillFallUnderGravity() {
    auto source = fixture("02-clamped-panels-06mps.json");
    for (auto &object : source["objects"]) {
        const unsigned id = object.at("id").get<unsigned>();
        if (id == 2 || id == 4 || id == 6) object["velocity_m_s"] = {0, 0, 0};
    }
    auto world = load(source);
    const auto initial = world->renderInstances();
    runSteps(*world, 96);
    const auto final = world->renderInstances();
    for (const unsigned ballId : {2U, 4U, 6U}) {
        const auto &start = instanceFor(initial, ballId);
        const auto &after = instanceFor(final, ballId);
        require(after.state.center_of_mass_world_m.y <
                    start.state.center_of_mass_world_m.y - 0.05,
                "zero-velocity projectiles must move under authored gravity");
        requireNear(after.state.center_of_mass_world_m.z,
                    start.state.center_of_mass_world_m.z, 1.0e-3,
                    "zero-velocity gravity control must remain out of contact lanes");
    }
}

void clampedPanelRestControlsRemainUndamaged() {
    auto source = fixture("01-clamped-panels-02mps.json");
    auto sixMps = fixture("02-clamped-panels-06mps.json");
    auto twelveMps = fixture("03-clamped-panels-12mps.json");
    auto &objects = source["objects"];
    objects.erase(std::remove_if(objects.begin(), objects.end(), [](const json &object) {
                      const unsigned id = object.at("id").get<unsigned>();
                      return id == 2 || id == 4 || id == 6;
                  }),
                  objects.end());
    auto normalizedSource = source;
    normalizedSource.erase("name");
    for (auto *variant : {&sixMps, &twelveMps}) {
        variant->erase("name");
        auto &variantObjects = (*variant)["objects"];
        variantObjects.erase(std::remove_if(variantObjects.begin(), variantObjects.end(),
                                            [](const json &object) {
                                                const unsigned id = object.at("id").get<unsigned>();
                                                return id == 2 || id == 4 || id == 6;
                                            }),
                             variantObjects.end());
    }
    require(normalizedSource == sixMps && normalizedSource == twelveMps,
            "projectile-free clamped-panel controls must be identical across speeds");
    auto world = load(source);
    runSteps(*world, 96);
    const auto result = report(*world);
    for (const unsigned panelId : {1U, 3U, 5U}) {
        const auto &panel = objectResult(result, panelId);
        require(panel.at("damaged_links") == 0 && panel.at("broken_links") == 0,
                "clamped panel rest controls must remain undamaged without projectiles");
    }
}

void tomatoProxyKnifeCutRetainsLocalCoreAndMass() {
    const auto tomatoSource = fixture("04-tomato-proxy-knife-cut.json");
    auto declarationBaseline = catalogFixture();
    auto tomatoObjects = tomatoSource.at("objects");
    auto baselineObjects = declarationBaseline.at("objects");
    for (auto &object : tomatoObjects) object.erase("name");
    for (auto &object : baselineObjects) object.erase("name");
    require(tomatoObjects == baselineObjects,
            "tomato proxy physical object declarations must match the runtime-v2 cut fixture");
    auto world = load(tomatoSource);
    const auto initial = report(*world);
    const auto &initialTomato = objectResult(initial, 1);
    const double initialMass = initialTomato.at("mass_kg").get<double>();
    runSteps(*world, 192); // 0.4 s at the authored fixed step.
    const auto result = report(*world);
    const auto &tomato = objectResult(result, 1);
    require(tomato.at("damaged_links") > 0,
            "tomato proxy knife cut must produce local soft-tissue damage");
    require(tomato.at("broken_links") > 0,
            "tomato proxy knife cut must break local soft-tissue links");
    require(tomato.at("largest_component_cells").get<unsigned>() * 4 >=
                tomato.at("cells").get<unsigned>() * 3,
            "tomato proxy knife cut must retain a connected core");
    requireNear(tomato.at("mass_kg").get<double>(), initialMass, 1.0e-12,
                "tomato proxy knife cut must retain all of its modeled mass");
    require(tomato.at("cells") == initialTomato.at("cells"),
            "tomato proxy knife cut must retain all modeled cell mass");
}

} // namespace

int main() {
    try {
        propertyCatalogAndSpeedInputsAreBounded();
        initialShowcaseGeometryIsInvariant();
        ballsSlowOnClampedPanelContact();
        zeroVelocityProjectilesStillFallUnderGravity();
        clampedPanelRestControlsRemainUndamaged();
        tomatoProxyKnifeCutRetainsLocalCoreAndMass();
        std::cout << "[PASS] material showcase catalog, clamped-panel contacts, controls and tomato proxy\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
