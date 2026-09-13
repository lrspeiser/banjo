// Ropes and chains.
//
// A link is two points that may be any distance apart UP TO a limit and no
// further. That one asymmetry is the whole of it: a rope pulls and it does not
// push. Below its length the link does nothing at all -- no force, no damping,
// no quiet stiffness -- so slack is really slack.
//
// A rope here is made of links rather than being a special kind of object: a
// run of small bodies, each tied to the next. Which means it hangs in a
// catenary because its own segments are heavy, drapes over what it touches
// because its segments collide, and can be cut anywhere along its length,
// because every link is separately real. Nothing in this file is a "rope
// object" and there is no rope solver.
//
// What is pinned:
//
// 1. A link pulls: a weight tied under an anchor hangs instead of falling.
// 2. A link does not push: the same weight, lifted, falls freely until the
//    rope goes taut, and the rope does nothing on the way.
// 3. Slack is slack: a weight on a long rope falls the whole slack length
//    before it is caught.
// 4. A rope of many links hangs in a curve, and the curve is not a straight
//    line between its ends.
// 5. Tension is reported, it is about right, and it is zero when slack.
// 6. A rope parts when it is overloaded, and says so.
// 7. Cutting a link drops what was under it.
// 8. A rope carries a load: hang a weight halfway and both ends take it.
// 9. A rope's length is measured between where it is tied, not between the
//    middles of the two things it ties, taut or slack.
// 10. Tension is a force: the same load reads the same at any step size, and a
//    hand pulling on it adds exactly the hand's strength.

#include "fastlattice/LiveWorld.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

const LiveBodyPose &named(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

// By value: joints() returns a fresh vector, so a reference into one dangles.
LiveJoint jointNumber(const std::vector<LiveJoint> &joints, unsigned id) {
    for (const LiveJoint &joint : joints)
        if (joint.id == id) return joint;
    throw std::runtime_error("no joint with that id");
}

void tick(LiveWorld &world, double dt_s = 1.0 / 240.0) {
    world.step(dt_s);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void run(LiveWorld &world, int steps) {
    for (int i = 0; i < steps; ++i) tick(world);
}

double heightOf(LiveWorld &world, const std::string &name) {
    return named(world.poses(), name).position_m.y;
}

// Where a point fixed in a body is now: its offset from the body's centre,
// turned the way the body has turned and carried to where the body stands.
Vec3 carried(const LiveBodyPose &pose, const Vec3 &offset) {
    const double w = pose.orientation_wxyz[0];
    const Vec3 q{pose.orientation_wxyz[1], pose.orientation_wxyz[2], pose.orientation_wxyz[3]};
    const Vec3 t = 2.0 * cross(q, offset);
    return pose.position_m + offset + w * t + cross(q, t);
}

// How far a body has turned from how it was built, about whatever axis.
double turnedDegrees(const LiveBodyPose &pose) {
    const double w = std::min(1.0, std::abs(pose.orientation_wxyz[0]));
    return 2.0 * std::acos(w) * 180.0 / 3.14159265358979323846;
}

// A beam overhead with a weight under it, and nothing between them yet.
//
// `weight_mm_below` is how far below the beam the weight starts. Tie a rope of
// the gap's length and it hangs; start the weight higher and the same rope has
// slack in it.
TileImpactRequest gantry(double weight_mm_below = 1000.0, int links = 0) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody beam;
    beam.name = "beam";
    beam.shape = BodyShape::Box;
    beam.material = MaterialPreset::Oak;
    beam.dimensions_m = {2.0, 0.2, 0.2};
    beam.center_m = {0.0, 4.0, 0.0};
    beam.anchored = true;
    SceneBody weight;
    weight.name = "weight";
    weight.shape = BodyShape::Box;
    weight.material = MaterialPreset::Iron;
    weight.dimensions_m = {0.2, 0.2, 0.2};
    weight.center_m = {0.0, 4.0 - weight_mm_below / 1000.0, 0.0};
    r.bodies = {beam, weight};
    // Rope segments, if this scene wants a rope rather than a single tie. They
    // are ordinary authored bodies: that is the point -- a rope is not a kind
    // of object here, it is a row of things tied to each other.
    for (int i = 0; i < links; ++i) {
        SceneBody segment;
        segment.name = "rope " + std::to_string(i + 1);
        segment.shape = BodyShape::Box;
        segment.material = MaterialPreset::Oak;
        segment.dimensions_m = {0.1, 0.1, 0.1};
        segment.center_m = {0.0, 3.85 - 0.15 * i, 0.0};
        r.bodies.push_back(segment);
    }
    return r;
}

// A stone post and an iron block on the ground, a metre of rope to be tied
// between them. This is the scene the chat built for the QA's tether check
// ("Tie an iron block to a stone post with a one-metre rope"), cell for cell.
TileImpactRequest postAndBlock() {
    TileImpactRequest r;
    r.cell_size_m = 0.04;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Concrete;
    post.dimensions_m = {0.16, 1.2, 0.16};
    post.center_m = {0.0, 0.6, 0.0};
    post.anchored = true;
    SceneBody block;
    block.name = "block";
    block.shape = BodyShape::Box;
    block.material = MaterialPreset::Iron;
    block.dimensions_m = {0.16, 0.16, 0.16};
    block.center_m = {0.84, 0.08, 0.0};
    r.bodies = {post, block};
    return r;
}

// -----------------------------------------------------------------------------

void aLinkPulls() {
    // The weight starts a metre under the beam and is tied to it. A metre of
    // rope: it hangs, and it does not fall.
    const auto world = LiveWorld::open(gantry(1000.0));
    const unsigned rope = world->tie("beam", "weight", Vec3{0.0, 3.9, 0.0},
                                     Vec3{0.0, 3.0, 0.0});
    require(rope != 0, "the weight would not tie to the beam");
    const double hung = heightOf(*world, "weight");
    run(*world, 720);
    const double after = heightOf(*world, "weight");
    const LiveJoint tied = jointNumber(world->joints(), rope);
    std::cout << "  tied a metre under the beam: after three seconds it is at y="
              << after << " (it started at " << hung << "), carrying "
              << tied.tension_n << " N\n";
    require(std::abs(after - hung) < 0.05, "the weight fell through its own rope");
    require(tied.kind == "link", "a tie came back as the wrong kind of joint");
}

void aLinkDoesNotPush() {
    // The same rope, with the weight lifted right up under the beam. A rod
    // would hold it out at arm's length; a rope lets it drop.
    const auto world = LiveWorld::open(gantry(1000.0));
    const unsigned rope = world->tie("beam", "weight", Vec3{0.0, 3.9, 0.0},
                                     Vec3{0.0, 3.0, 0.0});
    require(rope != 0, "the weight would not tie to the beam");
    // Carry it up to just under the beam and let go.
    require(world->grab("weight"), "could not take hold of the weight");
    for (int i = 1; i <= 80; ++i) {
        world->moveHeld(Vec3{0.0, 3.0 + 0.01 * i, 0.0});
        tick(*world);
    }
    const double lifted = heightOf(*world, "weight");
    world->release();
    run(*world, 480);
    const double fell = heightOf(*world, "weight");
    std::cout << "  lifted to y=" << lifted << " and let go: it fell to y=" << fell
              << ", which is " << (lifted - fell) << " m\n";
    require(lifted > 3.6, "the lift did not happen");
    require(fell < 3.1, "the weight did not fall: the rope is pushing it out");
}

void slackIsSlack() {
    // Two metres of rope, a weight that starts half a metre down. It should
    // fall the metre and a half of slack before the rope even notices.
    const auto world = LiveWorld::open(gantry(500.0));
    const unsigned rope = world->tie("beam", "weight", Vec3{0.0, 3.9, 0.0},
                                     Vec3{0.0, 3.5, 0.0}, 2.0);
    require(rope != 0, "the weight would not tie to the beam");
    const double began = heightOf(*world, "weight");
    // While it is still falling the rope must be carrying nothing at all.
    run(*world, 60);
    const double while_falling = jointNumber(world->joints(), rope).tension_n;
    run(*world, 720);
    const double caught = heightOf(*world, "weight");
    const LiveJoint tied = jointNumber(world->joints(), rope);
    std::cout << "  2 m of rope on a weight starting 400 mm down: it fell from y="
              << began << " to y=" << caught << ", and carried " << while_falling
              << " N on the way down\n";
    require(began - caught > 1.2, "it was caught before its slack ran out");
    require(while_falling < 1.0,
            "the rope was pulling on it while it still had slack, so slack is "
            "not slack");
    require(std::abs(tied.at - 2.0) < 0.15,
            "it ended up somewhere other than the end of its rope");
}

void aRopeHangsInACurve() {
    // Six segments tied end to end between two points on the same beam. A rope
    // that hangs straight between its ends is a rope whose middle is not heavy,
    // which means the segments are not being simulated.
    TileImpactRequest request = gantry(1000.0, 6);
    const auto world = LiveWorld::open(request);
    // Tie the run: beam -> 1 -> 2 -> ... -> 6 -> beam, with the two ends a
    // metre apart and 1.4 m of rope between them, so it must sag.
    const double gap = 1.0, rope_m = 1.4;
    const double each = rope_m / 7.0;
    std::vector<Vec3> knots;
    for (int i = 0; i <= 6; ++i)
        knots.push_back(Vec3{-gap / 2 + gap * i / 6.0, 3.9, 0.0});

    // Lay the segments out along the line first, so the ties start sensible.
    std::vector<unsigned> links;
    for (int i = 0; i < 6; ++i) {
        const std::string segment = "rope " + std::to_string(i + 1);
        require(world->grab(segment), "could not place " + segment);
        world->moveHeld(knots[static_cast<std::size_t>(i)] + Vec3{0.05, -0.1, 0.0});
        tick(*world);
        world->release();
    }
    for (int i = 0; i <= 6; ++i) {
        const std::string left = i == 0 ? "beam" : "rope " + std::to_string(i);
        const std::string right = i == 6 ? "beam" : "rope " + std::to_string(i + 1);
        const auto standing = world->poses();
        const Vec3 from = i == 0 ? knots.front() : named(standing, left).position_m;
        const Vec3 to = i == 6 ? knots.back() : named(standing, right).position_m;
        const unsigned link = world->tie(left, right, from, to, each);
        require(link != 0, "could not tie " + left + " to " + right);
        links.push_back(link);
    }
    run(*world, 960);

    const auto hanging = world->poses();
    double lowest = 1e9;
    for (int i = 1; i <= 6; ++i)
        lowest = std::min(lowest, named(hanging, "rope " + std::to_string(i)).position_m.y);
    const double sag = 3.9 - lowest;
    std::cout << "  six segments over a 1 m gap with 1.4 m of rope: the middle "
              << "hangs " << sag << " m below the ends\n";
    require(sag > 0.1, "the rope hangs in a straight line, so its middle has no weight");
    require(sag < rope_m, "it sagged further than there is rope to sag with");
}

void tensionIsReportedAndIsAboutRight() {
    // 0.2 m of iron is 8 litres at 7,870 kg/m3: 63 kg, 618 N of weight. A rope
    // holding it up is carrying that, and if the number that comes back is not
    // in that neighbourhood then the tension is not a tension.
    const auto world = LiveWorld::open(gantry(1000.0));
    const unsigned rope = world->tie("beam", "weight", Vec3{0.0, 3.9, 0.0},
                                     Vec3{0.0, 3.0, 0.0});
    require(rope != 0, "the weight would not tie to the beam");
    run(*world, 960);
    const double carrying = jointNumber(world->joints(), rope).tension_n;
    constexpr double kWeightN = 0.2 * 0.2 * 0.2 * 7870.0 * 9.81;
    std::cout << "  the weight is " << kWeightN << " N and the rope reports "
              << carrying << " N\n";
    require(carrying > 0.5 * kWeightN && carrying < 2.0 * kWeightN,
            "the rope holding a 618 N weight is not reporting anything like 618 N");
}

void aRopePartsWhenItIsOverloaded() {
    // The same weight on a rope rated well under what it weighs. It must not
    // hold: a rope that cannot fail will hold a cathedral up.
    const auto world = LiveWorld::open(gantry(1000.0));
    constexpr double kWeightN = 0.2 * 0.2 * 0.2 * 7870.0 * 9.81;
    const unsigned rope = world->tie("beam", "weight", Vec3{0.0, 3.9, 0.0},
                                     Vec3{0.0, 3.0, 0.0}, 0.0, 0.25 * kWeightN);
    require(rope != 0, "the weight would not tie to the beam");
    const double hung = heightOf(*world, "weight");
    run(*world, 480);
    const double after = heightOf(*world, "weight");
    const LiveJoint tied = jointNumber(world->joints(), rope);
    std::cout << "  a 618 N weight on a rope rated for 154 N: it fell from y="
              << hung << " to y=" << after << ", and the rope reports attached="
              << tied.attached << "\n";
    require(after < hung - 1.0, "the rope held four times what it was rated for");
    require(!tied.attached, "the rope parted but still says it is holding");
}

void cuttingALinkDropsWhatIsUnderIt() {
    const auto world = LiveWorld::open(gantry(1000.0));
    const unsigned rope = world->tie("beam", "weight", Vec3{0.0, 3.9, 0.0},
                                     Vec3{0.0, 3.0, 0.0});
    require(rope != 0, "the weight would not tie to the beam");
    run(*world, 240);
    const double hung = heightOf(*world, "weight");
    world->unhinge(rope);            // cut it
    run(*world, 480);
    const double fell = heightOf(*world, "weight");
    std::cout << "  cut: the weight went from y=" << hung << " to y=" << fell << "\n";
    require(fell < hung - 1.0, "cutting the rope did not drop the weight");
    require(world->joints().empty(), "the cut rope is still listed");
}

void aRopeIsMeasuredBetweenItsTiePoints() {
    // `at` is the rope's length as it is now, and every host reads it as that:
    // the C API's `at`, the MCP `joints` tool's `apart_m`, the line protocol's
    // "metres". It used to be measured between the two bodies' CENTRES, and on
    // this scene, hauled tight with the rope exactly its own length, it read
    // 1.272 m -- how far apart the middle of the post and the middle of the
    // block are, when the rope is tied at the post's foot and the block's back.
    const auto world = LiveWorld::open(postAndBlock());
    const Vec3 on_post{0.08, 0.12, 0.0}, on_block{0.76, 0.12, 0.0};
    const unsigned rope = world->tie("post", "block", on_post, on_block, 1.0);
    require(rope != 0, "the block would not tie to the post");
    // Each end in its own body's frame. The bodies are built unturned, so that
    // is where it is tied less where the body's centre is.
    const Vec3 post_end = on_post - Vec3{0.0, 0.6, 0.0};
    const Vec3 block_end = on_block - Vec3{0.84, 0.08, 0.0};

    struct Seen {
        double at, apart, tension_n, turned_deg;
    };
    const auto look = [&]() {
        const auto poses = world->poses();
        const LiveJoint tied = jointNumber(world->joints(), rope);
        const LiveBodyPose &block = named(poses, "block");
        return Seen{tied.at,
                    length(carried(block, block_end) - carried(named(poses, "post"), post_end)),
                    tied.tension_n, turnedDegrees(block)};
    };

    // Slack, as it was laid out: 0.68 m of a 1 m rope.
    run(*world, 120);
    const Seen laid_out = look();

    // Taut: hauled away and round to one side, so the block swings round the
    // post on its rope and turns to keep its back to it. A tie point on a body
    // that turns does not move the way the body's centre does, so this is what
    // tells "carried by the body's pose" from "offset from the body's centre".
    require(world->grab("block"), "could not take hold of the block");
    world->moveHeld(Vec3{1.84, 0.08, 1.0});
    run(*world, 720);
    const Seen taut = look();

    // Slack again: walked 0.4 m back towards the post, still turned.
    const Vec3 here = named(world->poses(), "block").position_m;
    Vec3 towards{on_post.x - here.x, 0.0, on_post.z - here.z};
    towards = (0.4 / length(towards)) * towards;
    world->moveHeld(here + towards);
    run(*world, 480);
    const Seen pushed_back = look();
    world->release();

    std::cout << "  laid out: reports " << laid_out.at << " m, tied " << laid_out.apart
              << " m apart\n  hauled:   reports " << taut.at << " m, tied " << taut.apart
              << " m apart, carrying " << taut.tension_n << " N, the block turned "
              << taut.turned_deg << " degrees\n  pushed back: reports " << pushed_back.at
              << " m, tied " << pushed_back.apart << " m apart, carrying "
              << pushed_back.tension_n << " N\n";

    require(laid_out.tension_n < 1.0 && laid_out.apart < 0.9,
            "the rope was not slack as it was laid out");
    require(std::abs(laid_out.at - laid_out.apart) < 1e-3,
            "a slack rope reports something other than how far apart its ends are");
    require(taut.tension_n > 100.0, "hauled away, the rope carried nothing: it never went taut");
    require(taut.turned_deg > 10.0,
            "the block never turned, so this did not test that a tie point turns with its body");
    require(std::abs(taut.at - taut.apart) < 1e-3,
            "a taut rope reports something other than how far apart its ends are");
    require(std::abs(taut.at - 1.0) < 1e-3, "hauled tight, a 1 m rope does not read 1 m");
    require(pushed_back.tension_n < 1.0 && pushed_back.apart < 0.9,
            "pushed back towards the post, the rope did not go slack");
    require(pushed_back.turned_deg > 10.0,
            "the block turned back square, so the slack reading did not test a turned tie point");
    require(std::abs(pushed_back.at - pushed_back.apart) < 1e-3,
            "a slack rope on a turned body reports something other than how far apart its "
            "ends are");
}

void tensionIsAForce() {
    // What a rope reports is the impulse Jolt's solver put through it over the
    // last step, divided by that step. That can be wrong in two ways that both
    // look like "about right" on one scene: divided by the wrong step, and then
    // the same weight reads differently at 60, 120 and 240 Hz, four times
    // differently between the ends; or counting something that is not the
    // rope's pull -- Jolt's position correction, say, which is solved
    // separately and never enters that impulse. So the same weight is hung at
    // three step sizes, and then held down by the hand, which pulls with a
    // known force: the rope has to carry the weight and exactly that.
    //
    // The hand here is moved once and then held. A host that moves it before
    // every step is applying a different load, not reading a different
    // tension -- see `tension_n` in docs/api/c-api.md.
    constexpr double kWeightN = 0.2 * 0.2 * 0.2 * 7870.0 * 9.81;
    for (const double dt : {1.0 / 240.0, 1.0 / 120.0, 1.0 / 60.0}) {
        const auto world = LiveWorld::open(gantry(1000.0));
        // Tied at the middle of the weight, so the rope's line runs through its
        // centre and nothing turns.
        const unsigned rope = world->tie("beam", "weight", Vec3{0.0, 3.9, 0.0},
                                         Vec3{0.0, 3.0, 0.0});
        require(rope != 0, "the weight would not tie to the beam");
        const int second = static_cast<int>(std::lround(1.0 / dt));
        for (int i = 0; i < 2 * second; ++i) tick(*world, dt);
        const double hanging = jointNumber(world->joints(), rope).tension_n;

        require(world->grab("weight"), "could not take hold of the weight");
        // A metre below it: far enough that the hand pulls with all it has.
        world->moveHeld(Vec3{0.0, 2.0, 0.0});
        for (int i = 0; i < second; ++i) tick(*world, dt);
        const double held_down = jointNumber(world->joints(), rope).tension_n;
        const double pulled = kWeightN + world->handStrength();
        world->release();

        std::cout << "  at " << std::lround(1.0 / dt) << " Hz: hanging it reads " << hanging
                  << " N (weight " << kWeightN << " N); held down by a "
                  << world->handStrength() << " N hand, " << held_down << " N (weight + hand "
                  << pulled << " N)\n";
        require(std::abs(hanging - kWeightN) < 0.01 * kWeightN,
                "a rope holding a weight still does not report the weight, so its tension is "
                "not a force at this step size");
        require(std::abs(held_down - pulled) < 0.01 * pulled,
                "held down by the hand, the rope does not report the weight plus the hand");
    }
}

void aRopeRefusesWhatItCannotTie() {
    const auto world = LiveWorld::open(gantry(1000.0));
    require(world->tie("beam", "nothing at all", Vec3{}, Vec3{}) == 0,
            "tied to a body that does not exist");
    require(world->tie("weight", "weight", Vec3{}, Vec3{}) == 0,
            "tied a body to itself");
    require(world->joints().empty(), "a refused tie was recorded anyway");
    std::cout << "  a tie refuses a missing body and a body tied to itself\n";
}

} // namespace

int main() {
    try {
        aLinkPulls();
        std::cout << "[PASS] a link pulls\n";
        aLinkDoesNotPush();
        std::cout << "[PASS] a link does not push\n";
        slackIsSlack();
        std::cout << "[PASS] slack is slack\n";
        aRopeHangsInACurve();
        std::cout << "[PASS] a rope of many links hangs in a curve\n";
        tensionIsReportedAndIsAboutRight();
        std::cout << "[PASS] tension is reported and is about right\n";
        aRopePartsWhenItIsOverloaded();
        std::cout << "[PASS] a rope parts when it is overloaded\n";
        cuttingALinkDropsWhatIsUnderIt();
        std::cout << "[PASS] cutting a link drops what is under it\n";
        aRopeRefusesWhatItCannotTie();
        std::cout << "[PASS] a tie refuses what it cannot hold\n";
        aRopeIsMeasuredBetweenItsTiePoints();
        std::cout << "[PASS] a rope is measured between its tie points\n";
        tensionIsAForce();
        std::cout << "[PASS] tension is a force\n";
        std::cout << "\nall rope tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
