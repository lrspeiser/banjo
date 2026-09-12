// A piece whose hull will not build still becomes a body.
//
// Some pieces come off a break nearly flat, or nearly in a line. Jolt's convex
// hull builder cannot always make a shape that contains such a point set, and
// says so: measured in a live room, "Hull building failed, point 166 had an
// error of 0.049654" -- five centimetres outside the hull it built, which is two
// and a half cells. That is not a tolerance to loosen. A hull that misses a
// point by five centimetres is the wrong shape, and accepting it would mean a
// shard that collides with thin air.
//
// The cells are right there, though, and they are the piece's ACTUAL shape
// rather than an approximation of one. Anchored scenery has always been built
// that way for a different reason -- a convex hull cannot be concave, so a bowl
// would be solid to the touch -- and the same fallback serves here.
//
// What it cost before: one shard the builder could not handle threw out of
// addFragments, which threw out of the fracture, and from outside a break
// simply did not happen.

#include "fracture/FragmentGeometry.hpp"
#include "rigid/JoltWorld.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace banjo;

namespace {

int failures = 0;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

FragmentMassProperties massOf(double kg) {
    FragmentMassProperties mass{};
    mass.mass_kg = kg;
    mass.center_of_mass_world_m = Vec3{0.0, 1.0, 0.0};
    // Any positive, well-conditioned inertia: this is about the collision
    // shape, and a body with a singular inertia would fail for its own reasons.
    mass.inertia_world_kg_m2 = Mat3{{{{{kg * 0.01, 0.0, 0.0}},
                                     {{0.0, kg * 0.01, 0.0}},
                                     {{0.0, 0.0, kg * 0.01}}}}};
    return mass;
}

// Points that all lie in one plane.
//
// Jolt copes with these -- it gives a coplanar set some thickness and builds a
// hull anyway -- so this one guards against that changing rather than
// exercising the fallback. The case that actually needs the fallback is the
// straight line below, which fails with "could not find a suitable initial
// triangle because its area was too small".
RigidFragmentDescription flatPiece(MatterBodyId id, std::size_t across) {
    RigidFragmentDescription piece{};
    piece.body_id = id;
    piece.mass_properties = massOf(0.4);
    piece.voxel_size_m = 0.02;
    for (std::size_t i = 0; i < across; ++i)
        for (std::size_t j = 0; j < across; ++j) {
            const Vec3 at{static_cast<double>(i) * 0.02, 0.0,
                          static_cast<double>(j) * 0.02};
            piece.collision_points_local_m.push_back(at);
            piece.voxel_centers_local_m.push_back(at);
        }
    piece.source_node_count = piece.voxel_centers_local_m.size();
    return piece;
}

void aFlatPieceStillBecomesABody() {
    JoltWorld world;
    world.setGravity({0.0, -9.80665, 0.0});
    const RigidFragmentDescription piece = flatPiece(2001, 6);

    bool threw = false;
    std::string said;
    try {
        world.addFragments({piece});
    } catch (const std::exception &error) {
        threw = true;
        said = error.what();
    }
    std::cout << "  a flat piece of " << piece.voxel_centers_local_m.size()
              << " cells: " << (threw ? said : std::string("became a body")) << "\n";
    require(!threw, "a flat piece refused to become a body: " + said);
    require(world.contains(2001), "the piece was accepted and is not in the world");
}

void aPieceInALineStillBecomesABody() {
    JoltWorld world;
    world.setGravity({0.0, -9.80665, 0.0});
    RigidFragmentDescription piece{};
    piece.body_id = 2002;
    piece.mass_properties = massOf(0.2);
    piece.voxel_size_m = 0.02;
    // Nine cells in a row: no area at all, let alone volume. This is the one
    // that needs the fallback -- checked by removing it, which fails here and
    // nowhere else in this file.
    for (std::size_t i = 0; i < 9; ++i) {
        const Vec3 at{static_cast<double>(i) * 0.02, 0.0, 0.0};
        piece.collision_points_local_m.push_back(at);
        piece.voxel_centers_local_m.push_back(at);
    }
    piece.source_node_count = piece.voxel_centers_local_m.size();

    bool threw = false;
    std::string said;
    try {
        world.addFragments({piece});
    } catch (const std::exception &error) {
        threw = true;
        said = error.what();
    }
    std::cout << "  a piece nine cells in a row: "
              << (threw ? said : std::string("became a body")) << "\n";
    require(!threw, "a piece in a straight line refused to become a body: " + said);
    require(world.contains(2002), "the piece was accepted and is not in the world");
}

void aPieceThatCannotBeBuiltAtAllStillSaysSo() {
    // No cells to fall back to. This one SHOULD refuse -- the point of the
    // fallback is that there is something to fall back to, and a failure with
    // nothing behind it must still be reported rather than swallowed.
    JoltWorld world;
    RigidFragmentDescription piece{};
    piece.body_id = 2003;
    piece.mass_properties = massOf(0.2);
    for (std::size_t i = 0; i < 8; ++i)
        piece.collision_points_local_m.push_back(
            Vec3{static_cast<double>(i) * 0.02, 0.0, 0.0});
    piece.source_node_count = 8;
    // voxel_centers deliberately empty, voxel_size 0.

    bool threw = false;
    try {
        world.addFragments({piece});
    } catch (const std::exception &) {
        threw = true;
    }
    std::cout << "  a piece with no cells to fall back to: "
              << (threw ? "refused, and said so" : "was quietly accepted") << "\n";
    require(threw,
            "a piece whose hull cannot be built and that has no cells was "
            "accepted anyway, so something is in the world with no shape");
}

void theFallbackIsTheShapeTheCellsMake() {
    // Not just "a body exists" -- it has to collide as the cells. A flat sheet
    // of cells is 20 mm thick, so something dropped on it stops 20 mm up, not
    // at the floor and not somewhere a bad hull put it.
    JoltWorld world;
    world.setGravity({0.0, -9.80665, 0.0});
    RigidFragmentDescription sheet = flatPiece(2004, 10);
    // Anchored, so it holds still and whatever lands on it has to rest on it.
    sheet.anchored = true;
    sheet.mass_properties.center_of_mass_world_m = Vec3{0.0, 0.5, 0.0};
    world.addFragments({sheet});
    require(world.contains(2004), "the sheet is not in the world");

    RigidFragmentDescription ball{};
    ball.body_id = 2005;
    ball.mass_properties = massOf(1.0);
    ball.mass_properties.center_of_mass_world_m = Vec3{0.09, 1.2, 0.09};
    ball.primitive = FragmentPrimitive::Sphere;
    ball.primitive_dimensions_m = Vec3{0.06, 0.06, 0.06};
    ball.voxel_size_m = 0.02;
    for (int i = -1; i <= 1; ++i)
        for (int j = -1; j <= 1; ++j)
            for (int k = -1; k <= 1; ++k) {
                const Vec3 at{i * 0.02, j * 0.02, k * 0.02};
                ball.collision_points_local_m.push_back(at);
                ball.voxel_centers_local_m.push_back(at);
            }
    ball.source_node_count = ball.voxel_centers_local_m.size();
    world.addFragments({ball});

    for (int i = 0; i < 480; ++i) world.step(1.0 / 240.0);
    const RigidSnapshot rest = world.snapshot(2005);
    const double y = rest.center_of_mass_world_m.y;
    std::cout << "  a ball dropped on the flat piece came to rest at y=" << y
              << " m (the sheet's cells are centred at 0.5 and 20 mm thick)\n";
    require(y > 0.5,
            "the ball fell through or into the flat piece, so the fallback shape "
            "is not the shape its cells make");
    require(y < 0.75, "the ball came to rest well above the sheet, so the shape "
                      "it landed on is not the sheet's cells either");
}

} // namespace

int main() {
    try {
        aFlatPieceStillBecomesABody();
        std::cout << "[PASS] a flat piece still becomes a body\n";
        aPieceInALineStillBecomesABody();
        std::cout << "[PASS] a piece in a line still becomes a body\n";
        aPieceThatCannotBeBuiltAtAllStillSaysSo();
        std::cout << "[PASS] a piece with nothing to fall back to still says so\n";
        theFallbackIsTheShapeTheCellsMake();
        std::cout << "[PASS] the fallback is the shape the cells make\n";
    } catch (const std::exception &error) {
        std::cout << "degenerate fragment tests failed: " << error.what() << std::endl;
        return 1;
    }
    if (failures) {
        std::cout << "\n" << failures << " failed\n";
        return 1;
    }
    std::cout << "\nall degenerate fragment tests passed\n";
    return 0;
}
