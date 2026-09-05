#pragma once
#include "material/MaterialCatalog.hpp"
#include "rigid/JoltWorld.hpp"
#include <filesystem>
#include <string>
#include <string_view>

namespace banjo {
// The versioned recipe is shared by a human editor and an LLM proposal.
// Unsupported geometry and laws fail compilation; they never become spheres
// or a different material silently.
struct ObjectRecipe {
    unsigned schema_version{1};
    std::string name{"Created ball"};
    std::string shape{"sphere"};
    std::string physics{"rigid-v1"};
    MaterialPreset material{MaterialPreset::Oak};
    double radius_m{.06};
    double tangent_m{-2},bitangent_m{},clearance_m{.002};
    Vec3 linear_velocity_m_s{},angular_velocity_rad_s{};
    Vec3 dimensions_m{.12,.08,.10};
    Quat orientation_world{};
    [[nodiscard]] RigidPrimitive geometry() const;
};
struct ResourceLot {
    std::string id,provenance;
    MaterialPreset material{MaterialPreset::Oak};
    double initial_mass_kg{},remaining_mass_kg{};
    bool collected{};
};
struct MaterialAllocation { std::string lot_id; double mass_kg{}; };
struct CreatedObject {
    MatterBodyId id{};
    std::string request_id;
    ObjectRecipe recipe;
    double volume_m3{},mass_kg{};
    Mat3 inertia_local_kg_m2{};
    std::vector<MaterialAllocation> allocations;
    RigidSnapshot state;
};
struct CreatorSettings {
    double slope_degrees{10};
    Vec3 gravity_m_s2{0,-9.81,0};
    MaterialPreset surface{MaterialPreset::Concrete};
};
struct CreationPreview {
    ObjectRecipe recipe;
    double volume_m3{},mass_kg{};
    Mat3 inertia_local_kg_m2{};
    Vec3 position_world_m;
    std::vector<MaterialAllocation> allocations;
};
struct CreatorProposal { std::string request_id,explanation;ObjectRecipe recipe; };
struct CreatorMotion {
    std::string state;
    double speed_m_s{},slip_m_s{},support_gap_m{};
    unsigned near_support_points{};
};
// Box diagnostics sample geometric bottom vertices against the finite top
// support, not a sphere-radius proxy or a claim to solver impulse/work data.
[[nodiscard]] CreatorMotion measureCreatorMotion(const CreatedObject &object,const SupportPlaneFrame &support);
// Single-thread-owned authoring/runtime state. Callers serialize commands on
// the simulation thread. The reference matter solver is a separate selection.
class CreatorWorld {
public:
    explicit CreatorWorld(CreatorSettings settings = {});
    ~CreatorWorld();
    CreatorWorld(CreatorWorld &&) noexcept;
    CreatorWorld &operator=(CreatorWorld &&) noexcept;
    CreatorWorld(const CreatorWorld &) = delete;
    CreatorWorld &operator=(const CreatorWorld &) = delete;

    [[nodiscard]] const std::vector<ResourceLot> &lots() const { return lots_; }
    [[nodiscard]] const std::vector<CreatedObject> &objects() const { return objects_; }
    [[nodiscard]] const CreatorSettings &settings() const { return settings_; }
    [[nodiscard]] SupportPlaneFrame support() const;
    [[nodiscard]] double timeSeconds() const { return static_cast<double>(ticks_)/240; }
    [[nodiscard]] double inventoryMass(MaterialPreset material) const;
    [[nodiscard]] RigidMechanicalState mechanicalState(MatterBodyId id) const;
    bool collect(std::string_view lot_id);
    [[nodiscard]] CreationPreview preview(const ObjectRecipe &recipe) const;
    [[nodiscard]] MatterBodyId create(std::string request_id,const ObjectRecipe &recipe);
    void step(unsigned ticks=1);

    [[nodiscard]] std::string inspectJson() const;
    [[nodiscard]] std::string serialize() const;
    [[nodiscard]] static CreatorWorld deserialize(std::string_view document);
    void save(const std::filesystem::path &path) const;
    [[nodiscard]] static CreatorWorld load(const std::filesystem::path &path);
    // One bounded command object or a bounded array; errors are structured and
    // do not debit inventory. No filesystem paths or executable code in commands.
    [[nodiscard]] std::string executeJson(std::string_view commands);
    [[nodiscard]] static ObjectRecipe parseRecipe(std::string_view document);
    [[nodiscard]] static std::string recipeJson(const ObjectRecipe &recipe);
    [[nodiscard]] static CreatorProposal parseProposal(std::string_view document);
private:
    CreatorSettings settings_;
    std::vector<ResourceLot> lots_;
    std::vector<CreatedObject> objects_;
    std::unique_ptr<JoltWorld> world_;
    std::uint64_t ticks_{};
};
}
