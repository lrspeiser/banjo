// The hand's own motions. docs/interaction-profiles.md.
//
// A throw is over in a tenth of a second and a draw is decided by how hard a
// hand can pull, so neither can be done a frame at a time from outside: the
// engine makes the stroke itself, at the step's rate, with the bounded hand
// every other hold has. What is pinned here:
//
// 1. A stroke needs a hand that pulls. A carried body is placed, not pushed,
//    and is refused, with the reason.
// 2. The same full-effort throw sends a light ball off faster than a heavy
//    one, and nothing gave either a speed: the heaviest leaves no faster than
//    the hand's strength could have made it over the length of the stroke.
// 3. The hand stays on what it holds: its target is never further ahead of
//    the grip than the lead.
// 4. The work the hand did is what the ball got -- its kinetic energy and the
//    height it was lifted.
// 5. A preview of the throw agrees with the throw, and a preview of the flight
//    comes down where the ball does.
// 6. Hauling against a spring, the hand gets as far as its strength takes it
//    and is blocked there; a stiffer spring stops it sooner. That is a draw.
// 7. Moving the hand takes it back from a stroke, and the thing stays held.
// 8. A preview changes nothing.

#include "fastlattice/LiveWorld.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

constexpr double kDt = 1.0 / 240.0;
constexpr double kGravity = 9.80665;
constexpr double kStrength = 800.0;   // the hand's, unless told otherwise
constexpr double kLead = 0.05;

const LiveBodyPose &named(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

// One ball, a metre and a half up, with nothing near it.
TileImpactRequest aBall(MaterialPreset material, double diameter_m, Vec3 at) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = BackendKind::CpuParallel;
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = material;
    ball.dimensions_m = {diameter_m, diameter_m, diameter_m};
    ball.center_m = at;
    r.bodies = {ball};
    return r;
}

const Vec3 kFrom{-0.8, 1.5, 0.0};
const Vec3 kTo{0.0, 1.5, 0.0};

// A full-effort throw along x over 0.8 m: as fast as a hand goes, as quickly as
// it can get there. What the ball does with it is up to the ball.
LiveStroke fullThrow() {
    LiveStroke s;
    s.path_m = {kFrom, kTo};
    s.speed_m_s = 20.0;
    s.accel_m_s2 = 2000.0;
    s.lead_m = kLead;
    s.let_go_at_end = true;
    s.give_up_s = 2.0;
    return s;
}

struct Throw {
    std::string label;
    double mass_kg{};
    std::string ended;
    Vec3 velocity{};
    double work_j{};
    double rose_m{};
    double most_lead_m{};
    double previewed_speed{};
    double range_m{};
    double landed_x{};             // where its centre line met the ground, flying free
    double predicted_x{};          // previewFlight from where it was let go
    double stroke_predicted_x{};   // previewStroke, before the throw was made
};

Throw throwOne(const std::string &label, MaterialPreset material, double diameter_m) {
    const auto live = LiveWorld::open(aBall(material, diameter_m, kFrom));
    require(live->wield("ball", kFrom), label + ": could not take hold of the ball");
    Throw out;
    out.label = label;
    out.mass_kg = named(live->poses(), "ball").mass_kg;
    require(out.mass_kg > 0.0, label + ": the ball reports no mass");

    const LiveStrokePreview seen = live->previewStroke(fullThrow(), kDt, 4.0);
    require(seen.possible && seen.reaches_end,
            label + ": the preview said the throw could not be made: " + seen.why);
    out.previewed_speed = length(seen.let_go_velocity_m_s);
    out.stroke_predicted_x = seen.flight.hit_point_m.x;

    std::string why;
    require(live->stroke(fullThrow(), why), label + ": a wielded ball refused a stroke: " + why);
    const double start_y = named(live->poses(), "ball").position_m.y;
    for (int i = 0; i < 480 && live->held() == "ball"; ++i) {
        live->step(kDt);
        const LiveHand hand = live->hand();
        if (hand.stroking)
            out.most_lead_m = std::max(out.most_lead_m, hand.target_m.x - hand.grip_m.x);
    }
    const LiveHand after = live->hand();
    out.ended = after.stroke_ended;
    out.velocity = after.let_go_velocity_m_s;
    out.work_j = after.let_go_work_j;
    if (out.ended != "let go") return out;

    // The loop stopped on the step that let it go, so this is that moment.
    const LiveBodyPose released = named(live->poses(), "ball");
    out.rose_m = released.position_m.y - start_y;
    const LiveFlight predicted =
        live->previewFlight(released.position_m, after.let_go_velocity_m_s, 4.0, "ball");
    require(predicted.hit, label + ": the flight preview never came down");

    // Fly it for real, and carry its last free state on to the ground the
    // preview stopped at, ballistically -- the preview follows the centre line.
    Vec3 p = released.position_m, v = released.velocity_m_s;
    const double r = 0.5 * diameter_m;
    for (int i = 0; i < 1200; ++i) {
        live->step(kDt);
        const LiveBodyPose now = named(live->poses(), "ball");
        if (now.position_m.y <= predicted.hit_point_m.y + r + 0.003 ||
            now.velocity_m_s.y > v.y + 1.0)
            break;
        p = now.position_m;
        v = now.velocity_m_s;
    }
    const double drop = p.y - predicted.hit_point_m.y;
    const double fall_s = (v.y + std::sqrt(v.y * v.y + 2.0 * kGravity * drop)) / kGravity;
    out.landed_x = p.x + v.x * fall_s;
    out.predicted_x = predicted.hit_point_m.x;
    out.range_m = out.landed_x - released.position_m.x;
    return out;
}

void aStrokeNeedsAHandThatPulls() {
    const auto live = LiveWorld::open(aBall(MaterialPreset::Rubber, 0.07, kFrom));
    require(live->grab("ball"), "could not pick the ball up");
    std::string why;
    require(!live->stroke(fullThrow(), why),
            "a carried ball accepted a stroke: a carry is placement and nothing pushes it");
    require(why.find("carried") != std::string::npos, "the refusal did not say why: " + why);
    std::cout << "  carried: refused -- " << why << "\n";
    const LiveStrokePreview seen = live->previewStroke(fullThrow(), kDt, 3.0);
    require(!seen.possible && !seen.why.empty(), "a carried ball's throw was previewed as possible");
    live->release();
    require(live->wield("ball", kFrom), "could not take hold of the ball");
    require(live->stroke(fullThrow(), why), "a wielded ball refused a stroke: " + why);
    LiveStroke nonsense = fullThrow();
    nonsense.path_m = {kFrom};
    require(!live->stroke(nonsense, why) && !why.empty(), "a one-point path was accepted");
    std::cout << "  wielded: accepted; a one-point path: refused -- " << why << "\n";
}

void lightAndHeavyBalls() {
    const std::vector<Throw> throws = {throwOne("rubber 70 mm", MaterialPreset::Rubber, 0.07),
                                       throwOne("iron 100 mm", MaterialPreset::Iron, 0.1),
                                       throwOne("iron 200 mm", MaterialPreset::Iron, 0.2)};
    // All three said before any is judged, so a failure shows the others too.
    for (const Throw &t : throws) {
        const double speed = length(t.velocity);
        const double gained = 0.5 * t.mass_kg * speed * speed + t.mass_kg * kGravity * t.rose_m;
        std::cout << "  " << t.label << ": " << t.mass_kg << " kg, " << t.ended << " at " << speed
                  << " m/s (preview " << t.previewed_speed << "); hand work " << t.work_j
                  << " J for " << gained << " J gained (lifted " << t.rose_m * 1000.0
                  << " mm); hand at most " << t.most_lead_m * 1000.0 << " mm ahead; landed at x="
                  << t.landed_x << " m, preview from release " << t.predicted_x
                  << ", preview before the throw " << t.stroke_predicted_x << "\n";
    }
    for (const Throw &t : throws) {
        const double speed = length(t.velocity);
        const double gained = 0.5 * t.mass_kg * speed * speed + t.mass_kg * kGravity * t.rose_m;
        require(t.ended == "let go", t.label + ": the throw ended \"" + t.ended + "\", not let go");
        require(t.most_lead_m <= kLead + 1e-9,
                t.label + ": the hand got further ahead of the ball than its lead");
        require(std::abs(t.work_j - gained) <= 0.02 * std::abs(gained) + 0.02,
                t.label + ": the hand's work is not what the ball gained");
        require(std::abs(t.previewed_speed - speed) <= 0.03 * speed + 0.05,
                t.label + ": the preview of the throw disagrees with the throw");
        require(std::abs(t.landed_x - t.predicted_x) <= 0.01 + 0.005 * std::abs(t.range_m),
                t.label + ": the flight preview did not come down where the ball did");
        require(std::abs(t.landed_x - t.stroke_predicted_x) <= 0.02 + 0.04 * std::abs(t.range_m),
                t.label + ": the throw's preview did not come down where the ball did");
    }
    const double light = length(throws[0].velocity), middle = length(throws[1].velocity),
                 heavy = length(throws[2].velocity);
    require(light > 1.1 * middle && middle > 1.1 * heavy,
            "the same throw did not send heavier balls off slower");
    // The heaviest is limited by the hand, not by what was asked: over 0.8 m
    // with what is left of 800 N after holding it up, it cannot have got faster
    // than this.
    const Throw &shot = throws[2];
    const double bound = std::sqrt(2.0 * (kStrength - shot.mass_kg * kGravity) * 0.8 / shot.mass_kg);
    require(heavy <= 1.02 * bound, "the heavy ball left faster than the hand's strength allows");
    std::cout << "  the heaviest could have reached at most " << bound << " m/s\n";
}

// An anchored post and a block on a spring from it, the block held by the hand:
// a haul, which is the draw of a bow without the bow.
struct Draw {
    double drawn_m{};
    double work_j{};
    std::string ended;
};

Draw drawAgainst(double stiffness_n_m) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Oak;
    post.dimensions_m = {0.1, 0.1, 0.1};
    post.center_m = {0.0, 1.0, 0.0};
    post.anchored = true;
    SceneBody block = post;
    block.name = "block";
    block.center_m = {0.4, 1.0, 0.0};
    block.anchored = false;
    r.bodies = {post, block};
    const auto live = LiveWorld::open(r);
    require(live->spring("post", "block", {0.05, 1.0, 0.0}, {0.35, 1.0, 0.0}, 0.0,
                         stiffness_n_m, 20.0) != 0,
            "the spring would not go on");
    require(live->grab("block"), "could not take hold of the block");
    LiveStroke draw;
    draw.path_m = {{0.4, 1.0, 0.0}, {1.0, 1.0, 0.0}};
    draw.speed_m_s = 0.5;
    draw.accel_m_s2 = 5.0;
    draw.lead_m = kLead;
    draw.let_go_at_end = false;
    draw.give_up_s = 4.0;
    std::string why;
    require(live->stroke(draw, why), "a hauled block refused a stroke: " + why);
    for (int i = 0; i < 1200 && live->hand().stroking; ++i) live->step(kDt);
    const LiveHand hand = live->hand();
    Draw out;
    out.ended = hand.stroke_ended;
    out.work_j = hand.work_j;
    out.drawn_m = named(live->poses(), "block").position_m.x - 0.4;
    require(live->held() == "block", "the draw let go of the block");
    return out;
}

void drawingAgainstASpring() {
    const Draw soft = drawAgainst(4000.0);
    const Draw stiff = drawAgainst(8000.0);
    for (const auto &[k, d] : {std::pair<double, const Draw *>{4000.0, &soft},
                               std::pair<double, const Draw *>{8000.0, &stiff}}) {
        const double expected = kStrength / k;
        const double stored = 0.5 * k * d->drawn_m * d->drawn_m;
        std::cout << "  " << k << " N/m: " << d->ended << " at " << d->drawn_m * 1000.0
                  << " mm (the hand's 800 N balances it at " << expected * 1000.0
                  << " mm); hand work " << d->work_j << " J, " << stored << " J in the spring\n";
        require(d->ended == "blocked", "the draw ended \"" + d->ended + "\", not blocked");
        require(std::abs(d->drawn_m - expected) <= 0.1 * expected + 0.005,
                "the draw did not stop where the hand's strength balances the spring");
        require(d->work_j >= 0.95 * stored && d->work_j <= 1.25 * stored + 0.5,
                "the hand's work is not what went into the spring and its damper");
    }
    require(stiff.drawn_m < 0.6 * soft.drawn_m, "a stiffer spring did not stop the draw sooner");
}

void movingTheHandTakesItBack() {
    const auto live = LiveWorld::open(aBall(MaterialPreset::Rubber, 0.07, kFrom));
    require(live->wield("ball", kFrom), "could not take hold of the ball");
    std::string why;
    require(live->stroke(fullThrow(), why), "a wielded ball refused a stroke: " + why);
    live->step(kDt);
    require(live->hand().stroking, "the stroke did not start");
    live->moveHeld({-0.8, 1.6, 0.0});
    const LiveHand hand = live->hand();
    require(!hand.stroking && hand.stroke_ended == "cancelled",
            "moving the hand did not take it back from the stroke");
    require(live->held() == "ball", "taking the hand back let go of the ball");
    std::cout << "  moved mid-stroke: " << hand.stroke_ended << ", still holding "
              << live->held() << "\n";
}

void aPreviewChangesNothing() {
    const auto live = LiveWorld::open(aBall(MaterialPreset::Iron, 0.1, kFrom));
    require(live->wield("ball", kFrom), "could not take hold of the ball");
    for (int i = 0; i < 24; ++i) live->step(kDt);
    const LiveBodyPose before = named(live->poses(), "ball");
    const double time_before = live->time_s();
    const LiveHand hand_before = live->hand();
    const LiveStrokePreview seen = live->previewStroke(fullThrow(), kDt, 3.0);
    const Vec3 up_and_out{5.0, 5.0, 0.0};
    const LiveFlight flight = live->previewFlight(before.position_m, up_and_out, 3.0, "ball");
    const LiveBodyPose after = named(live->poses(), "ball");
    const LiveHand hand_after = live->hand();
    require(seen.possible && seen.reaches_end, "the preview of a throw was refused: " + seen.why);
    // Where it comes down is checked against a real flight, in the throws
    // above; exact ballistics are not how this world moves things.
    require(flight.hit && flight.hit_name.empty() && flight.hit_after_s > 1.0,
            "a ball thrown up and out never came down");
    const double t = flight.hit_after_s;
    require(before.position_m.x == after.position_m.x && before.position_m.y == after.position_m.y &&
                before.position_m.z == after.position_m.z &&
                before.velocity_m_s.x == after.velocity_m_s.x &&
                before.velocity_m_s.y == after.velocity_m_s.y,
            "a preview moved the ball");
    require(live->time_s() == time_before, "a preview moved the clock");
    require(hand_after.work_j == hand_before.work_j && !hand_after.stroking,
            "a preview changed the hand");
    std::cout << "  previews: nothing moved; the flight came down at x=" << flight.hit_point_m.x
              << " after " << t << " s\n";
}

} // namespace

int main() {
    // Every check runs and every failure is said: one that stops at the first
    // hides the rest.
    const std::vector<std::pair<const char *, std::function<void()>>> tests = {
        {"a stroke needs a hand that pulls", aStrokeNeedsAHandThatPulls},
        {"the same throw, light and heavy balls", lightAndHeavyBalls},
        {"a draw against a spring", drawingAgainstASpring},
        {"moving the hand takes it back", movingTheHandTakesItBack},
        {"a preview changes nothing", aPreviewChangesNothing},
    };
    int failed = 0;
    for (const auto &[name, test] : tests) {
        std::cout << name << "\n";
        try {
            test();
        } catch (const std::exception &error) {
            std::cout << "  FAILED: " << error.what() << "\n";
            ++failed;
        }
    }
    if (failed) {
        std::cout << failed << " of " << tests.size() << " hand stroke tests failed\n";
        return 1;
    }
    std::cout << "all " << tests.size() << " hand stroke tests passed\n";
    return 0;
}
