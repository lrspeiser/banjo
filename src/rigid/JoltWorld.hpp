#pragma once

#include "core/Math.hpp"
#include "core/Plane.hpp"
#include "core/Types.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "fracture/ImpactEvent.hpp"
#include "material/Material.hpp"
#include "physics/SphereMaterialContact.hpp"

#include <memory>
#include <vector>

namespace banjo {

struct RigidSurfaceDescription {
    SupportPlaneFrame frame{};
    MaterialDefinition material{};
    double half_length_tangent_m{10.0};
    double half_length_bitangent_m{5.0};
    double thickness_m{0.5};
};

struct RigidBallDescription {
    MatterBodyId body_id{kInvalidMatterBodyId};
    double radius_m{};
    MaterialDefinition material{};
    Vec3 position_world_m{};
    Vec3 linear_velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
    double mass_override_kg{};
    double sphere_inertia_factor{0.4};
    bool defer_brittle_contacts_to_material{};
};

class JoltWorld {
public:
    JoltWorld();
    ~JoltWorld();

    JoltWorld(const JoltWorld &) = delete;
    JoltWorld &operator=(const JoltWorld &) = delete;
    JoltWorld(JoltWorld &&) noexcept;
    JoltWorld &operator=(JoltWorld &&) noexcept;

    void setGravity(const Vec3 &gravity_m_s2);
    void addFloor();
    void addSupportSurface(const RigidSurfaceDescription &description);
    void addBall(const RigidBallDescription &description);
    void addFragments(const std::vector<RigidFragmentDescription> &fragments);
    void step(double fixed_dt_s);
    [[nodiscard]] CoupledSphereState sphereContactState(MatterBodyId body_id) const;
    void applySphereContactState(MatterBodyId body_id, const CoupledSphereState &state);

    [[nodiscard]] std::vector<ImpactEvent> drainImpacts();
    [[nodiscard]] RigidSnapshot snapshot(MatterBodyId body_id) const;
    [[nodiscard]] bool contains(MatterBodyId body_id) const;
    void removeAndDestroy(MatterBodyId body_id);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo
