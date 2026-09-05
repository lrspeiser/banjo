#pragma once

#include "core/Math.hpp"
#include "core/RigidPrimitive.hpp"
#include "core/Plane.hpp"
#include "core/Types.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "fracture/ImpactEvent.hpp"
#include "material/Material.hpp"
#include "physics/SphereMaterialContact.hpp"
#include "physics/MechanicalAccounting.hpp"

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

struct RigidBoxDescription {
    MatterBodyId body_id{kInvalidMatterBodyId};
    Vec3 dimensions_m{};
    MaterialDefinition material{};
    RigidSnapshot state{};
    bool fixed{};
};

enum class PairContactOwner { Jolt, External };

struct PairImpulseAudit {
    MechanicalTotals before{}, after{};
    double impulse_work_j{}, numerical_energy_change_j{};
    Vec3 momentum_error_kg_m_s{}, applied_couple_kg_m2_s{}, angular_momentum_error_kg_m2_s{};
};

class JoltWorld {
public:
    JoltWorld();
    ~JoltWorld();

    JoltWorld(const JoltWorld &) = delete;
    JoltWorld &operator=(const JoltWorld &) = delete;
    JoltWorld(JoltWorld &&) noexcept;
    JoltWorld &operator=(JoltWorld &&) noexcept;
    [[nodiscard]] static unsigned positionPrecisionBits() noexcept;

    void setGravity(const Vec3 &gravity_m_s2);
    void addFloor();
    void addSupportSurface(const RigidSurfaceDescription &description);
    void addBall(const RigidBallDescription &description);
    void addBox(const RigidBoxDescription &description);
    // Host-thread only, between steps. External suppresses this pair's Jolt
    // contact response/events over both entire bodies, not just a joint face;
    // the caller must provide the physical response for all their contacts.
    // Ownership is transient and must be restored when rebuilding a world.
    void setPairContactOwner(MatterBodyId a,MatterBodyId b,PairContactOwner owner);
    [[nodiscard]] PairContactOwner pairContactOwner(MatterBodyId a,MatterBodyId b) const;
    // Instantaneous equal/opposite transfer supplied by an external law, not a
    // force law or a time advance. Requires External pair ownership and two
    // unpinned, unrestricted dynamic bodies. Points/impulse are world-space SI.
    // Preflights float rounding and speed limits before changing either body.
    // Budget bounds transfer roundoff only; the caller accounts for the source
    // of impulse work and any noncentral couple. Host thread, between steps.
    [[nodiscard]] PairImpulseAudit applyPairImpulse(MatterBodyId a,MatterBodyId b,
        Vec3 point_a_m,Vec3 point_b_m,Vec3 impulse_on_a_n_s,double maximum_roundoff_energy_j);
    void pinToWorld(MatterBodyId body_id);
    void releaseFromWorld(MatterBodyId body_id);
    void applyRigidState(MatterBodyId body_id,const RigidSnapshot &state);
    void addFragments(const std::vector<RigidFragmentDescription> &fragments);
    void step(double fixed_dt_s);
    [[nodiscard]] CoupledSphereState sphereContactState(MatterBodyId body_id) const;
    void applySphereContactState(MatterBodyId body_id, const CoupledSphereState &state);

    [[nodiscard]] std::vector<ImpactEvent> drainImpacts();
    [[nodiscard]] RigidSnapshot snapshot(MatterBodyId body_id) const;
    [[nodiscard]] RigidMechanicalState mechanicalState(MatterBodyId body_id) const;
    [[nodiscard]] MechanicalTotals mechanicalTotals(const Vec3 &gravity_m_s2 = {}) const;
    [[nodiscard]] bool contains(MatterBodyId body_id) const;
    void removeAndDestroy(MatterBodyId body_id);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo
