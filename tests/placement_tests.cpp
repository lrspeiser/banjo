// Where a thing would go set down, and whether it fits (LiveWorld::placement).
//
// The first half of placing a thing (docs/inventory-and-hands.md, section 5):
// the page shows a see-through copy where the person is looking and asks the
// engine this -- set down upright on the surface there, what would it go into,
// what would it rest on, and how much of it has something under it. Asked of
// the shapes the solver collides, and nothing in the room moves for it.

#include "fastlattice/LiveWorld.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

constexpr double kPi = 3.14159265358979323846;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

// A concrete slab to stand things on, an oak crate on it, and an iron ball
// beside the crate. The slab's top is y = 0; the crate's runs from x 0.8 to 1.2
// and is 0.4 m up.
TileImpactRequest room() {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody slab;
    slab.name = "slab";
    slab.shape = BodyShape::Box;
    slab.material = MaterialPreset::Concrete;
    slab.dimensions_m = {3.0, 0.1, 3.0};
    slab.center_m = {0.0, -0.05, 0.0};
    slab.anchored = true;
    SceneBody crate;
    crate.name = "oak crate";
    crate.shape = BodyShape::Box;
    crate.material = MaterialPreset::Oak;
    crate.dimensions_m = {0.4, 0.4, 0.4};
    crate.center_m = {1.0, 0.2, 0.0};
    SceneBody ball;
    ball.name = "iron ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.1, 0.1, 0.1};
    ball.center_m = {0.0, 0.05, 0.0};
    r.bodies = {slab, crate, ball};
    return r;
}

void onOpenSlabItFitsAndRestsOnTheSlab() {
    const auto world = LiveWorld::open(room());
    const LivePlacement p = world->placement("iron ball", Vec3{-1.0, 0.0, 0.5}, 0.0, "slab");
    std::cout << "  on open slab: " << p.why << "; its middle " << p.at_m.y << " m up, "
              << p.supported_corners << " corners with something under them\n";
    require(p.fits, "the ball does not fit on open slab: " + p.why);
    require(p.rests_on == "slab", "it rests on \"" + p.rests_on + "\", not the slab");
    require(std::abs(p.at_m.y - 0.052) < 1e-4, "its underside is not 2 mm over the slab");
    require(p.supported_corners == 4, "open slab left corners with nothing under them");
    require(p.touching.empty(), "it goes into something on open slab");
}

void onTheCrateItRestsOnTheCrate() {
    const auto world = LiveWorld::open(room());
    const LivePlacement p = world->placement("iron ball", Vec3{1.0, 0.4, 0.0}, 0.0, "oak crate");
    std::cout << "  on the crate: " << p.why << "\n";
    require(p.fits && p.rests_on == "oak crate", "on the crate's top: " + p.why);
    require(std::abs(p.at_m.y - 0.452) < 1e-4, "its underside is not 2 mm over the crate");
}

void overAnEdgeItFitsButIsSaidToTip() {
    const auto world = LiveWorld::open(room());
    // Its middle just inside the crate's edge at x = 1.2: half its footprint
    // is over nothing.
    const LivePlacement p = world->placement("iron ball", Vec3{1.19, 0.4, 0.0}, 0.0, "oak crate");
    std::cout << "  at the crate's edge: " << p.why << ", " << p.supported_corners
              << " corners with something under them\n";
    require(p.fits, "the ball at the crate's edge did not fit at all: " + p.why);
    require(p.supported_corners == 2, "at the edge " + std::to_string(p.supported_corners) +
                                          " corners had something under them, not 2");
    require(p.why.find("tip") != std::string::npos, "at the edge it was not said it may tip: " + p.why);
}

void theCrateWhereTheBallIsWouldGoIntoTheBall() {
    const auto world = LiveWorld::open(room());
    // Set on the slab where the ball lies: the slab is what it goes on, and the
    // ball is in the way -- it is not lifted onto the ball.
    const LivePlacement p = world->placement("oak crate", Vec3{0.0, 0.0, 0.0}, 0.0, "slab");
    std::cout << "  the crate where the ball is: " << p.why << "\n";
    require(!p.fits, "the crate fitted where the ball is");
    require(!p.touching.empty() && p.touching.front().first == "iron ball",
            "it was not the ball the crate would go into: " + p.why);
}

void turnedAboutTheVerticalItStaysUpright() {
    const auto world = LiveWorld::open(room());
    const double yaw = 0.25 * kPi;
    const LivePlacement p = world->placement("oak crate", Vec3{-1.0, 0.0, -1.0}, yaw, "slab");
    std::cout << "  the crate turned 45 degrees: " << p.why << "; its middle " << p.at_m.y << " m up\n";
    require(p.fits, "the crate turned 45 degrees on open slab did not fit: " + p.why);
    require(std::abs(p.turn_wxyz[0] - std::cos(0.5 * yaw)) < 1e-12 && p.turn_wxyz[1] == 0.0 &&
                std::abs(p.turn_wxyz[2] - std::sin(0.5 * yaw)) < 1e-12 && p.turn_wxyz[3] == 0.0,
            "the turn is not about the vertical alone");
    // Turned about the vertical, a box's underside is where it was: 0.2 m down.
    require(std::abs(p.at_m.y - 0.202) < 1e-4, "turned, its underside is not 2 mm over the slab");
    // A box built square faces the way its rigid frame does.
    for (int k = 0; k < 4; ++k)
        require(std::abs(p.facing_wxyz[k] - p.turn_wxyz[k]) < 1e-12, "a square box's facing is not its turn");
}

// The slab, with a concrete ramp on it tilted 20 degrees about z, and the ball.
TileImpactRequest rampRoom() {
    TileImpactRequest r = room();
    SceneBody ramp;
    ramp.name = "ramp";
    ramp.shape = BodyShape::Box;
    ramp.material = MaterialPreset::Concrete;
    ramp.dimensions_m = {1.0, 0.1, 1.0};
    ramp.center_m = {-1.0, 0.3, -1.0};
    ramp.rotation_deg = {0.0, 0.0, 20.0};
    ramp.anchored = true;
    r.bodies.push_back(ramp);
    return r;
}

void onASlopeItIsLiftedClearAndSaidToRoll() {
    const auto world = LiveWorld::open(rampRoom());
    // Straight down onto the ramp's top from above its middle: the point a
    // crosshair looking down would find.
    const LivePick top = world->pick(Vec3{-1.0, 2.0, -1.0}, Vec3{0.0, -1.0, 0.0});
    require(top.hit && top.name == "ramp", "the ray from above did not find the ramp's top");
    const LivePlacement p = world->placement("iron ball", top.point_world_m, 0.0, top.name);
    const double lifted = p.at_m.y - top.point_world_m.y;
    std::cout << "  on the ramp: " << p.why << "; its middle " << lifted << " m over the spot\n";
    require(p.fits, "the ball on a 20 degree ramp did not fit: " + p.why);
    require(p.rests_on == "ramp", "on the ramp it rests on \"" + p.rests_on + "\"");
    require(p.touching.empty(), "on the ramp it goes into something");
    // A 50 mm ball touching a 20 degree slope stands 0.05 / cos 20 = 53.2 mm
    // over the point under its middle -- more than the 52 mm a flat floor asks.
    require(lifted > 0.0525 && lifted < 0.065, "it was not lifted clear of the slope, or lifted too far");
    require(p.why.find("roll") != std::string::npos, "a slope was not said: " + p.why);
}

void onTheCratesSideItIsTooSteep() {
    const auto world = LiveWorld::open(room());
    // The crosshair on the crate's side, halfway up: not a place to set a thing.
    const LivePick side = world->pick(Vec3{2.0, 0.2, 0.0}, Vec3{-1.0, 0.0, 0.0});
    require(side.hit && side.name == "oak crate", "the ray did not find the crate's side");
    const LivePlacement p = world->placement("iron ball", side.point_world_m, 0.0, side.name);
    std::cout << "  on the crate's side: " << p.why << "\n";
    require(!p.fits && p.why.find("steep") != std::string::npos,
            "the crate's side was a place to set it: " + p.why);
}

void askingMovesNothing() {
    const auto world = LiveWorld::open(room());
    const auto before = world->poses();
    (void)world->placement("oak crate", Vec3{0.0, 0.0, 0.0}, 0.7);
    (void)world->placement("iron ball", Vec3{1.19, 0.4, 0.0}, 0.0);
    (void)world->placement("iron ball", Vec3{-1.0, 0.0, 0.5}, 2.0);
    const auto after = world->poses();
    require(before.size() == after.size(), "asking changed how many things there are");
    for (std::size_t i = 0; i < before.size(); ++i) {
        const LiveBodyPose &a = before[i], &b = after[i];
        const bool same = a.name == b.name && a.position_m.x == b.position_m.x &&
                          a.position_m.y == b.position_m.y && a.position_m.z == b.position_m.z &&
                          a.orientation_wxyz[0] == b.orientation_wxyz[0] &&
                          a.orientation_wxyz[1] == b.orientation_wxyz[1] &&
                          a.orientation_wxyz[2] == b.orientation_wxyz[2] &&
                          a.orientation_wxyz[3] == b.orientation_wxyz[3];
        require(same, "asking where " + a.name + " would go moved something");
    }
}

void supportRemainsVisibleWhenTheItemHasArrived() {
    const auto world = LiveWorld::open(room());
    // The query origin is inside the actual crate now. It must see the slab
    // beneath it, not stop at the same item whose destination is being checked.
    const LivePlacement p = world->placement("oak crate", Vec3{1.0, 0.0, 0.0}, 0.0, "slab");
    require(p.fits && p.rests_on == "slab" && p.supported_corners == 4,
            "an arrived item hid its own support: " + p.why);
}

// A tall, thin oak bookcase -- 0.9 m wide, 1.8 m tall, 0.3 m deep, its middle
// 0.9 m over its underside -- and an oak crate as wide as it is tall, both on
// the floor; concrete ramps tilted about x, so that each falls along z; and a
// concrete plinth with a flat top. Across its narrow side the bookcase goes
// over on a slope of 0.15 / 0.9 (9.5 degrees), along its wide side on
// 0.45 / 0.9 (26.6 degrees).
constexpr double kRampXs[] = {-4.5, -1.5, 1.5, 4.5};
constexpr double kRampDegrees[] = {3.0, 6.0, 7.0, 12.0};

TileImpactRequest slopesRoom() {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody bookcase;
    bookcase.name = "bookcase";
    bookcase.shape = BodyShape::Box;
    bookcase.material = MaterialPreset::Oak;
    bookcase.dimensions_m = {0.9, 1.8, 0.3};
    bookcase.center_m = {0.0, 0.9, -3.0};
    SceneBody crate;
    crate.name = "oak crate";
    crate.shape = BodyShape::Box;
    crate.material = MaterialPreset::Oak;
    crate.dimensions_m = {0.4, 0.4, 0.4};
    crate.center_m = {2.0, 0.2, -3.0};
    SceneBody plinth;
    plinth.name = "plinth";
    plinth.shape = BodyShape::Box;
    plinth.material = MaterialPreset::Concrete;
    plinth.dimensions_m = {0.8, 0.4, 0.8};
    plinth.center_m = {-3.0, 0.2, -3.0};
    plinth.anchored = true;
    r.bodies = {bookcase, crate, plinth};
    for (int k = 0; k < 4; ++k) {
        SceneBody ramp;
        ramp.name = "ramp " + std::to_string(static_cast<int>(kRampDegrees[k]));
        ramp.shape = BodyShape::Box;
        ramp.material = MaterialPreset::Concrete;
        ramp.dimensions_m = {1.5, 0.1, 1.5};
        ramp.center_m = {kRampXs[k], 0.6, 0.0};
        ramp.rotation_deg = {kRampDegrees[k], 0.0, 0.0};
        ramp.anchored = true;
        r.bodies.push_back(ramp);
    }
    return r;
}

// `name` set down on the middle of the ramp tilted `degrees`, turned `yaw`
// about the vertical.
LivePlacement onRamp(const LiveWorld &world, const std::string &name, double degrees, double yaw = 0.0) {
    for (int k = 0; k < 4; ++k) {
        if (kRampDegrees[k] != degrees) continue;
        const LivePick top = world.pick(Vec3{kRampXs[k], 3.0, 0.0}, Vec3{0.0, -1.0, 0.0});
        require(top.hit && top.name.rfind("ramp", 0) == 0, "the ray from above did not find the ramp's top");
        const LivePlacement p = world.placement(name, top.point_world_m, yaw, top.name);
        std::cout << "  " << name << " on " << top.name << (yaw != 0.0 ? " turned" : "") << ": " << p.why
                  << "; " << p.tipping_used << " of what tips it, " << p.supported_corners << " corners\n";
        return p;
    }
    throw std::runtime_error("no ramp of that slope");
}

bool near(double got, double want, double within) { return std::abs(got - want) <= within; }

void aTallThingOnAGentleSlopeFits() {
    const auto world = LiveWorld::open(slopesRoom());
    const LivePlacement p = onRamp(*world, "bookcase", 3.0);
    // Its middle leans out 0.9 tan 3 = 47 mm of the 150 it has.
    require(p.fits && !p.may_fall_over && p.why == "it fits here, on the ramp 3",
            "on 3 degrees the bookcase did not simply fit: " + p.why);
    require(near(p.tipping_used, 0.9 * std::tan(3.0 * kPi / 180.0) / 0.15, 0.01),
            "on 3 degrees it used " + std::to_string(p.tipping_used) + " of what tips it, not 0.31");
}

void pastHalfOfWhatTipsItItIsSaidToFallOver() {
    const auto world = LiveWorld::open(slopesRoom());
    const LivePlacement p = onRamp(*world, "bookcase", 6.0);
    require(p.fits && p.may_fall_over && p.why == "it fits, but it is tall for that slope: it may fall over",
            "on 6 degrees, 0.63 of what tips it, the bookcase was not said to be tall for it: " + p.why);
    require(near(p.tipping_used, 0.9 * std::tan(6.0 * kPi / 180.0) / 0.15, 0.01),
            "on 6 degrees it used " + std::to_string(p.tipping_used) + " of what tips it, not 0.63");
}

void pastWhatTipsItItIsRefused() {
    const auto world = LiveWorld::open(slopesRoom());
    // 12 degrees drops its downhill corners further below it than the 35 mm
    // the corners are otherwise read to, so this is also "little of it is on
    // the ramp" -- and why is the slope.
    const LivePlacement p = onRamp(*world, "bookcase", 12.0);
    require(!p.fits && p.may_fall_over && p.why == "it is too tall for that slope: it would fall over",
            "on 12 degrees, past the 9.5 it goes over at, the bookcase was not refused: " + p.why);
    require(near(p.tipping_used, 0.9 * std::tan(12.0 * kPi / 180.0) / 0.15, 0.01),
            "on 12 degrees it used " + std::to_string(p.tipping_used) + " of what tips it, not 1.28");
}

void itsOwnNarrowSideCountsWhicheverWayItIsTurned() {
    const auto world = LiveWorld::open(slopesRoom());
    // Turned 30 degrees, the slope runs across its narrow side at cos 30 of
    // itself: 0.64 of what tips it. The box around it turned is 0.71 m deep,
    // and read from that it would be 0.31, and fit.
    const LivePlacement turned = onRamp(*world, "bookcase", 7.0, kPi / 6.0);
    require(turned.fits && turned.may_fall_over,
            "turned 30 degrees on 7, the bookcase was not said to be tall for it: " + turned.why);
    require(near(turned.tipping_used, 0.9 * std::tan(7.0 * kPi / 180.0) * std::cos(kPi / 6.0) / 0.15, 0.01),
            "turned 30 degrees on 7 it used " + std::to_string(turned.tipping_used) + " of what tips it, not 0.64");
    // Turned a quarter, the same 6 degrees runs along its wide side, which it
    // goes over on only at 26.6 degrees.
    const LivePlacement quarter = onRamp(*world, "bookcase", 6.0, 0.5 * kPi);
    require(!quarter.may_fall_over && quarter.why.find("fall over") == std::string::npos,
            "turned a quarter on 6 degrees the bookcase was said to fall over: " + quarter.why);
    require(near(quarter.tipping_used, 0.9 * std::tan(6.0 * kPi / 180.0) / 0.45, 0.01),
            "turned a quarter on 6 it used " + std::to_string(quarter.tipping_used) + " of what tips it, not 0.21");
}

void aThingNoTallerThanItIsWideIsNotSaidToFallOver() {
    const auto world = LiveWorld::open(slopesRoom());
    // The crate slides long before it tips; the slope's own rules speak for it.
    const LivePlacement p = onRamp(*world, "oak crate", 12.0);
    require(!p.may_fall_over && p.tipping_used == 0.0 && p.why.find("fall over") == std::string::npos,
            "the crate on 12 degrees was said to fall over: " + p.why);
}

void overAnEdgeIsNotASlope() {
    const auto world = LiveWorld::open(slopesRoom());
    // Its middle 50 mm in from the plinth's edge: half of it is over the floor
    // 0.4 m below, which is a drop, not ground sloping down to it.
    const LivePick top = world->pick(Vec3{-2.65, 3.0, -3.0}, Vec3{0.0, -1.0, 0.0});
    require(top.hit && top.name == "plinth", "the ray from above did not find the plinth");
    const LivePlacement p = world->placement("bookcase", top.point_world_m, 0.0, top.name);
    std::cout << "  the bookcase at the plinth's edge: " << p.why << "\n";
    require(p.fits && p.why.find("tip off") != std::string::npos && p.tipping_used == 0.0,
            "at the plinth's edge it was not said to tip off, or the drop was read as a slope: " + p.why);
}

void theSlabIsFixedAndWhatIsNotThereIsSaid() {
    const auto world = LiveWorld::open(room());
    const LivePlacement fixed = world->placement("slab", Vec3{0.0, 0.0, 0.0}, 0.0);
    require(!fixed.fits && fixed.why == "it is fixed in place", "the slab: " + fixed.why);
    const LivePlacement missing = world->placement("anvil", Vec3{0.0, 0.0, 0.0}, 0.0);
    require(!missing.fits && missing.why == "there is nothing called that here", "an anvil: " + missing.why);
}

} // namespace

int main() {
    try {
        onOpenSlabItFitsAndRestsOnTheSlab();
        std::cout << "[PASS] on open slab it fits, 2 mm clear, resting on the slab\n";
        onTheCrateItRestsOnTheCrate();
        std::cout << "[PASS] on the crate it rests on the crate\n";
        overAnEdgeItFitsButIsSaidToTip();
        std::cout << "[PASS] over an edge it fits, and is said to tip\n";
        theCrateWhereTheBallIsWouldGoIntoTheBall();
        std::cout << "[PASS] the crate where the ball is would go into the ball\n";
        turnedAboutTheVerticalItStaysUpright();
        std::cout << "[PASS] turned about the vertical it stays upright\n";
        onASlopeItIsLiftedClearAndSaidToRoll();
        std::cout << "[PASS] on a slope it is lifted clear, and said to roll\n";
        onTheCratesSideItIsTooSteep();
        std::cout << "[PASS] on the crate's side it is too steep\n";
        askingMovesNothing();
        std::cout << "[PASS] asking moves nothing\n";
        supportRemainsVisibleWhenTheItemHasArrived();
        std::cout << "[PASS] an arrived item does not hide its own support\n";
        theSlabIsFixedAndWhatIsNotThereIsSaid();
        std::cout << "[PASS] the slab is fixed, and what is not there is said\n";
        aTallThingOnAGentleSlopeFits();
        std::cout << "[PASS] a tall thing on a gentle slope fits\n";
        pastHalfOfWhatTipsItItIsSaidToFallOver();
        std::cout << "[PASS] past half of what tips it, a tall thing is said to fall over\n";
        pastWhatTipsItItIsRefused();
        std::cout << "[PASS] past what tips it, it is refused\n";
        itsOwnNarrowSideCountsWhicheverWayItIsTurned();
        std::cout << "[PASS] its own narrow side counts, whichever way it is turned\n";
        aThingNoTallerThanItIsWideIsNotSaidToFallOver();
        std::cout << "[PASS] a thing no taller than it is wide is not said to fall over\n";
        overAnEdgeIsNotASlope();
        std::cout << "[PASS] a drop over an edge is not read as a slope\n";
        std::cout << "\nall placement tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
