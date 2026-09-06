#include "fracture/CellSkin.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <initializer_list>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {

using banjo::CellSkinMesh;
using banjo::CellSkinTriangle;
using banjo::CellSkinTopology;
using banjo::Quat;
using banjo::SkinCell;
using banjo::SkinFaceLink;
using banjo::Vec3;

struct Failure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, std::string_view message) {
    if (!condition) {
        throw Failure(std::string(message));
    }
}

bool near(double a, double b, double epsilon = 1.0e-10) {
    return std::abs(a - b) <= epsilon;
}

bool near(Vec3 a, Vec3 b, double epsilon = 1.0e-10) {
    return near(a.x, b.x, epsilon) && near(a.y, b.y, epsilon) && near(a.z, b.z, epsilon);
}

SkinCell cell(std::uint32_t id, std::array<int, 3> grid, Vec3 center = {}) {
    return {
        id,
        0,
        grid,
        center,
        center,
        {Vec3{0.5, 0.0, 0.0}, Vec3{0.0, 0.5, 0.0}, Vec3{0.0, 0.0, 0.5}},
    };
}

std::vector<SkinFaceLink> allLinks(std::initializer_list<std::pair<std::uint32_t, std::uint32_t>> pairs) {
    std::vector<SkinFaceLink> links;
    for (const auto [a, b] : pairs) {
        links.push_back({a, b, true});
    }
    return links;
}

CellSkinMesh evaluate(const std::vector<SkinCell> &cells,
                      const std::vector<SkinFaceLink> &links,
                      std::uint64_t revision = 17) {
    return banjo::evaluateCellSkin(
        banjo::buildCellSkinTopology(cells, links, revision), cells);
}

void requireFinite(const CellSkinMesh &mesh) {
    for (const auto &triangle : mesh.triangles) {
        for (const auto point : triangle.positions_world_m) {
            require(std::isfinite(point.x) && std::isfinite(point.y) && std::isfinite(point.z),
                    "skin positions must be finite");
        }
    }
}

void isolatedCellHasSixOutwardFaces() {
    const std::vector<SkinCell> cells{cell(10, {0, 0, 0})};
    const std::vector<SkinFaceLink> links;
    const auto topology = banjo::buildCellSkinTopology(cells, links, 1);
    const auto mesh = banjo::evaluateCellSkin(topology, cells);

    require(topology.vertex_count == 8U, "isolated cell should have eight vertices");
    require(topology.faces.size() == 6U, "isolated cell should expose six faces");
    require(mesh.exposed_faces == 6U && mesh.fracture_faces == 0U,
            "isolated cell should expose only outer faces");
    require(mesh.triangles.size() == 12U, "each exposed quad should emit two triangles");

    for (const auto &triangle : mesh.triangles) {
        const Vec3 normal = banjo::cross(
            triangle.positions_world_m[1] - triangle.positions_world_m[0],
            triangle.positions_world_m[2] - triangle.positions_world_m[0]);
        const Vec3 centroid = (triangle.positions_world_m[0] + triangle.positions_world_m[1] +
                               triangle.positions_world_m[2]) /
                              3.0;
        require(banjo::dot(normal, centroid - cells[0].center_world_m) > 0.0,
                "isolated face winding must point outward");
    }
}

void liveAdjacencyRemovesInternalFace() {
    const std::vector<SkinCell> cells{cell(1, {0, 0, 0}), cell(2, {1, 0, 0}, {1.0, 0.0, 0.0})};
    const auto topology = banjo::buildCellSkinTopology(cells, allLinks({{1, 2}}), 2);
    const auto mesh = banjo::evaluateCellSkin(topology, cells);

    require(topology.faces.size() == 10U, "two live adjacent cells should expose ten faces");
    require(mesh.exposed_faces == 10U && mesh.fracture_faces == 0U,
            "live adjacency must suppress its shared face");
    require(mesh.triangles.size() == 20U, "ten exposed quads should emit twenty triangles");
    for (const auto &face : topology.faces) {
        require(face.component == topology.faces.front().component,
                "live adjacent cells should remain one component");
    }
}

void brokenAdjacencyExposesFractureAndSeparatesComponents() {
    auto cells = std::vector<SkinCell>{cell(1, {0, 0, 0}), cell(2, {1, 0, 0}, {1.0, 0.0, 0.0})};
    cells[1].component = 1;
    const std::vector<SkinFaceLink> links{{1, 2, false}};
    const auto topology = banjo::buildCellSkinTopology(cells, links, 3);
    const auto mesh = banjo::evaluateCellSkin(topology, cells);

    require(topology.faces.size() == 12U, "broken adjacency should expose both sides");
    require(mesh.exposed_faces == 12U && mesh.fracture_faces == 2U,
            "broken adjacency should mark two fracture faces");
    require(mesh.triangles.size() == 28U,
            "ten intact outer quads and two four-triangle fracture fans should emit twenty-eight triangles");
    require(mesh.fracture_faces * 4U ==
                static_cast<unsigned>(std::count_if(mesh.triangles.begin(), mesh.triangles.end(),
                                                     [](const auto &triangle) {
                                                         return triangle.fracture_surface;
                                                     })),
            "fracture triangles should match fracture quads");
    require(topology.faces[0].component != topology.faces.back().component,
            "broken adjacency should produce separate components");
}

void partialBreakInConnectedPatchExposesFailedInterface() {
    const std::vector<SkinCell> cells{
        cell(1, {0, 0, 0}), cell(2, {1, 0, 0}, {1.0, 0.0, 0.0}),
        cell(3, {0, 1, 0}, {0.0, 1.0, 0.0}), cell(4, {1, 1, 0}, {1.0, 1.0, 0.0}),
    };
    const std::vector<SkinFaceLink> links{
        {1, 2, false}, {1, 3, true}, {2, 4, true}, {3, 4, true},
    };
    const auto topology = banjo::buildCellSkinTopology(cells, links, 4);
    const auto mesh = banjo::evaluateCellSkin(topology, cells);

    require(topology.faces.size() == 18U, "a partial break should expose two failed interface faces");
    require(mesh.fracture_faces == 2U, "partial break should retain the failed interface as fracture faces");
    require(mesh.triangles.size() == 40U,
            "sixteen intact outer quads and two four-triangle fracture fans should emit forty triangles");
    require(mesh.fracture_faces * 4U ==
                static_cast<unsigned>(std::count_if(mesh.triangles.begin(), mesh.triangles.end(),
                                                     [](const auto &triangle) {
                                                         return triangle.fracture_surface;
                                                     })),
            "partial fracture triangles should match four-triangle fracture fans");
    for (const auto &face : topology.faces) {
        require(face.component == topology.faces.front().component,
                "alternate live links should keep the patch connected");
    }
}

bool triangleContains(const CellSkinTriangle &triangle, Vec3 point) {
    for (const auto corner : triangle.positions_world_m)
        if (near(corner, point)) return true;
    return false;
}

void interiorPartialCutRetainsComponentAndOwnerLocalLips() {
    std::vector<SkinCell> cells;
    cells.reserve(27U);
    for (int z = 0; z < 3; ++z)
        for (int y = 0; y < 3; ++y)
            for (int x = 0; x < 3; ++x) {
                const auto id = static_cast<std::uint32_t>(1 + x + 3 * y + 9 * z);
                cells.push_back(cell(id, {x, y, z}, {static_cast<double>(x), static_cast<double>(y),
                                                     static_cast<double>(z)}));
            }

    auto index = [](int x, int y, int z) { return 1U + static_cast<unsigned>(x + 3 * y + 9 * z); };
    std::vector<SkinFaceLink> links;
    for (int z = 0; z < 3; ++z)
        for (int y = 0; y < 3; ++y)
            for (int x = 0; x < 3; ++x) {
                if (x < 2) links.push_back({index(x, y, z), index(x + 1, y, z),
                                            !(x == 1 && y == 1 && z == 1)});
                if (y < 2) links.push_back({index(x, y, z), index(x, y + 1, z), true});
                if (z < 2) links.push_back({index(x, y, z), index(x, y, z + 1), true});
            }

    // Separate the two owners in world space while leaving the physics component
    // identity unchanged. The fracture fan center must be local to each owner.
    cells[index(1, 1, 1) - 1].center_world_m.x -= 0.1;
    cells[index(2, 1, 1) - 1].center_world_m.x += 0.1;
    const auto topology = banjo::buildCellSkinTopology(cells, links, 9);
    const auto mesh = banjo::evaluateCellSkin(topology, cells);

    require(mesh.exposed_faces == 56U && mesh.fracture_faces == 2U,
            "interior partial cut should retain fifty-four outer and two failed faces");
    require(mesh.triangles.size() == 116U, "interior partial cut should emit 116 triangles");
    unsigned leftFracture = 0U, rightFracture = 0U;
    const Vec3 leftCenter{1.4, 1.0, 1.0};
    const Vec3 rightCenter{1.6, 1.0, 1.0};
    for (const auto &triangle : mesh.triangles) {
        require(triangle.component == 0U, "a partial interior cut must not change the supplied component");
        if (!triangle.fracture_surface) continue;
        require(triangle.source_cell == index(1, 1, 1) || triangle.source_cell == index(2, 1, 1),
                "fracture fan must retain its owner cell ID");
        if (triangle.source_cell == index(1, 1, 1)) {
            ++leftFracture;
            require(triangleContains(triangle, leftCenter),
                    "left fracture fan must use its owner-local face center");
        } else {
            ++rightFracture;
            require(triangleContains(triangle, rightCenter),
                    "right fracture fan must use its owner-local face center");
        }
    }
    require(leftFracture == 4U && rightFracture == 4U,
            "each owner side of a failed face must emit four fracture triangles");
    for (const auto &face : topology.faces)
        require(face.component == 0U, "all welded perimeter faces must retain one component");
}

void rigidTransformIsEquivariant() {
    const std::vector<SkinCell> original{cell(1, {0, 0, 0}), cell(2, {1, 0, 0}, {1.0, 0.0, 0.0})};
    const auto links = allLinks({{1, 2}});
    const auto reference = evaluate(original, links, 5);

    const Quat rotation{std::sqrt(0.5), 0.0, 0.0, std::sqrt(0.5)};
    const Vec3 translation{3.0, -2.0, 0.75};
    auto transformed = original;
    for (auto &item : transformed) {
        item.center_world_m = rotation.rotate(item.center_world_m) + translation;
        for (auto &axis : item.half_axes_world_m) {
            axis = rotation.rotate(axis);
        }
    }
    const auto moved = evaluate(transformed, links, 5);
    require(moved.triangles.size() == reference.triangles.size(), "rigid transform must preserve topology");
    for (std::size_t index = 0; index < moved.triangles.size(); ++index) {
        for (unsigned corner = 0; corner < 3U; ++corner) {
            const Vec3 expected = rotation.rotate(reference.triangles[index].positions_world_m[corner]) +
                                  translation;
            require(near(moved.triangles[index].positions_world_m[corner], expected),
                    "skin positions must be equivariant under rigid transforms");
        }
    }
}

void finiteDeformationProducesFinitePositions() {
    auto cells = std::vector<SkinCell>{cell(1, {0, 0, 0})};
    cells[0].center_world_m = {2.0, -1.0, 4.0};
    cells[0].half_axes_world_m = {
        Vec3{0.6, 0.1, 0.0}, Vec3{0.0, 0.45, 0.05}, Vec3{0.02, 0.0, 0.55}};
    const auto mesh = evaluate(cells, {}, 6);
    require(mesh.triangles.size() == 12U, "finite deformation should preserve blocky topology");
    requireFinite(mesh);
}

void rejectsInvalidAndStaleInputs() {
    const std::vector<SkinCell> one{cell(1, {0, 0, 0})};
    const auto expectThrow = [](const std::function<void()> &operation, std::string_view message) {
        bool threw = false;
        try {
            operation();
        } catch (const std::exception &) {
            threw = true;
        }
        require(threw, message);
    };

    const std::vector<SkinCell> emptyCells;
    const std::vector<SkinFaceLink> emptyLinks;
    expectThrow([&] { banjo::buildCellSkinTopology(emptyCells, emptyLinks, 1); },
                "empty input should be rejected");
    const std::vector<SkinCell> duplicateCells{
        cell(1, {0, 0, 0}), cell(1, {1, 0, 0})};
    expectThrow([&] { banjo::buildCellSkinTopology(duplicateCells, emptyLinks, 1); },
                "duplicate cell IDs should be rejected");

    auto topology = banjo::buildCellSkinTopology(one, emptyLinks, 7);
    auto wrongId = one;
    wrongId[0].id = 99;
    expectThrow([&] { banjo::evaluateCellSkin(topology, wrongId); },
                "topology with mismatched cell IDs should be rejected");

    auto wrongGrid = one;
    wrongGrid[0].grid = {1, 0, 0};
    expectThrow([&] { banjo::evaluateCellSkin(topology, wrongGrid); },
                "stale topology after a grid change should be rejected");

    auto badTopology = topology;
    badTopology.faces.front().cell_index = 99;
    expectThrow([&] { banjo::evaluateCellSkin(badTopology, one); },
                "topology with an invalid cell index should be rejected");

    auto badLink = std::vector<SkinFaceLink>{{1, 999, true}};
    expectThrow([&] { banjo::buildCellSkinTopology(one, badLink, 1); },
                "links to unknown cells should be rejected");
}

void rejectsOversizedInput() {
    std::vector<SkinCell> cells;
    cells.reserve(4097U);
    for (std::uint32_t id = 1; id <= 4097U; ++id) {
        cells.push_back(cell(id, {static_cast<int>(id), 0, 0}));
    }
    bool threw = false;
    try {
        const std::vector<SkinFaceLink> emptyLinks;
        (void)banjo::buildCellSkinTopology(cells, emptyLinks, 8);
    } catch (const std::exception &) {
        threw = true;
    }
    require(threw, "oversized topology input should be rejected by the bounded API");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"isolated cell has six outward faces", isolatedCellHasSixOutwardFaces},
        {"live adjacency removes internal face", liveAdjacencyRemovesInternalFace},
        {"broken adjacency exposes fracture and separates components",
         brokenAdjacencyExposesFractureAndSeparatesComponents},
        {"partial break in connected patch exposes failed interface",
         partialBreakInConnectedPatchExposesFailedInterface},
        {"interior partial cut retains component and owner-local lips",
         interiorPartialCutRetainsComponentAndOwnerLocalLips},
        {"rigid transform is equivariant", rigidTransformIsEquivariant},
        {"finite deformation produces finite positions", finiteDeformationProducesFinitePositions},
        {"invalid and stale inputs are rejected", rejectsInvalidAndStaleInputs},
        {"oversized input is rejected", rejectsOversizedInput},
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
