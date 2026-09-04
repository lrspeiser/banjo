#include "material/MaterialCatalog.hpp"
#include "prediction/BallScenarioProjection.hpp"
#include "prediction/ScenarioCache.hpp"

#include <array>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <numbers>

int main(int argc, char **argv) {
    try {
        const std::filesystem::path output_path =
            argc > 1 ? std::filesystem::path(argv[1])
                     : std::filesystem::path("ball-scenarios.csv");

        constexpr std::array strikers{
            banjo::MaterialPreset::Iron,
            banjo::MaterialPreset::Aluminum,
            banjo::MaterialPreset::Rubber,
            banjo::MaterialPreset::Oak,
            banjo::MaterialPreset::Ice,
        };
        constexpr std::array targets{
            banjo::MaterialPreset::Glass,
            banjo::MaterialPreset::Ceramic,
            banjo::MaterialPreset::Rubber,
            banjo::MaterialPreset::Oak,
        };
        constexpr std::array speeds{2.0, 4.0, 8.0, 12.0};
        constexpr std::array slopes{0.0, 10.0, 20.0};

        constexpr double radius_m = 0.25;
        constexpr double voxel_size_m = 0.04;
        constexpr std::uint64_t seed = 971;
        const double sphere_volume =
            (4.0 / 3.0) * std::numbers::pi * radius_m * radius_m * radius_m;
        const std::size_t estimated_nodes = static_cast<std::size_t>(
            sphere_volume / (voxel_size_m * voxel_size_m * voxel_size_m));
        const std::size_t estimated_bonds = estimated_nodes * 13U;

        banjo::ScenarioProjectionCache cache;
        for (const banjo::MaterialPreset striker : strikers) {
            for (const banjo::MaterialPreset target : targets) {
                for (const double speed : speeds) {
                    for (const double slope : slopes) {
                        banjo::BallScenarioInput input;
                        input.striker_material = banjo::makeReferenceMaterial(striker, seed);
                        input.target_material = banjo::makeReferenceMaterial(target, seed);
                        input.surface_material = banjo::makeReferenceMaterial(
                            banjo::MaterialPreset::Concrete, seed);
                        input.striker_radius_m = radius_m;
                        input.target_radius_m = radius_m;
                        input.striker_speed_m_s = speed;
                        input.slope_angle_degrees = slope;
                        input.voxel_size_m = voxel_size_m;
                        input.estimated_active_nodes = estimated_nodes;
                        input.estimated_bonds = estimated_bonds;

                        const banjo::ScenarioKey key = banjo::makeScenarioKey(
                            striker,
                            target,
                            banjo::MaterialPreset::Concrete,
                            radius_m,
                            speed,
                            slope,
                            input.gravity_m_s2,
                            voxel_size_m,
                            seed);
                        cache.store(key, banjo::projectBallScenario(input));
                    }
                }
            }
        }

        cache.saveCsv(output_path);
        std::cout << "Precomputed " << cache.size()
                  << " deterministic ball scenario projections into "
                  << output_path.string() << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << "Precompute failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
