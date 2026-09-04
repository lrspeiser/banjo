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
constexpr Color kIron{116, 124, 136, 255};
constexpr Color kIronHighlight{225, 198, 93, 255};
constexpr Color kGlass{83, 185, 222, 255};
constexpr Color kGlassLight{156, 224, 244, 255};
constexpr Color kCrack{255, 111, 76, 255};
constexpr Color kDebris{119, 204, 232, 255};
constexpr Color kText{231, 236, 243, 255};
constexpr Color kMuted{156, 165, 180, 255};

struct ViewerOptions {
    std::string capture_path;
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
        } else if (argument == "--frames") {
            if (index + 1 >= argc) {
                throw std::invalid_argument("--frames requires a positive integer");
            }
            options.capture_frames = static_cast<unsigned>(std::stoul(argv[++index]));
            if (options.capture_frames == 0U) {
                throw std::invalid_argument("--frames must be positive");
            }
        } else {
            throw std::invalid_argument("unknown command-line argument: " + std::string(argument));
        }
    }
    return options;
}

[[nodiscard]] Model buildModel(const banjo::FragmentSurfaceMesh &source) {
    if (source.indices.empty() || source.indices.size() % 3U != 0U) {
        throw std::invalid_argument("fragment surface does not contain triangles");
    }
    if (source.indices.size() >
        static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw std::overflow_error("fragment surface is too large for raylib");
    }

    Mesh mesh{};
    mesh.vertexCount = static_cast<int>(source.indices.size());
    mesh.triangleCount = mesh.vertexCount / 3;

    const std::size_t value_count = source.indices.size() * 3U;
    const std::size_t byte_count = value_count * sizeof(float);
    if (byte_count > std::numeric_limits<unsigned int>::max()) {
        throw std::overflow_error("fragment vertex buffer exceeds raylib allocator limit");
    }
    mesh.vertices = static_cast<float *>(MemAlloc(static_cast<unsigned int>(byte_count)));
    mesh.normals = static_cast<float *>(MemAlloc(static_cast<unsigned int>(byte_count)));
    if (mesh.vertices == nullptr || mesh.normals == nullptr) {
        throw std::bad_alloc();
    }

    for (std::size_t output = 0; output < source.indices.size(); ++output) {
        const std::uint32_t source_index = source.indices[output];
        if (source_index >= source.vertices.size()) {
            throw std::out_of_range("fragment surface index is invalid");
        }
        const banjo::SurfaceVertex &vertex = source.vertices[source_index];
        mesh.vertices[3U * output + 0U] = static_cast<float>(vertex.position_local_m.x);
        mesh.vertices[3U * output + 1U] = static_cast<float>(vertex.position_local_m.y);
        mesh.vertices[3U * output + 2U] = static_cast<float>(vertex.position_local_m.z);
        mesh.normals[3U * output + 0U] = static_cast<float>(vertex.normal_local.x);
        mesh.normals[3U * output + 1U] = static_cast<float>(vertex.normal_local.y);
        mesh.normals[3U * output + 2U] = static_cast<float>(vertex.normal_local.z);
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

[[nodiscard]] std::vector<double> calculateNodeDamage(const banjo::ActiveMatter &matter) {
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
        return static_cast<unsigned char>(
            std::clamp((1.0 - t) * static_cast<double>(a) + t * static_cast<double>(b),
                       0.0,
                       255.0));
    };
    return {blend(from.r, to.r), blend(from.g, to.g), blend(from.b, to.b), 255};
}

void drawRigidBall(
    const banjo::RollingBallExperiment &experiment,
    banjo::MatterBodyId body_id,
    double radius,
    Color color,
    Color marker_color) {
    const std::optional<banjo::RigidSnapshot> snapshot = experiment.rigidSnapshot(body_id);
    if (!snapshot) {
        return;
    }
    const Vector3 center = toRaylib(snapshot->center_of_mass_world_m);
    DrawSphere(center, static_cast<float>(radius), color);
    DrawSphereWires(center, static_cast<float>(radius), 16, 24, Fade(marker_color, 0.45F));
    const banjo::Vec3 marker_local = snapshot->orientation_world.rotate({radius, 0.0, 0.0});
    DrawLine3D(center, toRaylib(snapshot->center_of_mass_world_m + marker_local), marker_color);
}

void drawActiveMatter(const banjo::ActiveMatter &matter, bool show_bonds, bool wireframe) {
    const double voxel_size = matter.asset->recipe.voxel_size_m;
    const float render_size = static_cast<float>(voxel_size * 0.90);
    const std::vector<double> node_damage = calculateNodeDamage(matter);

    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        const Color color = blendColor(kGlassLight, kCrack, node_damage[index]);
        const Vector3 position = toRaylib(matter.nodes[index].position_world_m);
        DrawCube(position, render_size, render_size, render_size, color);
        if (wireframe) {
            DrawCubeWires(position, render_size, render_size, render_size, Fade(WHITE, 0.35F));
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
            state.alive ? Fade(kGlassLight, 0.18F) : Fade(kCrack, 0.80F));
    }
}

void drawFragments(
    const banjo::RollingBallExperiment &experiment,
    const std::vector<FragmentModel> &models,
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
        const float angle_degrees = angle_radians * RAD2DEG;
        const Color tint = blendColor(
            kGlass,
            kGlassLight,
            static_cast<double>(index % 7U) / 9.0);
        const Vector3 position = toRaylib(snapshot->center_of_mass_world_m);
        DrawModelEx(
            fragment.model,
            position,
            axis,
            angle_degrees,
            {1.0F, 1.0F, 1.0F},
            tint);
        if (wireframe) {
            DrawModelWiresEx(
                fragment.model,
                position,
                axis,
                angle_degrees,
                {1.0F, 1.0F, 1.0F},
                Fade(WHITE, 0.45F));
        }
    }

    for (const banjo::DebrisParticleState &particle : experiment.debrisParticles()) {
        DrawSphere(
            toRaylib(particle.position_world_m),
            static_cast<float>(particle.radius_m),
            kDebris);
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
        toRaylib(impact->contact_point_world_m + 0.40 * impact->normal_a_to_b),
        kCrack);
}

[[nodiscard]] std::string formatDouble(double value, int precision = 2) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(precision) << value;
    return stream.str();
}

void drawOverlay(
    const banjo::RollingBallExperiment &experiment,
    bool paused,
    bool show_bonds,
    bool wireframe,
    double simulation_speed) {
    const banjo::ExperimentStats &stats = experiment.stats();
    const banjo::ExperimentSettings &settings = experiment.settings();

    DrawRectangle(18, 18, 430, 324, Fade(BLACK, 0.78F));
    DrawRectangleLines(18, 18, 430, 324, Fade(kGlass, 0.60F));
    DrawText("BANJO // MATTER TRANSITION LAB", 34, 32, 20, kText);
    DrawText(TextFormat("Phase: %s%s",
                        std::string(banjo::experimentPhaseName(stats.phase)).c_str(),
                        paused ? "  [PAUSED]" : ""),
             34,
             63,
             18,
             paused ? kIronHighlight : kGlassLight);

    int y = 94;
    const auto row = [&y](std::string_view label, const std::string &value, Color color = kText) {
        DrawText(std::string(label).c_str(), 34, y, 16, kMuted);
        DrawText(value.c_str(), 225, y, 16, color);
        y += 23;
    };
    row("Iron speed", formatDouble(settings.iron_speed_m_s) + " m/s");
    row("Voxel size", formatDouble(settings.voxel_size_m * 1000.0, 0) + " mm");
    row("Nodes / bonds", TextFormat("%zu / %zu", stats.active_nodes, stats.total_bonds));
    row("Broken bonds", TextFormat("%zu", stats.broken_bonds), stats.broken_bonds > 0 ? kCrack : kText);
    row("Components", TextFormat("%zu", stats.connected_components));
    row("Rigid / debris", TextFormat("%zu / %zu", stats.rigid_fragments, stats.debris_particles));
    row("Impact energy",
        stats.impact_energy_j > 0.0 ? formatDouble(stats.impact_energy_j, 1) + " J" : "waiting");
    row("Threshold ratio",
        stats.normalized_impact_energy > 0.0
            ? formatDouble(stats.normalized_impact_energy, 1) + "x"
            : "waiting");
    row("Mass error", formatDouble(stats.mass_error_kg, 8) + " kg");

    DrawText(TextFormat("R reset   SPACE pause   N step   B bonds [%s]   W wire [%s]",
                        show_bonds ? "on" : "off",
                        wireframe ? "on" : "off"),
             24,
             GetScreenHeight() - 64,
             16,
             kText);
    DrawText(TextFormat("UP/DOWN speed   1/2/3 voxel detail   G gravity   RMB orbit   wheel zoom   sim %.2fx",
                        simulation_speed),
             24,
             GetScreenHeight() - 38,
             16,
             kMuted);
    DrawFPS(GetScreenWidth() - 100, 24);
}

[[nodiscard]] Camera3D makeCamera(float yaw, float pitch, float distance) {
    const Vector3 target{0.0F, 0.35F, 0.0F};
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

} // namespace

int main(int argc, char **argv) {
    try {
        const ViewerOptions options = parseOptions(argc, argv);
        const bool capture_mode = !options.capture_path.empty();

        SetConfigFlags(FLAG_MSAA_4X_HINT | FLAG_WINDOW_RESIZABLE);
        InitWindow(1280, 800, "Banjo — Editable Matter Transition Lab");
        SetTargetFPS(60);

        banjo::ExperimentSettings settings;
        banjo::RollingBallExperiment experiment(settings);
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
                if (IsKeyPressed(KEY_SPACE)) {
                    paused = !paused;
                }
                if (IsKeyPressed(KEY_N)) {
                    single_step = true;
                }
                if (IsKeyPressed(KEY_B)) {
                    show_bonds = !show_bonds;
                }
                if (IsKeyPressed(KEY_W)) {
                    wireframe = !wireframe;
                }

                bool reset = IsKeyPressed(KEY_R);
                if (IsKeyPressed(KEY_UP)) {
                    settings.iron_speed_m_s = std::min(18.0, settings.iron_speed_m_s + 1.0);
                    reset = true;
                }
                if (IsKeyPressed(KEY_DOWN)) {
                    settings.iron_speed_m_s = std::max(1.0, settings.iron_speed_m_s - 1.0);
                    reset = true;
                }
                if (IsKeyPressed(KEY_ONE)) {
                    settings.voxel_size_m = 0.050;
                    reset = true;
                }
                if (IsKeyPressed(KEY_TWO)) {
                    settings.voxel_size_m = 0.040;
                    reset = true;
                }
                if (IsKeyPressed(KEY_THREE)) {
                    settings.voxel_size_m = 0.032;
                    reset = true;
                }
                if (IsKeyPressed(KEY_G)) {
                    if (std::abs(settings.gravity_m_s2.y + 9.81) < 0.01) {
                        settings.gravity_m_s2 = {0.0, 0.0, -9.81};
                    } else if (std::abs(settings.gravity_m_s2.z + 9.81) < 0.01) {
                        settings.gravity_m_s2 = {0.0, 9.81, 0.0};
                    } else {
                        settings.gravity_m_s2 = {0.0, -9.81, 0.0};
                    }
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
                    camera_pitch = std::clamp(camera_pitch - 0.006F * delta.y, -0.15F, 1.25F);
                }
                camera_distance = std::clamp(
                    camera_distance - 0.30F * GetMouseWheelMove(), 1.8F, 9.0F);
            }

            const double frame_dt = capture_mode ? 1.0 / 60.0 : GetFrameTime();
            if (!paused || capture_mode) {
                accumulator_s += std::min(frame_dt, 0.05) * simulation_speed;
            }
            if (single_step) {
                accumulator_s = std::max(accumulator_s, settings.rigid_step_s);
                single_step = false;
            }

            unsigned fixed_steps_this_frame = 0U;
            while (accumulator_s + 1.0e-12 >= settings.rigid_step_s &&
                   fixed_steps_this_frame < 12U) {
                experiment.stepFixed();
                accumulator_s -= settings.rigid_step_s;
                ++fixed_steps_this_frame;
            }
            if (fixed_steps_this_frame == 12U) {
                accumulator_s = 0.0;
            }
            syncFragmentModels(experiment, fragment_models);

            const Camera3D camera = makeCamera(camera_yaw, camera_pitch, camera_distance);
            BeginDrawing();
            ClearBackground(kBackground);
            BeginMode3D(camera);

            DrawPlane({0.0F, -0.002F, 0.0F}, {20.0F, 10.0F}, kFloor);
            DrawGrid(40, 0.25F);

            drawRigidBall(
                experiment,
                banjo::RollingBallExperiment::kIronBallId,
                settings.radius_m,
                kIron,
                kIronHighlight);

            if (experiment.phase() == banjo::ExperimentPhase::Rigid) {
                drawRigidBall(
                    experiment,
                    banjo::RollingBallExperiment::kGlassBallId,
                    settings.radius_m,
                    kGlass,
                    kGlassLight);
            } else if (const banjo::ActiveMatter *matter = experiment.activeMatter()) {
                drawActiveMatter(*matter, show_bonds, wireframe);
            } else {
                drawFragments(experiment, fragment_models, wireframe);
            }
            drawImpact(experiment.activatingImpact());

            EndMode3D();
            drawOverlay(experiment, paused, show_bonds, wireframe, simulation_speed);
            EndDrawing();

            ++rendered_frames;
            if (capture_mode && rendered_frames >= options.capture_frames) {
                const std::filesystem::path capture_path(options.capture_path);
                if (capture_path.has_parent_path()) {
                    std::filesystem::create_directories(capture_path.parent_path());
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
