#include "platform/CompiledObject.hpp"
#include "material/MaterialCatalog.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <algorithm>
#include <iterator>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string_view>

namespace {

using namespace banjo;

struct TestFailure : std::runtime_error { using std::runtime_error::runtime_error; };

void require(bool condition, std::string_view message) {
    if (!condition) throw TestFailure(std::string(message));
}

void requireNear(double actual, double expected, double tolerance, std::string_view message) {
    if (std::abs(actual - expected) > tolerance) throw TestFailure(std::string(message));
}

double component(Vec3 v, unsigned axis) { return axis == 0 ? v.x : axis == 1 ? v.y : v.z; }

double totalMass(const CompiledObject &object) {
    double mass = 0.0;
    for (const auto &sample : object.samples) mass += sample.mass_kg;
    return mass;
}

Vec3 centerOfMass(const CompiledObject &object) {
    Vec3 center{};
    const double mass = totalMass(object);
    for (const auto &sample : object.samples) center += sample.mass_kg * sample.center_m;
    return center / mass;
}

Mat3 aggregateInertia(const CompiledObject &object) {
    Mat3 inertia;
    for (const auto &sample : object.samples) {
        const double r2 = lengthSquared(sample.center_m);
        for (unsigned i = 0; i < 3; ++i) {
            for (unsigned j = 0; j < 3; ++j) {
                inertia.m[i][j] += sample.intrinsic_inertia.m[i][j] +
                    sample.mass_kg * ((i == j ? r2 : 0.0) -
                                      component(sample.center_m, i) * component(sample.center_m, j));
            }
        }
    }
    return inertia;
}

std::size_t connectivityCount(const CompiledObject &object,
                              const std::vector<unsigned char> &live) {
    std::vector<unsigned> parent(object.samples.size());
    for (unsigned i = 0; i < parent.size(); ++i) parent[i] = i;
    const auto find = [&](auto self, unsigned i) -> unsigned {
        return parent[i] == i ? i : parent[i] = self(self, parent[i]);
    };
    for (std::size_t i = 0; i < object.links.size(); ++i) {
        if (!live[i]) continue;
        const auto &link = object.links[i];
        const unsigned a = find(find, link.a), b = find(find, link.b);
        if (a != b) parent[b] = a;
    }
    std::vector<unsigned> roots;
    for (unsigned i = 0; i < parent.size(); ++i) {
        const unsigned root = find(find, i);
        if (std::find(roots.begin(), roots.end(), root) == roots.end()) roots.push_back(root);
    }
    return roots.size();
}

void checkAnalyticalMassProperties() {
    const RigidPrimitive sphere{PrimitiveKind::Sphere, .06, {}};
    const RigidPrimitive box{PrimitiveKind::Box, 0.0, {.12, .08, .10}};
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        const auto material = makeReferenceMaterial(preset, 7);
        for (const auto &shape : {sphere, box}) {
            const auto object = compileObject(shape, material, 7);
            const double expectedMass = shape.volume() * material.density_kg_m3;
            requireNear(totalMass(object), expectedMass, expectedMass * 1.0e-12,
                        "compiled samples must preserve analytical mass");
            require(length(centerOfMass(object)) < 1.0e-12,
                    "symmetric compiled samples must have centered COM");
            const auto expectedInertia = shape.inertia(expectedMass);
            const auto actualInertia = aggregateInertia(object);
            for (unsigned i = 0; i < 3; ++i) for (unsigned j = 0; j < 3; ++j)
                requireNear(actualInertia.m[i][j], expectedInertia.m[i][j],
                            std::max(1.0e-14, std::abs(expectedInertia.m[i][j]) * 2.0e-10),
                            "compiled samples must preserve analytical inertia");
        }
    }
}

void checkSeededFieldAndNameIndependence() {
    const RigidPrimitive sphere{PrimitiveKind::Sphere, .06, {}};
    const auto base = makeReferenceMaterial(MaterialPreset::Glass, 1);
    auto renamed = base;
    renamed.name = "a completely different display name";
    const auto first = compileObject(sphere, base, 101);
    const auto sameSeedRenamed = compileObject(sphere, renamed, 101);
    const auto differentSeed = compileObject(sphere, base, 102);
    require(first.links.size() == sameSeedRenamed.links.size() && first.links.size() == differentSeed.links.size(),
            "seed comparison requires the same compiled topology");
    bool changed = false;
    for (std::size_t i = 0; i < first.links.size(); ++i) {
        require(first.links[i].strength_pa == sameSeedRenamed.links[i].strength_pa,
                "display names must not change the seeded physical field");
        if (first.links[i].strength_pa != differentSeed.links[i].strength_pa) changed = true;
    }
    require(changed, "changing the seed must change the persistent strength field");
    require(first.initial_factor == sameSeedRenamed.initial_factor,
            "same seed must produce deterministic response factors");
}

void checkImpactBudgetAndProgressiveTopology() {
    const RigidPrimitive sphere{PrimitiveKind::Sphere, .06, {}};
    const auto material = makeReferenceMaterial(MaterialPreset::Glass, 2);

    CompiledDamage zero(compileObject(sphere, material, 2));
    const auto zeroResult = zero.impact(0, {}, 1.0e6);
    require(zeroResult.failures.empty() && zeroResult.work_j == 0.0,
            "zero impulse must not damage the object");
    const auto intact = zero.liveLinks();

    CompiledDamage noAllowance(compileObject(sphere, material, 2));
    const auto blocked = noAllowance.impact(0, {10.0, 0.0, 0.0}, 0.0);
    require(blocked.failures.empty() && blocked.work_j == 0.0,
            "inadequate work allowance must prevent damage");
    require(noAllowance.liveLinks() == intact, "blocked impact must preserve topology");

    bool observedFailure = false;
    for (const double impulse : {.1, 1.0, 10.0}) {
        CompiledDamage damage(compileObject(sphere, material, 2));
        const auto result = damage.impact(0, {impulse, 0.0, 0.0}, 1.0e6, 8);
        require(result.work_j <= 1.0e6, "fracture work must not exceed its allowance");
        require(result.failures.size() <= 8, "impact must honor its failure bound");
        require(result.factor_builds <= result.failures.size(), "factor rebuild count must be bounded");
        if (!result.failures.empty()) {
            observedFailure = true;
            require(result.factor_builds >= result.failures.size() - 1,
                    "each continuing failure solve must rebuild the changed topology");
            require(result.solves > result.failures.size(),
                    "a damaging impact must perform a subsequent solve after failure");
            const auto components = damage.components();
            std::vector<unsigned> reportedRoots;
            for (const unsigned root : components)
                if (std::find(reportedRoots.begin(), reportedRoots.end(), root) == reportedRoots.end())
                    reportedRoots.push_back(root);
            require(connectivityCount(damage.object(), damage.liveLinks()) == reportedRoots.size(),
                    "reported components must match surviving-link connectivity");
            require(std::count(damage.liveLinks().begin(), damage.liveLinks().end(),
                               static_cast<unsigned char>(1)) > 0,
                    "a damaging impact must retain surviving links");

            const auto beforeRepeated = damage.liveLinks();
            const auto second = damage.impact(0, {impulse, 0.0, 0.0}, 1.0e6, 8);
            require(second.work_j <= 1.0e6, "repeated fracture work must honor its allowance");
            bool furtherDamage = false;
            for (std::size_t i = 0; i < beforeRepeated.size(); ++i)
                if (damage.liveLinks()[i] < beforeRepeated[i]) furtherDamage = true;
            require(furtherDamage || second.failures.empty(),
                    "repeated impact must preserve irreversible damage and may extend it");
            break;
        }
    }
    require(observedFailure, "at least one bounded impulse must exercise local fracture");
}

void checkRigidOnlyAndInvalidInputs() {
    const RigidPrimitive sphere{PrimitiveKind::Sphere, .06, {}};
    for (const auto preset : {MaterialPreset::Oak, MaterialPreset::Iron}) {
        const auto material = makeReferenceMaterial(preset, 3);
        CompiledDamage damage(compileObject(sphere, material, 3));
        const auto before = damage.liveLinks();
        const auto result = damage.impact(0, {10.0, 0.0, 0.0}, 1.0e6);
        require(result.failures.empty() && result.work_j == 0.0 && damage.liveLinks() == before,
                "rigid-only oak and iron must not claim unsupported fracture");
    }

    bool rejected = false;
    try { auto bad = makeReferenceMaterial(MaterialPreset::Glass); bad.density_kg_m3 = 0; (void)compileObject(sphere, bad, 1); }
    catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "invalid material density must be rejected");
    rejected = false;
    try { const RigidPrimitive bad{PrimitiveKind::Sphere, .001, {}}; (void)compileObject(bad, makeReferenceMaterial(MaterialPreset::Glass), 1); }
    catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "out-of-range geometry must be rejected");
    rejected = false;
    try { CompiledDamage damage(compileObject(sphere, makeReferenceMaterial(MaterialPreset::Glass), 1)); (void)damage.impact(0, {}, 1.0, 257); }
    catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "out-of-range failure bound must be rejected");
}

} // namespace

int main() {
    const std::pair<std::string_view, std::function<void()>> tests[] = {
        {"analytical mass properties", checkAnalyticalMassProperties},
        {"seeded field and name independence", checkSeededFieldAndNameIndependence},
        {"impact budget and progressive topology", checkImpactBudgetAndProgressiveTopology},
        {"rigid-only materials and invalid inputs", checkRigidOnlyAndInvalidInputs},
    };
    std::size_t failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "[PASS] " << name << '\n'; }
        catch (const std::exception &error) { ++failures; std::cerr << "[FAIL] " << name << ": " << error.what() << '\n'; }
    }
    std::cout << (std::size(tests) - failures) << '/' << std::size(tests) << " tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
