// Dumps the elastic reference lattice the solver probe builds, so an external
// modal analysis operates on the engine's own nodes, masses, bonds and
// compliances rather than a reimplementation of them.
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"

#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <cmath>
#include <limits>
#include <string>

int main(int argc, char **argv) {
    try {
        double h = 0.065;
        std::string material_name = "glass";
        std::string out = "lattice.json";
        for (int i = 1; i + 1 < argc; i += 2) {
            const std::string option = argv[i];
            const std::string value = argv[i + 1];
            if (option == "--voxel-size") h = std::stod(value);
            else if (option == "--material") material_name = value;
            else if (option == "--out") out = value;
            else throw std::invalid_argument("unknown option " + option);
        }
        auto preset = banjo::MaterialPreset::Glass;
        if (material_name == "oak") preset = banjo::MaterialPreset::Oak;
        else if (material_name == "iron") preset = banjo::MaterialPreset::Iron;
        else if (material_name != "glass") throw std::invalid_argument("material must be glass, oak or iron");

        // Identical construction to banjo_solver_probe, so the dumped lattice is
        // the one the solver actually integrates.
        const auto material = banjo::makeReferenceMaterial(preset, 17);
        // The failure surface is what makes the damage thresholds finite; the bare
        // elastic reference leaves them at infinity.
        const auto compiled = banjo::withStrengthDerivedFailure(
            banjo::compileElasticLatticeReference(material, h, 2), material);
        const auto asset = banjo::generateSphereLattice({.25, h, 2, 3}, compiled);

        std::ofstream file(out);
        file << std::setprecision(std::numeric_limits<double>::max_digits10);
        file << "{\"material\":\"" << material_name << "\",\"voxel_size_m\":" << h
             << ",\"density_kg_m3\":" << compiled.density_kg_m3
             << ",\"node_count\":" << asset.nodes.size()
             << ",\"bond_count\":" << asset.bonds.size() << ",\"nodes\":[";
        for (std::size_t i = 0; i < asset.nodes.size(); ++i) {
            const auto &n = asset.nodes[i];
            if (i) file << ',';
            file << '[' << n.local_position_m.x << ',' << n.local_position_m.y << ','
                 << n.local_position_m.z << ',' << n.represented_volume_m3 * compiled.density_kg_m3
                 << ',' << (n.surface_node ? 1 : 0) << ']';
        }
        file << "],\"bonds\":[";
        for (std::size_t i = 0; i < asset.bonds.size(); ++i) {
            const auto &b = asset.bonds[i];
            if (i) file << ',';
            // compliance is 1/stiffness; damage_start_stretch is the failure onset.
            const auto number=[&](double v){ if(std::isfinite(v)) file << v; else file << "null"; };
            file << '[' << b.node_a << ',' << b.node_b << ',' << b.rest_length_m << ','
                 << b.compliance << ','; number(b.damage_start_stretch);
            file << ','; number(b.damage_end_stretch); file << ']';
        }
        file << "]}\n";
        std::cout << "nodes=" << asset.nodes.size() << " bonds=" << asset.bonds.size()
                  << " -> " << out << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "lattice dump error: " << error.what() << '\n';
        return 1;
    }
}
