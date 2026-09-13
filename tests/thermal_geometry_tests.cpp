// One material state: heat, burning, fracture and geometry read from the same
// field (docs/thermal-mechanics.md, "One material state").
//
// The owner's review of main 81a27c6 found two places where the engine held
// two answers to one question. A heated beam's overload check used its
// heat-weakened section while the lattice that works out its fracture used
// room-temperature bonds; and what burned left the section and the mass but
// not the collision shape, the drawn shape, the centre of mass or the inertia.
// Every test here asks one quantity of two consumers and requires the same
// answer, and says the numbers.
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "fracture/SustainedLoad.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "thermo/ThermalMechanics.hpp"
#include "thermo/ThermoWorld.hpp"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

constexpr double kDt = 1.0 / 240.0;   // what the room steps at

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

bool near(double a, double b, double tolerance) { return std::abs(a - b) <= tolerance; }

std::unique_ptr<LiveWorld> openScene(const std::string &scene, double cell_m) {
    TileImpactRequest request;
    request.cell_size_m = cell_m;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(scene);
    readSceneSettings(scene, request);
    return LiveWorld::open(request);
}

std::string box(const std::string &name, const std::string &material, Vec3 size, Vec3 at,
                bool anchored, const std::string &extra = "") {
    char text[512];
    std::snprintf(text, sizeof text,
                  R"({"name":"%s","shape":"box","material":"%s","dimensions_m":[%g,%g,%g],)"
                  R"("center_m":[%g,%g,%g],"anchored":%s%s})",
                  name.c_str(), material.c_str(), size.x, size.y, size.z, at.x, at.y, at.z,
                  anchored ? "true" : "false", extra.c_str());
    return text;
}

std::string scene(const std::string &bodies) { return std::string(R"({"bodies":[)") + bodies + "]}"; }

// Step without answering anything: a break the world asks about is declined,
// so a test sees the world's own offers and nothing is broken behind its back.
void stepOnce(LiveWorld &world) {
    for (int tries = 0; tries < 8; ++tries) {
        world.step(kDt);
        if (!world.steppedBack()) return;
        for (const std::string &name : world.breakable()) world.declineBreak(name);
    }
}

void stepFor(LiveWorld &world, double seconds) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int done = 0; done < steps; ++done) stepOnce(world);
}

std::optional<LiveBodyPose> findPose(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name) return pose;
    return std::nullopt;
}

LiveBodyPose poseOf(const LiveWorld &world, const std::string &name) {
    const auto found = findPose(world, name);
    if (!found) throw std::runtime_error("no body called " + name);
    return *found;
}

// ---- the field, on its own ---------------------------------------------------

// Cold and whole is exactly as it was built; the cells' shares add up to what
// the field says is left; and the section the survey reads is the field
// integrated over a cross-section -- here checked against a direct integral of
// cellFactors over a fine grid of cells.
void theFieldIsOneState() {
    const thermo::MechanicalLaw *oak = thermo::lawFor("oak");
    require(oak != nullptr, "oak has a law");
    const Vec3 box_m{0.40, 0.06, 0.10};
    thermo::MatterState cold;
    cold.material = "oak";
    cold.surface_kg = 700.0 * 0.40 * 0.06 * 0.10;
    const thermo::MaterialField whole = thermo::materialField(oak, cold, box_m);
    for (const Vec3 at : {Vec3{0.19, 0.02, 0.04}, Vec3{0.0, 0.0, 0.0}, Vec3{-0.19, -0.02, -0.04}}) {
        const thermo::CellShare share = thermo::cellShare(whole, at, 0.02);
        const thermo::ZoneFactors f = thermo::cellFactors(whole, share);
        require(share.remaining() == 1.0 && f.stiffness == 1.0 && f.tension == 1.0 && f.compression == 1.0 &&
                    f.shear == 1.0,
                "a cold, whole cell is exactly as it was built");
    }

    // Hot, charred and partly burned: a 3 mm layer at 700 K over a 400 K core,
    // 12% of its dry wood gone.
    thermo::MatterState hot = cold;
    hot.layered = true;
    hot.layer_depth_m = 0.003;
    hot.surface_k = hot.peak_surface_k = 700.0;
    hot.core_k = hot.peak_core_k = 400.0;
    hot.consumed_fraction = 0.12;
    hot.surface_kg = 0.2 * cold.surface_kg;
    hot.core_kg = 0.6 * cold.surface_kg;
    const thermo::MaterialField field = thermo::materialField(oak, hot, box_m);
    require(field.surface_char && !field.core_char, "the layer has charred and the core has not (the premise)");

    // What is left, cell by cell, is the field's own remaining volume.
    const double cell = 0.002;   // fine enough that the cells tile the box exactly
    double left = 0.0;
    for (double x = -0.2 + 0.5 * cell; x < 0.2; x += cell)
        for (double y = -0.03 + 0.5 * cell; y < 0.03; y += cell)
            for (double z = -0.05 + 0.5 * cell; z < 0.05; z += cell)
                left += thermo::cellShare(field, {x, y, z}, cell).remaining() * cell * cell * cell;
    std::cout << "    cells add up to " << left * 1e6 << " cm3 left of " << 0.40 * 0.06 * 0.10 * 1e6
              << " cm3; the field says " << thermo::remainingVolumeM3(field) * 1e6 << " cm3 ("
              << field.consumed_m * 1000.0 << " mm burned from every face)" << std::endl;
    require(near(left, thermo::remainingVolumeM3(field), 1e-9), "the cells hold exactly what the field says is left");
    require(near(1.0 - left / (0.40 * 0.06 * 0.10), 0.12, 1e-6), "and that is 12% gone, the network's share");

    // A cross-section: the survey's tension factor is the field's tension
    // factor averaged over the section's area. Integrated here cell by cell,
    // from the same field, over one slice.
    const thermo::SectionState section = thermo::evaluateSection(*oak, hot, box_m, 0);
    double sum = 0.0, count = 0.0;
    for (double y = -0.03 + 0.5 * cell; y < 0.03; y += cell)
        for (double z = -0.05 + 0.5 * cell; z < 0.05; z += cell) {
            // A cell one cell long, so its share across the section is exact.
            const thermo::CellShare share = thermo::cellShare(field, {0.0, y, z}, cell);
            sum += thermo::cellFactors(field, share).tension;
            count += 1.0;
        }
    std::cout << "    the section's tension factor " << section.tension << "; the field integrated over it "
              << sum / count << std::endl;
    require(near(section.tension, sum / count, 1e-9), "the section is the field integrated over a cross-section");

    // Mass properties: all of the network's matter, the inertia of the box that
    // is left.
    const thermo::FieldMassProperties mass = thermo::massProperties(field);
    const Vec3 d = thermo::remainingBox(field);
    require(near(mass.mass_kg, hot.surface_kg + hot.core_kg, 1e-12), "all the matter the network holds, no more");
    require(near(mass.inertia_kg_m2.x, mass.mass_kg * (d.y * d.y + d.z * d.z) / 12.0, 1e-15),
            "and the inertia of what is left");

    // A bond is two half-cells in series, as strong as its weaker end.
    const thermo::ZoneFactors a{0.5, 0.4, 0.3, 0.2}, b{0.25, 0.8, 0.9, 0.1};
    const thermo::ZoneFactors f = thermo::bondFactors(a, b);
    require(near(f.stiffness, 2.0 * 0.5 * 0.25 / 0.75, 1e-15) && f.tension == 0.4 && f.compression == 0.3 &&
                f.shear == 0.1,
            "bond stiffness in series, each strength the lesser end's");
}

// ---- statics against beam theory ----------------------------------------------
//
// A box lattice of oak, simply supported on its two end cells of the bottom
// layer, loaded on its two middle cells of the top layer: what statics gives
// for the midspan deflection and for the load its bonds first reach the
// criterion at, next to Euler-Bernoulli beam theory with the catalogue's E and
// tensile strength. Measured at three depths, because a lattice's outermost
// cells sit inside the surface -- at (n - 1) / n of the half-depth for n cells
// -- and that is what the survey (beam theory) and the lattice differ by.
struct BoxBeam {
    std::unique_ptr<LatticeAsset> asset;
    ActiveMatter matter;
    double density{};
};

BoxBeam boxBeam(MaterialPreset preset, unsigned nx, unsigned ny, unsigned nz, double cell) {
    BoxBeam beam;
    const MaterialDefinition definition = makeReferenceMaterial(preset, 0);
    const CompiledBrittleMaterial compiled =
        withFailureLaw(compileElasticLatticeReference(definition, cell, 2), definition, cell, 2);
    beam.asset = std::make_unique<LatticeAsset>(generateBoxLattice({nx, ny, nz, cell, 2}, compiled));
    beam.density = definition.density_kg_m3;
    beam.matter.asset = beam.asset.get();
    beam.matter.material = compiled;
    for (const LatticeNodeRest &node : beam.asset->nodes) {
        ActiveNodeState state{};
        state.position_world_m = node.local_position_m;
        state.previous_position_world_m = node.local_position_m;
        state.mass_kg = node.represented_volume_m3 * definition.density_kg_m3;
        beam.matter.nodes.push_back(state);
        beam.matter.reference_positions_world_m.push_back(node.local_position_m);
    }
    beam.matter.bonds.assign(beam.asset->bonds.size(), ActiveBondState{});
    return beam;
}

struct BeamAnswer {
    double deflection_m{}, theory_deflection_m{};
    double failure_load_n{}, theory_failure_load_n{};
    std::string stop;
};

BeamAnswer simplySupported(unsigned nx, unsigned ny, unsigned nz, double cell, double load_n) {
    BoxBeam beam = boxBeam(MaterialPreset::Oak, nx, ny, nz, cell);
    const std::size_t count = beam.matter.nodes.size();
    double low_y = 1e30, high_y = -1e30, low_x = 1e30, high_x = -1e30;
    for (const Vec3 &p : beam.matter.reference_positions_world_m) {
        low_y = std::min(low_y, p.y); high_y = std::max(high_y, p.y);
        low_x = std::min(low_x, p.x); high_x = std::max(high_x, p.x);
    }
    SustainedLoadScene scene;
    scene.loads_n.assign(count, Vec3{});
    std::vector<std::uint32_t> loaded;
    double support_x = 0.0;
    for (std::uint32_t i = 0; i < count; ++i) {
        const Vec3 p = beam.matter.reference_positions_world_m[i];
        // No self-weight: the point load alone, so the answer scales with it.
        if (p.y < low_y + 0.5 * cell && (p.x < low_x + 0.5 * cell || p.x > high_x - 0.5 * cell)) {
            scene.supported_nodes.push_back(i);
            support_x = std::max(support_x, std::abs(p.x));
        }
        if (p.y > high_y - 0.5 * cell && std::abs(p.x) < 0.75 * cell) loaded.push_back(i);
    }
    for (const std::uint32_t i : loaded) scene.loads_n[i] = {0.0, -load_n / static_cast<double>(loaded.size()), 0.0};
    const SustainedLoadResult result = solveSustainedLoad(beam.matter, scene);
    // Midspan deflection: the mean of the bottom layer's middle cells.
    double sum = 0.0, n = 0.0;
    for (std::uint32_t i = 0; i < count; ++i) {
        const Vec3 p = beam.matter.reference_positions_world_m[i];
        if (p.y < low_y + 0.5 * cell && std::abs(p.x) < 0.75 * cell) { sum += result.displacement_m[i].y; n += 1.0; }
    }
    const MaterialDefinition oak = makeReferenceMaterial(MaterialPreset::Oak, 0);
    const double span = 2.0 * support_x;
    const double b = nz * cell, d = ny * cell;
    const double inertia = b * d * d * d / 12.0;
    BeamAnswer answer;
    answer.deflection_m = -sum / n;
    answer.theory_deflection_m = load_n * span * span * span / (48.0 * oak.young_modulus_pa * inertia);
    answer.failure_load_n = result.first_failure_ratio > 0.0 ? load_n / result.first_failure_ratio : 0.0;
    answer.theory_failure_load_n = oak.tensile_strength_pa * 2.0 * b * d * d / (3.0 * span);
    answer.stop = result.stop;
    return answer;
}

void staticsAgainstBeamTheory() {
    for (const unsigned depth : {3U, 4U, 6U}) {
        const double cell = 0.06 / depth;
        const unsigned nx = static_cast<unsigned>(std::lround(1.2 / cell));
        const unsigned nz = static_cast<unsigned>(std::lround(0.06 / cell));
        const auto started = std::chrono::steady_clock::now();
        const BeamAnswer a = simplySupported(nx, depth, nz, cell, 1000.0);
        const double ms = 1000.0 * std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::cout << "    60 x 60 mm oak, 1.2 m, " << depth << " cells deep (" << nx * depth * nz
                  << " cells): 1 kN at midspan deflects it " << a.deflection_m * 1000.0 << " mm (beam theory "
                  << a.theory_deflection_m * 1000.0 << " mm); its bonds reach the criterion at "
                  << a.failure_load_n / 1000.0 << " kN (beam theory at 90 MPa: " << a.theory_failure_load_n / 1000.0
                  << " kN); " << a.stop << " in " << ms << " ms" << std::endl;
    }
}

// ---- measurement: a heated beam, over time ------------------------------------
LiveMaterialState stateOf(const LiveWorld &world, const std::string &name) {
    for (const LiveMaterialState &m : world.materialStates())
        if (m.name == name) return m;
    throw std::runtime_error("no material state for " + name);
}

void measureAHeatedBeam() {
    const std::string bodies = box("pier left", "concrete", {0.16, 0.4, 0.3}, {-0.6, 0.2, 0.0}, true) + "," +
                               box("pier right", "concrete", {0.16, 0.4, 0.3}, {0.6, 0.2, 0.0}, true) + "," +
                               box("beam", "oak", {1.4, 0.06, 0.06}, {0.0, 0.43, 0.0}, false);
    auto world = openScene(scene(bodies), 0.02);
    stepFor(*world, 1.0);
    (void)world->heat("beam", 8000.0, 1200.0);
    const auto started = std::chrono::steady_clock::now();
    for (int k = 1; k <= 80; ++k) {
        stepFor(*world, 15.0);
        const LiveMaterialState m = stateOf(*world, "beam");
        std::cout << "    " << world->time_s() << " s: surface " << m.surface_k << " K, core " << m.core_k
                  << " K; bending " << m.section.bending * 100.0 << "%, compression " << m.section.compression * 100.0
                  << "%; burned " << m.section.consumed_m * 1000.0 << " mm, char " << m.section.char_m * 1000.0
                  << " mm; now " << m.remaining_m.x * 1000.0 << " x " << m.remaining_m.y * 1000.0 << " x "
                  << m.remaining_m.z * 1000.0 << " mm, " << m.mass_kg << " kg, " << m.cells << " cells ("
                  << m.cells_burned << " burned), bonds tension mean " << m.bond_tension_mean << " min "
                  << m.bond_tension_min << ", revision " << m.revision << std::endl;
        if (!findPose(*world, "beam")) break;
    }
    const double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    std::cout << "    " << world->time_s() << " s of world in " << wall << " s of wall" << std::endl;
    for (const LiveBurnedAway &b : world->burnedAway())
        std::cout << "    burned away: " << b.name << " at " << b.time_s << " s, " << b.residue_kg << " kg left ("
                  << b.why << ")" << std::endl;
}

// ---- the owner's acceptance: two loaded beams, one heated ---------------------
//
// Two identical assemblies 3 m apart: an oak beam 1.4 x 0.06 x 0.1 m -- three
// cells deep, the least a lattice can bend -- on two concrete piers 1.04 m
// clear, under a 300 mm iron cube. A declared 8 kW heater goes into one beam.
// Followed through heating, the survey's offer, statics' answer, the pieces,
// cooling, and a second blow: the same iron ball dropped on both. Nothing here
// sets a time, a temperature or a strength at which anything happens.
struct Beams {
    std::unique_ptr<LiveWorld> world;
    std::string material;
};

std::string sphere(const std::string &name, const std::string &material, double diameter, Vec3 at) {
    char text[320];
    std::snprintf(text, sizeof text,
                  R"({"name":"%s","shape":"sphere","material":"%s","dimensions_m":[%g,%g,%g],"center_m":[%g,%g,%g]})",
                  name.c_str(), material.c_str(), diameter, diameter, diameter, at.x, at.y, at.z);
    return text;
}

// The assembly, and beside it -- clear of it -- a 120 mm iron ball (7 kg) on a
// concrete pedestal, for the second blow.
std::string assembly(const std::string &tag, double x, const std::string &material) {
    return box(tag + " pier left", "concrete", {0.16, 0.4, 0.3}, {x - 0.6, 0.2, 0.0}, true) + "," +
           box(tag + " pier right", "concrete", {0.16, 0.4, 0.3}, {x + 0.6, 0.2, 0.0}, true) + "," +
           box(tag + " beam", material, {1.4, 0.06, 0.1}, {x, 0.43, 0.0}, false) + "," +
           box(tag + " load", "iron", {0.3, 0.3, 0.3}, {x, 0.46 + 0.15, 0.0}, false) + "," +
           box(tag + " pedestal", "concrete", {0.2, 0.3, 0.2}, {x, 0.15, 0.9}, true) + "," +
           sphere(tag + " ball", "iron", 0.12, {x, 0.3 + 0.06, 0.9});
}

// Step as the room does: every break the world offers is answered by running
// it, so what the model says is what happens.
struct Answered {
    std::vector<std::string> broke;
};

void stepAnswering(LiveWorld &world, Answered &log) {
    for (int tries = 0; tries < 8; ++tries) {
        world.step(kDt);
        const std::vector<std::string> offered = world.breakable();
        for (const std::string &name : offered) {
            const std::size_t pieces = world.fracture(name);
            if (pieces > 1) log.broke.push_back(name);
        }
        if (!world.steppedBack()) return;
    }
}

struct Snapshot {
    double t{};
    LiveMaterialState state;
    bool present{};
    // What the thermal network says the body's matter weighs: the rigid body
    // must weigh the same.
    double network_kg{};
    std::string name;
};

Snapshot snapshotOf(const LiveWorld &world, const std::string &name) {
    Snapshot s;
    s.t = world.time_s();
    s.name = name;
    for (const LiveMaterialState &m : world.materialStates())
        if (m.name == name) { s.state = m; s.present = true; }
    if (world.thermo() != nullptr)
        if (const auto matter = world.thermo()->matter(name)) s.network_kg = matter->surface_kg + matter->core_kg;
    return s;
}

// The largest body descended from a name -- what is left of a beam.
std::optional<LiveBodyPose> largestOf(const LiveWorld &world, const std::string &name) {
    std::optional<LiveBodyPose> best;
    for (const LiveBodyPose &pose : world.poses()) {
        if (pose.name != name && pose.name.rfind(name + " piece ", 0) != 0) continue;
        if (!best || pose.mass_kg > best->mass_kg) best = pose;
    }
    return best;
}

std::size_t descendantsOf(const LiveWorld &world, const std::string &name) {
    std::size_t count = 0;
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name || pose.name.rfind(name + " piece ", 0) == 0) ++count;
    return count;
}

std::string describe(const Snapshot &s) {
    const LiveMaterialState &m = s.state;
    char text[640];
    std::snprintf(text, sizeof text,
                  "%.0f s: surface %.0f K core %.0f K; bending %.1f%% tension %.1f%% compression %.1f%%; bonds "
                  "tension mean %.3f min %.3f; burned %.2f mm, char %.1f mm; %.1f x %.1f x %.1f mm, %.3f kg, "
                  "inertia %.4f %.4f %.4f kg m2",
                  s.t, m.surface_k, m.core_k, 100.0 * m.section.bending, 100.0 * m.section.tension,
                  100.0 * m.section.compression, m.bond_tension_mean, m.bond_tension_min,
                  1000.0 * m.section.consumed_m, 1000.0 * m.section.char_m, 1000.0 * m.remaining_m.x,
                  1000.0 * m.remaining_m.y, 1000.0 * m.remaining_m.z, m.mass_kg, m.inertia_kg_m2.x,
                  m.inertia_kg_m2.y, m.inertia_kg_m2.z);
    return text;
}

struct Blow {
    double closing_m_s{}, threshold_m_s{};
    bool admitted{};
    std::size_t pieces_before{}, pieces_after{};
    std::string on;
};

struct BeamRun {
    std::string material;
    double power_w{};
    double offered_s{-1.0}, broke_s{-1.0};
    double offered_stress_mpa{}, offered_strength_mpa{}, offered_fraction{};
    std::size_t statics_asked{};
    double first_statics_pct{}, last_statics_pct{};
    LiveStatics statics;
    std::size_t pieces_after_heat{};
    // How far the heated beam's load had come down 3 s after the beam came
    // apart, from where it rested before the heat went on; -1 if it did not.
    double load_down_m{-1.0};
    bool cold_offered{}, cold_broke{};
    double wall_s{}, world_s{};
    Snapshot before, at_offer, last_whole, hot_end, cooled, cold_end;
    Blow blow_hot, blow_cold;
    double costliest_run_ms{}, runs_ms{};
    std::size_t runs{};
    // For tracing: every piece of the heated beam at the end of heating, and
    // every lattice run that took more than half a second.
    std::vector<std::string> pieces_seen, slow_runs;
};

// Drop a ball from 1.5 m onto what is left of a beam, by hand, and answer what
// it breaks.
Blow dropOn(LiveWorld &world, const std::string &ball, const std::string &beam, Answered &log) {
    Blow blow;
    blow.pieces_before = descendantsOf(world, beam);
    const std::optional<LiveBodyPose> target = largestOf(world, beam);
    if (!target || !world.grab(ball)) return blow;
    blow.on = target->name;
    // On a whole beam, 0.35 m along it from its middle: clear of the 300 mm load
    // on it. On a piece, square on the piece -- its load has gone.
    const bool whole = target->name == beam;
    world.moveHeld(target->position_m + Vec3{whole ? 0.35 : 0.0, 1.5, 0.0});
    for (int i = 0; i < 24; ++i) stepAnswering(world, log);
    world.forgetImpacts();
    world.release();
    for (int i = 0; i < static_cast<int>(3.0 / kDt); ++i) {
        stepAnswering(world, log);
        for (const LiveImpact &impact : world.impacts(0.5)) {
            if (impact.by != ball) continue;
            if (impact.struck != beam && impact.struck.rfind(beam + " piece ", 0) != 0) continue;
            if (impact.closing_speed_m_s > blow.closing_m_s) {
                blow.closing_m_s = impact.closing_speed_m_s;
                blow.threshold_m_s = impact.threshold_speed_m_s;
                blow.admitted = impact.would_break;
            }
        }
    }
    blow.pieces_after = descendantsOf(world, beam);
    return blow;
}

BeamRun twoBeams(const std::string &material, double heat_s, double cool_s, bool verbose,
                 double power_w = 8000.0) {
    BeamRun run;
    run.material = material;
    run.power_w = power_w;
    auto world = openScene(scene(assembly("hot", 0.0, material) + "," + assembly("cold", 3.0, material)), 0.02);
    Answered log;
    for (int i = 0; i < 240; ++i) stepAnswering(*world, log);
    const double load_y0 = findPose(*world, "hot load")->position_m.y;
    (void)world->heat("hot beam", power_w, heat_s);
    // Taken once the network holds it: cold, whole, as built.
    run.before = snapshotOf(*world, "hot beam");
    const auto started = std::chrono::steady_clock::now();
    const double t0 = world->time_s();
    bool heated_gone = false;
    const int steps = static_cast<int>(std::lround((heat_s + cool_s) / kDt));
    for (int i = 0; i < steps; ++i) {
        stepAnswering(*world, log);
        for (const LiveOverload &o : world->overloaded()) {
            if (o.name == "cold beam") run.cold_offered = true;
            if (o.name == "hot beam" && run.offered_s < 0.0) {
                run.offered_s = world->time_s() - t0;
                run.offered_stress_mpa = o.stress_pa / 1e6;
                run.offered_strength_mpa = o.strength_pa / 1e6;
                run.offered_fraction = o.capacity_fraction;
                run.at_offer = snapshotOf(*world, "hot beam");
            }
        }
        if (!heated_gone && findPose(*world, "hot beam") && i % 24 == 0) run.last_whole = snapshotOf(*world, "hot beam");
        if (!heated_gone && !findPose(*world, "hot beam")) {
            heated_gone = true;
            run.broke_s = world->time_s() - t0;
        }
        if (heated_gone && run.load_down_m < 0.0 && world->time_s() - t0 >= run.broke_s + 3.0)
            if (const auto load = findPose(*world, "hot load")) run.load_down_m = load_y0 - load->position_m.y;
        if (std::abs(world->time_s() - t0 - heat_s) < 0.5 * kDt) {
            if (const auto rest = largestOf(*world, "hot beam")) run.hot_end = snapshotOf(*world, rest->name);
            run.pieces_after_heat = descendantsOf(*world, "hot beam");
            for (const LiveBodyPose &pose : world->poses(true)) {
                if (pose.name.rfind("hot beam", 0) != 0) continue;
                char text[256];
                std::snprintf(text, sizeof text, "%s: %s, %zu cells, %.0f x %.0f x %.0f mm, %.3f kg at y %.3f",
                              pose.name.c_str(), pose.shape.c_str(), pose.cells_local_m.size(),
                              1000.0 * pose.dimensions_m.x, 1000.0 * pose.dimensions_m.y,
                              1000.0 * pose.dimensions_m.z, pose.mass_kg, pose.position_m.y);
                run.pieces_seen.push_back(text);
            }
        }
        if (verbose && i % static_cast<int>(60.0 / kDt) == 0 && findPose(*world, "hot beam"))
            std::cout << "      " << describe(snapshotOf(*world, "hot beam")) << std::endl;
    }
    run.wall_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    run.world_s = world->time_s() - t0;
    for (const std::string &name : log.broke) run.cold_broke = run.cold_broke || name == "cold beam";
    for (const LiveStatics &s : world->statics())
        if (s.name == "hot beam") run.statics = s;
    for (const LiveDelay &d : world->delays()) {
        if (std::string_view(d.kind) == "statics") {
            // lead_ms carries how near its bonds came, in percent of the criterion.
            if (run.statics_asked == 0) run.first_statics_pct = d.lead_ms;
            run.last_statics_pct = d.lead_ms;
            ++run.statics_asked;
        }
        if (std::string_view(d.kind) != "blocked") continue;
        ++run.runs;
        run.runs_ms += d.cost_ms;
        run.costliest_run_ms = std::max(run.costliest_run_ms, d.cost_ms);
        if (d.cost_ms > 500.0) {
            char text[256];
            std::snprintf(text, sizeof text, "%.2f s: %s, %.0f ms", d.at_s, d.object.c_str(), d.cost_ms);
            run.slow_runs.push_back(text);
        }
    }
    if (const auto rest = largestOf(*world, "hot beam")) run.cooled = snapshotOf(*world, rest->name);
    run.cold_end = snapshotOf(*world, "cold beam");

    // The second blow: the same 7 kg iron ball, from 1.5 m, on what is left of
    // each beam -- the cold one whole, the heated one cooled and as heat left it.
    run.blow_hot = dropOn(*world, "hot ball", "hot beam", log);
    run.blow_cold = dropOn(*world, "cold ball", "cold beam", log);
    return run;
}

void report(const BeamRun &r) {
    std::cout << "    " << r.material << " (" << r.power_w / 1000.0 << " kW): before heating " << describe(r.before)
              << std::endl;
    if (r.offered_s >= 0.0) {
        std::cout << "      offered as overloaded " << r.offered_s << " s into " << r.power_w / 1000.0
                  << " kW: bending " << r.offered_stress_mpa
                  << " MPa against " << r.offered_strength_mpa << " MPa (" << 100.0 * r.offered_fraction
                  << "% of its cold governing strength)" << std::endl;
        std::cout << "      at the offer: " << describe(r.at_offer) << std::endl;
    } else {
        std::cout << "      never offered as overloaded" << std::endl;
    }
    std::cout << "      statics asked " << r.statics_asked << " times (its bonds at " << r.first_statics_pct
              << "% of the criterion the first time, " << r.last_statics_pct << "% the last); last answer: "
              << (r.statics.stop.empty() ? std::string("none") : r.statics.stop) << " (its bonds at "
              << 100.0 * r.statics.first_failure_ratio << "% of the criterion, " << r.statics.bonds_removed
              << " bonds, " << r.statics.pieces << " pieces, " << r.statics.cost_ms << " ms)" << std::endl;
    if (r.broke_s >= 0.0)
        std::cout << "      broke " << r.broke_s << " s in; last whole: " << describe(r.last_whole)
                  << "; its block came down " << 1000.0 * r.load_down_m << " mm in the 3 s after" << std::endl;
    std::cout << "      end of heating: " << r.pieces_after_heat << " bodies of the heated beam; largest: "
              << describe(r.hot_end) << std::endl;
    std::cout << "      cooled: " << describe(r.cooled) << "; would keep "
              << 100.0 * r.cooled.state.section.bending_if_cooled << "% (tension side) cold" << std::endl;
    std::cout << "      the cold twin at the end: " << describe(r.cold_end) << std::endl;
    std::cout << "      second blow, 7 kg iron from 1.5 m: heated -> " << r.blow_hot.on << " at "
              << r.blow_hot.closing_m_s << " m/s against a " << r.blow_hot.threshold_m_s << " m/s bar, "
              << r.blow_hot.pieces_before << " -> " << r.blow_hot.pieces_after << " bodies; cold -> "
              << r.blow_cold.on << " at " << r.blow_cold.closing_m_s << " m/s against " << r.blow_cold.threshold_m_s
              << " m/s, " << r.blow_cold.pieces_before << " -> " << r.blow_cold.pieces_after << " bodies"
              << std::endl;
    for (const std::string &piece : r.pieces_seen) std::cout << "        piece " << piece << std::endl;
    for (const std::string &slow : r.slow_runs) std::cout << "        slow run " << slow << std::endl;
    std::cout << "      " << r.runs << " lattice runs, " << r.runs_ms << " ms in all, the costliest "
              << r.costliest_run_ms << " ms; " << r.world_s << " s of world in " << r.wall_s << " s of wall ("
              << r.world_s / r.wall_s << "x real time)" << std::endl;
}

// What must hold whatever the numbers come out as.
void checkOneState(const Snapshot &s, const std::string &what) {
    if (!s.present) return;
    const LiveMaterialState &m = s.state;
    // The rigid body weighs what the thermal network says is left -- to the
    // thousandth the host mirrors it at (LiveWorld::settleThermo asks the
    // network for masses that have moved by more than 1e-3 of themselves).
    require(near(m.mass_kg, s.network_kg, 1e-3 * s.network_kg) || s.network_kg == 0.0,
            what + ": the rigid body weighs what the network says is left");
    // Its box is the reference box less the burned depth on every face, to
    // within the 0.2 mm the shape is re-cut at.
    const double burned = m.section.consumed_m;
    for (const auto &[now, was] : {std::pair{m.remaining_m.x, m.reference_m.x}, std::pair{m.remaining_m.y, m.reference_m.y},
                                   std::pair{m.remaining_m.z, m.reference_m.z}})
        require(std::abs(now - (was - 2.0 * burned)) <= 2.0 * 2.0e-4 + 1e-9,
                what + ": what collides and is drawn is the box less what burned from every face");
    // Its inertia is the box that is left, with the matter left in it.
    const Vec3 d = m.remaining_m;
    require(near(m.inertia_kg_m2.x, m.mass_kg * (d.y * d.y + d.z * d.z) / 12.0, 0.01 * m.inertia_kg_m2.x),
            what + ": its inertia is the box that is left");
    // The lattice a run would get is the field the section integrates: the
    // mean of its bonds' tension factors and the section's, side by side.
    require(std::abs(m.bond_tension_mean - m.section.tension) < 0.05,
            what + ": its bonds carry the section's state");
}

void theOwnersTwoBeams() {
    const BeamRun oak = twoBeams("oak", 720.0, 360.0, true);
    report(oak);
    require(!oak.cold_offered && !oak.cold_broke, "the cold oak twin is never offered and never breaks");
    require(oak.offered_s > 0.0, "the heated oak beam is offered once its section cannot carry its load");
    // Offered when beam theory at its governing strength -- oak's 52 MPa in
    // compression, times what heat has left of that side -- passes the stress.
    require(near(oak.offered_strength_mpa, 52.0 * oak.offered_fraction, 1e-6),
            "the survey's strength is oak's governing 52 MPa times what is left");
    checkOneState(oak.at_offer, "oak at the offer");
    checkOneState(oak.last_whole, "oak last whole");
    if (oak.broke_s >= 0.0) {
        // Statics broke it only once its own criterion was reached.
        require(oak.statics.stop == "broke" && oak.statics.first_failure_ratio >= 1.0,
                "statics broke the heated beam only at its own criterion");
        require(oak.broke_s > oak.offered_s, "and not before the survey asked");
        // And what it carried came down. Asleep on the beam through the re-cuts,
        // the room's block once hung 0.43 m up over a beam that had come apart
        // into 56 pieces under it (LiveWorld::applyPending).
        require(oak.load_down_m > 0.1, "and the block it carried came down");
    }
    // Heat that weakens it without lighting it. At 3 kW for 15 minutes the
    // owner's beam only dries -- it releases no heat (measure: heater powers)
    // -- so what it loses it loses to temperature alone. Then it cools for 10
    // minutes and takes the same blow as its cold twin, from the state it is in.
    const BeamRun warm = twoBeams("oak", 900.0, 600.0, false, 3000.0);
    report(warm);
    require(warm.hot_end.state.section.char_m == 0.0 && warm.hot_end.state.section.consumed_m == 0.0,
            "3 kW dries the beam: it neither chars nor burns (the premise of this run)");
    require(!warm.cold_offered && !warm.cold_broke,
            "the cold twin of the 3 kW beam is never offered and never breaks");
    checkOneState(warm.hot_end, "oak at the end of 3 kW");
    checkOneState(warm.cooled, "oak cooled after 3 kW");
    require(warm.blow_hot.closing_m_s > 0.0 && warm.blow_cold.closing_m_s > 0.0, "the ball struck both beams");
    for (const std::string material : {"glass", "iron"}) {
        const BeamRun r = twoBeams(material, 720.0, 360.0, false);
        report(r);
        require(!r.cold_offered && !r.cold_broke, "the cold " + material + " twin is never offered and never breaks");
        checkOneState(r.hot_end, material + " at the end of heating");
        if (material == "glass")
            require(r.hot_end.state.section.bending == 1.0 && r.offered_s < 0.0,
                    "glass has no law: heat changes nothing it can carry");
    }
}

// ---- what burns leaves the shape ------------------------------------------------
//
// An oak slat 40 mm thick -- two cells -- bridging two concrete piers, a 60 mm
// iron cube resting on it, and an iron weight hanging under it on a fixing made
// on the slat's underside. Heated until it has burned away. What collides and is
// drawn is the slat's box less what burned from every face; the cube settles
// with it; the fixing lets go once more than half a cell has burned away from
// under it; and once the slat's load-bearing matter is gone the slat leaves the
// world, its residue leaves the thermal network on the ledger, and the cube
// falls through where it was.
void whatBurnsLeavesTheShape() {
    const std::string bodies = box("pier left", "concrete", {0.16, 0.3, 0.2}, {-0.34, 0.15, 0.0}, true) + "," +
                               box("pier right", "concrete", {0.16, 0.3, 0.2}, {0.34, 0.15, 0.0}, true) + "," +
                               box("slat", "oak", {0.84, 0.04, 0.2}, {0.0, 0.32, 0.0}, false) + "," +
                               box("cube", "iron", {0.06, 0.06, 0.06}, {0.0, 0.34 + 0.03, 0.0}, false) + "," +
                               box("weight", "iron", {0.06, 0.06, 0.06}, {0.0, 0.3 - 0.005 - 0.03, 0.0}, false);
    auto world = openScene(scene(bodies), 0.02);
    // The weight hangs on a fixing whose point is on the slat's underside.
    const unsigned fixing = world->fix("slat", "weight", {0.0, 0.3, 0.0}, {0.0, 1.0, 0.0}, 800.0, 800.0);
    require(fixing > 0, "the weight is fixed under the slat");
    stepFor(*world, 1.0);
    const double cube_before = poseOf(*world, "cube").position_m.y;
    const double slat_before = poseOf(*world, "slat").position_m.y;
    (void)world->heat("slat", 8000.0, 4000.0);
    double parted_at = -1.0, parted_gone_mm = 0.0, gone_at = -1.0;
    std::string parted_why;
    Snapshot last;
    double cube_at_last = cube_before, burned_at_last = 0.0;
    const double t0 = world->time_s();
    const auto started = std::chrono::steady_clock::now();
    for (int k = 0; k < static_cast<int>(4200.0 / kDt) && gone_at < 0.0; ++k) {
        stepOnce(*world);
        if (parted_at < 0.0)
            for (const LiveJoint &j : world->joints())
                if (j.id == fixing && !j.attached) {
                    parted_at = world->time_s() - t0;
                    parted_why = j.parted_because;
                    parted_gone_mm = 1000.0 * snapshotOf(*world, "slat").state.section.consumed_m;
                }
        if (!findPose(*world, "slat")) {
            gone_at = world->time_s() - t0;
            const thermo::Ledger at_gone = world->thermo()->ledger();
            std::cout << "    as it went: left " << at_gone.left_kg << " kg, joined " << at_gone.joined_kg
                      << " kg, mass residual " << at_gone.massResidualKg() << " kg" << std::endl;
            break;
        }
        if (k % 4800 == 0) {
            const thermo::Ledger now = world->thermo()->ledger();
            std::cout << "    " << world->time_s() - t0 << " s: left " << now.left_kg << " kg, joined "
                      << now.joined_kg << " kg, mass residual " << now.massResidualKg() << " kg" << std::endl;
        }
        if (k % 480 == 0) {
            last = snapshotOf(*world, "slat");
            cube_at_last = poseOf(*world, "cube").position_m.y;
            burned_at_last = last.state.section.consumed_m;
            checkOneState(last, "the burning slat");
        }
    }
    const double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    std::cout << "    last seen whole: " << describe(last) << std::endl;
    std::cout << "    the cube had settled " << (cube_before - cube_at_last) * 1000.0 << " mm with "
              << burned_at_last * 1000.0 << " mm burned from every face (twice that: "
              << 2000.0 * burned_at_last << " mm: the slat's top comes down by what burned from it, and the "
              << "slat by what burned from its underside, onto its piers)" << std::endl;
    (void)slat_before;
    std::cout << "    the fixing let go " << parted_at << " s in, with " << parted_gone_mm << " mm burned: " << parted_why
              << std::endl;
    std::cout << "    the slat burned away " << gone_at << " s in";
    double residue = 0.0;
    for (const LiveBurnedAway &b : world->burnedAway()) {
        std::cout << " (" << b.name << ": " << b.residue_kg << " kg of residue left with it; " << b.why << ")";
        if (b.name == "slat") residue += b.residue_kg;
    }
    std::cout << "; " << world->time_s() - t0 << " s of world in " << wall << " s of wall" << std::endl;
    require(parted_at > 0.0 && parted_why.find("burned away") != std::string::npos,
            "the fixing let go of matter that burned away from under it, and said so");
    require(parted_gone_mm > 10.0 - 0.5, "and not before more than half a cell (10 mm) had gone");
    require(std::abs((cube_before - cube_at_last) - 2.0 * burned_at_last) < 0.0015,
            "the cube settled with the slat: twice the burned depth, to within a millimetre and a half");
    require(gone_at > 0.0, "the slat burned away");
    // Then the cube falls through where it was.
    stepFor(*world, 1.0);
    const LiveBodyPose cube = poseOf(*world, "cube");
    std::cout << "    a second later the cube is at y = " << cube.position_m.y << " m" << std::endl;
    require(cube.position_m.y < 0.1, "and the cube fell through where the slat had been");
    const thermo::Ledger ledger = world->thermo()->ledger();
    std::cout << "    ledger: residual " << ledger.residualJ() << " J on " << ledger.storedJ() << " J stored; "
              << ledger.left_kg << " kg left the network with bodies" << std::endl;
    require(std::abs(ledger.residualJ()) < 1e-6 * std::max(1.0, std::abs(ledger.storedJ())), "the ledger closes");
    require(ledger.left_kg > 0.0, "and what the slat still held left it as a counted crossing");
    // Once. Nothing else leaves this network, so what left is the slat's
    // residue: the same lump's mass read twice, which only the order of a sum
    // can tell apart. Before ThermoWorld forgot a departed body's shape, a hot
    // neighbour brought the slat back for the next refresh to take out again,
    // and 0.315 kg left for 0.158 kg of residue.
    require(near(ledger.left_kg, residue, 1e-9 * residue), "and it left once: what left is its residue");
}

// ---- a piece whose cells burn away is rebuilt from the rest ---------------------
//
// A join of two boxes is a hull from the start: its shape is its cells. Burned
// long enough for its outer cells to go, it is rebuilt from the cells it has
// left, keeps its name while they still join, weighs what the network says, and
// its box of cells is smaller.
void aPieceIsRebuiltFromTheCellsItHasLeft() {
    const std::string bodies =
        box("stand", "concrete", {0.3, 0.1, 0.3}, {0.0, 0.05, 0.0}, true) + "," +
        R"({"name":"lump","shape":"box","material":"oak","dimensions_m":[0.12,0.12,0.12],"center_m":[0,0.16,0],"join":"lump"},)"
        R"({"name":"lump top","shape":"box","material":"oak","dimensions_m":[0.08,0.04,0.08],"center_m":[0,0.24,0],"join":"lump"})";
    auto world = openScene(scene(bodies), 0.02);
    stepFor(*world, 1.0);
    const LiveBodyPose before = poseOf(*world, "lump");
    require(before.shape == "hull", "a join is drawn and collides as its cells");
    (void)world->heat("lump", 8000.0, 3000.0);
    const double t0 = world->time_s();
    std::optional<Snapshot> reformed;
    for (int k = 0; k < static_cast<int>(3000.0 / kDt); ++k) {
        stepOnce(*world);
        if (k % 240 != 0 || !findPose(*world, "lump")) continue;
        const Snapshot s = snapshotOf(*world, "lump");
        if (s.state.cells_burned > 0) { reformed = s; break; }
    }
    require(reformed.has_value(), "its outer cells burned away within 50 minutes of 8 kW");
    const LiveBodyPose after = poseOf(*world, "lump");
    std::cout << "    " << world->time_s() - t0 << " s in: " << reformed->state.cells_burned << " of "
              << reformed->state.cells + reformed->state.cells_burned << " cells gone, revision "
              << reformed->state.revision << "; its cells' box " << before.dimensions_m.x * 1000.0 << " x "
              << before.dimensions_m.y * 1000.0 << " x " << before.dimensions_m.z * 1000.0 << " mm -> "
              << after.dimensions_m.x * 1000.0 << " x " << after.dimensions_m.y * 1000.0 << " x "
              << after.dimensions_m.z * 1000.0 << " mm; " << after.mass_kg << " kg (the network: "
              << reformed->network_kg << " kg)" << std::endl;
    require(after.revision > 0 && after.shape == "hull", "it was rebuilt from the cells it has left");
    // The first cells to go are corners -- a corner cell loses matter from
    // three faces -- so its box of cells need not be smaller yet; its cells are.
    std::size_t cells_before = 0, cells_after = 0;
    (void)before;
    for (const LiveMaterialState &m : world->materialStates())
        if (m.name == "lump") { cells_after = m.cells; cells_before = m.cells + m.cells_burned; }
    require(cells_after > 0 && cells_after < cells_before, "and it has fewer cells than it had");
    require(near(after.mass_kg, reformed->network_kg, 0.02 * reformed->network_kg),
            "and it weighs what the network says is left");
}

// ---- measurement: which heater lights the beam ---------------------------------
//
// Whether a heater lights the beam is the model's answer, not the test's. This
// finds, for the owner's loaded beam, what each power does in 900 s: how hot
// its surface gets, whether its dry wood burns (heat released) or only dries,
// how far its section falls, what the survey and statics say, and what it
// keeps once it has cooled for 600 s.
void measureHeaterPowers() {
    for (const double power : {2000.0, 3000.0, 4000.0, 5000.0, 6000.0}) {
        auto world = openScene(scene(assembly("hot", 0.0, "oak")), 0.02);
        Answered log;
        for (int i = 0; i < 240; ++i) stepAnswering(*world, log);
        (void)world->heat("hot beam", power, 900.0);
        const double t0 = world->time_s();
        double hottest = 0.0, released = 0.0, lowest_bending = 1.0, lowest_compression = 1.0, offered = -1.0;
        const auto started = std::chrono::steady_clock::now();
        for (int i = 0; i < static_cast<int>(1500.0 / kDt) && findPose(*world, "hot beam"); ++i) {
            stepAnswering(*world, log);
            if (i % 24 != 0) continue;
            for (const thermo::BodyHeat &b : world->thermo()->bodies())
                if (b.body == "hot beam") {
                    hottest = std::max(hottest, b.temperature_k);
                    released = std::max(released, b.heat_release_w);
                }
            const Snapshot s = snapshotOf(*world, "hot beam");
            lowest_bending = std::min(lowest_bending, s.state.section.bending);
            lowest_compression = std::min(lowest_compression, s.state.section.bending_compression);
            for (const LiveOverload &o : world->overloaded())
                if (o.name == "hot beam" && offered < 0.0) offered = world->time_s() - t0;
        }
        const double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::cout << "    " << power / 1000.0 << " kW for 900 s: surface up to " << hottest << " K, heat released up to "
                  << released << " W (" << (released > 0.0 ? "it burned" : "it only dried") << "); bending down to "
                  << 100.0 * lowest_bending << "%, compression side to " << 100.0 * lowest_compression << "%; ";
        if (offered >= 0.0) std::cout << "offered " << offered << " s in; ";
        if (!log.broke.empty()) std::cout << "broke (" << log.broke.front() << "); ";
        if (findPose(*world, "hot beam")) {
            const Snapshot s = snapshotOf(*world, "hot beam");
            std::cout << "after 600 s cooling: surface " << s.state.surface_k << " K, core " << s.state.core_k
                      << " K, bending " << 100.0 * s.state.section.bending << "% (keeps "
                      << 100.0 * s.state.section.bending_if_cooled << "% cold), compression side "
                      << 100.0 * s.state.section.bending_compression << "%";
        }
        for (const LiveStatics &st : world->statics())
            if (st.name == "hot beam")
                std::cout << "; statics: " << st.stop << " at " << 100.0 * st.first_failure_ratio << "%";
        std::cout << " [" << wall << " s wall]" << std::endl;
    }
}

// ---- an answer goes with its load --------------------------------------------------
//
// Statics' answer is about a load. Once nothing rests on the body it was about,
// it is not "under its load" any more, and the answer goes. Measured in the page
// before this: a block fell through a beam that had not broken, and the Heat
// panel went on saying "under its load: holds".
void anAnswerGoesWithItsLoad() {
    const std::string bodies = box("left pier", "iron", {0.2, 0.4, 0.3}, {-0.6, 0.2, 0.0}, true) + "," +
                               box("right pier", "iron", {0.2, 0.4, 0.3}, {0.6, 0.2, 0.0}, true) + "," +
                               box("shelf", "concrete", {1.4, 0.1, 0.3}, {0.0, 0.45, 0.0}, false) + "," +
                               box("crate", "iron", {0.45, 0.45, 0.45}, {0.0, 0.5 + 0.225, 0.0}, false);
    auto world = openScene(scene(bodies), 0.05);
    stepFor(*world, 2.0);
    const std::vector<std::string> offered = world->breakable();
    require(std::find(offered.begin(), offered.end(), "shelf") != offered.end(),
            "a stone shelf under a 717 kg crate is asked about");
    const std::size_t pieces = world->fracture("shelf");
    const auto answer = [&]() -> std::optional<LiveStatics> {
        for (const LiveStatics &s : world->statics())
            if (s.name == "shelf") return s;
        return std::nullopt;
    };
    require(pieces == 1 && answer() && answer()->stop == "held", "statics held it, and says so");
    std::cout << "    under the crate: statics " << answer()->stop << ", its bonds at "
              << 100.0 * answer()->first_failure_ratio << "% of the criterion" << std::endl;
    require(world->grab("crate"), "the crate is taken hold of");
    world->moveHeld(poseOf(*world, "crate").position_m + Vec3{0.0, 0.6, 0.0});
    stepFor(*world, 1.0);
    std::cout << "    the crate lifted off: " << (answer() ? "the answer is still there" : "no answer about its load")
              << std::endl;
    require(!answer(), "with nothing on it, there is no answer about what it carries");
}

// ---- the owner's room: answers not waited for -----------------------------------
//
// The two beams as the room builds them: the yard's cells are 40 mm, so the
// owner's 60 x 100 mm beam is two cells, 80 x 80 mm, and the 300 mm block a
// 320 mm, 258 kg cube. And answered as the room answers: it starts a fracture
// without waiting, steps on in batches of four, and collects the answer when it
// is ready. Measured in the page before the fix: a body waiting on statics was
// held -- its velocity zeroed and it woken after every step -- each held answer
// left the block about a millimetre deeper in the beam (4.1 to 9.3 mm over
// eight), and then the block fell through a beam that had not broken. With that
// fixed, the beam's re-cuts did it more slowly: woken at every cut to settle
// onto a narrower top, the block rolled a little further each time it was
// awake -- 0.14 degrees before the first cut, 1.9 after eight, 9.4 after
// eighteen -- and then off a beam that had not broken. What rests on a burning
// box now comes down with its top, exactly and asleep (planRecession).
void theRoomWithAnswersNotWaitedFor() {
    const auto pair = [](const std::string &tag, double x) {
        return box(tag + " pier left", "concrete", {0.16, 0.4, 0.32}, {x - 0.6, 0.2, 0.0}, true) + "," +
               box(tag + " pier right", "concrete", {0.16, 0.4, 0.32}, {x + 0.6, 0.2, 0.0}, true) + "," +
               box(tag + " beam", "oak", {1.4, 0.08, 0.08}, {x, 0.44, 0.0}, false) + "," +
               box(tag + " load", "iron", {0.32, 0.32, 0.32}, {x, 0.48 + 0.16, 0.0}, false);
    };
    auto world = openScene(scene(pair("hot", 0.0) + "," + pair("cold", 3.0)), 0.04);
    stepFor(*world, 2.0);
    // How far the block sits into the beam: the rigid solver's resting allowance.
    const auto sunk = [&]() {
        const LiveBodyPose beam = poseOf(*world, "hot beam");
        const LiveBodyPose load = poseOf(*world, "hot load");
        return (beam.position_m.y + 0.5 * beam.dimensions_m.y) - (load.position_m.y - 0.5 * load.dimensions_m.y);
    };
    const double resting = sunk();
    const double load_y0 = poseOf(*world, "hot load").position_m.y;
    (void)world->heat("hot beam", 8000.0, 900.0);
    const double t0 = world->time_s();
    double deepest = resting, broke_s = -1.0, tilted = 0.0;
    std::size_t asked = 0;
    bool cold_asked = false;
    const auto started = std::chrono::steady_clock::now();
    for (int batch = 0; world->time_s() - t0 < 1000.0; ++batch) {
        for (int k = 0; k < 4; ++k) world->step(kDt);
        if (world->fracturePending() && world->fractureReady()) (void)world->finishFracture();
        if (!world->fracturePending()) {
            const std::vector<std::string> offered = world->breakable();
            if (!offered.empty() && world->beginFracture(offered.front())) {
                ++asked;
                cold_asked = cold_asked || offered.front().rfind("cold", 0) == 0;
            }
        }
        if (!findPose(*world, "hot beam")) {
            broke_s = world->time_s() - t0;
            break;
        }
        if (batch % 15 == 0) {
            deepest = std::max(deepest, sunk());
            // And level: how far its up has turned from the world's. Dropped onto
            // the beam at every re-cut instead of coming down with it, it had
            // turned 9.4 degrees, 28 mm to one side, when it rolled off.
            const double *q = poseOf(*world, "hot load").orientation_wxyz;
            const double up_y = 1.0 - 2.0 * (q[1] * q[1] + q[3] * q[3]);
            tilted = std::max(tilted, std::acos(std::clamp(up_y, -1.0, 1.0)) * 180.0 / 3.14159265358979323846);
        }
    }
    stepFor(*world, 3.0);
    const double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    std::optional<LiveStatics> last;
    for (const LiveStatics &s : world->statics())
        if (s.name == "hot beam") last = s;
    const double load_now = poseOf(*world, "hot load").position_m.y;
    std::cout << "    " << asked << " answers started without waiting; the block rested " << 1000.0 * resting
              << " mm into the beam and was never more than " << 1000.0 * deepest << " mm into it while the beam was whole"
              << std::endl;
    std::cout << "    " << (broke_s >= 0.0 ? "broke " + std::to_string(broke_s) + " s in" : std::string("did not break"))
              << "; statics' last answer: " << (last ? last->stop : std::string("none")) << " (its bonds at "
              << (last ? 100.0 * last->first_failure_ratio : 0.0) << "% of the criterion, "
              << (last ? last->bonds_removed : 0) << " bonds, " << (last ? last->pieces : 0) << " pieces); the block came down "
              << 1000.0 * (load_y0 - load_now) << " mm; " << world->time_s() - t0 << " s of world in " << wall << " s"
              << std::endl;
    // The block may sit up to a millimetre deeper than it rested before anything
    // was asked: a re-cut takes 0.2 mm off each face of the beam and the block
    // comes down onto what is left. Held bodies drove it 5.2 mm deeper.
    std::cout << "    the block turned at most " << tilted << " degrees from level while the beam was whole"
              << std::endl;
    require(deepest - resting < 1.0e-3, "the block stays where it rests while statics is asked and holds");
    // Two degrees: well past a resting block's jitter, a fifth of the tilt that
    // rolled it off.
    require(tilted < 2.0, "and it stays level on the beam as the beam burns");
    require(!cold_asked, "the cold twin is never asked about");
    if (broke_s >= 0.0) {
        require(last && last->stop == "broke" && last->first_failure_ratio >= 1.0,
                "the beam broke only when statics said its bonds had reached the criterion");
        require(load_y0 - load_now > 0.1, "and the block came down when it broke");
    } else {
        require(!last || last->stop != "broke", "statics did not say it broke");
        require(load_y0 - load_now < 0.05, "a beam that did not break still carries its block");
    }
}

}  // namespace

int main(int argc, char **argv) {
    // What every push can afford is banjo_thermal_geometry_tests. The two that
    // take minutes -- the owner's beams and the heater powers -- are
    // banjo_thermal_geometry_long_tests, the same source built with
    // BANJO_THERMAL_GEOMETRY_LONG, labelled long in CMakeLists.txt and run by
    // .github/workflows/long-physics.yml. A test's name on the command line
    // runs that test, whichever binary it is.
#ifdef BANJO_THERMAL_GEOMETRY_LONG
    constexpr bool kTakesMinutes = true;
#else
    constexpr bool kTakesMinutes = false;
#endif
    struct Test {
        std::string_view name;
        std::function<void()> run;
        bool takes_minutes;
    };
    const std::vector<Test> tests{
        {"the field is one state", theFieldIsOneState, false},
        {"statics against beam theory", staticsAgainstBeamTheory, false},
        {"measure: a heated beam", measureAHeatedBeam, false},
        {"the owner's two beams", theOwnersTwoBeams, true},
        {"what burns leaves the shape", whatBurnsLeavesTheShape, false},
        {"a piece is rebuilt from the cells it has left", aPieceIsRebuiltFromTheCellsItHasLeft, false},
        {"measure: heater powers", measureHeaterPowers, true},
        {"an answer goes with its load", anAnswerGoesWithItsLoad, false},
        {"the owner's room, answers not waited for", theRoomWithAnswersNotWaitedFor, true},
    };
    unsigned failures = 0, ran = 0;
    for (const Test &test : tests) {
        const std::string_view name = test.name;
        if (argc > 1 ? std::string_view(argv[1]) != name : test.takes_minutes != kTakesMinutes) continue;
        ++ran;
        const auto started = std::chrono::steady_clock::now();
        try {
            test.run();
            std::cout << "[PASS] " << name;
        } catch (const std::exception &error) {
            ++failures;
            std::cout << "[FAIL] " << name << ": " << error.what();
        }
        std::cout << " (" << std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count()
                  << " s)" << std::endl;
    }
    std::cout << ran - failures << '/' << ran << " tests passed" << std::endl;
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
