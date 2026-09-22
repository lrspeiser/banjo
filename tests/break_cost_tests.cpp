// What a break costs (docs/what-a-break-costs.md): the charge the room's
// failure law makes for a crack, and what a break actually took away.
//
// A crack in oak should cost oak's own 1,000 J/m2 whatever size the cells are.
//
// 1. Under the energy-scaled law the charge is the material's own fracture
//    energy, at every cell size, for every material that declares one.
// 2. Under the strain-threshold law -- the law every room runs today -- the
//    charge is not the material's, and it goes with the cell size: halve the
//    cells and it halves. That law has no length in it.
// 3. A break reports what it took: the bonds removed, the crack area they
//    stand for (h^2 / N_100 each), and the energy that left with them.
// 4. A scene may name its law, and a name that is not a law is refused.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "material/MaterialCompiler.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

using namespace banjo;
using namespace banjo::fastlattice;

namespace {

int failures = 0;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

bool near(double got, double want, double relative = 1e-9) {
    return std::abs(got - want) <= relative * std::max(1.0, std::abs(want));
}

// A plate of `material` lying on the ground, and an iron ball above it. Its
// sides are a whole number of cells at 20, 10 and 5 mm.
TileImpactRequest plateRoom(const std::string &material, double cell_m, BondFailureLaw law) {
    TileImpactRequest request;
    request.cell_size_m = cell_m;
    request.backend = BackendKind::CpuParallel;
    request.failure_law = law;
    SceneBody plate;
    plate.name = "plate";
    plate.shape = BodyShape::Box;
    plate.material = material == "oak" ? MaterialPreset::Oak : MaterialPreset::Glass;
    plate.dimensions_m = {0.16, 0.06, 0.16};
    plate.center_m = {0.0, 0.03, 0.0};
    request.bodies = {plate};
    return request;
}

LiveBreakCost costOf(const std::string &material, double cell_m, BondFailureLaw law) {
    const auto world = LiveWorld::open(plateRoom(material, cell_m, law));
    return world->crackCost("plate");
}

void theEnergyLawChargesTheMaterialsOwn() {
    for (const char *material : {"oak", "glass"}) {
        const LiveBreakCost coarse = costOf(material, 0.02, BondFailureLaw::EnergyScaled);
        const LiveBreakCost fine = costOf(material, 0.005, BondFailureLaw::EnergyScaled);
        std::cout << "    " << material << ", energy-scaled: " << coarse.law_energy_j_m2 << " J/m2 at 20 mm cells, "
                  << fine.law_energy_j_m2 << " at 5 mm; its own is " << coarse.declared_energy_j_m2 << "\n";
        require(coarse.failure_law == "energy-scaled", "the room runs the law it was given");
        require(coarse.declared_energy_j_m2 > 0.0, "the material declares a fracture energy");
        require(near(coarse.law_energy_j_m2, coarse.declared_energy_j_m2, 1e-9) &&
                    near(fine.law_energy_j_m2, fine.declared_energy_j_m2, 1e-9),
                std::string("a crack in ") + material + " costs what " + material + " says it costs");
        require(near(coarse.law_energy_j_m2, fine.law_energy_j_m2, 1e-9), "at any cell size");
        require(!coarse.bounded_by_strength && !fine.bounded_by_strength,
                "and its strength did not bound it first");
    }
}

void theStrainLawChargesWhateverTheCellSizeMakesIt() {
    for (const char *material : {"oak", "glass"}) {
        const LiveBreakCost coarse = costOf(material, 0.02, BondFailureLaw::StrainThreshold);
        const LiveBreakCost half = costOf(material, 0.01, BondFailureLaw::StrainThreshold);
        const LiveBreakCost quarter = costOf(material, 0.005, BondFailureLaw::StrainThreshold);
        std::cout << "    " << material << ", strain-threshold: " << coarse.law_energy_j_m2 << " J/m2 at 20 mm, "
                  << half.law_energy_j_m2 << " at 10 mm, " << quarter.law_energy_j_m2 << " at 5 mm; its own is "
                  << coarse.declared_energy_j_m2 << "\n";
        require(coarse.failure_law == "strain-threshold", "the room runs the law it was given");
        require(near(half.law_energy_j_m2, coarse.law_energy_j_m2 / 2.0, 1e-9) &&
                    near(quarter.law_energy_j_m2, coarse.law_energy_j_m2 / 4.0, 1e-9),
                "halve the cells and the charge halves: the law has no length in it");
        require(coarse.law_energy_j_m2 > 10.0 * coarse.declared_energy_j_m2,
                std::string("and it is nothing like what ") + material + " says a crack costs");
    }
}

void aBreakSaysWhatItTook() {
    TileImpactRequest request = plateRoom("glass", 0.02, BondFailureLaw::EnergyScaled);
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.06, 0.06, 0.06};
    ball.center_m = {0.0, 0.1, 0.0};
    ball.velocity_m_s = {0.0, -30.0, 0.0};
    request.bodies.push_back(ball);
    const auto world = LiveWorld::open(request);
    bool offered = false;
    for (int i = 0; i < 240 && !offered; ++i) {
        world->step(1.0 / 240.0);
        for (const std::string &name : world->breakable())
            if (name == "plate") offered = true;
    }
    require(offered, "the world offered the plate to break");
    if (!offered) return;
    const std::size_t pieces = world->fracture("plate");
    const LiveBreakCost cost = world->lastBreak();
    const LatticeHorizonGeometry g = latticeHorizonGeometry(request.neighbor_horizon_cells);
    const double area = static_cast<double>(cost.broken_bonds) * request.cell_size_m * request.cell_size_m /
                        g.crossings_100;
    std::cout << "    a 60 mm iron ball at 30 m/s: " << pieces << " pieces, " << cost.broken_bonds << " bonds ("
              << cost.tensile_bonds << " pulled apart, " << cost.compressive_bonds << " crushed, " << cost.shear_bonds
              << " sheared), " << cost.removed_energy_j << " J over " << cost.crack_area_m2 * 1.0e6 << " mm2: "
              << cost.crack_energy_j_m2 << " J/m2 against a charge of " << cost.law_energy_j_m2 << "\n";
    require(cost.broken_bonds > 0 && cost.removed_energy_j > 0.0, "it cost something");
    require(near(cost.crack_area_m2, area, 1e-12), "the crack area is the bonds' own share of a lattice plane");
    require(near(cost.crack_energy_j_m2, cost.removed_energy_j / cost.crack_area_m2, 1e-12),
            "and what it cost per square metre is the energy over that area");
    require(cost.tensile_bonds + cost.compressive_bonds + cost.shear_bonds == cost.broken_bonds,
            "every removed bond went one of the three ways");
    // The number this test exists to keep honest: what left is not what the law
    // charges, because a bond is removed at whatever stretch it had reached,
    // not at the stretch the charge is set for.
    require(cost.crack_energy_j_m2 > cost.law_energy_j_m2,
            "what left is more than the charge, and the gap is the overshoot");
}

void aSceneNamesItsLaw() {
    TileImpactRequest request;
    readSceneSettings(R"({"failure_law":"energy-scaled","bodies":[]})", request);
    require(request.failure_law == BondFailureLaw::EnergyScaled, "a scene may name the energy-scaled law");
    readSceneSettings(R"({"failure_law":"strain-threshold","bodies":[]})", request);
    require(request.failure_law == BondFailureLaw::StrainThreshold, "and the strain-threshold law");
    bool refused = false;
    try {
        readSceneSettings(R"({"failure_law":"whatever-breaks","bodies":[]})", request);
    } catch (const std::exception &error) {
        refused = std::string(error.what()).find("failure_law") != std::string::npos;
    }
    require(refused, "and a name that is not a law is refused, saying so");
    require(request.failure_law == BondFailureLaw::StrainThreshold, "leaving the law as it was");
}

} // namespace

int main() {
    const std::pair<const char *, void (*)()> tests[] = {
        {"the energy law charges the material's own", theEnergyLawChargesTheMaterialsOwn},
        {"the strain law charges whatever the cell size makes it", theStrainLawChargesWhateverTheCellSizeMakesIt},
        {"a break says what it took", aBreakSaysWhatItTook},
        {"a scene names its law", aSceneNamesItsLaw},
    };
    for (const auto &[name, test] : tests) {
        const int before = failures;
        try {
            test();
        } catch (const std::exception &error) {
            std::cout << "[FAIL] " << name << ": " << error.what() << std::endl;
            ++failures;
        }
        if (failures == before) std::cout << "[PASS] " << name << std::endl;
    }
    std::cout << (failures == 0 ? "all passed" : std::to_string(failures) + " failed") << std::endl;
    return failures == 0 ? 0 : 1;
}
