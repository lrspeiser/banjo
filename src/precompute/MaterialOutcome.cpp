#include "precompute/MaterialOutcome.hpp"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace banjo {
namespace {

constexpr const char *kMagic = "BANJO_MATERIAL_OUTCOME";
constexpr std::size_t kMaximumNodes = 10'000'000U;
constexpr std::size_t kMaximumBonds = 100'000'000U;

[[nodiscard]] std::int32_t quantizeInt32(double value, double scale) {
    if (!std::isfinite(value)) {
        throw std::invalid_argument("material outcome key values must be finite");
    }
    const long long rounded = std::llround(value * scale);
    if (rounded < std::numeric_limits<std::int32_t>::min() ||
        rounded > std::numeric_limits<std::int32_t>::max()) {
        throw std::out_of_range("material outcome key value exceeds int32 range");
    }
    return static_cast<std::int32_t>(rounded);
}

[[nodiscard]] std::int64_t quantizeInt64(double value, double scale) {
    if (!std::isfinite(value)) {
        throw std::invalid_argument("material outcome key values must be finite");
    }
    const long double scaled =
        static_cast<long double>(value) * static_cast<long double>(scale);
    if (scaled < static_cast<long double>(std::numeric_limits<std::int64_t>::min()) ||
        scaled > static_cast<long double>(std::numeric_limits<std::int64_t>::max())) {
        throw std::out_of_range("material outcome key value exceeds int64 range");
    }
    return static_cast<std::int64_t>(std::llround(value * scale));
}

[[nodiscard]] Quat normalizedConjugate(const Quat &input) {
    const double magnitude_squared =
        input.w * input.w + input.x * input.x + input.y * input.y + input.z * input.z;
    if (magnitude_squared <= 1.0e-18) {
        throw std::invalid_argument("activation orientation is not a valid quaternion");
    }
    return {
        input.w / magnitude_squared,
        -input.x / magnitude_squared,
        -input.y / magnitude_squared,
        -input.z / magnitude_squared,
    };
}

template <typename Value>
void fnvAppend(std::uint64_t &hash, const Value &value) {
    static_assert(std::is_trivially_copyable_v<Value>);
    const auto *bytes = reinterpret_cast<const unsigned char *>(&value);
    for (std::size_t index = 0; index < sizeof(Value); ++index) {
        hash ^= static_cast<std::uint64_t>(bytes[index]);
        hash *= 1099511628211ULL;
    }
}

void writeKey(std::ostream &output, const MaterialOutcomeKey &key) {
    output << key.format_version << ' '
           << key.solver_model_version << ' '
           << static_cast<unsigned>(key.striker) << ' '
           << static_cast<unsigned>(key.target) << ' '
           << static_cast<unsigned>(key.surface) << ' '
           << key.radius_micrometers << ' '
           << key.voxel_micrometers << ' '
           << key.striker_speed_millimeters_per_second << ' '
           << key.target_speed_millimeters_per_second << ' '
           << key.slope_millidegrees << ' '
           << key.gravity_x_millimeters_per_second2 << ' '
           << key.gravity_y_millimeters_per_second2 << ' '
           << key.gravity_z_millimeters_per_second2 << ' '
           << key.neighbor_horizon_cells << ' '
           << key.occupancy_samples_per_axis << ' '
           << key.solver_substeps << ' '
           << key.constraint_iterations << ' '
           << key.minimum_material_steps << ' '
           << key.stable_material_steps << ' '
           << key.maximum_material_steps << ' '
           << key.impact_internal_energy_parts_per_million << ' '
           << key.maximum_internal_energy_millijoules << ' '
           << key.material_seed << '\n';
}

[[nodiscard]] MaterialOutcomeKey readKey(std::istream &input) {
    MaterialOutcomeKey key;
    unsigned striker = 0U;
    unsigned target = 0U;
    unsigned surface = 0U;
    if (!(input >> key.format_version
                >> key.solver_model_version
                >> striker
                >> target
                >> surface
                >> key.radius_micrometers
                >> key.voxel_micrometers
                >> key.striker_speed_millimeters_per_second
                >> key.target_speed_millimeters_per_second
                >> key.slope_millidegrees
                >> key.gravity_x_millimeters_per_second2
                >> key.gravity_y_millimeters_per_second2
                >> key.gravity_z_millimeters_per_second2
                >> key.neighbor_horizon_cells
                >> key.occupancy_samples_per_axis
                >> key.solver_substeps
                >> key.constraint_iterations
                >> key.minimum_material_steps
                >> key.stable_material_steps
                >> key.maximum_material_steps
                >> key.impact_internal_energy_parts_per_million
                >> key.maximum_internal_energy_millijoules
                >> key.material_seed)) {
        throw std::runtime_error("material outcome key is truncated");
    }
    key.striker = materialPresetFromOrdinal(striker);
    key.target = materialPresetFromOrdinal(target);
    key.surface = materialPresetFromOrdinal(surface);
    return key;
}

void validateOutcome(const MaterialOutcome &outcome) {
    if (outcome.key.format_version != kMaterialOutcomeFormatVersion ||
        outcome.key.solver_model_version != kMaterialSolverModelVersion) {
        throw std::invalid_argument("material outcome version is incompatible");
    }
    if (outcome.nodes.empty() || outcome.nodes.size() > kMaximumNodes ||
        outcome.bonds.empty() || outcome.bonds.size() > kMaximumBonds ||
        outcome.represented_mass_kg <= 0.0 ||
        !std::isfinite(outcome.represented_mass_kg)) {
        throw std::invalid_argument("material outcome contents are invalid");
    }
}

} // namespace

MaterialOutcomeKey makeMaterialOutcomeKey(
    const MaterialOutcomeKeyInput &input) {
    if (input.radius_m <= 0.0 || input.voxel_size_m <= 0.0 ||
        input.striker_speed_m_s < 0.0 || input.target_speed_m_s < 0.0 ||
        input.neighbor_horizon_cells == 0U ||
        input.occupancy_samples_per_axis == 0U ||
        input.solver_substeps == 0U || input.constraint_iterations == 0U ||
        input.maximum_material_steps == 0U ||
        input.minimum_material_steps > input.maximum_material_steps ||
        input.impact_internal_energy_fraction < 0.0 ||
        input.maximum_internal_energy_j < 0.0) {
        throw std::invalid_argument("material outcome key input is invalid");
    }

    MaterialOutcomeKey key;
    key.striker = input.striker;
    key.target = input.target;
    key.surface = input.surface;
    key.radius_micrometers = quantizeInt32(input.radius_m, 1.0e6);
    key.voxel_micrometers = quantizeInt32(input.voxel_size_m, 1.0e6);
    key.striker_speed_millimeters_per_second =
        quantizeInt32(input.striker_speed_m_s, 1.0e3);
    key.target_speed_millimeters_per_second =
        quantizeInt32(input.target_speed_m_s, 1.0e3);
    key.slope_millidegrees = quantizeInt32(input.slope_degrees, 1.0e3);
    key.gravity_x_millimeters_per_second2 =
        quantizeInt32(input.gravity_world_m_s2.x, 1.0e3);
    key.gravity_y_millimeters_per_second2 =
        quantizeInt32(input.gravity_world_m_s2.y, 1.0e3);
    key.gravity_z_millimeters_per_second2 =
        quantizeInt32(input.gravity_world_m_s2.z, 1.0e3);
    key.neighbor_horizon_cells = input.neighbor_horizon_cells;
    key.occupancy_samples_per_axis = input.occupancy_samples_per_axis;
    key.solver_substeps = input.solver_substeps;
    key.constraint_iterations = input.constraint_iterations;
    key.minimum_material_steps = input.minimum_material_steps;
    key.stable_material_steps = input.stable_material_steps;
    key.maximum_material_steps = input.maximum_material_steps;
    key.impact_internal_energy_parts_per_million =
        quantizeInt32(input.impact_internal_energy_fraction, 1.0e6);
    key.maximum_internal_energy_millijoules =
        quantizeInt64(input.maximum_internal_energy_j, 1.0e3);
    key.material_seed = input.material_seed;
    return key;
}

std::uint64_t materialOutcomeFingerprint(const MaterialOutcomeKey &key) {
    std::uint64_t hash = 1469598103934665603ULL;
    fnvAppend(hash, key.format_version);
    fnvAppend(hash, key.solver_model_version);
    const auto striker = static_cast<std::uint8_t>(key.striker);
    const auto target = static_cast<std::uint8_t>(key.target);
    const auto surface = static_cast<std::uint8_t>(key.surface);
    fnvAppend(hash, striker);
    fnvAppend(hash, target);
    fnvAppend(hash, surface);
    fnvAppend(hash, key.radius_micrometers);
    fnvAppend(hash, key.voxel_micrometers);
    fnvAppend(hash, key.striker_speed_millimeters_per_second);
    fnvAppend(hash, key.target_speed_millimeters_per_second);
    fnvAppend(hash, key.slope_millidegrees);
    fnvAppend(hash, key.gravity_x_millimeters_per_second2);
    fnvAppend(hash, key.gravity_y_millimeters_per_second2);
    fnvAppend(hash, key.gravity_z_millimeters_per_second2);
    fnvAppend(hash, key.neighbor_horizon_cells);
    fnvAppend(hash, key.occupancy_samples_per_axis);
    fnvAppend(hash, key.solver_substeps);
    fnvAppend(hash, key.constraint_iterations);
    fnvAppend(hash, key.minimum_material_steps);
    fnvAppend(hash, key.stable_material_steps);
    fnvAppend(hash, key.maximum_material_steps);
    fnvAppend(hash, key.impact_internal_energy_parts_per_million);
    fnvAppend(hash, key.maximum_internal_energy_millijoules);
    fnvAppend(hash, key.material_seed);
    return hash;
}

MaterialOutcome captureMaterialOutcome(
    const MaterialOutcomeKey &key,
    const ActiveMatter &matter,
    const RigidSnapshot &activation_rigid,
    std::uint64_t material_steps) {
    if (matter.asset == nullptr || matter.nodes.empty() || matter.bonds.empty()) {
        throw std::invalid_argument("active matter is not capturable");
    }
    const Quat inverse_orientation =
        normalizedConjugate(activation_rigid.orientation_world);

    MaterialOutcome outcome;
    outcome.key = key;
    outcome.material_steps = material_steps;
    outcome.nodes.reserve(matter.nodes.size());
    outcome.bonds.reserve(matter.bonds.size());
    for (const ActiveNodeState &node : matter.nodes) {
        outcome.represented_mass_kg += node.mass_kg;
        outcome.nodes.push_back({
            inverse_orientation.rotate(
                node.position_world_m -
                activation_rigid.center_of_mass_world_m),
            inverse_orientation.rotate(
                node.velocity_m_s -
                activation_rigid.linear_velocity_m_s),
            inverse_orientation.rotate(node.spin_angular_velocity_rad_s),
        });
    }
    for (const ActiveBondState &bond : matter.bonds) {
        outcome.bonds.push_back({
            bond.damage,
            bond.failure_mode,
            bond.alive,
        });
    }
    validateOutcome(outcome);
    return outcome;
}

void applyMaterialOutcome(
    const MaterialOutcome &outcome,
    const RigidSnapshot &activation_rigid,
    ActiveMatter &matter) {
    validateOutcome(outcome);
    if (matter.asset == nullptr || matter.nodes.size() != outcome.nodes.size() ||
        matter.bonds.size() != outcome.bonds.size()) {
        throw std::invalid_argument(
            "cached material outcome does not match the active lattice topology");
    }

    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        ActiveNodeState &node = matter.nodes[index];
        const CachedMaterialNode &cached = outcome.nodes[index];
        node.position_world_m =
            activation_rigid.center_of_mass_world_m +
            activation_rigid.orientation_world.rotate(
                cached.position_from_activation_com_local_m);
        node.previous_position_world_m = node.position_world_m;
        node.velocity_m_s =
            activation_rigid.linear_velocity_m_s +
            activation_rigid.orientation_world.rotate(
                cached.velocity_minus_activation_linear_local_m_s);
        node.spin_angular_velocity_rad_s = activation_rigid.orientation_world.rotate(
            cached.spin_angular_velocity_local_rad_s);
    }
    for (std::size_t index = 0; index < matter.bonds.size(); ++index) {
        ActiveBondState &bond = matter.bonds[index];
        const CachedMaterialBond &cached = outcome.bonds[index];
        bond.accumulated_lambda = 0.0;
        bond.damage = cached.damage;
        bond.failure_mode = cached.failure_mode;
        bond.alive = cached.alive;
    }
    matter.connectivity_dirty = true;
    matter.step_index = outcome.material_steps;
}

void saveMaterialOutcome(
    const MaterialOutcome &outcome,
    const std::filesystem::path &path) {
    validateOutcome(outcome);
    if (path.has_parent_path()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error("could not open material outcome for writing");
    }

    output << kMagic << ' ' << kMaterialOutcomeFormatVersion << '\n';
    writeKey(output, outcome.key);
    output << outcome.material_steps << ' '
           << std::setprecision(17) << outcome.represented_mass_kg << ' '
           << outcome.nodes.size() << ' ' << outcome.bonds.size() << '\n';
    output << std::setprecision(17);
    for (const CachedMaterialNode &node : outcome.nodes) {
        output << node.position_from_activation_com_local_m.x << ' '
               << node.position_from_activation_com_local_m.y << ' '
               << node.position_from_activation_com_local_m.z << ' '
               << node.velocity_minus_activation_linear_local_m_s.x << ' '
               << node.velocity_minus_activation_linear_local_m_s.y << ' '
               << node.velocity_minus_activation_linear_local_m_s.z << ' '
               << node.spin_angular_velocity_local_rad_s.x << ' '
               << node.spin_angular_velocity_local_rad_s.y << ' '
               << node.spin_angular_velocity_local_rad_s.z << '\n';
    }
    for (const CachedMaterialBond &bond : outcome.bonds) {
        output << (bond.alive ? 1 : 0) << ' '
               << static_cast<unsigned>(bond.failure_mode) << ' '
               << bond.damage << '\n';
    }
    if (!output) {
        throw std::runtime_error("failed while writing material outcome");
    }
}

MaterialOutcome loadMaterialOutcome(const std::filesystem::path &path) {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("could not open material outcome for reading");
    }

    std::string magic;
    std::uint32_t file_version = 0U;
    if (!(input >> magic >> file_version) || magic != kMagic ||
        file_version != kMaterialOutcomeFormatVersion) {
        throw std::runtime_error("material outcome header is incompatible");
    }

    MaterialOutcome outcome;
    outcome.key = readKey(input);
    std::size_t node_count = 0U;
    std::size_t bond_count = 0U;
    if (!(input >> outcome.material_steps >> outcome.represented_mass_kg >>
          node_count >> bond_count)) {
        throw std::runtime_error("material outcome summary is truncated");
    }
    if (node_count == 0U || node_count > kMaximumNodes || bond_count == 0U ||
        bond_count > kMaximumBonds) {
        throw std::runtime_error("material outcome topology count is invalid");
    }

    outcome.nodes.resize(node_count);
    for (CachedMaterialNode &node : outcome.nodes) {
        if (!(input >> node.position_from_activation_com_local_m.x
                    >> node.position_from_activation_com_local_m.y
                    >> node.position_from_activation_com_local_m.z
                    >> node.velocity_minus_activation_linear_local_m_s.x
                    >> node.velocity_minus_activation_linear_local_m_s.y
                    >> node.velocity_minus_activation_linear_local_m_s.z
                    >> node.spin_angular_velocity_local_rad_s.x
                    >> node.spin_angular_velocity_local_rad_s.y
                    >> node.spin_angular_velocity_local_rad_s.z)) {
            throw std::runtime_error("material outcome node state is truncated");
        }
    }

    outcome.bonds.resize(bond_count);
    for (CachedMaterialBond &bond : outcome.bonds) {
        unsigned alive = 0U;
        unsigned failure_mode = 0U;
        if (!(input >> alive >> failure_mode >> bond.damage)) {
            throw std::runtime_error("material outcome bond state is truncated");
        }
        if (alive > 1U || failure_mode > static_cast<unsigned>(BondFailureMode::Shear)) {
            throw std::runtime_error("material outcome bond enum is invalid");
        }
        bond.alive = alive != 0U;
        bond.failure_mode = static_cast<BondFailureMode>(failure_mode);
    }

    validateOutcome(outcome);
    return outcome;
}

} // namespace banjo
