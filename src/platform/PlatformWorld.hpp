#pragma once
#include "core/RigidPrimitive.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/CellSkin.hpp"
#include "material/MaterialCatalog.hpp"
#include <memory>
#include <string>
#include <vector>
namespace banjo {
struct PlatformInstance {
    MatterBodyId object_id{};
    unsigned element_id{};
    unsigned component_id{};
    MaterialPreset material{};
    RigidPrimitive geometry;
    RigidSnapshot state;
    std::uint32_t color_rgba{};
    std::vector<std::array<Vec3,3>> local_mesh;
    std::string material_id; // Property-defined v2 material; empty for legacy presets.
    bool deformable_cell{};
};
struct PlatformSkin {
    MatterBodyId object_id{};
    std::string material_id;
    std::uint32_t color_rgba{};
    CellSkinMesh mesh;
};
struct PlatformStep {
    unsigned completed_steps{};
    double elapsed_s{}, wall_ms{};
    std::string error;
};
struct PlatformBondLine {
    Vec3 a,b;bool live{};
    double damage{},plastic_extension_m{};
    unsigned object_id{},a_element{},b_element{};
};
// Host-thread API. No inventory, model calls, file access or renderer dependency.
// A package is initial authoring state, not a saved simulation checkpoint.
// Explicit backend selection; no unvalidated rigid/material switching.
class PlatformWorld {
public:
    static std::unique_ptr<PlatformWorld> load(const std::string &package_json);
    static std::string capabilitiesJson();
    ~PlatformWorld();
    PlatformStep step(unsigned fixed_steps=1);
    std::vector<PlatformInstance> renderInstances() const;
    std::vector<PlatformBondLine> renderBonds() const;
    std::vector<PlatformSkin> renderSkins() const;
    std::string reportJson() const;
    std::string packageJson() const;
    const std::vector<std::array<Vec3,3>> &supportMesh() const;
    double fixedStep() const;
    unsigned fractureCount() const;
private:
    PlatformWorld();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
