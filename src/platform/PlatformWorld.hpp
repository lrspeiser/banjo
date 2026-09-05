#pragma once
#include "core/RigidPrimitive.hpp"
#include "fracture/ActiveMatter.hpp"
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
};
struct PlatformStep {
    unsigned completed_steps{};
    double elapsed_s{}, wall_ms{};
    std::string error;
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
    std::string reportJson() const;
    std::string packageJson() const;
    const std::vector<std::array<Vec3,3>> &supportMesh() const;
    double fixedStep() const;
private:
    PlatformWorld();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
