// Physics check (a) for the energy-scaled failure law: a pre-cracked strip in
// tension, with two answers known in advance.
//
// Scene. A rectangular strip of uniform cubic cells, clamped along its top and
// bottom faces (the outermost node layer of each is pinned by giving it zero
// mass, which is how the XPBD solve expresses an infinite mass) and released
// from rest in a uniform tensile strain e0 along y. A slit of length a0 is cut
// on the mid-height plane by removing every bond that crosses it left of a0.
// Nothing else acts: no gravity, no contact, no damping, no prescribed motion
// after t = 0. The stored elastic energy of the strained strip is the only
// thing driving the crack.
//
// Known answer 1 (energy). The crack consumes Gc for every unit of area it
// opens. The probe reports the measured dissipation per unit crack area over
// the interval in which the tip advances, and the full ledger it comes from:
// the elastic energy the strip loses, the part that becomes kinetic energy of
// the two relaxing halves, and the part the criterion removes.
//
// Known answer 2 (speed). No crack in an elastic solid can outrun the Rayleigh
// wave, and a real mode-I crack in a brittle solid stays well below it (branching
// intervenes near 0.6 c_R; Freund, Dynamic Fracture Mechanics, ch. 7). The probe
// reports the tip speed against this lattice's own c_R, computed from the cubic
// constants the criterion's derivation uses (C11 = E sum n_x^4 / m,
// C12 = C44 = E sum n_x^2 n_y^2 / m) rather than from the material's nominal E.
//
// The strip geometry is held in metres and only the cell size changes between
// runs, so the loading is identical at every resolution and the discretisation
// is the only difference. The tensile strain is set from a requested energy
// release rate: e0 = sqrt(2 G / (C11 H)), and the probe refuses to run if that
// strain would break the bulk on its own (e0 >= the removal stretch), because
// then there is no crack to measure.

#include "fracture/BondFailure.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using nlohmann::json;

MaterialPreset presetFromName(const std::string &name) {
    if (name == "glass") return MaterialPreset::Glass;
    if (name == "oak") return MaterialPreset::Oak;
    if (name == "iron") return MaterialPreset::Iron;
    if (name == "concrete") return MaterialPreset::Concrete;
    if (name == "ceramic") return MaterialPreset::Ceramic;
    if (name == "ice") return MaterialPreset::Ice;
    throw std::invalid_argument("unknown material: " + name);
}

struct Options {
    MaterialPreset material{MaterialPreset::Glass};
    double length_m{0.40};
    double height_m{0.10};
    double thickness_m{0.02};
    double cell_m{0.005};
    unsigned horizon{2};
    double precrack_m{0.10};
    double energy_release_ratio{1.6};  // G / Gc requested
    double dt_factor{0.5};
    unsigned iterations{1};
    double window_us{300.0};
    std::string law{"energy-scaled"};
    std::string report;
};

[[nodiscard]] double storedEnergy(const ActiveMatter &matter) {
    double energy = 0.0;
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
        if (!matter.bonds[i].alive) continue;
        const BondRest &rest = matter.asset->bonds[i];
        if (rest.compliance <= 0.0) continue;
        const double extension = length(matter.nodes[rest.node_b].position_world_m -
                                        matter.nodes[rest.node_a].position_world_m) -
                                 rest.rest_length_m;
        energy += 0.5 * extension * extension / rest.compliance;
    }
    return energy;
}

[[nodiscard]] double kineticEnergy(const ActiveMatter &matter) {
    double energy = 0.0;
    for (const ActiveNodeState &node : matter.nodes)
        energy += 0.5 * node.mass_kg * lengthSquared(node.velocity_m_s);
    return energy;
}

int run(const Options &o) {
    MaterialDefinition material = makeReferenceMaterial(o.material, 971);
    material.strength_variation = 0.0;  // a clean crack path, not a flaw study
    material.failure_law = parseBondFailureLaw(o.law);
    const CompiledBrittleMaterial compiled = withFailureLaw(
        compileElasticLatticeReference(material, o.cell_m, o.horizon), material, o.cell_m, o.horizon);
    const LatticeHorizonGeometry g = latticeHorizonGeometry(o.horizon);

    // This lattice's own elastic constants and wave speeds; the nominal E is
    // not the lattice's modulus (docs/criterion-energy-scaled-checkpoint.md).
    const double m = static_cast<double>(o.horizon);
    const double c11 = material.young_modulus_pa * g.sum_nx4 / m;
    const double c44 = material.young_modulus_pa * g.sum_nx2ny2 / m;
    const double c12 = c44;  // central-force lattices obey the Cauchy relation
    const double rho = material.density_kg_m3;
    const double poisson = c12 / (c11 + c12);
    const double shear_speed = std::sqrt(c44 / rho);
    const double dilatational_speed = std::sqrt(c11 / rho);
    // Isotropic Rayleigh approximation on the lattice's own shear speed. The
    // lattice is cubic, not isotropic (Zener A = 2 C44 / (C11 - C12)), so this
    // is an estimate; it is quoted with the anisotropy so the reader can judge.
    const double zener = 2.0 * c44 / (c11 - c12);
    const double rayleigh_speed = shear_speed * (0.862 + 1.14 * poisson) / (1.0 + poisson);
    // The lattice's own Young modulus, which is not the material's nominal E:
    // the compliance rule makes the lattice stiffer than the number it was fed.
    const double young_effective = (c11 - c12) * (c11 + 2.0 * c12) / (c11 + c12);

    // Loading. The strip starts in the uniaxial-STRESS state the grips and the
    // free side faces hold it in, so it begins in equilibrium and does not ring:
    // e_yy = e0, e_xx = e_zz = -nu e0. Its energy density is then
    // W = E_eff e0^2 / 2, and since the material behind the crack unloads
    // completely while the material ahead carries W over the full height, the
    // energy release rate is G = W H. Inverting that for e0:
    const double target_g = o.energy_release_ratio * material.fracture_energy_j_m2;
    const double strain = std::sqrt(2.0 * target_g / (young_effective * o.height_m));
    const double removal_stretch = compiled.damage_end_stretch;
    if (!(strain < removal_stretch)) {
        std::cerr << "[refused] the loading strain " << strain << " reaches the removal stretch "
                  << removal_stretch << ": the bulk would break with no crack. Use finer cells "
                     "(the removal stretch grows as h^-1/2) or a smaller --energy-ratio.\n";
        return 2;
    }

    BoxLatticeLayout layout{};
    const LatticeAsset asset = generateBoxTileLattice(
        {{o.length_m, o.height_m, o.thickness_m}, o.cell_m, o.horizon}, compiled, &layout);

    // Build the active state by hand: at rest, affinely strained in y, with the
    // outermost y layers pinned. Reference positions stay unstrained, so the
    // bonds see the strain as their own extension.
    ActiveMatter matter;
    matter.body_id = 1;
    matter.asset = &asset;
    matter.material = compiled;
    matter.bonds.resize(asset.bonds.size());
    matter.nodes.reserve(asset.nodes.size());
    matter.reference_positions_world_m.reserve(asset.nodes.size());
    const double node_mass = o.cell_m * o.cell_m * o.cell_m * material.density_kg_m3;
    std::size_t pinned = 0;
    for (const LatticeNodeRest &rest : asset.nodes) {
        const Vec3 reference = rest.local_position_m;
        const Vec3 strained{reference.x * (1.0 - poisson * strain), reference.y * (1.0 + strain),
                            reference.z * (1.0 - poisson * strain)};
        const bool grip = rest.grid.y == 0 || rest.grid.y + 1 == static_cast<int>(layout.ny);
        if (grip) ++pinned;
        matter.nodes.push_back({strained, strained, Vec3{}, grip ? 0.0 : node_mass, Vec3{}});
        matter.reference_positions_world_m.push_back(reference);
    }

    // The slit: every bond crossing the mid-height plane left of a0.
    const int mid_layer = static_cast<int>(layout.ny) / 2;
    const double left_edge = -0.5 * o.length_m;
    const auto crossesMidPlane = [&](const BondRest &bond) {
        return (asset.nodes[bond.node_a].grid.y < mid_layer) !=
               (asset.nodes[bond.node_b].grid.y < mid_layer);
    };
    const auto bondCentreX = [&](const BondRest &bond) {
        return 0.5 * (asset.nodes[bond.node_a].local_position_m.x +
                      asset.nodes[bond.node_b].local_position_m.x);
    };
    std::vector<std::uint32_t> plane_bonds;
    std::size_t precut = 0;
    for (std::uint32_t i = 0; i < asset.bonds.size(); ++i) {
        if (!crossesMidPlane(asset.bonds[i])) continue;
        plane_bonds.push_back(i);
        if (bondCentreX(asset.bonds[i]) - left_edge < o.precrack_m) {
            matter.bonds[i].alive = false;
            matter.bonds[i].damage = 1.0;
            matter.bonds[i].failure_mode = BondFailureMode::Tension;
            ++precut;
        }
    }
    matter.connectivity_dirty = true;
    if (precut == 0) throw std::runtime_error("the pre-crack removed no bonds");

    const LatticeResolutionLimit limit = measureLatticeResolutionLimit(asset, compiled);
    const double dt = o.dt_factor * limit.explicit_substep_limit_s;
    const auto steps = static_cast<std::uint64_t>(std::llround(o.window_us * 1e-6 / dt));

    BrittleSolverSettings settings;
    settings.substeps = 1;
    settings.constraint_iterations = o.iterations;
    settings.support_enabled = false;
    settings.use_support_plane = false;
    const BrittleBondSolver solver(settings);

    // The crack front, and the criterion's own measure of the area it opened.
    // The derivation says N_100 / h^2 bonds cross each unit of a {100} plane, so
    // a count of broken mid-plane bonds IS an area, in exactly the accounting
    // the threshold was derived from; it does not depend on guessing where a
    // ragged front lies. The tip position is reported alongside it.
    struct Front {
        double tip_m;
        std::size_t plane_broken, off_plane_broken;
    };
    const auto measureFront = [&]() {
        Front f{o.precrack_m, 0, 0};
        for (const std::uint32_t i : plane_bonds) {
            if (matter.bonds[i].alive) continue;
            ++f.plane_broken;
            f.tip_m = std::max(f.tip_m, bondCentreX(asset.bonds[i]) - left_edge);
        }
        for (std::size_t i = 0; i < matter.bonds.size(); ++i)
            if (!matter.bonds[i].alive) ++f.off_plane_broken;
        f.off_plane_broken -= f.plane_broken;
        return f;
    };
    const auto areaOf = [&](std::size_t plane_bonds_broken) {
        return static_cast<double>(plane_bonds_broken) * o.cell_m * o.cell_m / g.crossings_100;
    };

    struct Sample {
        double t_s, tip_m, elastic_j, kinetic_j, dissipated_j;
        std::size_t broken, plane_broken, off_plane_broken;
    };
    std::vector<Sample> history;
    const double elastic_0 = storedEnergy(matter);
    double dissipated = 0.0;
    {
        const Front f = measureFront();
        history.push_back({0.0, f.tip_m, elastic_0, kineticEnergy(matter), 0.0, precut,
                           f.plane_broken, f.off_plane_broken});
    }
    // The solver's own energy leak, measured on this scene while the crack is
    // still standing still: XPBD damps the modes it cannot resolve, and at
    // dt_factor 0.5 the fastest bond mode has omega dt = 1. This belongs to the
    // lane, not to the criterion, and the energy check is stated against it.
    double quiet_leak_per_us = 0.0;
    double quiet_until_s = 0.0;

    const auto wall_start = std::chrono::steady_clock::now();
    for (std::uint64_t step = 1; step <= steps; ++step) {
        const MaterialStepStats stats = solver.step(matter, dt, Vec3{}, nullptr, {});
        dissipated += stats.unassigned_bond_removal_energy_j;
        const Front f = measureFront();
        const double t = static_cast<double>(step) * dt;
        const double elastic = storedEnergy(matter);
        const double kinetic = kineticEnergy(matter);
        if (stats.total_broken_bonds == precut && t > 0.0) {
            quiet_until_s = t;
            quiet_leak_per_us = (elastic_0 - elastic - kinetic) / elastic_0 / (t * 1e6);
        }
        history.push_back({t, f.tip_m, elastic, kinetic, dissipated, stats.total_broken_bonds,
                           f.plane_broken, f.off_plane_broken});
    }
    const double wall_s = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - wall_start).count();

    // The steady interval: from the moment the tip has left the pre-crack by
    // one tenth of the run's total advance to the moment it reaches nine
    // tenths of it, so the starting transient and any arrest at the far grip
    // are outside the fit.
    const double tip_final = history.back().tip_m;
    const double advance = tip_final - o.precrack_m;
    const double area_final = areaOf(history.back().plane_broken - precut);
    json steady = nullptr;
    double speed = 0.0, dissipated_per_area = 0.0, released_per_area = 0.0, kinetic_per_area = 0.0;
    if (advance > 4.0 * o.cell_m) {
        // The steady interval: the middle 80% of the advance, so that neither
        // the start transient nor any arrest at the end is inside the fit.
        // Bracketed on the broken mid-plane bond count, which only ever grows,
        // so the bracket is well defined even when the tip jumps several cells
        // in one substep.
        const std::size_t opened = history.back().plane_broken - precut;
        const std::size_t lo = precut + opened / 10;
        const std::size_t hi = precut + (9 * opened) / 10;
        const Sample *a = nullptr, *b = nullptr;
        for (const Sample &s : history) {
            if (a == nullptr && s.plane_broken >= lo) a = &s;
            if (a != nullptr && s.plane_broken <= hi) b = &s;
        }
        if (a != nullptr && b != nullptr && b->t_s > a->t_s && b->plane_broken > a->plane_broken) {
            // Area by the criterion's own bond accounting, and by the rectangle
            // the tip swept; the two agree when the front is straight.
            const double area = areaOf(b->plane_broken - a->plane_broken);
            const double swept = (b->tip_m - a->tip_m) * o.thickness_m;
            speed = (b->tip_m - a->tip_m) / (b->t_s - a->t_s);
            dissipated_per_area = (b->dissipated_j - a->dissipated_j) / area;
            released_per_area = (a->elastic_j - b->elastic_j) / area;
            kinetic_per_area = (b->kinetic_j - a->kinetic_j) / area;
            steady = {{"from_t_s", a->t_s}, {"to_t_s", b->t_s}, {"from_tip_m", a->tip_m},
                      {"to_tip_m", b->tip_m}, {"crack_area_m2", area},
                      {"swept_area_m2", swept}, {"area_over_swept", area / swept},
                      {"plane_bonds_broken", b->plane_broken - a->plane_broken},
                      {"off_plane_bonds_broken", b->off_plane_broken - a->off_plane_broken},
                      {"tip_speed_m_s", speed},
                      {"dissipated_per_area_j_m2", dissipated_per_area},
                      {"elastic_released_per_area_j_m2", released_per_area},
                      {"kinetic_gained_per_area_j_m2", kinetic_per_area},
                      {"dissipated_over_gc", dissipated_per_area / material.fracture_energy_j_m2},
                      {"speed_over_rayleigh", speed / rayleigh_speed},
                      {"speed_over_shear", speed / shear_speed}};
        }
    }

    json history_json = json::array();
    const std::size_t stride = std::max<std::size_t>(1, history.size() / 300);
    for (std::size_t i = 0; i < history.size(); i += stride) {
        const Sample &s = history[i];
        history_json.push_back({{"t_s", s.t_s}, {"tip_m", s.tip_m}, {"elastic_j", s.elastic_j},
                                {"kinetic_j", s.kinetic_j}, {"dissipated_j", s.dissipated_j},
                                {"broken", s.broken}, {"plane_broken", s.plane_broken},
                                {"off_plane_broken", s.off_plane_broken}});
    }
    const double final_total = history.back().elastic_j + history.back().kinetic_j +
                               history.back().dissipated_j;
    json out = {
        {"request", {{"material", materialPresetName(o.material)}, {"failure_law", o.law},
                     {"length_m", o.length_m}, {"height_m", o.height_m},
                     {"thickness_m", o.thickness_m}, {"cell_m", o.cell_m},
                     {"horizon", o.horizon}, {"precrack_m", o.precrack_m},
                     {"energy_release_ratio", o.energy_release_ratio},
                     {"iterations", o.iterations}, {"dt_factor", o.dt_factor},
                     {"window_us", o.window_us}}},
        {"lattice", {{"cells", asset.nodes.size()}, {"bonds", asset.bonds.size()},
                     {"nx", layout.nx}, {"ny", layout.ny}, {"nz", layout.nz},
                     {"pinned_nodes", pinned}, {"precut_bonds", precut},
                     {"mid_plane_bonds", plane_bonds.size()},
                     {"dt_s", dt}, {"steps", steps}}},
        {"material", {{"young_modulus_pa", material.young_modulus_pa},
                      {"fracture_energy_j_m2", material.fracture_energy_j_m2},
                      {"tensile_strength_pa", material.tensile_strength_pa},
                      {"density_kg_m3", rho},
                      {"removal_stretch", removal_stretch},
                      {"energy_scaled_stretch", compiled.energy_scaled_stretch},
                      {"strength_bound_active", compiled.strength_bound_active}}},
        {"lattice_elasticity", {{"c11_pa", c11}, {"c12_pa", c12}, {"c44_pa", c44},
                                {"poisson_effective", poisson}, {"zener_anisotropy", zener},
                                {"dilatational_speed_m_s", dilatational_speed},
                                {"shear_speed_m_s", shear_speed},
                                {"rayleigh_speed_m_s", rayleigh_speed},
                                {"young_effective_pa", young_effective}}},
        {"loading", {{"strain", strain}, {"strain_over_removal_stretch", strain / removal_stretch},
                     {"requested_g_j_m2", target_g},
                     {"initial_elastic_j", elastic_0},
                     {"poisson_contraction", poisson},
                     {"predicted_g_j_m2", 0.5 * young_effective * strain * strain * o.height_m}}},
        {"steady", steady},
        {"solver_leak", {{"quiet_until_s", quiet_until_s},
                         {"fraction_per_us", quiet_leak_per_us}}},
        {"final", {{"tip_m", tip_final}, {"advance_m", advance},
                   {"advance_cells", advance / o.cell_m},
                   {"crack_area_m2", area_final},
                   {"plane_bonds_broken", history.back().plane_broken - precut},
                   {"off_plane_bonds_broken", history.back().off_plane_broken},
                   {"advanced", advance > 1.5 * o.cell_m},
                   {"broken", history.back().broken},
                   {"elastic_j", history.back().elastic_j},
                   {"kinetic_j", history.back().kinetic_j},
                   {"dissipated_j", history.back().dissipated_j},
                   {"ledger_residual_j", final_total - elastic_0},
                   {"ledger_residual_fraction", (final_total - elastic_0) / elastic_0}}},
        {"history", history_json},
        {"wall_s", wall_s}};

    std::cout << "strip " << o.length_m << " x " << o.height_m << " x " << o.thickness_m
              << " m at " << o.cell_m * 1000.0 << " mm (" << asset.nodes.size() << " cells, "
              << asset.bonds.size() << " bonds), " << o.law << "\n"
              << "  loading strain " << strain << " = " << strain / removal_stretch
              << " of the removal stretch; requested G/Gc = " << o.energy_release_ratio << "\n"
              << "  tip " << o.precrack_m << " -> " << tip_final << " m (" << advance / o.cell_m
              << " cells) in " << o.window_us << " us\n";
    if (!steady.is_null()) {
        std::cout << "  steady tip speed " << speed << " m/s = " << speed / rayleigh_speed
                  << " c_R (c_R = " << rayleigh_speed << " m/s, c_s = " << shear_speed << ")\n"
                  << "  dissipated per unit crack area " << dissipated_per_area << " J/m^2 = "
                  << dissipated_per_area / material.fracture_energy_j_m2 << " Gc"
                  << " (elastic released " << released_per_area << ", kinetic gained "
                  << kinetic_per_area << ")\n";
    } else {
        std::cout << "  no steady interval: the crack did not advance far enough to fit\n";
    }
    std::cout << "  ledger residual " << (final_total - elastic_0) / elastic_0 * 100.0
              << " % of the initial elastic energy; solver leak before the crack moved "
              << quiet_leak_per_us * 100.0 << " %/us over " << quiet_until_s * 1e6
              << " us; " << wall_s << " s wall\n";

    if (!o.report.empty()) {
        std::ofstream file(o.report);
        if (!file) throw std::runtime_error("cannot write " + o.report);
        file << out.dump(2) << '\n';
    }
    return 0;
}

void usage() {
    std::cout <<
        "usage: banjo_criterion_strip_probe [options]\n"
        "  --material glass|oak|iron|...   strip material (default glass)\n"
        "  --strip L H T                   strip length, height, thickness in metres\n"
        "  --cell H --horizon N            uniform cubic cell size and neighbour horizon\n"
        "  --precrack A                    slit length from the left edge\n"
        "  --energy-ratio R                requested G / Gc; sets the tensile strain\n"
        "  --failure-law LAW               strain-threshold or energy-scaled (default)\n"
        "  --dt-factor F --iterations N    substep fraction and constraint iterations\n"
        "  --window-us T                   simulated window in microseconds\n"
        "  --report PATH                   write the measurement JSON\n";
}

} // namespace

int main(int argc, char **argv) {
    try {
        Options o;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            const auto value = [&]() -> std::string {
                if (i + 1 >= argc) throw std::invalid_argument(option + " needs a value");
                return argv[++i];
            };
            const auto number = [](const std::string &text) { return std::stod(text); };
            if (option == "--help" || option == "-h") { usage(); return 0; }
            else if (option == "--material") o.material = presetFromName(value());
            else if (option == "--strip") {
                o.length_m = number(value());
                o.height_m = number(value());
                o.thickness_m = number(value());
            }
            else if (option == "--cell") o.cell_m = number(value());
            else if (option == "--horizon") o.horizon = static_cast<unsigned>(number(value()));
            else if (option == "--precrack") o.precrack_m = number(value());
            else if (option == "--energy-ratio") o.energy_release_ratio = number(value());
            else if (option == "--failure-law") o.law = value();
            else if (option == "--dt-factor") o.dt_factor = number(value());
            else if (option == "--iterations") o.iterations = static_cast<unsigned>(number(value()));
            else if (option == "--window-us") o.window_us = number(value());
            else if (option == "--report") o.report = value();
            else { usage(); throw std::invalid_argument("unknown option " + option); }
        }
        return run(o);
    } catch (const std::exception &error) {
        std::cerr << "[error] " << error.what() << '\n';
        return 1;
    }
}
