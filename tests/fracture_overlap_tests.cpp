#include "physics/FractureOverlap.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;

struct TestFailure : std::runtime_error { using std::runtime_error::runtime_error; };
void check(bool value, std::string_view message) {
    if (!value) throw TestFailure(std::string(message));
}
void near(double a, double b, double tolerance, std::string_view message) {
    if (!std::isfinite(a) || std::abs(a - b) > tolerance)
        throw TestFailure(std::string(message));
}
template<class F> void rejects(F &&f, std::string_view message) {
    try { f(); } catch (const std::invalid_argument &) { return; }
    throw TestFailure(std::string(message));
}

FractureTopology topology(unsigned count = 2) {
    FractureTopology out;
    for (unsigned tet = 0; tet < count; ++tet) {
        const unsigned base = tet * 4;
        out.duplicated_definition.reference_positions_m.insert(
            out.duplicated_definition.reference_positions_m.end(),
            {{3. * tet, 0., 0.}, {3. * tet + 1., 0., 0.},
             {3. * tet, 1., 0.}, {3. * tet, 0., 1.}});
        out.duplicated_definition.elements.push_back({{base, base + 1, base + 2, base + 3}, 0});
        out.tetrahedra.push_back({1. / 6., 1.});
    }
    return out;
}

FractureSeparation separate(unsigned count) {
    FractureSeparation out;
    for (unsigned i = 0; i < count; ++i) {
        out.component_by_tetrahedron.push_back(i);
        out.components.push_back({i});
    }
    return out;
}

void moveTet(std::vector<Vec3> &p, unsigned tet, const Vec3 &offset) {
    for (unsigned i = 0; i < 4; ++i) p[tet * 4 + i] = p[i] + offset;
}

void separation_touch_and_penetration() {
    const auto top = topology();
    auto p = top.duplicated_definition.reference_positions_m;
    moveTet(p, 1, {1.1, 0., 0.});
    auto result = detectFractureOverlap(top, p, separate(2));
    check(result.resolved && !result.interpenetrating, "separated tetrahedra resolve");
    near(result.minimum_signed_separation_m, .1, 1.e-13, "separation distance");

    moveTet(p, 1, {1., 0., 0.});
    result = detectFractureOverlap(top, p, separate(2));
    check(result.resolved && !result.interpenetrating, "touch is not penetration");
    near(result.minimum_signed_separation_m, 0., 1.e-13, "touch measure");

    moveTet(p, 1, {.8, 0., 0.});
    result = detectFractureOverlap(top, p, separate(2));
    check(result.resolved && result.interpenetrating, "volume overlap detected");
    check(result.minimum_signed_separation_m < -.1, "penetration measure is negative");
    check(result.tetrahedron_a == 0 && result.tetrahedron_b == 1, "offending ids reported");
}

void edge_cross_axis_is_required() {
    const auto top = topology();
    auto p = top.duplicated_definition.reference_positions_m;
    const std::array<Vec3, 4> b = {{{.8913574864335214, .2561765097785413, .9261679816785446},
                                     {1.8182109715844392, -.1043017563895034, 1.0310395063364695},
                                     {.5896929217167634, -.6252139726594057, .5626445190766776},
                                     {1.114832557655898, .5614734751880955, .0005046219986497569}}};
    for (unsigned i = 0; i < 4; ++i) p[4 + i] = b[i];
    const auto result = detectFractureOverlap(top, p, separate(2));
    check(result.resolved && !result.interpenetrating, "edge-edge axis separates tetrahedra");
    check(result.minimum_signed_separation_m > .09, "edge-edge separation retained");
    check(result.sat_axes > 8, "edge cross axes were visited");
}

Vec3 transform(Vec3 p) {
    return {-p.y + 4., p.x - 2., p.z + .7};
}

void rigid_transform_invariance_and_component_exclusion() {
    const auto top = topology();
    auto p = top.duplicated_definition.reference_positions_m;
    moveTet(p, 1, {.82, .03, .02});
    const auto before = detectFractureOverlap(top, p, separate(2));
    for (auto &position : p) position = transform(position);
    const auto after = detectFractureOverlap(top, p, separate(2));
    near(after.minimum_signed_separation_m, before.minimum_signed_separation_m, 1.e-12,
         "rigid transform preserves SAT measure");
    check(after.interpenetrating == before.interpenetrating, "rigid transform preserves result");

    FractureSeparation joined;
    joined.component_by_tetrahedron = {0, 0};
    joined.components = {{0, 1}};
    const auto excluded = detectFractureOverlap(top, p, joined);
    check(excluded.resolved && !excluded.interpenetrating && excluded.tetrahedron_pairs == 0,
          "same-component pair excluded");
    check(std::isinf(excluded.minimum_signed_separation_m), "no cross-component measure");
}

void work_caps_are_explicitly_unresolved() {
    const auto top = topology(3);
    auto p = top.duplicated_definition.reference_positions_m;
    moveTet(p, 1, {1.1, 0., 0.});
    moveTet(p, 2, {2.2, 0., 0.});
    auto limits = FractureOverlapLimits{};
    limits.maximum_tetrahedron_pairs = 1;
    auto result = detectFractureOverlap(top, p, separate(3), limits);
    check(!result.resolved && result.tetrahedron_pairs == 1, "pair cap is unresolved");

    limits = {};
    limits.maximum_sat_axes = 1;
    result = detectFractureOverlap(topology(), [&] {
        auto q = topology().duplicated_definition.reference_positions_m;
        moveTet(q, 1, {.8, 0., 0.}); return q;
    }(), separate(2), limits);
    check(!result.resolved && result.sat_axes == 1, "axis cap is unresolved");
}

void same_component_work_is_not_enumerated() {
    constexpr unsigned count = 10;
    const auto top = topology(count);
    FractureSeparation components;
    components.component_by_tetrahedron.assign(count, 0);
    components.component_by_tetrahedron.back() = 1;
    components.components.resize(2);
    for (unsigned tet = 0; tet + 1 < count; ++tet)
        components.components[0].push_back(tet);
    components.components[1] = {count - 1};

    auto limits = FractureOverlapLimits{};
    limits.maximum_tetrahedron_pairs = 2;
    const auto result = detectFractureOverlap(
        top, top.duplicated_definition.reference_positions_m, components, limits);
    check(!result.resolved && result.tetrahedron_pairs == 2,
          "only charged cross-component pairs reach cap");
    check(result.broad_phase_candidates == 0,
          "separated cross-component pairs use the broad phase");
}

void invalid_geometry_is_rejected() {
    const auto top = topology();
    auto p = top.duplicated_definition.reference_positions_m;
    p[0].x = std::numeric_limits<double>::quiet_NaN();
    rejects([&] { (void)detectFractureOverlap(top, p, separate(2)); }, "nonfinite rejected");
    p = top.duplicated_definition.reference_positions_m;
    p[3] = p[0];
    rejects([&] { (void)detectFractureOverlap(top, p, separate(2)); }, "degenerate rejected");
    auto invalid = separate(2);
    invalid.components = {{0, 1}, {1}};
    rejects([&] { (void)detectFractureOverlap(top, top.duplicated_definition.reference_positions_m,
                                              invalid); }, "invalid partition rejected");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests = {
        {"separation, touch, penetration", separation_touch_and_penetration},
        {"edge cross axis", edge_cross_axis_is_required},
        {"rigid invariance and exclusion", rigid_transform_invariance_and_component_exclusion},
        {"bounded work", work_caps_are_explicitly_unresolved},
        {"same component work exclusion", same_component_work_is_not_enumerated},
        {"invalid geometry", invalid_geometry_is_rejected},
    };
    for (const auto &[name, test] : tests) {
        try { test(); }
        catch (const std::exception &error) {
            std::cerr << "FAIL: " << name << ": " << error.what() << '\n'; return EXIT_FAILURE;
        }
    }
    std::cout << tests.size() << " fracture overlap tests passed\n";
}
