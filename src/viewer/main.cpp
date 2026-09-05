#include "sim/RollingBallExperiment.hpp"

#include <raylib.h>
#include <raymath.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <iomanip>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

constexpr Color kBackground{12, 18, 28, 255};
constexpr Color kFloor{48, 55, 66, 255};
constexpr Color kIronHighlight{225, 198, 93, 255};
constexpr Color kGlassLight{156, 224, 244, 255};
constexpr Color kCrack{255, 111, 76, 255};
constexpr Color kText{231, 236, 243, 255};
constexpr Color kMuted{156, 165, 180, 255};

struct ViewerOptions {
    std::string capture_path;
    std::string cache_path;
    unsigned capture_frames{210};
};

struct FragmentModel {
    banjo::MatterBodyId body_id{banjo::kInvalidMatterBodyId};
    Model model{};
    std::size_t node_count{};
};

[[nodiscard]] Vector3 toRaylib(const banjo::Vec3 &value) {
    return {
        static_cast<float>(value.x),
        static_cast<float>(value.y),
        static_cast<float>(value.z),
    };
}

[[nodiscard]] ViewerOptions parseOptions(int argc, char **argv) {
    ViewerOptions options;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument = argv[index];
        if (argument == "--capture") {
            if (index + 1 >= argc) {
                throw std::invalid_argument("--capture requires a file path");
            }
            options.capture_path = argv[++index];
        } else if (argument == "--cache") {
            if (index + 1 >= argc) {
                throw std::invalid_argument("--cache requires a file path");
            }
            options.cache_path = argv[++index];
        } else if (argument == "--frames") {
            if (index + 1 >= argc) {
                throw std::invalid_argument("--frames requires a positive integer");
            }
            options.capture_frames =
                static_cast<unsigned>(std::stoul(argv[++index]));
            if (options.capture_frames == 0U) {
                throw std::invalid_argument("--frames must be positive");
            }
        } else {
            throw std::invalid_argument(
                "unknown command-line argument: " + std::string(argument));
        }
    }
    return options;
}

[[nodiscard]] Color materialColor(banjo::MaterialPreset preset) {
    switch (preset) {
    case banjo::MaterialPreset::Iron:
        return {116, 124, 136, 255};
    case banjo::MaterialPreset::Aluminum:
        return {183, 190, 198, 255};
    case banjo::MaterialPreset::Glass:
        return {83, 185, 222, 255};
    case banjo::MaterialPreset::Ceramic:
        return {224, 220, 205, 255};
    case banjo::MaterialPreset::Oak:
        return {145, 95, 55, 255};
    case banjo::MaterialPreset::Rubber:
        return {48, 54, 61, 255};
    case banjo::MaterialPreset::Ice:
        return {175, 222, 239, 255};
    case banjo::MaterialPreset::Concrete:
        return {116, 112, 108, 255};
    }
    return WHITE;
}

[[nodiscard]] Model buildModel(const banjo::FragmentSurfaceMesh &source) {
    if (source.indices.empty() || source.indices.size() % 3U != 0U) {
        throw std::invalid_argument(
            "fragment surface does not contain triangles");
    }
    if (source.indices.size() >
        static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw std::overflow_error(
            "fragment surface is too large for raylib");
    }

    Mesh mesh{};
    mesh.vertexCount = static_cast<int>(source.indices.size());
    mesh.triangleCount = mesh.vertexCount / 3;

    const std::size_t value_count = source.indices.size() * 3U;
    const std::size_t byte_count = value_count * sizeof(float);
    if (byte_count > std::numeric_limits<unsigned int>::max()) {
        throw std::overflow_error(
            "fragment vertex buffer exceeds raylib allocator limit");
    }
    mesh.vertices = static_cast<float *>(
        MemAlloc(static_cast<unsigned int>(byte_count)));
    mesh.normals = static_cast<float *>(
        MemAlloc(static_cast<unsigned int>(byte_count)));
    if (mesh.vertices == nullptr || mesh.normals == nullptr) {
        throw std::bad_alloc();
    }

    for (std::size_t output = 0; output < source.indices.size(); ++output) {
        const std::uint32_t source_index = source.indices[output];
        if (source_index >= source.vertices.size()) {
            throw std::out_of_range(
                "fragment surface index is invalid");
        }
        const banjo::SurfaceVertex &vertex = source.vertices[source_index];
        mesh.vertices[3U * output + 0U] =
            static_cast<float>(vertex.position_local_m.x);
        mesh.vertices[3U * output + 1U] =
            static_cast<float>(vertex.position_local_m.y);
        mesh.vertices[3U * output + 2U] =
            static_cast<float>(vertex.position_local_m.z);
        mesh.normals[3U * output + 0U] =
            static_cast<float>(vertex.normal_local.x);
        mesh.normals[3U * output + 1U] =
            static_cast<float>(vertex.normal_local.y);
        mesh.normals[3U * output + 2U] =
            static_cast<float>(vertex.normal_local.z);
    }

    UploadMesh(&mesh, false);
    Model model = LoadModelFromMesh(mesh);
    model.materials[0].maps[MATERIAL_MAP_DIFFUSE].color = WHITE;
    return model;
}

void unloadModels(std::vector<FragmentModel> &models) {
    for (FragmentModel &fragment : models) {
        UnloadModel(fragment.model);
    }
    models.clear();
}

void syncFragmentModels(
    const banjo::RollingBallExperiment &experiment,
    std::vector<FragmentModel> &models) {
    const auto &descriptions = experiment.fragmentBuild().rigid_fragments;
    if (descriptions.empty() || models.size() == descriptions.size()) {
        return;
    }

    unloadModels(models);
    models.reserve(descriptions.size());
    for (const banjo::RigidFragmentDescription &description : descriptions) {
        models.push_back({
            description.body_id,
            buildModel(description.surface_mesh),
            description.source_node_count,
        });
    }
}

[[nodiscard]] std::vector<double> calculateNodeDamage(
    const banjo::ActiveMatter &matter) {
    std::vector<double> damage(matter.nodes.size(), 0.0);
    for (std::size_t index = 0; index < matter.bonds.size(); ++index) {
        const banjo::BondRest &rest = matter.asset->bonds[index];
        const banjo::ActiveBondState &state = matter.bonds[index];
        const double value = state.alive ? state.damage : 1.0;
        damage[rest.node_a] = std::max(damage[rest.node_a], value);
        damage[rest.node_b] = std::max(damage[rest.node_b], value);
    }
    return damage;
}

[[nodiscard]] Color blendColor(Color from, Color to, double amount) {
    const double t = std::clamp(amount, 0.0, 1.0);
    const auto blend = [t](unsigned char a, unsigned char b) {
        return static_cast<unsigned char>(std::clamp(
            (1.0 - t) * static_cast<double>(a) +
                t * static_cast<double>(b),
            0.0,
            255.0));
    };
    return {
        blend(from.r, to.r),
        blend(from.g, to.g),
        blend(from.b, to.b),
        255,
    };
}

void drawSupportSurface(
    const banjo::SupportPlaneFrame &plane,
    Color surface_color) {
    constexpr double kHalfLength = 10.0;
    constexpr double kHalfWidth = 5.0;
    const Vector3 a = toRaylib(
        banjo::pointInPlaneFrame(plane, -kHalfLength, -kHalfWidth));
    const Vector3 b = toRaylib(
        banjo::pointInPlaneFrame(plane, kHalfLength, -kHalfWidth));
    const Vector3 c = toRaylib(
        banjo::pointInPlaneFrame(plane, kHalfLength, kHalfWidth));
    const Vector3 d = toRaylib(
        banjo::pointInPlaneFrame(plane, -kHalfLength, kHalfWidth));

    const Color fill = blendColor(kFloor, surface_color, 0.32);
    DrawTriangle3D(a, b, c, fill);
    DrawTriangle3D(a, c, d, fill);
    DrawTriangle3D(c, b, a, fill);
    DrawTriangle3D(d, c, a, fill);

    for (int index = -20; index <= 20; ++index) {
        const double distance = 0.5 * static_cast<double>(index);
        DrawLine3D(
            toRaylib(banjo::pointInPlaneFrame(
                plane, distance, -kHalfWidth, 0.002)),
            toRaylib(banjo::pointInPlaneFrame(
                plane, distance, kHalfWidth, 0.002)),
            Fade(WHITE, index % 2 == 0 ? 0.16F : 0.08F));
    }
    for (int index = -10; index <= 10; ++index) {
        const double distance = 0.5 * static_cast<double>(index);
        DrawLine3D(
            toRaylib(banjo::pointInPlaneFrame(
                plane, -kHalfLength, distance, 0.002)),
            toRaylib(banjo::pointInPlaneFrame(
                plane, kHalfLength, distance, 0.002)),
            Fade(WHITE, index % 2 == 0 ? 0.16F : 0.08F));
    }
}

void drawRigidBall(
    const banjo::RollingBallExperiment &experiment,
    banjo::MatterBodyId body_id,
    double radius,
    Color color,
    Color marker_color) {
    const std::optional<banjo::RigidSnapshot> snapshot =
        experiment.rigidSnapshot(body_id);
    if (!snapshot) {
        return;
    }
    const Vector3 center = toRaylib(snapshot->center_of_mass_world_m);
    DrawSphere(center, static_cast<float>(radius), color);
    DrawSphereWires(
        center,
        static_cast<float>(radius),
        16,
        24,
        Fade(marker_color, 0.45F));
    const banjo::Vec3 marker_local =
        snapshot->orientation_world.rotate({radius, 0.0, 0.0});
    DrawLine3D(
        center,
        toRaylib(snapshot->center_of_mass_world_m + marker_local),
        marker_color);
}

void drawActiveMatter(
    const banjo::ActiveMatter &matter,
    Color base_color,
    bool show_bonds,
    bool wireframe) {
    const double voxel_size = matter.asset->recipe.voxel_size_m;
    const float render_size = static_cast<float>(voxel_size * 0.90);
    const std::vector<double> node_damage = calculateNodeDamage(matter);

    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        const Color color = blendColor(base_color, kCrack, node_damage[index]);
        const Vector3 position =
            toRaylib(matter.nodes[index].position_world_m);
        DrawCube(position, render_size, render_size, render_size, color);
        if (wireframe) {
            DrawCubeWires(
                position,
                render_size,
                render_size,
                render_size,
                Fade(WHITE, 0.35F));
        }
    }

    if (!show_bonds) {
        return;
    }
    const std::size_t stride = matter.bonds.size() > 6000U ? 5U : 2U;
    for (std::size_t index = 0; index < matter.bonds.size(); index += stride) {
        const banjo::BondRest &bond = matter.asset->bonds[index];
        const banjo::ActiveBondState &state = matter.bonds[index];
        if (!state.alive && index % (stride * 3U) != 0U) {
            continue;
        }
        DrawLine3D(
            toRaylib(matter.nodes[bond.node_a].position_world_m),
            toRaylib(matter.nodes[bond.node_b].position_world_m),
            state.alive ? Fade(kGlassLight, 0.18F)
                        : Fade(kCrack, 0.80F));
    }
}

void drawFragments(
    const banjo::RollingBallExperiment &experiment,
    const std::vector<FragmentModel> &models,
    Color base_color,
    bool wireframe) {
    for (std::size_t index = 0; index < models.size(); ++index) {
        const FragmentModel &fragment = models[index];
        const std::optional<banjo::RigidSnapshot> snapshot =
            experiment.rigidSnapshot(fragment.body_id);
        if (!snapshot) {
            continue;
        }

        const Quaternion rotation{
            static_cast<float>(snapshot->orientation_world.x),
            static_cast<float>(snapshot->orientation_world.y),
            static_cast<float>(snapshot->orientation_world.z),
            static_cast<float>(snapshot->orientation_world.w),
        };
        Vector3 axis{0.0F, 1.0F, 0.0F};
        float angle_radians = 0.0F;
        QuaternionToAxisAngle(rotation, &axis, &angle_radians);
        const Color tint = blendColor(
            base_color,
            kGlassLight,
            static_cast<double>(index % 7U) / 9.0);
        const Vector3 position =
            toRaylib(snapshot->center_of_mass_world_m);
        DrawModelEx(
            fragment.model,
            position,
            axis,
            angle_radians * RAD2DEG,
            {1.0F, 1.0F, 1.0F},
            tint);
        if (wireframe) {
            DrawModelWiresEx(
                fragment.model,
                position,
                axis,
                angle_radians * RAD2DEG,
                {1.0F, 1.0F, 1.0F},
                Fade(WHITE, 0.45F));
        }
    }

    for (const banjo::DebrisParticleState &particle :
         experiment.debrisParticles()) {
        DrawSphere(
            toRaylib(particle.position_world_m),
            static_cast<float>(particle.radius_m),
            blendColor(base_color, kGlassLight, 0.35));
    }
}

void drawImpact(const std::optional<banjo::ImpactEvent> &impact) {
    if (!impact) {
        return;
    }
    const Vector3 point = toRaylib(impact->contact_point_world_m);
    DrawSphere(point, 0.035F, kCrack);
    DrawLine3D(
        point,
        toRaylib(
            impact->contact_point_world_m +
            0.40 * impact->normal_a_to_b),
        kCrack);
}

[[nodiscard]] std::string formatDouble(double value, int precision = 2) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(precision) << value;
    return stream.str();
}

[[nodiscard]] std::string formatPressure(double pressure_pa) {
    if (pressure_pa >= 1.0e9) {
        return formatDouble(pressure_pa / 1.0e9, 2) + " GPa";
    }
    if (pressure_pa >= 1.0e6) {
        return formatDouble(pressure_pa / 1.0e6, 1) + " MPa";
    }
    return formatDouble(pressure_pa / 1.0e3, 1) + " kPa";
}

void drawOverlay(
    const banjo::RollingBallExperiment &experiment,
    bool paused,
    bool show_bonds,
    bool wireframe,
    double simulation_speed) {
    const banjo::ExperimentStats &stats = experiment.stats();
    const banjo::ExperimentSettings &settings = experiment.settings();

    DrawRectangle(18, 18, 560, 430, Fade(BLACK, 0.80F));
    DrawRectangleLines(18, 18, 560, 430, Fade(kGlassLight, 0.55F));
    DrawText("BANJO // CONTACT-DRIVEN MATERIAL LAB", 34, 32, 20, kText);
    DrawText(
        TextFormat(
            "Phase: %s%s",
            std::string(banjo::experimentPhaseName(stats.phase)).c_str(),
            paused ? "  [PAUSED]" : ""),
        34,
        61,
        18,
        paused ? kIronHighlight : kGlassLight);

    DrawText(TextFormat("Time: %.4f s  |  Tick: %llu", stats.simulated_time_s,
                       static_cast<unsigned long long>(stats.fixed_ticks)),
             34, 416, 15, kMuted);

    int y = 91;
    const auto row = [&y](
                         std::string_view label,
                         const std::string &value,
                         Color color = kText) {
        DrawText(std::string(label).c_str(), 34, y, 15, kMuted);
        DrawText(value.c_str(), 250, y, 15, color);
        y += 21;
    };

    row("Striker / target",
        std::string(banjo::materialPresetName(settings.striker_material)) +
            " / " +
            std::string(banjo::materialPresetName(settings.target_material)));
    row("Surface / slope",
        std::string(banjo::materialPresetName(settings.surface_material)) +
            " / " + formatDouble(settings.surface_slope_degrees, 1) + " deg");
    row("Speed / gravity",
        formatDouble(settings.iron_speed_m_s) + " m/s / " +
            formatDouble(banjo::length(settings.gravity_m_s2)) + " m/s^2");
    row("Masses",
        formatDouble(stats.predicted_striker_mass_kg, 1) + " / " +
            formatDouble(stats.predicted_target_mass_kg, 1) + " kg");
    row("Predicted contact",
        std::string(banjo::predictedFailureModeName(stats.predicted_failure)),
        stats.predicted_failure == banjo::PredictedFailureMode::Fragmentation
            ? kCrack
            : kText);
    row("Runtime plan",
        std::string(banjo::runtimeStrategyName(stats.runtime_strategy)) +
            (stats.projection_cache_hit ? " [projection cache]" : " [calculated]"));
    row("Slope regime",
        std::string(banjo::inclineMotionRegimeName(
            stats.predicted_incline_regime)) +
            " / " +
            formatDouble(stats.predicted_slope_acceleration_m_s2, 2) +
            " m/s^2");
    row("Peak force / pressure",
        formatDouble(stats.predicted_peak_force_n / 1000.0, 1) +
            " kN / " + formatPressure(stats.predicted_peak_pressure_pa));
    row("Actual impact",
        stats.impact_energy_j > 0.0
            ? formatDouble(stats.impact_speed_m_s, 2) + " m/s / " +
                  formatDouble(stats.impact_energy_j, 1) + " J"
            : "waiting");
    row("Actual contact mu / e",
        stats.impact_energy_j > 0.0
            ? formatDouble(stats.actual_contact_friction, 3) + " / " +
                  formatDouble(stats.actual_contact_restitution, 3)
            : "waiting");
    row("Voxel nodes / bonds",
        TextFormat("%zu / %zu", stats.active_nodes, stats.total_bonds));
    row("Broken / components",
        TextFormat("%zu / %zu", stats.broken_bonds, stats.connected_components),
        stats.broken_bonds > 0U ? kCrack : kText);
    row("Rigid / debris",
        TextFormat("%zu / %zu", stats.rigid_fragments, stats.debris_particles));
    row("Mass error", formatDouble(stats.mass_error_kg, 8) + " kg");

    const int panel_x = GetScreenWidth() - 412;
    DrawRectangle(panel_x, 64, 394, 250, Fade(BLACK, 0.82F));
    DrawText("MEASURED MOTION / CONTACT", panel_x + 12, 77, 16, kGlassLight);
    int motion_y = 102;
    const auto motion_line = [&](const std::string &text) {
        DrawText(text.c_str(), panel_x + 12, motion_y, 15, kText);
        motion_y += 22;
    };
    motion_line("Striker: " + std::string(banjo::rollingStateName(stats.striker_motion.state)));
    motion_line("v / r*w: " + formatDouble(stats.striker_motion.translation_speed_m_s, 3) +
        " / " + formatDouble(stats.striker_motion.rolling_surface_speed_m_s, 3) + " m/s");
    motion_line("Contact slip: " + formatDouble(stats.striker_motion.contact_slip_speed_m_s, 4) + " m/s");
    motion_line("Initial spin ratio: " + formatDouble(settings.striker_spin_ratio, 1) + " [L]");
    motion_line("Target: " + (experiment.phase() == banjo::ExperimentPhase::Rigid
        ? std::string(banjo::rollingStateName(stats.target_motion.state)) : "active / fragmented"));
    motion_line("Coupled contact impulses: " + std::to_string(stats.coupled_contact_points));
    motion_line("Transferred impulse: " + formatDouble(stats.coupled_impulse_n_s, 2) + " N s");
    motion_line("Contact loss: " + formatDouble(stats.coupled_contact_dissipation_j, 2) + " J");
    motion_line("Synthetic fracture pulse: OFF");

    DrawText(
        TextFormat(
            "R reset  SPACE pause  N step  B bonds [%s]  W wire [%s]",
            show_bonds ? "on" : "off",
            wireframe ? "on" : "off"),
        24,
        GetScreenHeight() - 85,
        16,
        kText);
    DrawText(
        "M striker  T target  S surface  [ / ] slope  UP/DOWN speed  L spin",
        24,
        GetScreenHeight() - 59,
        16,
        kText);
    DrawText(
        TextFormat(
            "1/2/3 voxels  G gravity magnitude  V gravity direction  RMB orbit  wheel zoom  %.2fx",
            simulation_speed),
        24,
        GetScreenHeight() - 33,
        16,
        kMuted);
    DrawFPS(GetScreenWidth() - 100, 24);
}

[[nodiscard]] Camera3D makeCamera(
    float yaw,
    float pitch,
    float distance,
    const banjo::SupportPlaneFrame &plane) {
    const Vector3 target = toRaylib(
        plane.point_world_m + 0.35 * plane.normal_world);
    Camera3D camera{};
    camera.target = target;
    camera.position = {
        target.x + distance * std::cos(pitch) * std::cos(yaw),
        target.y + distance * std::sin(pitch),
        target.z + distance * std::cos(pitch) * std::sin(yaw),
    };
    camera.up = {0.0F, 1.0F, 0.0F};
    camera.fovy = 45.0F;
    camera.projection = CAMERA_PERSPECTIVE;
    return camera;
}

void cycleGravityMagnitude(banjo::ExperimentSettings &settings) {
    const double magnitude = banjo::length(settings.gravity_m_s2);
    const banjo::Vec3 direction =
        banjo::normalized(settings.gravity_m_s2, {0.0, -1.0, 0.0});
    if (magnitude > 5.0) {
        settings.gravity_m_s2 = 1.62 * direction;
    } else if (magnitude > 0.1) {
        settings.gravity_m_s2 = {};
    } else {
        settings.gravity_m_s2 = {0.0, -9.81, 0.0};
    }
}

void cycleGravityDirection(banjo::ExperimentSettings &settings) {
    double magnitude = banjo::length(settings.gravity_m_s2);
    if (magnitude < 0.1) {
        magnitude = 9.81;
    }
    const banjo::Vec3 direction =
        banjo::normalized(settings.gravity_m_s2, {0.0, -1.0, 0.0});
    if (direction.y < -0.5) {
        settings.gravity_m_s2 = {magnitude, 0.0, 0.0};
    } else if (direction.x > 0.5) {
        settings.gravity_m_s2 = {0.0, magnitude, 0.0};
    } else {
        settings.gravity_m_s2 = {0.0, -magnitude, 0.0};
    }
}

} // namespace

int main(int argc, char **argv) {
    try {
        const ViewerOptions options = parseOptions(argc, argv);
        const bool capture_mode = !options.capture_path.empty();

        SetConfigFlags(FLAG_MSAA_4X_HINT | FLAG_WINDOW_RESIZABLE);
        InitWindow(1280, 800, "Banjo — First-Principles Matter Lab");
        SetTargetFPS(60);

        banjo::ExperimentSettings settings;
        banjo::RollingBallExperiment experiment(settings);
        if (!options.cache_path.empty()) {
            (void)experiment.loadProjectionCache(options.cache_path);
        }
        std::vector<FragmentModel> fragment_models;

        bool paused = false;
        bool single_step = false;
        bool show_bonds = false;
        bool wireframe = false;
        double simulation_speed = capture_mode ? 1.0 : 0.60;
        double accumulator_s = 0.0;

        float camera_yaw = -2.45F;
        float camera_pitch = 0.32F;
        float camera_distance = 4.1F;
        unsigned rendered_frames = 0U;

        while (!WindowShouldClose()) {
            if (!capture_mode) {
                // A press and release can both arrive between rendered frames.
                // The final key state then misses the tap; the event queue keeps it.
                std::vector<int> pressed_keys;
                for (int key = GetKeyPressed(); key != 0; key = GetKeyPressed()) {
                    pressed_keys.push_back(key);
                }
                const auto pressed = [&](int key) {
                    return std::find(pressed_keys.begin(), pressed_keys.end(), key) !=
                           pressed_keys.end();
                };
                if (pressed(KEY_SPACE)) {
                    paused = !paused;
                }
                if (pressed(KEY_N)) {
                    single_step = true;
                }
                if (pressed(KEY_B)) {
                    show_bonds = !show_bonds;
                }
                if (pressed(KEY_W)) {
                    wireframe = !wireframe;
                }

                bool reset = pressed(KEY_R);
                if (pressed(KEY_UP)) {
                    settings.iron_speed_m_s =
                        std::min(18.0, settings.iron_speed_m_s + 1.0);
                    reset = true;
                }
                if (pressed(KEY_DOWN)) {
                    settings.iron_speed_m_s =
                        std::max(0.5, settings.iron_speed_m_s - 1.0);
                    reset = true;
                }
                if (pressed(KEY_ONE)) {
                    settings.voxel_size_m = 0.050;
                    reset = true;
                }
                if (pressed(KEY_TWO)) {
                    settings.voxel_size_m = 0.040;
                    reset = true;
                }
                if (pressed(KEY_THREE)) {
                    settings.voxel_size_m = 0.032;
                    reset = true;
                }
                if (pressed(KEY_M)) {
                    settings.striker_material =
                        banjo::nextMaterialPreset(settings.striker_material);
                    reset = true;
                }
                if (pressed(KEY_T)) {
                    settings.target_material =
                        banjo::nextMaterialPreset(settings.target_material);
                    reset = true;
                }
                if (pressed(KEY_S)) {
                    settings.surface_material =
                        banjo::nextMaterialPreset(settings.surface_material);
                    reset = true;
                }
                if (pressed(KEY_LEFT_BRACKET)) {
                    settings.surface_slope_degrees = std::max(
                        -30.0, settings.surface_slope_degrees - 5.0);
                    reset = true;
                }
                if (pressed(KEY_RIGHT_BRACKET)) {
                    settings.surface_slope_degrees = std::min(
                        30.0, settings.surface_slope_degrees + 5.0);
                    reset = true;
                }
                if (pressed(KEY_L)) {
                    const double ratio = settings.striker_spin_ratio;
                    settings.striker_spin_ratio = ratio == 1.0 ? 0.0
                        : ratio == 0.0 ? -1.0 : ratio == -1.0 ? 2.0 : 1.0;
                    reset = true;
                }
                if (pressed(KEY_G)) {
                    cycleGravityMagnitude(settings);
                    reset = true;
                }
                if (pressed(KEY_V)) {
                    cycleGravityDirection(settings);
                    reset = true;
                }
                if (reset) {
                    unloadModels(fragment_models);
                    experiment.reset(settings);
                    accumulator_s = 0.0;
                    paused = false;
                }

                if (IsMouseButtonDown(MOUSE_BUTTON_RIGHT)) {
                    const Vector2 delta = GetMouseDelta();
                    camera_yaw -= 0.006F * delta.x;
                    camera_pitch = std::clamp(
                        camera_pitch - 0.006F * delta.y,
                        -0.15F,
                        1.25F);
                }
                camera_distance = std::clamp(
                    camera_distance - 0.30F * GetMouseWheelMove(),
                    1.8F,
                    9.0F);
            }

            const double frame_dt =
                capture_mode ? 1.0 / 60.0 : GetFrameTime();
            if (!paused || capture_mode) {
                accumulator_s +=
                    std::min(frame_dt, 0.05) * simulation_speed;
            }
            if (single_step) {
                accumulator_s =
                    std::max(accumulator_s, settings.rigid_step_s);
                single_step = false;
            }

            unsigned fixed_steps_this_frame = 0U;
            while (accumulator_s + 1.0e-12 >= settings.rigid_step_s &&
                   fixed_steps_this_frame < 12U) {
                experiment.stepFixed();
                accumulator_s -= settings.rigid_step_s;
                ++fixed_steps_this_frame;
            }
            // Retain unprocessed simulation time. A slow solver slows display
            // progression instead of silently skipping part of the experiment.
            syncFragmentModels(experiment, fragment_models);

            const Camera3D camera = makeCamera(
                camera_yaw,
                camera_pitch,
                camera_distance,
                experiment.supportPlane());
            const Color striker_color = materialColor(settings.striker_material);
            const Color target_color = materialColor(settings.target_material);
            const Color surface_color = materialColor(settings.surface_material);

            BeginDrawing();
            ClearBackground(kBackground);
            BeginMode3D(camera);

            drawSupportSurface(experiment.supportPlane(), surface_color);
            drawRigidBall(
                experiment,
                banjo::RollingBallExperiment::kStrikerBallId,
                settings.radius_m,
                striker_color,
                kIronHighlight);

            if (experiment.phase() == banjo::ExperimentPhase::Rigid) {
                drawRigidBall(
                    experiment,
                    banjo::RollingBallExperiment::kTargetBallId,
                    settings.radius_m,
                    target_color,
                    kGlassLight);
            } else if (const banjo::ActiveMatter *matter =
                           experiment.activeMatter()) {
                drawActiveMatter(
                    *matter,
                    blendColor(target_color, kGlassLight, 0.30),
                    show_bonds,
                    wireframe);
            } else {
                drawFragments(
                    experiment,
                    fragment_models,
                    target_color,
                    wireframe);
            }
            drawImpact(experiment.activatingImpact());

            EndMode3D();
            drawOverlay(
                experiment,
                paused,
                show_bonds,
                wireframe,
                simulation_speed);
            EndDrawing();

            ++rendered_frames;
            if (capture_mode && rendered_frames >= options.capture_frames) {
                const std::filesystem::path capture_path(options.capture_path);
                if (capture_path.has_parent_path()) {
                    std::filesystem::create_directories(
                        capture_path.parent_path());
                }
                TakeScreenshot(options.capture_path.c_str());
                break;
            }
        }

        unloadModels(fragment_models);
        CloseWindow();
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        TraceLog(LOG_ERROR, "Fatal error: %s", error.what());
        if (IsWindowReady()) {
            CloseWindow();
        }
        return EXIT_FAILURE;
    }
}
