#include <raylib.h>
#include <raymath.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using json = nlohmann::json;

constexpr std::uintmax_t kMaxReportBytes = 64U * 1024U * 1024U;
constexpr std::size_t kMaxCases = 4U;
constexpr std::size_t kMaxFrames = 256U;
constexpr std::size_t kMaxNodes = 4096U;
constexpr std::size_t kMaxTriangles = 32768U;
constexpr double kCoordinateLimitM = 1000.0;
constexpr double kDisplacementLimitM = 1000.0;
constexpr int kFooterHeight = 216;

struct Vec3d {
    double x{};
    double y{};
    double z{};
};

Vec3d operator+(Vec3d a, Vec3d b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3d operator-(Vec3d a, Vec3d b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3d operator*(Vec3d a, double b) { return {a.x * b, a.y * b, a.z * b}; }

Vector3 toRaylib(Vec3d value) {
    return {static_cast<float>(value.x), static_cast<float>(value.y),
            static_cast<float>(value.z)};
}

struct Frame {
    double load_fraction{};
    std::string phase;
    std::vector<Vec3d> displacements_m;
    bool accepted{};
    double stored_free_energy_j{};
    double plastic_dissipation_j{};
    double maximum_equivalent_plastic_strain{};
    double free_force_residual_n{};
    std::string error;
    double maximum_displacement_m{};
};

struct ContinuumCase {
    std::string name;
    std::string material_id;
    std::vector<Vec3d> reference_positions_m;
    std::vector<std::array<std::size_t, 3>> boundary_triangles;
    std::vector<Frame> frames;
    std::string status{"unknown"};
    std::string error;
};

struct Report {
    std::vector<ContinuumCase> cases;
    double maximum_plastic_strain{};
    double maximum_displacement_m{};
};

struct ViewerOptions {
    std::filesystem::path report_path;
    std::filesystem::path capture_path;
};

[[noreturn]] void invalid(const std::string &message) {
    throw std::invalid_argument("invalid continuum report: " + message);
}

double finiteNumber(const json &value, const std::string &field) {
    if (!value.is_number()) {
        invalid(field + " must be a number");
    }
    const double result = value.get<double>();
    if (!std::isfinite(result)) {
        invalid(field + " must be finite");
    }
    return result;
}

std::string boundedString(const json &value, const std::string &field,
                          bool allow_empty = false) {
    if (!value.is_string()) {
        invalid(field + " must be a string");
    }
    std::string result = value.get<std::string>();
    if (!allow_empty && result.empty()) {
        invalid(field + " must not be empty");
    }
    if (result.size() > 512U) {
        invalid(field + " is too long");
    }
    return result;
}

Vec3d vector3(const json &value, const std::string &field,
              double coordinate_limit) {
    if (!value.is_array() || value.size() != 3U) {
        invalid(field + " must contain exactly three numbers");
    }
    Vec3d result{};
    double *components[] = {&result.x, &result.y, &result.z};
    for (std::size_t component = 0; component < 3U; ++component) {
        *components[component] = finiteNumber(
            value[component], field + "[" + std::to_string(component) + "]");
        if (std::abs(*components[component]) > coordinate_limit) {
            invalid(field + " exceeds the bounded world extent");
        }
    }
    return result;
}

const json &required(const json &object, const char *key,
                     const std::string &context) {
    if (!object.is_object() || !object.contains(key)) {
        invalid(context + " is missing " + key);
    }
    return object.at(key);
}

Report loadReport(const std::filesystem::path &path) {
    std::error_code error;
    const std::uintmax_t size = std::filesystem::file_size(path, error);
    if (error) {
        throw std::runtime_error("cannot stat report: " + path.string());
    }
    if (size > kMaxReportBytes) {
        throw std::runtime_error("continuum report exceeds 64 MiB");
    }

    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("cannot open report: " + path.string());
    }
    std::string source;
    source.resize(static_cast<std::size_t>(size));
    if (size != 0U) {
        input.read(source.data(), static_cast<std::streamsize>(size));
    }
    if (!input && !input.eof()) {
        throw std::runtime_error("cannot read report: " + path.string());
    }

    json document;
    try {
        document = json::parse(source);
    } catch (const std::exception &exception) {
        throw std::invalid_argument("invalid continuum report JSON: " +
                                    std::string(exception.what()));
    }
    if (!document.is_object()) {
        invalid("top level must be an object");
    }
    if (boundedString(required(document, "schema", "report"), "schema") !=
        "banjo.continuum-patch-trial.v1") {
        invalid("unsupported schema");
    }
    const json &cases = required(document, "cases", "report");
    if (!cases.is_array() || cases.empty() || cases.size() > kMaxCases) {
        invalid("cases must contain between one and four entries");
    }

    Report result;
    result.cases.reserve(cases.size());
    for (std::size_t case_index = 0; case_index < cases.size(); ++case_index) {
        const json &source_case = cases[case_index];
        const std::string prefix = "cases[" + std::to_string(case_index) + "]";
        if (!source_case.is_object()) {
            invalid(prefix + " must be an object");
        }
        ContinuumCase parsed_case{
            boundedString(required(source_case, "name", prefix), prefix + ".name"),
            boundedString(required(source_case, "material_id", prefix),
                           prefix + ".material_id"),
            {},
            {},
            {},
            "unknown",
            {},
        };

        if (source_case.contains("status")) {
            parsed_case.status = boundedString(source_case.at("status"),
                                               prefix + ".status");
        }
        if (source_case.contains("error")) {
            parsed_case.error = boundedString(source_case.at("error"),
                                              prefix + ".error", true);
        }
        const json &limitations = required(source_case, "limitations", prefix);
        if (!limitations.is_array() || limitations.size() > 32U) {
            invalid(prefix + ".limitations must contain at most 32 strings");
        }
        for (std::size_t limitation = 0; limitation < limitations.size();
             ++limitation) {
            (void)boundedString(
                limitations[limitation], prefix + ".limitations[" +
                                               std::to_string(limitation) + "]",
                true);
        }

        const json &positions =
            required(source_case, "reference_positions_m", prefix);
        if (!positions.is_array() || positions.size() < 4U ||
            positions.size() > kMaxNodes) {
            invalid(prefix + ".reference_positions_m must contain 4..4096 nodes");
        }
        parsed_case.reference_positions_m.reserve(positions.size());
        for (std::size_t node = 0; node < positions.size(); ++node) {
            parsed_case.reference_positions_m.push_back(vector3(
                positions[node], prefix + ".reference_positions_m[" +
                                    std::to_string(node) + "]",
                kCoordinateLimitM));
        }

        const json &triangles = required(source_case, "boundary_triangles", prefix);
        if (!triangles.is_array() || triangles.empty() ||
            triangles.size() > kMaxTriangles) {
            invalid(prefix + ".boundary_triangles must contain 1..32768 triangles");
        }
        parsed_case.boundary_triangles.reserve(triangles.size());
        for (std::size_t triangle = 0; triangle < triangles.size(); ++triangle) {
            const json &indices = triangles[triangle];
            if (!indices.is_array() || indices.size() != 3U) {
                invalid(prefix + ".boundary_triangles[" +
                        std::to_string(triangle) + "] must contain three indices");
            }
            std::array<std::size_t, 3> parsed_indices{};
            for (std::size_t corner = 0; corner < 3U; ++corner) {
                if (!indices[corner].is_number_integer()) {
                    invalid(prefix + ".boundary_triangles index must be an integer");
                }
                const auto signed_index = indices[corner].get<long long>();
                if (signed_index < 0 ||
                    static_cast<std::uintmax_t>(signed_index) >=
                        parsed_case.reference_positions_m.size()) {
                    invalid(prefix + ".boundary_triangles contains an out-of-range index");
                }
                parsed_indices[corner] = static_cast<std::size_t>(signed_index);
            }
            const Vec3d edge_a = parsed_case.reference_positions_m[parsed_indices[1]] -
                                 parsed_case.reference_positions_m[parsed_indices[0]];
            const Vec3d edge_b = parsed_case.reference_positions_m[parsed_indices[2]] -
                                 parsed_case.reference_positions_m[parsed_indices[0]];
            const Vec3d cross_product{
                edge_a.y * edge_b.z - edge_a.z * edge_b.y,
                edge_a.z * edge_b.x - edge_a.x * edge_b.z,
                edge_a.x * edge_b.y - edge_a.y * edge_b.x,
            };
            const double area_measure = cross_product.x * cross_product.x +
                                        cross_product.y * cross_product.y +
                                        cross_product.z * cross_product.z;
            if (area_measure <= 1.0e-28) {
                invalid(prefix + ".boundary_triangles contains a degenerate triangle");
            }
            parsed_case.boundary_triangles.push_back(parsed_indices);
        }

        const json &frames = required(source_case, "frames", prefix);
        if (!frames.is_array() || frames.empty() || frames.size() > kMaxFrames) {
            invalid(prefix + ".frames must contain 1..256 frames");
        }
        parsed_case.frames.reserve(frames.size());
        for (std::size_t frame_index = 0; frame_index < frames.size(); ++frame_index) {
            const json &source_frame = frames[frame_index];
            const std::string frame_prefix = prefix + ".frames[" +
                                              std::to_string(frame_index) + "]";
            if (!source_frame.is_object()) {
                invalid(frame_prefix + " must be an object");
            }
            Frame frame{};
            frame.load_fraction = finiteNumber(
                required(source_frame, "load_fraction", frame_prefix),
                frame_prefix + ".load_fraction");
            if (frame.load_fraction < 0.0 || frame.load_fraction > 1.0) {
                invalid(frame_prefix + ".load_fraction must be in [0,1]");
            }
            frame.phase = boundedString(
                required(source_frame, "phase", frame_prefix),
                frame_prefix + ".phase");
            if (frame.phase != "initial" && frame.phase != "load" &&
                frame.phase != "unload") {
                invalid(frame_prefix + ".phase must be initial, load, or unload");
            }
            const json &displacements =
                required(source_frame, "displacements_m", frame_prefix);
            if (!displacements.is_array() ||
                displacements.size() != parsed_case.reference_positions_m.size()) {
                invalid(frame_prefix + ".displacements_m must match node count");
            }
            frame.displacements_m.reserve(displacements.size());
            for (std::size_t node = 0; node < displacements.size(); ++node) {
                frame.displacements_m.push_back(vector3(
                    displacements[node], frame_prefix + ".displacements_m[" +
                                               std::to_string(node) + "]",
                    kDisplacementLimitM));
                const Vec3d displacement = frame.displacements_m.back();
                result.maximum_displacement_m = std::max(
                    result.maximum_displacement_m,
                    std::sqrt(displacement.x * displacement.x +
                              displacement.y * displacement.y +
                              displacement.z * displacement.z));
            }
            const json &accepted = required(source_frame, "accepted", frame_prefix);
            if (!accepted.is_boolean()) {
                invalid(frame_prefix + ".accepted must be boolean");
            }
            frame.accepted = accepted.get<bool>();
            frame.stored_free_energy_j = finiteNumber(
                required(source_frame, "stored_free_energy_j", frame_prefix),
                frame_prefix + ".stored_free_energy_j");
            frame.plastic_dissipation_j = finiteNumber(
                required(source_frame, "plastic_dissipation_j", frame_prefix),
                frame_prefix + ".plastic_dissipation_j");
            frame.maximum_equivalent_plastic_strain = finiteNumber(
                required(source_frame, "maximum_equivalent_plastic_strain", frame_prefix),
                frame_prefix + ".maximum_equivalent_plastic_strain");
            frame.free_force_residual_n = finiteNumber(
                required(source_frame, "free_force_residual_n", frame_prefix),
                frame_prefix + ".free_force_residual_n");
            if (source_frame.contains("error")) {
                frame.error = boundedString(source_frame.at("error"),
                                            frame_prefix + ".error", true);
            }
            if (frame.stored_free_energy_j < 0.0 ||
                frame.plastic_dissipation_j < 0.0 ||
                frame.maximum_equivalent_plastic_strain < 0.0 ||
                frame.free_force_residual_n < 0.0) {
                invalid(frame_prefix + " contains a negative magnitude");
            }
            frame.maximum_displacement_m = 0.0;
            for (const Vec3d displacement : frame.displacements_m) {
                frame.maximum_displacement_m = std::max(
                    frame.maximum_displacement_m,
                    std::sqrt(displacement.x * displacement.x +
                              displacement.y * displacement.y +
                              displacement.z * displacement.z));
            }
            result.maximum_plastic_strain = std::max(
                result.maximum_plastic_strain,
                frame.maximum_equivalent_plastic_strain);
            parsed_case.frames.push_back(std::move(frame));
        }
        result.cases.push_back(std::move(parsed_case));
    }
    return result;
}

ViewerOptions parseOptions(int argc, char **argv) {
    if (argc < 2 || argc > 4) {
        throw std::invalid_argument(
            "usage: banjo_continuum_lab report.json [--capture output.png]");
    }
    ViewerOptions options{argv[1], {}};
    for (int index = 2; index < argc; ++index) {
        if (std::string_view(argv[index]) != "--capture") {
            throw std::invalid_argument(
                "usage: banjo_continuum_lab report.json [--capture output.png]");
        }
        if (index + 1 >= argc || options.capture_path != std::filesystem::path{}) {
            throw std::invalid_argument("--capture requires one output path");
        }
        options.capture_path = argv[++index];
        if (options.capture_path.empty()) {
            throw std::invalid_argument("--capture output path must not be empty");
        }
    }
    return options;
}

struct Bounds {
    Vec3d low{std::numeric_limits<double>::max(),
              std::numeric_limits<double>::max(),
              std::numeric_limits<double>::max()};
    Vec3d high{std::numeric_limits<double>::lowest(),
               std::numeric_limits<double>::lowest(),
               std::numeric_limits<double>::lowest()};
};

void include(Bounds &bounds, Vec3d value) {
    bounds.low.x = std::min(bounds.low.x, value.x);
    bounds.low.y = std::min(bounds.low.y, value.y);
    bounds.low.z = std::min(bounds.low.z, value.z);
    bounds.high.x = std::max(bounds.high.x, value.x);
    bounds.high.y = std::max(bounds.high.y, value.y);
    bounds.high.z = std::max(bounds.high.z, value.z);
}

Color materialColor(std::string_view material) {
    if (material.find("glass") != std::string_view::npos) {
        return {91, 190, 222, 255};
    }
    if (material.find("oak") != std::string_view::npos ||
        material.find("wood") != std::string_view::npos) {
        return {181, 122, 66, 255};
    }
    if (material.find("iron") != std::string_view::npos ||
        material.find("steel") != std::string_view::npos) {
        return {151, 170, 193, 255};
    }
    return {111, 192, 176, 255};
}

Color scaleColor(Color color, double brightness) {
    const auto component = [brightness](unsigned char value) {
        return static_cast<unsigned char>(std::clamp(
            brightness * static_cast<double>(value), 0.0, 255.0));
    };
    return {component(color.r), component(color.g), component(color.b), 255};
}

Color blendColor(Color first, Color second, double amount) {
    const double t = std::clamp(amount, 0.0, 1.0);
    const auto component = [t](unsigned char a, unsigned char b) {
        return static_cast<unsigned char>(std::clamp(
            (1.0 - t) * static_cast<double>(a) + t * static_cast<double>(b),
            0.0, 255.0));
    };
    return {component(first.r, second.r), component(first.g, second.g),
            component(first.b, second.b), 255};
}

Vec3d displayPosition(const ContinuumCase &continuum_case, const Frame &frame,
                      std::size_t node, Vec3d offset, double magnification) {
    return continuum_case.reference_positions_m[node] + offset +
           frame.displacements_m[node] * magnification;
}

std::size_t lastAcceptedFrame(const ContinuumCase &continuum_case) {
    for (std::size_t index = continuum_case.frames.size(); index > 0U; --index) {
        if (continuum_case.frames[index - 1U].accepted) {
            return index - 1U;
        }
    }
    return continuum_case.frames.size() - 1U;
}

std::size_t visibleFrameIndex(const ContinuumCase &continuum_case,
                              std::size_t global_frame_index) {
    if (global_frame_index < continuum_case.frames.size()) {
        return global_frame_index;
    }
    return lastAcceptedFrame(continuum_case);
}

double commonPhysicalSpan(const Report &report, double magnification) {
    double span = 0.0;
    for (const ContinuumCase &continuum_case : report.cases) {
        for (const Frame &frame : continuum_case.frames) {
            Bounds bounds;
            for (std::size_t node = 0;
                 node < continuum_case.reference_positions_m.size(); ++node) {
                include(bounds, displayPosition(continuum_case, frame, node,
                                               {0.0, 0.0, 0.0}, magnification));
            }
            const Vec3d extent = bounds.high - bounds.low;
            span = std::max(span, std::max({extent.x, extent.y, extent.z}));
        }
    }
    return std::max(1.0e-4, span * 1.25);
}

Camera3D makeCaseCamera(const ContinuumCase &continuum_case,
                        double common_span) {
    Bounds bounds;
    for (const Vec3d position : continuum_case.reference_positions_m) {
        include(bounds, position);
    }
    const Vec3d target = (bounds.low + bounds.high) * 0.5;
    const double distance = std::max(0.03, common_span * 1.9);
    return {
        toRaylib(target + Vec3d{distance * 0.92, distance * 0.68, distance * 1.08}),
        toRaylib(target),
        {0.0F, 1.0F, 0.0F},
        42.0F,
        CAMERA_PERSPECTIVE,
    };
}

void drawMesh(const ContinuumCase &continuum_case, const Frame &frame,
              Vec3d offset, double magnification, double maximum_plastic_strain,
              bool wireframe) {
    const double plastic_amount = maximum_plastic_strain > 0.0
                                      ? frame.maximum_equivalent_plastic_strain /
                                            maximum_plastic_strain
                                      : 0.0;
    const Color base = materialColor(continuum_case.material_id);
    const Color fill = blendColor(base, {240, 105, 71, 255}, plastic_amount);
    const Color wire = {226, 235, 242, 205};
    const Vector3 light_direction = Vector3Normalize({-0.35F, 0.72F, 0.60F});

    for (const auto &triangle : continuum_case.boundary_triangles) {
        const Vec3d p0 = displayPosition(continuum_case, frame, triangle[0], offset,
                                         magnification);
        const Vec3d p1 = displayPosition(continuum_case, frame, triangle[1], offset,
                                         magnification);
        const Vec3d p2 = displayPosition(continuum_case, frame, triangle[2], offset,
                                         magnification);
        const Vector3 a = toRaylib(p0);
        const Vector3 b = toRaylib(p1);
        const Vector3 c = toRaylib(p2);
        const Vector3 normal = Vector3Normalize(
            Vector3CrossProduct(Vector3Subtract(b, a), Vector3Subtract(c, a)));
        const double brightness =
            0.38 + 0.62 * std::abs(Vector3DotProduct(normal, light_direction));
        const Color shaded = scaleColor(fill, brightness);
        DrawTriangle3D(a, b, c, shaded);
        DrawTriangle3D(c, b, a, shaded);

        if (wireframe) {
            DrawLine3D(a, b, wire);
            DrawLine3D(b, c, wire);
            DrawLine3D(c, a, wire);
        }

        const Vec3d r0 = continuum_case.reference_positions_m[triangle[0]] + offset;
        const Vec3d r1 = continuum_case.reference_positions_m[triangle[1]] + offset;
        const Vec3d r2 = continuum_case.reference_positions_m[triangle[2]] + offset;
        DrawLine3D(toRaylib(r0), toRaylib(r1), Fade({166, 183, 195, 255}, 0.35F));
        DrawLine3D(toRaylib(r1), toRaylib(r2), Fade({166, 183, 195, 255}, 0.35F));
        DrawLine3D(toRaylib(r2), toRaylib(r0), Fade({166, 183, 195, 255}, 0.35F));
    }
}

bool button(Rectangle rectangle, const char *label) {
    const bool hover = CheckCollisionPointRec(GetMousePosition(), rectangle);
    DrawRectangleRounded(rectangle, 0.16F, 6,
                         hover ? Color{62, 98, 111, 255}
                               : Color{37, 60, 72, 255});
    DrawRectangleRoundedLines(rectangle, 0.16F, 6, {112, 145, 157, 255});
    const int text_width = MeasureText(label, 16);
    DrawText(label, static_cast<int>(rectangle.x +
                                     (rectangle.width - text_width) * 0.5F),
             static_cast<int>(rectangle.y + 9.0F), 16, RAYWHITE);
    return hover && IsMouseButtonPressed(MOUSE_BUTTON_LEFT);
}

void drawOverlay(const Report &report, std::size_t frame_index, bool playing,
                 double magnification) {
    const int width = GetScreenWidth();
    const int height = GetScreenHeight();
    DrawRectangle(0, 0, width, 122, {11, 20, 29, 238});
    DrawText("BANJO / CONTINUUM LAB", 22, 15, 25, {207, 237, 135, 255});
    DrawText("QUASISTATIC FORCE LOAD / COMPUTED SEQUENCE / NO COLLISION", 22, 49,
             17, RAYWHITE);
    DrawText("Experimental constitutive response; not calibrated material prediction",
             22, 76, 16, {234, 186, 115, 255});
    const std::size_t maximum_frames = [&] {
        std::size_t result = 0U;
        for (const ContinuumCase &continuum_case : report.cases) {
            result = std::max(result, continuum_case.frames.size());
        }
        return result;
    }();
    DrawText(TextFormat("Frame %u / %u   %s   display displacement %.0fx",
                        static_cast<unsigned>(frame_index + 1U),
                        static_cast<unsigned>(maximum_frames),
                        playing ? "PLAYING" : "PAUSED",
                        magnification),
             22, 99, 15, {165, 190, 202, 255});

    const int footer_top = height - kFooterHeight;
    DrawRectangle(0, footer_top, width, kFooterHeight, {11, 20, 29, 242});
    DrawText("Keys: R reset, Left/Right frame, Space play, M magnification",
             22, footer_top + 134, 14, {156, 177, 190, 255});
    DrawText("Reference wire / actual displaced surface; color increases with reported plastic strain",
             22, footer_top + 158, 14, {156, 177, 190, 255});
    DrawText("Display only; displacement magnification does not alter report values", 22,
             footer_top + 182, 14, {156, 177, 190, 255});
}

void drawCaseLabels(const Report &report, std::size_t frame_index) {
    const int width = GetScreenWidth();
    const int column_width = width / static_cast<int>(report.cases.size());
    for (std::size_t index = 0; index < report.cases.size(); ++index) {
        const ContinuumCase &continuum_case = report.cases[index];
        const std::size_t selected_frame =
            visibleFrameIndex(continuum_case, frame_index);
        const Frame &frame = continuum_case.frames[selected_frame];
        const int x = static_cast<int>(index) * column_width + 12;
        const bool frozen = frame_index >= continuum_case.frames.size();
        Bounds reference_bounds;
        for (const Vec3d position : continuum_case.reference_positions_m) {
            include(reference_bounds, position);
        }
        const Vec3d reference_extent =
            reference_bounds.high - reference_bounds.low;
        DrawText(continuum_case.name.c_str(), x, 132, 17, RAYWHITE);
        DrawText(TextFormat("%s  |  load %.3f  |  %s",
                            continuum_case.material_id.c_str(), frame.load_fraction,
                            frame.phase.c_str()),
                 x, 154, 13, {171, 192, 203, 255});
        DrawText(TextFormat("frame %u/%u%s", static_cast<unsigned>(
                                selected_frame + 1U),
                            static_cast<unsigned>(continuum_case.frames.size()),
                            frozen ? "  (frozen at last valid)" : ""),
                 x, 173, 13, frozen ? Color{245, 170, 116, 255}
                                   : Color{145, 220, 174, 255});
        DrawText(TextFormat("size %.3gx%.3gx%.3g mm", reference_extent.x * 1000.0,
                            reference_extent.y * 1000.0,
                            reference_extent.z * 1000.0),
                 x + column_width - 170, 173, 12, {171, 192, 203, 255});
    }
}

struct DistanceDisplay {
    double value{};
    const char *unit{};
};

DistanceDisplay displayDistance(double meters) {
    if (meters >= 1.0) {
        return {meters, "m"};
    }
    if (meters >= 1.0e-3) {
        return {meters * 1.0e3, "mm"};
    }
    return {meters * 1.0e6, "um"};
}

std::string clippedText(std::string value, int pixel_width, int font_size) {
    if (MeasureText(value.c_str(), font_size) <= pixel_width) {
        return value;
    }
    constexpr std::string_view suffix = "...";
    while (value.size() > suffix.size() &&
           MeasureText((value.substr(0, value.size() - suffix.size()) +
                        std::string(suffix))
                           .c_str(),
                       font_size) > pixel_width) {
        value.pop_back();
    }
    if (value.size() <= suffix.size()) {
        return std::string(suffix);
    }
    return value.substr(0, value.size() - suffix.size()) + std::string(suffix);
}

std::string caseStatus(const ContinuumCase &continuum_case, const Frame &frame,
                       bool frozen) {
    std::string result = continuum_case.status;
    if (result.empty() || result == "unknown") {
        result = frame.accepted ? "accepted" : "not accepted";
    }
    const std::string &reason = !continuum_case.error.empty()
                                    ? continuum_case.error
                                    : frame.error;
    if (!reason.empty()) {
        result += ": ";
        result += reason;
    }
    if (frozen) {
        result += " (last valid frame)";
    }
    return result;
}

void drawMetrics(const Report &report, std::size_t frame_index,
                 double magnification) {
    const int width = GetScreenWidth();
    const int height = GetScreenHeight();
    const int column_width = width / static_cast<int>(report.cases.size());
    const int footer_top = height - kFooterHeight;
    const int y = footer_top + 12;
    for (std::size_t index = 0; index < report.cases.size(); ++index) {
        const ContinuumCase &continuum_case = report.cases[index];
        const std::size_t selected_frame =
            visibleFrameIndex(continuum_case, frame_index);
        const Frame &frame = continuum_case.frames[selected_frame];
        const int x = static_cast<int>(index) * column_width + 12;
        const DistanceDisplay displacement =
            displayDistance(frame.maximum_displacement_m);
        DrawText(TextFormat("max disp %.4g %s (display %.0fx)", displacement.value,
                            displacement.unit,
                            magnification),
                 x, y, 13, RAYWHITE);
        DrawText(TextFormat("max eps %.5g | stored %.5g J", frame.maximum_equivalent_plastic_strain,
                            frame.stored_free_energy_j),
                 x, y + 18, 13, {171, 192, 203, 255});
        const char *residual_label = frame.accepted ? "residual" :
                                                    "failed trial residual";
        DrawText(TextFormat("plastic %.5g J | %s %.5g N", frame.plastic_dissipation_j,
                            residual_label, frame.free_force_residual_n),
                 x, y + 36, 13, {171, 192, 203, 255});
        const bool frozen = frame_index >= continuum_case.frames.size();
        const std::string status = clippedText(
            caseStatus(continuum_case, frame, frozen), column_width - 24, 12);
        DrawText(status.c_str(), x, y + 54, 12,
                 continuum_case.status == "solver_limit"
                     ? Color{245, 170, 116, 255}
                     : Color{156, 177, 190, 255});
    }
}

} // namespace

int main(int argc, char **argv) {
    bool window_ready = false;
    std::vector<RenderTexture2D> case_views;
    try {
        const ViewerOptions options = parseOptions(argc, argv);
        const Report report = loadReport(options.report_path);
        // The report is immutable during playback. Cache the only three camera
        // scales so frame rendering never rescans every case/frame/node.
        const std::array<double, 3> common_spans{
            commonPhysicalSpan(report, 1.0),
            commonPhysicalSpan(report, 10.0),
            commonPhysicalSpan(report, 100.0),
        };

        const std::size_t maximum_frames = [&] {
            std::size_t result = 0U;
            for (const ContinuumCase &continuum_case : report.cases) {
                result = std::max(result, continuum_case.frames.size());
            }
            return result;
        }();

        SetConfigFlags(FLAG_MSAA_4X_HINT | FLAG_WINDOW_RESIZABLE);
        InitWindow(1360, 850, "Banjo - Continuum Lab");
        window_ready = true;
        SetTargetFPS(60);

        const bool capture = !options.capture_path.empty();
        std::size_t frame_index = capture ? maximum_frames - 1U : 0U;
        double magnifications[] = {1.0, 10.0, 100.0};
        std::size_t magnification_index = 0U;
        bool playing = false;
        double playback_accumulator = 0.0;
        int view_width = 0;
        int view_height = 0;
        auto ensureCaseViews = [&] {
            constexpr int scene_top = 190;
            const int next_width = std::max(
                1, GetScreenWidth() / static_cast<int>(report.cases.size()));
            const int next_height = std::max(
                1, GetScreenHeight() - kFooterHeight - scene_top);
            if (next_width == view_width && next_height == view_height &&
                case_views.size() == report.cases.size()) {
                return;
            }
            for (RenderTexture2D &view : case_views) {
                if (view.texture.id != 0U) {
                    UnloadRenderTexture(view);
                }
            }
            case_views.clear();
            case_views.reserve(report.cases.size());
            for (std::size_t index = 0; index < report.cases.size(); ++index) {
                case_views.push_back(LoadRenderTexture(next_width, next_height));
                if (case_views.back().texture.id == 0U) {
                    throw std::runtime_error("failed to allocate continuum case view");
                }
            }
            view_width = next_width;
            view_height = next_height;
        };

        while (!WindowShouldClose()) {
            if (!capture) {
                std::vector<int> pressed;
                for (int key = GetKeyPressed(); key != 0; key = GetKeyPressed()) {
                    pressed.push_back(key);
                }
                const auto wasPressed = [&pressed](int key) {
                    return std::find(pressed.begin(), pressed.end(), key) !=
                           pressed.end();
                };
                if (wasPressed(KEY_R)) {
                    frame_index = 0U;
                    playing = false;
                }
                if (wasPressed(KEY_LEFT)) {
                    frame_index = frame_index == 0U ? 0U : frame_index - 1U;
                    playing = false;
                }
                if (wasPressed(KEY_RIGHT)) {
                    frame_index = std::min(maximum_frames - 1U, frame_index + 1U);
                    playing = false;
                }
                if (wasPressed(KEY_SPACE)) {
                    playing = !playing;
                }
                if (wasPressed(KEY_M)) {
                    magnification_index =
                        (magnification_index + 1U) % std::size(magnifications);
                }
                if (playing) {
                    playback_accumulator += std::min(GetFrameTime(), 0.1F);
                    while (playback_accumulator >= 0.30 &&
                           frame_index + 1U < maximum_frames) {
                        playback_accumulator -= 0.30;
                        ++frame_index;
                    }
                    if (frame_index + 1U >= maximum_frames) {
                        playing = false;
                    }
                }
            }

            const double magnification = magnifications[magnification_index];
            ensureCaseViews();
            const double common_span = common_spans[magnification_index];
            constexpr int scene_top = 190;
            for (std::size_t case_index = 0; case_index < report.cases.size();
                 ++case_index) {
                const ContinuumCase &continuum_case = report.cases[case_index];
                const Frame &frame = continuum_case.frames[
                    visibleFrameIndex(continuum_case, frame_index)];
                BeginTextureMode(case_views[case_index]);
                ClearBackground({12, 18, 28, 255});
                BeginMode3D(makeCaseCamera(continuum_case, common_span));
                drawMesh(continuum_case, frame, {0.0, 0.0, 0.0}, magnification,
                         report.maximum_plastic_strain, true);
                EndMode3D();
                EndTextureMode();
            }
            BeginDrawing();
            ClearBackground({12, 18, 28, 255});
            for (std::size_t case_index = 0; case_index < report.cases.size();
                 ++case_index) {
                const int x = static_cast<int>(case_index) * view_width;
                DrawTexturePro(
                    case_views[case_index].texture,
                    {0.0F, 0.0F, static_cast<float>(view_width),
                     -static_cast<float>(view_height)},
                    {static_cast<float>(x), static_cast<float>(scene_top),
                     static_cast<float>(view_width), static_cast<float>(view_height)},
                    {0.0F, 0.0F}, 0.0F, WHITE);
            }
            drawOverlay(report, frame_index, playing, magnification);
            drawCaseLabels(report, frame_index);
            drawMetrics(report, frame_index, magnification);

            if (!capture) {
                const int footer_top = GetScreenHeight() - kFooterHeight;
                const int button_width = 116;
                const int button_gap = 10;
                const int first_x = 22;
                if (button({static_cast<float>(first_x), static_cast<float>(footer_top + 88),
                            static_cast<float>(button_width), 34.0F},
                           "Reset")) {
                    frame_index = 0U;
                    playing = false;
                }
                if (button({static_cast<float>(first_x + button_width + button_gap),
                            static_cast<float>(footer_top + 88),
                            static_cast<float>(button_width), 34.0F},
                           "Previous")) {
                    frame_index = frame_index == 0U ? 0U : frame_index - 1U;
                    playing = false;
                }
                if (button({static_cast<float>(first_x + 2 * (button_width + button_gap)),
                            static_cast<float>(footer_top + 88),
                            static_cast<float>(button_width), 34.0F},
                           "Next")) {
                    frame_index = std::min(maximum_frames - 1U, frame_index + 1U);
                    playing = false;
                }
                if (button({static_cast<float>(first_x + 3 * (button_width + button_gap)),
                            static_cast<float>(footer_top + 88),
                            static_cast<float>(button_width), 34.0F},
                           playing ? "Pause" : "Play")) {
                    playing = !playing;
                }
                if (button({static_cast<float>(first_x + 4 * (button_width + button_gap)),
                            static_cast<float>(footer_top + 88), 136.0F, 34.0F},
                           TextFormat("Scale %.0fx", magnification))) {
                    magnification_index =
                        (magnification_index + 1U) % std::size(magnifications);
                }
            }
            EndDrawing();

            if (capture) {
                const std::filesystem::path parent = options.capture_path.parent_path();
                if (!parent.empty()) {
                    std::filesystem::create_directories(parent);
                }
                Image image = LoadImageFromScreen();
                const bool exported =
                    ExportImage(image, options.capture_path.string().c_str());
                UnloadImage(image);
                if (!exported) {
                    throw std::runtime_error("failed to export capture: " +
                                             options.capture_path.string());
                }
                break;
            }
        }

        for (RenderTexture2D &view : case_views) {
            if (view.texture.id != 0U) {
                UnloadRenderTexture(view);
            }
        }
        case_views.clear();
        CloseWindow();
        window_ready = false;
        return EXIT_SUCCESS;
    } catch (const std::exception &exception) {
        for (RenderTexture2D &view : case_views) {
            if (view.texture.id != 0U && window_ready) {
                UnloadRenderTexture(view);
            }
        }
        if (window_ready) {
            CloseWindow();
        }
        std::fprintf(stderr, "continuum viewer error: %s\n", exception.what());
        return EXIT_FAILURE;
    }
}
