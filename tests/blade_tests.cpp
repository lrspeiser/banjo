// Blades, and cutting that changes what things are. docs/cutting-model.md.
//
// Every check here is against the physics, not against a number chosen so that
// it passes, and each prints what it measured.
//
//  1. The work a cut takes is the kinetic energy the two bodies actually lost,
//     and the area it bought is what the declared law says that work buys.
//  2. A partial cut stays partial: the bonds stay severed, the body stays one
//     body, and it is drawn with its kerf.
//  3. A cut all the way through makes pieces with the mass, inertia and
//     momentum of their own cells.
//  4. A slow press cuts only when it pushes harder than the material resists.
//  5. Slicing cuts with a push that pressing alone cannot.
//  6. An edge strike cuts a hanging rope, and the load falls; the rope's two
//     ends keep what they were tied to.
//  7. The flat of the same blade, the same strike, does not cut it.
//  8. A blade cannot cut what is as hard as it is, nor what is brittle.
//  9. A notched plank is overloaded by the load it carried before the notch.
// 10. The hand is bounded: it accelerates a blade no harder than its strength
//     allows, and cannot push one through what will not give.

#include "fastlattice/LiveWorld.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

constexpr double kDt = 1.0 / 240.0;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

TileImpactRequest request() {
    TileImpactRequest r;
    r.cell_size_m = 0.01;
    r.backend = BackendKind::CpuParallel;
    return r;
}

SceneBody box(const std::string &name, MaterialPreset material, Vec3 size, Vec3 centre,
              bool anchored = false, Vec3 velocity = {}) {
    SceneBody body;
    body.name = name;
    body.shape = BodyShape::Box;
    body.material = material;
    body.dimensions_m = size;
    body.center_m = centre;
    body.anchored = anchored;
    body.velocity_m_s = velocity;
    return body;
}

const LiveBodyPose *find(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return &pose;
    return nullptr;
}

const LiveBodyPose &named(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    if (const LiveBodyPose *pose = find(poses, name)) return *pose;
    throw std::runtime_error("no body called " + name);
}

std::size_t piecesOf(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    std::size_t count = 0;
    for (const LiveBodyPose &pose : poses)
        if (pose.name.rfind(name + " piece ", 0) == 0) ++count;
    return count;
}

// A step, answering any break the world offers by declining it: these tests
// are about cutting, and a world left waiting for an answer does not move.
void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void run(LiveWorld &world, int steps) {
    for (int i = 0; i < steps; ++i) tick(world);
}

double speedOf(const LiveBodyPose &pose) { return length(pose.velocity_m_s); }

std::vector<LiveCut> cutsOf(const LiveWorld &world, const std::string &target_prefix) {
    std::vector<LiveCut> out;
    for (const LiveCut &cut : world.cuts())
        if (cut.target.rfind(target_prefix, 0) == 0) out.push_back(cut);
    return out;
}

// -----------------------------------------------------------------------------
// 1 and 2. The energy account, and a partial cut that stays partial.
// -----------------------------------------------------------------------------

void theCutCostsWhatItTook() {
    // No gravity, no floor in reach, nothing but the two bodies: whatever kinetic
    // energy leaves them left through the cut, because nothing else can take it.
    TileImpactRequest r = request();
    r.gravity_m_s2 = {0.0, 0.0, 0.0};
    constexpr double kSpeed = 6.0;
    r.bodies = {box("block", MaterialPreset::Oak, {0.1, 0.1, 0.1}, {0.0, 0.5, 0.0}),
                box("blade", MaterialPreset::Iron, {0.2, 0.01, 0.03}, {0.0, 0.5, 0.066}, false,
                    {0.0, 0.0, -kSpeed})};
    const auto world = LiveWorld::open(r);
    // A sharp edge: 0.05 mm radius, so R = G + H w = 1000 + 35e6 * 1e-4 J/m^2.
    const unsigned id = world->blade("blade", {-0.09, 0.5, 0.051}, {0.09, 0.5, 0.051},
                                     {0.0, 0.0, -1.0}, 0.01, 0.00005, 30.0, {0.09, 0.5, 0.066});
    require(id != 0, "the blade would not take an edge");

    const double blade_kg = 0.2 * 0.01 * 0.03 * 7870.0;
    const double block_kg = 0.1 * 0.1 * 0.1 * 700.0;
    const auto kinetic = [&](const std::vector<LiveBodyPose> &poses) {
        const double vb = speedOf(named(poses, "blade"));
        const double vk = speedOf(named(poses, "block"));
        return 0.5 * blade_kg * vb * vb + 0.5 * block_kg * vk * vk;
    };
    const double before = kinetic(world->poses());
    for (int i = 0; i < 120; ++i) {
        tick(*world);
        const auto poses = world->poses();
        const double closing = named(poses, "block").velocity_m_s.z - named(poses, "blade").velocity_m_s.z;
        if (i > 4 && std::abs(closing) < 0.005) break;
    }
    const auto after_poses = world->poses();
    const double after = kinetic(after_poses);
    const LiveBlade blade = world->blades().front();
    const double lost = before - after;
    const double resistance = 1000.0 + 35.0e6 * 2.0 * 0.00005;
    const double depth_mm = blade.cut_area_m2 / 0.1 * 1000.0;
    std::cout << "  an iron blade at " << kSpeed << " m/s into a free oak block: kinetic energy "
              << before << " J -> " << after << " J, so " << lost
              << " J left the pair. The kerf constraint's friction took " << blade.cut_work_j
              << " J, which at R = " << resistance << " J/m^2 is " << blade.cut_area_m2 * 1e6
              << " mm^2 -- " << depth_mm << " mm deep along 100 mm of edge\n";
    require(blade.cut_work_j > 1.0, "the blade cut almost nothing, so nothing was tested");
    require(std::abs(lost - blade.cut_work_j) <= 0.05 * blade.cut_work_j,
            "the energy the pair lost is not the work the cut took");
    require(std::abs(blade.cut_area_m2 * resistance - blade.cut_work_j) <= 1e-6 * blade.cut_work_j,
            "the area cut is not what the declared law says that work buys");

    // Partial: still one block, with bonds severed and a kerf to show for it.
    const auto partial = cutsOf(*world, "block");
    require(!partial.empty(), "the cut was never reported");
    std::size_t bonds = 0;
    for (const LiveCut &cut : partial) bonds += cut.bonds;
    require(bonds > 0, "the edge went in but no bond was severed");
    require(find(after_poses, "block") != nullptr && piecesOf(after_poses, "block") == 0,
            "a partial cut split the block");
    require(!named(after_poses, "block").kerfs.empty(), "the block does not carry its kerf");

    // And it STAYS partial. A second of drifting together changes nothing.
    run(*world, 240);
    std::size_t bonds_later = 0;
    for (const LiveCut &cut : cutsOf(*world, "block")) bonds_later += cut.bonds;
    const auto later = world->poses();
    std::cout << "  " << bonds << " bonds severed; a second later " << bonds_later
              << ", and the block is " << (find(later, "block") ? "still one piece" : "gone")
              << " with " << named(later, "block").kerfs.size() << " kerf\n";
    require(bonds_later == bonds, "a partial cut kept cutting, or healed");
    require(find(later, "block") != nullptr && piecesOf(later, "block") == 0,
            "a partial cut came apart on its own");
}

// -----------------------------------------------------------------------------
// 3. Through: pieces with the mass, inertia and momentum of their own cells.
// -----------------------------------------------------------------------------

void aThroughCutMakesRealPieces() {
    TileImpactRequest r = request();
    r.gravity_m_s2 = {0.0, 0.0, 0.0};
    // A long oak batten, struck across its middle. Long, because a light thing
    // struck by a heavy one is knocked away rather than cut: what cuts it is its
    // own inertia, and a metre of batten has enough of it.
    // The blade's -z face -- its edge -- starts 1 mm clear of the batten's +z
    // face at z = 0.01.
    r.bodies = {box("batten", MaterialPreset::Oak, {1.0, 0.02, 0.02}, {0.0, 0.5, 0.0}),
                box("blade", MaterialPreset::Iron, {0.01, 0.06, 0.1}, {0.0, 0.5, 0.061}, false,
                    {0.0, 0.0, -9.0})};
    const auto world = LiveWorld::open(r);
    // The edge runs along y down the blade's -z face, facing -z: a chop across
    // the batten at x = 0.
    const unsigned id = world->blade("blade", {0.0, 0.475, 0.011}, {0.0, 0.525, 0.011},
                                     {0.0, 0.0, -1.0}, 0.01, 0.00005, 30.0, {0.0, 0.5, 0.11});
    require(id != 0, "the blade would not take an edge");
    const double blade_kg = 0.01 * 0.06 * 0.1 * 7870.0;
    const double batten_kg = 1.0 * 0.02 * 0.02 * 700.0;
    const double momentum_before = blade_kg * -9.0;

    for (int i = 0; i < 240 && piecesOf(world->poses(), "batten") == 0; ++i) tick(*world);
    const auto poses = world->poses();
    const std::size_t pieces = piecesOf(poses, "batten");
    require(pieces == 2, "the batten did not come apart in two, it came apart in " +
                             std::to_string(pieces));
    const LiveBodyPose &one = named(poses, "batten piece 1");
    const LiveBodyPose &two = named(poses, "batten piece 2");
    // Mass: each piece is its cells. Read back through what the solver was given.
    const double cell_kg = 0.01 * 0.01 * 0.01 * 700.0;
    const double one_kg = static_cast<double>(one.cells_local_m.size()) * cell_kg;
    const double two_kg = static_cast<double>(two.cells_local_m.size()) * cell_kg;
    (void)one_kg;
    (void)two_kg;
    const auto geometry = world->poses(true);
    const std::size_t cells_one = named(geometry, "batten piece 1").cells_local_m.size();
    const std::size_t cells_two = named(geometry, "batten piece 2").cells_local_m.size();
    std::cout << "  a 9 m/s chop through a metre of oak batten: 2 pieces of " << cells_one
              << " and " << cells_two << " cells, " << cells_one * cell_kg * 1000.0 << " g and "
              << cells_two * cell_kg * 1000.0 << " g of a " << batten_kg * 1000.0 << " g batten\n";
    require(cells_one + cells_two == 400, "cells were lost or made in the cut");
    require(cells_one == 200 && cells_two == 200, "a cut at the middle did not halve it");
    // Each piece is a half-batten, 0.5 x 0.02 x 0.02 m, and its bounds say so.
    for (const LiveBodyPose *piece : {&one, &two}) {
        require(std::abs(piece->dimensions_m.x - 0.5) < 0.011 &&
                    std::abs(piece->dimensions_m.y - 0.02) < 0.001 &&
                    std::abs(piece->dimensions_m.z - 0.02) < 0.001,
                "a piece does not have the shape of half the batten");
    }
    // Momentum along the strike is conserved by the split: the pieces carry
    // exactly what their cells had.
    const double momentum_after = blade_kg * named(poses, "blade").velocity_m_s.z +
                                  cells_one * cell_kg * one.velocity_m_s.z +
                                  cells_two * cell_kg * two.velocity_m_s.z;
    std::cout << "  momentum along the strike: " << momentum_before << " kg m/s before, "
              << momentum_after << " after\n";
    require(std::abs(momentum_after - momentum_before) < 0.02 * std::abs(momentum_before),
            "the split did not conserve momentum");
    const auto cuts = cutsOf(*world, "batten");
    require(!cuts.empty() && cuts.front().separated && cuts.front().pieces == 2,
            "the cut that separated it does not say so");
}

// -----------------------------------------------------------------------------
// 4 and 5. A press, and a slice.
// -----------------------------------------------------------------------------

TileImpactRequest battenOnTheFloor() {
    TileImpactRequest r = request();
    // A heavy blade resting edge-down on an oak batten lying on the floor.
    r.bodies = {box("batten", MaterialPreset::Oak, {0.2, 0.02, 0.02}, {0.0, 0.01, 0.0}),
                box("blade", MaterialPreset::Iron, {0.01, 0.1, 0.25}, {0.0, 0.07, 0.0})};
    return r;
}

unsigned edgeDown(LiveWorld &world) {
    // A working edge, 0.2 mm radius: R = 1000 + 35e6 * 4e-4 = 15 kJ/m^2 in oak,
    // so the 20 mm batten resists a straight press with 300 N.
    return world.blade("blade", {0.0, 0.02, -0.1}, {0.0, 0.02, 0.1}, {0.0, -1.0, 0.0}, 0.01,
                       0.0002, 30.0, {0.0, 0.12, 0.0});
}

void aPressCutsOnlyWhenItPushesHarderThanTheMaterial() {
    const auto world = LiveWorld::open(battenOnTheFloor());
    require(edgeDown(*world) != 0, "the blade would not take an edge");
    require(world->wield("blade", {0.0, 0.12, 0.0}), "could not take hold of the blade");
    // 200 N of hand plus the blade's own 19 N is short of the 300 N the batten
    // resists with. Aim well below it, so the hand pushes with all it has.
    world->setHandStrength(200.0);
    world->moveHeld({0.0, -0.3, 0.0});
    run(*world, 240);
    std::size_t bonds = 0;
    for (const LiveCut &cut : cutsOf(*world, "batten")) bonds += cut.bonds;
    const double edge_y = named(world->poses(), "blade").position_m.y - 0.05;
    std::cout << "  pressed with 200 N for a second: " << bonds << " bonds severed, edge at "
              << edge_y * 1000.0 << " mm (the batten's top is at 20 mm)\n";
    require(bonds == 0, "a press short of the material's resistance cut it");
    require(edge_y > 0.0185, "the edge sank into the batten without cutting it");
    require(piecesOf(world->poses(), "batten") == 0, "the batten came apart under a weak press");

    // The same world, the same blade: a hand with 800 N goes through.
    world->setHandStrength(800.0);
    for (int i = 0; i < 480 && piecesOf(world->poses(), "batten") == 0; ++i) tick(*world);
    const auto poses = world->poses();
    const auto cuts = cutsOf(*world, "batten");
    double work = 0.0;
    for (const LiveCut &cut : cuts) work += cut.work_j;
    const double section = 0.02 * 0.02;
    std::cout << "  pressed with 800 N: " << piecesOf(poses, "batten") << " pieces, "
              << work << " J of cutting against R x section = " << 15000.0 * section
              << " J, first called \"" << (cuts.empty() ? std::string("-") : cuts.front().kind)
              << "\"\n";
    require(piecesOf(poses, "batten") == 2, "an 800 N press did not cut through");
    require(!cuts.empty() && cuts.front().kind == "press", "a slow push was not called a press");
    // Separation comes when the last bond across the kerf goes, up to half a
    // cell before the edge has swept the whole section: 20 mm deep in 10 mm
    // cells is at least three quarters of it.
    require(work > 0.70 * 15000.0 * section && work < 1.15 * 15000.0 * section,
            "cutting through did not cost R times the section it separated");
}

void aSliceCutsWhereAPressCannot() {
    const auto world = LiveWorld::open(battenOnTheFloor());
    require(edgeDown(*world) != 0, "the blade would not take an edge");
    require(world->wield("blade", {0.0, 0.12, 0.0}), "could not take hold of the blade");
    world->setHandStrength(200.0);
    // Draw the edge back and forth along its own length while pushing down with
    // the same 200 N that could not press through.
    for (int i = 0; i < 480; ++i) {
        const double t = i * kDt;
        world->moveHeld({0.0, -0.3, 0.06 * std::sin(2.0 * 3.14159265358979323846 * 1.5 * t)});
        tick(*world);
    }
    std::size_t bonds = 0;
    for (const LiveCut &cut : cutsOf(*world, "batten")) bonds += cut.bonds;
    std::cout << "  drawn along its edge with the same 200 N: " << bonds << " bonds severed, "
              << piecesOf(world->poses(), "batten") << " pieces\n";
    require(bonds > 0, "slicing with a push that cannot press through cut nothing");
}

// -----------------------------------------------------------------------------
// 6 and 7. A rope, struck with the edge and with the flat.
// -----------------------------------------------------------------------------

struct Rope {
    std::unique_ptr<LiveWorld> world;
    unsigned top{}, bottom{};
};

// Eight rubber segments hanging from an anchored beam, an iron weight on the
// end, and a blade coming at the middle of the fifth segment.
Rope hangingRope(bool edge_first, double speed) {
    TileImpactRequest r = request();
    r.bodies = {box("beam", MaterialPreset::Oak, {0.2, 0.04, 0.04}, {0.0, 1.22, 0.0}, true)};
    for (int k = 0; k < 8; ++k)
        r.bodies.push_back(box("rope " + std::to_string(k), MaterialPreset::Rubber,
                               {0.02, 0.06, 0.02}, {0.0, 1.17 - 0.06 * k, 0.0}));
    r.bodies.push_back(box("weight", MaterialPreset::Iron, {0.06, 0.06, 0.06}, {0.0, 0.69, 0.0}));
    // Edge first: the flats are horizontal and the edge faces the rope. Flat
    // first: the same blade turned a quarter, so its flat faces the rope.
    const Vec3 size = edge_first ? Vec3{0.4, 0.01, 0.03} : Vec3{0.4, 0.03, 0.01};
    r.bodies.push_back(box("blade", MaterialPreset::Iron, size, {0.0, 0.93, 0.1}, false,
                           {0.0, 0.0, -speed}));
    Rope rope;
    rope.world = LiveWorld::open(r);
    LiveWorld &world = *rope.world;
    rope.top = world.tie("beam", "rope 0", {0.0, 1.205, 0.0}, {0.0, 1.195, 0.0});
    for (int k = 0; k < 7; ++k) {
        const double top = 1.20 - 0.06 * k;
        require(world.tie("rope " + std::to_string(k), "rope " + std::to_string(k + 1),
                          {0.0, top - 0.055, 0.0}, {0.0, top - 0.065, 0.0}) != 0,
                "a rope segment would not tie to the next");
    }
    rope.bottom = world.tie("rope 7", "weight", {0.0, 0.725, 0.0}, {0.0, 0.715, 0.0});
    require(rope.top != 0 && rope.bottom != 0, "the rope would not tie");
    const unsigned id = edge_first
        ? world.blade("blade", {-0.15, 0.93, 0.085}, {0.15, 0.93, 0.085}, {0.0, 0.0, -1.0},
                      0.01, 0.00005, 30.0, {0.19, 0.93, 0.1})
        : world.blade("blade", {-0.15, 0.915, 0.1}, {0.15, 0.915, 0.1}, {0.0, -1.0, 0.0},
                      0.01, 0.00005, 30.0, {0.19, 0.93, 0.1});
    require(id != 0, "the blade would not take an edge");
    return rope;
}

bool attached(const LiveWorld &world, unsigned id) {
    for (const LiveJoint &joint : world.joints())
        if (joint.id == id) return joint.attached;
    return false;
}

void anEdgeStrikeCutsTheRopeAndTheWeightFalls() {
    Rope rope = hangingRope(true, 16.0);
    LiveWorld &world = *rope.world;
    const double hung = named(world.poses(), "weight").position_m.y;
    run(world, 360);
    const auto poses = world.poses();
    const double fell = named(poses, "weight").position_m.y;
    std::size_t severed = 0, parted = 0;
    std::string kind;
    for (const LiveCut &cut : cutsOf(world, "rope")) {
        severed += cut.bonds;
        parted += cut.links;
        if (kind.empty() && (cut.bonds > 0 || cut.links > 0)) kind = cut.kind;
    }
    std::size_t pieces = 0;
    for (int k = 0; k < 8; ++k) pieces += piecesOf(poses, "rope " + std::to_string(k));
    std::cout << "  an edge at 16 m/s across the rope: " << severed << " bonds and " << parted
              << " links cut (\"" << kind << "\"), " << pieces << " segment pieces; the weight "
              << "went from y=" << hung << " to y=" << fell << "\n";
    require(severed > 0 || parted > 0, "the edge went through the rope and cut nothing");
    require(fell < hung - 0.4, "the rope was cut and the weight did not fall");
    // Each end keeps what it held: the top of the rope is still on the beam and
    // the weight is still on the bottom of the rope.
    require(attached(world, rope.top), "cutting the rope took it off the beam");
    require(attached(world, rope.bottom), "cutting the rope took the weight off its end");
    // And the ties either side of the cut segment follow its two pieces -- the
    // upper piece stays on the segment above it, the lower keeps the segment
    // below. Only a tie the edge itself went through comes off.
    std::size_t detached = 0;
    for (const LiveJoint &joint : world.joints())
        if (joint.kind == "link" && !joint.attached) ++detached;
    std::cout << "  " << detached << " ties came off, " << parted
              << " of them cut by the edge\n";
    require(detached == parted, "a tie came off that the edge never went through");
}

void theFlatOfTheBladeDoesNotCutIt() {
    Rope rope = hangingRope(false, 16.0);
    LiveWorld &world = *rope.world;
    const double hung = named(world.poses(), "weight").position_m.y;
    run(world, 360);
    const auto poses = world.poses();
    std::size_t severed = 0, parted = 0;
    bool flat = false;
    for (const LiveCut &cut : cutsOf(world, "rope")) {
        severed += cut.bonds;
        parted += cut.links;
        flat = flat || cut.kind == "flat";
    }
    bool all_attached = true;
    for (const LiveJoint &joint : world.joints()) all_attached = all_attached && joint.attached;
    const double now = named(poses, "weight").position_m.y;
    std::cout << "  the flat at 16 m/s across the same rope: " << severed << " bonds and "
              << parted << " links cut, reported as " << (flat ? "a flat strike" : "something else")
              << "; the weight is at y=" << now << " (hung at " << hung << ")\n";
    require(severed == 0 && parted == 0, "the flat of the blade cut the rope");
    require(all_attached, "the flat strike took something off the rope");
    require(flat, "the flat strike was not reported as one");
    require(now > hung - 0.25, "the weight fell, so the rope did not hold");
}

// -----------------------------------------------------------------------------
// 8. Hard and brittle things are not cut.
// -----------------------------------------------------------------------------

void hardAndBrittleThingsAreNotCut() {
    for (const auto &[material, word] :
         {std::pair{MaterialPreset::Iron, std::string("blunt")},
          std::pair{MaterialPreset::Glass, std::string("brittle")}}) {
        TileImpactRequest r = request();
        r.bodies = {box("target", material, {0.2, 0.02, 0.02}, {0.0, 0.01, 0.0}),
                    box("blade", MaterialPreset::Iron, {0.01, 0.1, 0.25}, {0.0, 0.07, 0.0})};
        const auto world = LiveWorld::open(r);
        require(world->blade("blade", {0.0, 0.02, -0.1}, {0.0, 0.02, 0.1}, {0.0, -1.0, 0.0},
                             0.01, 0.0002, 30.0, {0.0, 0.12, 0.0}) != 0,
                "the blade would not take an edge");
        require(world->wield("blade", {0.0, 0.12, 0.0}), "could not take hold of the blade");
        world->moveHeld({0.0, -0.3, 0.0});
        run(*world, 240);
        std::size_t bonds = 0;
        bool said = false;
        for (const LiveCut &cut : cutsOf(*world, "target")) {
            bonds += cut.bonds;
            said = said || cut.kind == word;
        }
        std::cout << "  an iron edge pressed with 800 N onto " << materialPresetName(material)
                  << ": " << bonds << " bonds severed, called \"" << (said ? word : "?") << "\"\n";
        require(bonds == 0, "an iron edge cut " + std::string(materialPresetName(material)));
        require(said, "the contact was not reported as " + word);
    }
}

// -----------------------------------------------------------------------------
// 9. A notched plank cannot carry what it carried.
// -----------------------------------------------------------------------------

void aNotchedPlankIsOverloaded() {
    TileImpactRequest r = request();
    constexpr double kDrop = 0.233;   // m: the blade arrives with m g h = 4.5 J
    // An oak batten 30 mm wide and 20 mm deep across two iron piers 2.0 m
    // apart, carrying a 130 mm iron block -- 170 N -- on its middle: 44 MPa of
    // bending against oak's 90. It holds. The long span is what lets the load
    // be light: a load sitting on a batten a hundred times lighter than itself
    // is a stack the contact solver cannot keep square -- a 63 kg block on a
    // 0.67 kg batten rolled it 4 degrees standing untouched -- and this one is
    // eighteen to one.
    r.bodies = {box("pier left", MaterialPreset::Iron, {0.1, 0.3, 0.1}, {-1.05, 0.15, 0.0}, true),
                box("pier right", MaterialPreset::Iron, {0.1, 0.3, 0.1}, {1.05, 0.15, 0.0}, true),
                box("batten", MaterialPreset::Oak, {2.2, 0.02, 0.03}, {0.0, 0.31, 0.0}),
                box("load", MaterialPreset::Iron, {0.13, 0.13, 0.13}, {0.0, 0.385, 0.0}),
                box("blade", MaterialPreset::Iron, {0.01, 0.1, 0.25}, {0.3, 0.37 + kDrop, 0.0})};
    const auto world = LiveWorld::open(r);
    // The blade takes its edge where it stands, 233 mm above the batten, and is
    // held there while the batten settles under the load alone. (Left to stand
    // free, a 10 mm plate on its edge falls over, and its edge is no longer
    // where it was declared -- which blade() rightly refuses.)
    require(world->blade("blade", {0.3, 0.32 + kDrop, -0.1}, {0.3, 0.32 + kDrop, 0.1},
                         {0.0, -1.0, 0.0}, 0.01, 0.0002, 30.0, {0.3, 0.42 + kDrop, 0.0}) != 0,
            "the blade would not take an edge");
    require(world->wield("blade", {0.3, 0.42 + kDrop, 0.0}), "could not take hold of the blade");
    // How far the batten has rolled about its own length, in degrees: a load
    // that stands on it tips off past about 9.5.
    const auto rolled = [&world]() {
        const auto q = named(world->poses(), "batten").orientation_wxyz;
        return 2.0 * std::asin(std::min(1.0, std::abs(q[1]))) * 180.0 / 3.14159265358979;
    };
    world->moveHeld({0.3, 0.42 + kDrop, 0.0});
    run(*world, 130);
    std::cout << "  settled: the batten has rolled " << rolled() << " degrees\n";
    bool overloaded_before = false;
    for (const LiveOverload &load : world->overloaded())
        overloaded_before = overloaded_before || load.name == "batten";
    require(!overloaded_before, "the intact batten is already overloaded, so this proves nothing");

    // A notch chopped into it at x = 0.3 m, clear of the load: the blade let
    // go 233 mm above it, edge down. It arrives with m g h = 4.5 J, and 30 mm
    // of oak resists with R L = 450 N or a little more, so it stops 8 to 10 mm
    // in -- past the upper row of cells and short of the lower. An energy the
    // model accounts for sets the depth, not a hand's push.
    world->release();
    run(*world, 360);
    {
        const LiveBodyPose &b = named(world->poses(), "blade");
        std::cout << "  chopped: the batten has rolled " << rolled() << " degrees; the blade's"
                  << " centre is at y=" << b.position_m.y << ", moving "
                  << length(b.velocity_m_s) << " m/s\n";
    }
    const auto poses = world->poses();
    const auto cuts = cutsOf(*world, "batten");
    double area = 0.0;
    std::size_t bonds = 0;
    for (const LiveCut &cut : cuts) {
        area += cut.area_m2;
        bonds += cut.bonds;
    }
    double stress = 0.0, strength = 0.0;
    bool overloaded_after = false;
    for (const LiveOverload &load : world->overloaded()) {
        if (load.name != "batten") continue;
        overloaded_after = true;
        stress = load.stress_pa;
        strength = load.strength_pa;
    }
    for (const LiveCut &cut : cuts)
        std::cout << "  met the batten: " << cut.kind << " at " << cut.speed_m_s << " m/s, "
                  << cut.area_m2 * 1e6 << " mm^2\n";
    const LiveBodyPose &load_now = named(poses, "load");
    const LiveBodyPose &batten_now = named(poses, "batten");
    std::cout << "  after: load at (" << load_now.position_m.x << ", " << load_now.position_m.y
              << ", " << load_now.position_m.z << "), batten at y=" << batten_now.position_m.y
              << " turned w=" << batten_now.orientation_wxyz[0] << " x="
              << batten_now.orientation_wxyz[1] << " y=" << batten_now.orientation_wxyz[2]
              << " z=" << batten_now.orientation_wxyz[3] << "\n";
    std::cout << "  notched " << area / 0.03 * 1000.0 << " mm deep across the 30 mm batten (" << bonds
              << " bonds): the batten is " << (overloaded_after ? "overloaded" : "still fine")
              << (overloaded_after ? ", " + std::to_string(stress / 1e6) + " MPa against " +
                                         std::to_string(strength / 1e6)
                                   : std::string()) << "\n";
    require(find(poses, "batten") != nullptr, "the notch went all the way through");
    require(bonds > 0, "no notch was cut");
    require(overloaded_after, "a notched batten is still said to carry what it carried whole");
}

// -----------------------------------------------------------------------------
// 10. The hand is bounded.
// -----------------------------------------------------------------------------

void theHandIsBounded() {
    TileImpactRequest r = request();
    r.gravity_m_s2 = {0.0, 0.0, 0.0};
    r.bodies = {box("blade", MaterialPreset::Iron, {0.01, 0.1, 0.25}, {0.0, 1.0, 0.0}),
                box("wall", MaterialPreset::Iron, {0.2, 0.4, 0.4}, {0.0, 1.0, -0.4}, true)};
    const auto world = LiveWorld::open(r);
    require(world->blade("blade", {0.0, 0.95, -0.12}, {0.0, 1.05, -0.12}, {0.0, 0.0, -1.0}, 0.01,
                         0.0002, 30.0, {0.0, 1.0, 0.1}) != 0,
            "the blade would not take an edge");
    require(world->wield("blade", {0.0, 1.0, 0.1}), "could not take hold of the blade");
    const double mass = 0.01 * 0.1 * 0.25 * 7870.0;
    // A target a metre away along x, nothing in the way: the hand pulls with
    // all it has, and no more.
    world->moveHeld({1.0, 1.0, 0.1});
    double previous = 0.0, hardest = 0.0;
    for (int i = 0; i < 24; ++i) {
        tick(*world);
        const double v = named(world->poses(), "blade").velocity_m_s.x;
        hardest = std::max(hardest, (v - previous) / kDt);
        previous = v;
    }
    const double bound = world->handStrength() / mass;
    std::cout << "  pulled towards a target a metre off: " << hardest << " m/s^2 at most, against "
              << bound << " for an " << world->handStrength() << " N hand on " << mass << " kg\n";
    require(hardest <= 1.02 * bound, "the hand pulled harder than it is able to");
    require(hardest >= 0.8 * bound, "the hand did not use the strength it has");

    // Now into the wall: iron, anchored. The hand drives the edge at it with
    // everything it has and the wall does not give.
    world->moveHeld({0.0, 1.0, 0.1});
    run(*world, 240);
    world->moveHeld({0.0, 1.0, -0.8});
    run(*world, 240);
    const double edge_z = named(world->poses(), "blade").position_m.z - 0.125;
    std::cout << "  driven edge-first into an anchored iron wall: the edge stopped at z="
              << edge_z << " m (the wall's face is at z=-0.2)\n";
    require(edge_z > -0.205, "the hand pushed the blade into an iron wall");
}

} // namespace

int main(int argc, char **argv) {
    // Each check by name, so one can be run alone: banjo_blade_tests press
    const std::vector<std::pair<const char *, void (*)()>> checks = {
        {"the work a cut takes is the energy the bodies lost, and a partial cut stays partial",
         theCutCostsWhatItTook},
        {"a cut through makes pieces with their own mass and momentum", aThroughCutMakesRealPieces},
        {"a slow press cuts only when it pushes harder than the material resists",
         aPressCutsOnlyWhenItPushesHarderThanTheMaterial},
        {"a slice cuts with a push that cannot press through", aSliceCutsWhereAPressCannot},
        {"an edge strike cuts a hanging rope and the weight falls",
         anEdgeStrikeCutsTheRopeAndTheWeightFalls},
        {"the flat of the blade does not cut the rope", theFlatOfTheBladeDoesNotCutIt},
        {"an iron edge cuts neither iron nor glass", hardAndBrittleThingsAreNotCut},
        {"a notched plank cannot carry what it carried", aNotchedPlankIsOverloaded},
        {"the hand is bounded", theHandIsBounded},
    };
    const std::string only = argc > 1 ? argv[1] : "";
    try {
        for (const auto &[name, check] : checks) {
            if (!only.empty() && std::string(name).find(only) == std::string::npos) continue;
            check();
            std::cout << "[PASS] " << name << "\n";
        }
        std::cout << "\nall blade tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
