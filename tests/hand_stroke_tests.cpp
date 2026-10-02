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
// 9. A thing on a joint hangs on it. A gate heavier than the hand could lift
//    is still pushed round its upright pins; the same oak in upright grooves
//    is lifted by the hand's strength or not at all.

#include "fastlattice/LiveWorld.hpp"
#include "physics/GripPull.hpp"
#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <map>
#include <limits>
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

void sharedGripAnalyticalOracles() {
    RigidMechanicalState body;body.mass_kg=2;
    for (int i=0;i<3;++i) body.inertia_world_kg_m2.m[i][i]=1;
    const auto mass=gripEffectiveMass(2,body.inertia_world_kg_m2,{.5,0,0});
    require(std::abs(mass.m[0][0]-2)<1e-14&&std::abs(mass.m[1][1]-4.0/3)<1e-14&&std::abs(mass.m[2][2]-4.0/3)<1e-14,
        "point effective mass does not match translation plus rotational response");
    const auto pull=gripPull(body,{},{.01,0,0},{},{},800,60,{});
    require(std::abs(pull.force.x-160)<1e-12&&length(pull.torque)==0,"centre grip spring force oracle");
    const auto full=gripPull(body,{},{2,0,0},{},{},800,60,{});
    require(std::abs(full.force.x-800)<1e-12,"hand force cap");
    const Quat facing{std::cos(.05),0,0,std::sin(.05)};
    const auto wrist=gripPull(body,{},{},{},facing,800,60,{});
    require(std::abs(wrist.torque.z-60)<1e-12,"wrist torque cap");
    const auto opposite=gripTurnBetween({},Quat{-facing.w,0,0,-facing.z});
    require(length(opposite-Vec3{0,0,.1})<1e-14,"short rotation must not depend on quaternion sign");
    const double a=std::sqrt(.5);body.motion.orientation_world={a,0,0,a};
    const auto rotated=gripPull(body,{},{0,.01,0},{},body.motion.orientation_world,800,60,{});
    require(length(rotated.force-Vec3{0,160,0})<1e-12,"rotated centre grip force oracle");
    body.mass_kg=100;const auto heavy=gripPull(body,{},{},{},body.motion.orientation_world,800,60,{0,-9.81,0});
    require(length(heavy.force-Vec3{0,800,0})<1e-12,"unliftable body exceeded the same finite hand");

    body.mass_kg=2;body.motion={};body.motion.center_of_mass_world_m={-.5,0,0};
    body.motion.linear_velocity_m_s={1,2,3};body.motion.angular_velocity_rad_s={0,0,4};
    auto other=body;other.motion.center_of_mass_world_m={.5,0,0};other.motion.linear_velocity_m_s={100,100,100};
    const auto feedback=makeGripFeedback(body,{body,other},{-.25,0,0});
    require(feedback.held.mass_kg==4&&length(feedback.held.motion.center_of_mass_world_m)<1e-14&&
        std::abs(feedback.held.inertia_world_kg_m2.m[0][0]-2)<1e-14&&std::abs(feedback.held.inertia_world_kg_m2.m[1][1]-3)<1e-14,
        "aggregate grip mass and parallel-axis inertia oracle");
    const Vec3 grip_velocity=feedback.held.motion.linear_velocity_m_s+
        cross(feedback.held.motion.angular_velocity_rad_s,feedback.held.motion.orientation_world.rotate(feedback.grip_local));
    require(length(grip_velocity-Vec3{1,1,3})<1e-14&&length(feedback.held.motion.angular_velocity_rad_s-Vec3{0,0,4})==0,
        "aggregate feedback hid the actual root's grip motion");
}

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

// A box thrown along a plank it is lying on slides along it. That is not a
// promise anyone would think to make, and it was not being kept: Jolt sweeps a
// fast body so that it cannot pass through things (EMotionQuality::LinearCast),
// and it swept a square-edged box as itself, starting the sweep already
// touching the plank under it. The sweep reported a hit along the way the box
// was going, and the solver stopped it dead and threw it back -- from 7 m/s to
// -4.6 in one step, measured; and the courtyard's arrow, sliding over its rest
// as it was shot, the same way on 13 of 19 draws. Every moving box and hull now
// has round edges -- 2 mm, or a tenth of its thinnest half if that is less --
// inside its authored size (JoltWorld's kSweepRadiusM).
void aBoxThrownAlongAPlankSlidesAlongIt() {
    TileImpactRequest r;
    r.cell_size_m = 0.04;
    r.backend = BackendKind::CpuParallel;
    SceneBody plank;
    plank.name = "plank";
    plank.shape = BodyShape::Box;
    plank.material = MaterialPreset::Oak;
    plank.dimensions_m = {1.6, 0.04, 0.12};
    plank.center_m = {0.0, 1.10, 0.0};
    plank.anchored = true;
    SceneBody box = plank;
    box.name = "box";
    box.dimensions_m = {0.6, 0.04, 0.04};
    box.center_m = {-0.4, 1.14, 0.0};
    box.anchored = false;
    r.bodies = {plank, box};
    const auto live = LiveWorld::open(r);
    for (int i = 0; i < 120; ++i) live->step(kDt);   // lying on it, as it would be

    const Vec3 at = named(live->poses(), "box").position_m;
    require(live->wield("box", at), "could not take hold of the box");
    LiveStroke shove;
    shove.path_m = {at, Vec3{at.x + 0.3, at.y, at.z}};
    shove.speed_m_s = 7.0;
    shove.accel_m_s2 = 5000.0;
    shove.lead_m = kLead;
    shove.let_go_at_end = true;
    std::string why;
    require(live->stroke(shove, why), "the box refused a shove: " + why);
    for (int i = 0; i < 240 && live->held() == "box"; ++i) live->step(kDt);
    require(live->held().empty(), "the hand never let the box go");

    // Along the plank, until it reaches the end: friction takes 0.02 m/s a step
    // off it at most. A step that takes a metre a second is not friction.
    double was = named(live->poses(), "box").velocity_m_s.x, fastest = was, worst = 0.0;
    for (int i = 0; i < 240; ++i) {
        live->step(kDt);
        const LiveBodyPose now = named(live->poses(), "box");
        if (now.position_m.x > 0.45) break;
        worst = std::max(worst, was - now.velocity_m_s.x);
        require(now.velocity_m_s.x > 0.0,
                "the box, sliding along the plank at " + std::to_string(was) +
                    " m/s, turned round and went back the way it came");
        was = now.velocity_m_s.x;
    }
    std::cout << "  let go at " << fastest << " m/s along the plank; the most one step took off "
              << worst << " m/s\n";
    require(fastest > 4.0, "the shove never got the box moving fast enough for the sweep");
    require(worst < 1.0, "a step took " + std::to_string(worst) +
                             " m/s off a box sliding along a plank: that is not friction");
}

// A thing on a joint hangs on it: the joint holds its weight up, and the hand
// has only to move it the way the joint lets it go. The stroke once counted the
// whole weight against the hand, so the playground's 110 kg oak gate -- more
// than 800 N of it -- left the hand nothing to move it with: a turn of it never
// began, and the stroke gave up with the gate where it was. Round upright pins
// none of the weight lies along the way it goes; up upright grooves all of it
// does, and there the hand lifts what its strength holds up, or nothing.
constexpr double kPi = 3.14159265358979323846;

struct Hauled {
    double mass_kg{};
    double went{};          // degrees round the pin, or metres up the grooves
    std::string ended;
};

Hauled haulTheGate(bool on_pins) {
    TileImpactRequest r;
    r.cell_size_m = 0.04;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Oak;
    post.dimensions_m = {0.16, 2.0, 0.16};
    post.center_m = {0.0, 1.0, 0.0};
    post.anchored = true;
    SceneBody gate = post;
    gate.name = "gate";
    gate.dimensions_m = {1.2, 1.6, 0.08};
    gate.center_m = {0.7, 1.0, 0.0};
    gate.anchored = false;
    r.bodies = {post, gate};
    const auto live = LiveWorld::open(r);
    const Vec3 pin{0.1, 1.0, 0.0}, up{0.0, 1.0, 0.0};
    require(on_pins ? live->hinge("post", "gate", pin, up, 0.0, 100.0, 10.0) != 0
                    : live->slide("post", "gate", pin, up, 0.0, 1.0, 0.0) != 0,
            "the gate's joint would not go on");
    Hauled out;
    out.mass_kg = named(live->poses(), "gate").mass_kg;
    require(live->grab("gate"), "could not take hold of the gate");
    const Vec3 from = named(live->poses(), "gate").position_m;
    LiveStroke s;
    if (on_pins) {
        // Thirty degrees round the pin, right-handed about it, the way a pin's
        // degrees count.
        const double x = from.x - pin.x, z = from.z - pin.z;
        for (int k = 0; k <= 3; ++k) {
            const double a = 10.0 * k * kPi / 180.0;
            s.path_m.push_back({pin.x + x * std::cos(a) + z * std::sin(a), from.y,
                                pin.z - x * std::sin(a) + z * std::cos(a)});
        }
    } else {
        s.path_m = {from, Vec3{from.x, from.y + 0.3, from.z}};
    }
    s.speed_m_s = 0.4;
    s.accel_m_s2 = 2.0;
    s.lead_m = kLead;
    s.let_go_at_end = false;
    s.give_up_s = 3.0;
    std::string why;
    require(live->stroke(s, why), "the hauled gate refused a stroke: " + why);
    for (int i = 0; i < 1200 && live->hand().stroking; ++i) live->step(kDt);
    out.ended = live->hand().stroke_ended;
    for (const LiveJoint &j : live->joints())
        if (j.kind == (on_pins ? "hinge" : "slider")) out.went = on_pins ? j.at * 180.0 / kPi : j.at;
    require(live->held() == "gate", "the stroke let go of the gate");
    return out;
}

void aGateTooHeavyToLiftStillSwings() {
    const Hauled round = haulTheGate(true);
    const Hauled up = haulTheGate(false);
    std::cout << "  " << round.mass_kg << " kg of oak: round its pins " << round.ended << " at "
              << round.went << " of 30 degrees; up its grooves " << up.ended << " at "
              << up.went * 1000.0 << " of 300 mm\n";
    require(round.mass_kg * kGravity > kStrength, "the gate is light enough to lift: it tests nothing");
    require(round.ended == "reached" && round.went > 25.0,
            "a gate on upright pins, pushed round with none of its weight, was not taken round");
    require(up.ended == "gave up" && up.went < 0.01,
            "the hand took more oak up its grooves than its strength can hold up");
}

void refusedStepsRestoreEveryPlayersHand() {
    const auto sameHand=[](const LiveHand &a,const LiveHand &b) {
        require(a.holding==b.holding&&a.mode==b.mode&&length(a.target_m-b.target_m)==0&&
            length(a.grip_m-b.grip_m)==0&&length(a.grip_velocity_m_s-b.grip_velocity_m_s)==0&&
            length(a.force_n-b.force_n)==0&&a.work_j==b.work_j&&a.stroking==b.stroking&&
            a.stroke_along_m==b.stroke_along_m&&a.stroke_length_m==b.stroke_length_m&&a.stroke_ended==b.stroke_ended&&
            a.let_go_body==b.let_go_body&&length(a.let_go_velocity_m_s-b.let_go_velocity_m_s)==0&&
            a.let_go_at_s==b.let_go_at_s&&a.let_go_work_j==b.let_go_work_j,"refused/retried step changed a player's hand state");
    };
    for (const std::string mode:{"grip","haul","fixed"}) for (auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        auto request=aBall(material,.1,{-1,1.5,1});request.gravity_m_s2={};request.bodies[0].name="left tool";
        auto right=request.bodies[0];right.name="right tool";right.center_m={1,1.5,1};request.bodies.push_back(right);
        SceneBody pane;pane.name="pane";pane.shape=BodyShape::Box;pane.material=MaterialPreset::Glass;
        pane.dimensions_m={.3,.04,.3};pane.center_m={0,.1,0};request.bodies.push_back(pane);
        SceneBody striker;striker.name="striker";striker.shape=BodyShape::Sphere;striker.material=MaterialPreset::Iron;
        striker.dimensions_m={.1,.1,.1};striker.center_m={0,.24,0};striker.velocity_m_s={0,-8,0};request.bodies.push_back(striker);
        if (mode!="grip") for (const std::string actor:{"left","right"}) {
            SceneBody support;support.name=actor+(mode=="haul"?" anchor":" handle");support.shape=BodyShape::Box;
            support.material=mode=="haul"?MaterialPreset::Iron:MaterialPreset::Oak;
            support.anchored=mode=="haul";support.dimensions_m=mode=="haul"?Vec3{.04,.04,.04}:Vec3{.24,.04,.04};
            support.center_m={actor=="left"?-1.16:1.16,1.5,mode=="haul"?.8:1.0};request.bodies.push_back(support);
        }
        auto live=LiveWorld::open(request),control=LiveWorld::open(request);
        for (auto *world:{live.get(),control.get()}) {
            world->foreseeCollisions(0);
            for (auto actor:{std::string("left"),std::string("right")}) {
                world->selectHand(actor);const bool left=actor=="left";
                const Vec3 start{left?-1.0:1.0,1.5,1};
                if (mode=="haul") require(world->hinge(actor+" anchor",actor+" tool",start+Vec3{0,0,-.1},{0,1,0},-180,180,0)!=0,
                    "two-player hinge creation failed");
                if (mode=="fixed") require(world->fix(actor+" handle",actor+" tool",start+Vec3{left?-.05:.05,0,0},{1,0,0},0,0)!=0,
                    "two-player ideal fixed-group creation failed");
                require(mode=="haul"?world->grab(actor+" tool"):world->wield(actor+" tool",start),"two-player fixture could not hold tool");
                LiveStroke stroke;stroke.path_m={start,start+Vec3{left?.8:-.8,0,0}};
                stroke.speed_m_s=4;stroke.accel_m_s2=40;stroke.lead_m=.05;
                stroke.facings_wxyz={{},{std::cos(.2),0,0,std::sin(.2)}};
                std::string why;require(world->stroke(stroke,why),"two-player fixture could not begin stroke: "+why);
            }
        }
        bool refused=false;
        for (unsigned step=0;step<24&&!refused;++step) {
            std::map<std::string,LiveHand> before;
            for (auto actor:{std::string("left"),std::string("right")}) {live->selectHand(actor);before[actor]=live->hand();}
            const double time=live->time_s();live->step(kDt);
            refused=live->steppedBack();
            if (refused) {
                require(live->time_s()==time,"refused player step advanced world time");
                for (auto actor:{std::string("left"),std::string("right")}) {live->selectHand(actor);sameHand(before.at(actor),live->hand());}
                const auto waiting=live->breakable();require(!waiting.empty(),"refused fixture has no real material admission");
                for (const auto &name:waiting) {live->declineBreak(name);control->declineBreak(name);}
                live->step(kDt);require(!live->steppedBack(),"declined material offer did not admit retry");
            }
            control->step(kDt);require(!control->steppedBack(),"never-rejected control refused the selected collision");
            require(live->time_s()==control->time_s(),"retry/control accepted clocks diverged");
            for (auto actor:{std::string("left"),std::string("right")}) {
                live->selectHand(actor);control->selectHand(actor);sameHand(live->hand(),control->hand());
                for (const std::string suffix:mode=="fixed"?std::vector<std::string>{" tool"," handle"}:std::vector<std::string>{" tool"}) {
                    const auto a=named(live->poses(),actor+suffix),b=named(control->poses(),actor+suffix);
                    require(length(a.position_m-b.position_m)==0&&length(a.velocity_m_s-b.velocity_m_s)==0&&
                        std::equal(std::begin(a.orientation_wxyz),std::end(a.orientation_wxyz),std::begin(b.orientation_wxyz)),
                        "retry changed a player's constituent motion or desired wrist facing");
                }
            }
        }
        require(refused,"two-player hand rollback fixture never refused a collision");
        const auto before_error=live->playerHands();const double accepted_time=live->time_s();bool threw=false;
        try {live->step(std::numeric_limits<double>::max());}catch (const std::invalid_argument &) {threw=true;}
        require(threw&&live->time_s()==accepted_time,"unrepresentable native step was accepted or advanced time");
        for (const std::string actor:{"left","right"}) {live->selectHand(actor);sameHand(before_error.at(actor),live->hand());}
        live->step(kDt);control->step(kDt);
        require(!live->steppedBack()&&!control->steppedBack()&&live->time_s()==control->time_s(),"exception recovery failed to accept one step");
        for (const std::string actor:{"left","right"}) {
            live->selectHand(actor);control->selectHand(actor);sameHand(live->hand(),control->hand());live->cancelStroke();control->cancelStroke();
        }
        std::string why;const auto saved=live->snapshot(why);require(!saved.empty(),"post-rollback snapshot refused: "+why);
        const auto saved_control=control->snapshot(why);require(!saved_control.empty(),"control snapshot refused: "+why);
        const auto state=nlohmann::json::parse(saved),expected=nlohmann::json::parse(saved_control);
        require(state.at("steps")==expected.at("steps")&&state.at("steps").get<std::uint64_t>()==static_cast<std::uint64_t>(std::llround(live->time_s()/kDt))&&
            state.at("last_dt_s")==expected.at("last_dt_s"),"refused/exceptional attempts polluted persisted accepted scheduler metadata");
        require(state.at("player_hands")==expected.at("player_hands")&&state.at("hand")==expected.at("hand"),
            "refused/exceptional attempts polluted saved personal grip, wrist or work history");
        require(std::isfinite(live->hand().work_j)&&std::abs(live->hand().work_j)>0,"rollback fixture did not retain actual hand work");
        auto restarted=LiveWorld::open(request,saved),restarted_control=LiveWorld::open(request,saved_control);
        require(restarted->restored().tier=="whole"&&restarted_control->restored().tier=="whole",
            "post-rollback fixture could not restore the whole saved world");
        for (unsigned step=0;step<8;++step) {
            restarted->step(kDt);restarted_control->step(kDt);
            require(!restarted->steppedBack()&&!restarted_control->steppedBack()&&restarted->time_s()==restarted_control->time_s(),
                "restarted rollback/control clocks diverged");
            for (const std::string actor:{"left","right"}) {
                restarted->selectHand(actor);restarted_control->selectHand(actor);
                sameHand(restarted->hand(),restarted_control->hand());
                for (const std::string suffix:mode=="fixed"?std::vector<std::string>{" tool"," handle"}:std::vector<std::string>{" tool"}) {
                    const auto a=named(restarted->poses(),actor+suffix),b=named(restarted_control->poses(),actor+suffix);
                    require(length(a.position_m-b.position_m)==0&&length(a.velocity_m_s-b.velocity_m_s)==0&&
                        std::equal(std::begin(a.orientation_wxyz),std::end(a.orientation_wxyz),std::begin(b.orientation_wxyz)),
                        "restarted tool/constituent motion diverged after rollback");
                }
            }
        }
        std::cout<<"  "<<mode<<" "<<materialPresetName(material)<<": two-player refused/exceptional hand and accepted retry = exact; work="
            <<live->hand().work_j<<" J; mass="<<named(live->poses(),"right tool").mass_kg<<" kg\n";
    }
}
} // namespace

int main() {
    // Every check runs and every failure is said: one that stops at the first
    // hides the rest.
    const std::vector<std::pair<const char *, std::function<void()>>> tests = {
        {"shared grip effective mass, bounds and root-feedback oracles", sharedGripAnalyticalOracles},
        {"refused native collision restores every player's hand", refusedStepsRestoreEveryPlayersHand},
        {"a stroke needs a hand that pulls", aStrokeNeedsAHandThatPulls},
        {"the same throw, light and heavy balls", lightAndHeavyBalls},
        {"a draw against a spring", drawingAgainstASpring},
        {"moving the hand takes it back", movingTheHandTakesItBack},
        {"a preview changes nothing", aPreviewChangesNothing},
        {"a box thrown along a plank slides along it", aBoxThrownAlongAPlankSlidesAlongIt},
        {"a gate too heavy to lift still swings on its pins", aGateTooHeavyToLiftStillSwings},
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
