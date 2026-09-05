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
#include "physics/CohesiveInterface.hpp"
#include "physics/CohesiveRigidPair.hpp"
#include "physics/RigidAttachment.hpp"

#include <memory>
#include <functional>
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
struct CohesiveTensionKick {
    CohesiveInterfaceIncrement interface_increment;
    PairImpulseAudit transfer;
};

struct CohesiveTensionPatchKick {
    std::vector<CohesiveInterfaceIncrement> interface_increments;
    PairImpulseAudit transfer;
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
    // Central tensile connector between body-local points; Jolt retains every
    // surface contact. Compression stiffness must be zero. Requires double
    // positions and Jolt pair ownership; material-activation deferral rejects.
    // Caller owns geometric validity, site
    // history, time integration and its full work/error budget. No world step
    // or multi-kick rollback is implied. History is returned only on success.
    // Keeps both bodies awake while called, including a failed/slack site;
    // the external scheduler must stop calls when normal sleeping may resume.
    [[nodiscard]] CohesiveTensionKick applyCohesiveTensionKick(MatterBodyId a,MatterBodyId b,
        Vec3 attachment_a_local_m,Vec3 attachment_b_local_m,double rest_distance_m,
        const CohesiveInterfaceLaw &law,const CohesiveInterfaceState &history,
        double impulse_duration_s,double maximum_roundoff_energy_j);
    // 1..256 caller-compiled local sites, each with its own area/history.
    // Common law.area_m2 is ignored. Every site is evaluated from the same
    // pose; the complete velocity update is preflighted before either write.
    // Returns histories only on success; does not step or own persistence.
    [[nodiscard]] CohesiveTensionPatchKick applyCohesiveTensionPatchKick(MatterBodyId a,MatterBodyId b,
        const std::vector<CohesivePatchSite> &sites,const CohesiveInterfaceLaw &law,
        double impulse_duration_s,double maximum_roundoff_energy_j);
    void pinToWorld(MatterBodyId body_id);
    void releaseFromWorld(MatterBodyId body_id);
    void applyRigidState(MatterBodyId body_id,const RigidSnapshot &state);
    void addFragments(const std::vector<RigidFragmentDescription> &fragments);
    // Trusted host callback, between steps. True accepts; false or an exception
    // restores Jolt bodies/contacts/constraints/global state, ticks and queued
    // impacts. Geometry/configuration mutations reject while a trial is open.
    // Caller owns external histories and must keep this world alive/unmoved.
    // At most 256 bodies and 16 nested trials; no persistence/portable snapshot.
    [[nodiscard]] bool runReversibleTrial(const std::function<bool()> &trial);
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
    [[nodiscard]] PairImpulseAudit applyAuditedPairImpulses(MatterBodyId a,MatterBodyId b,
        const std::vector<AttachmentImpulse> &impulses,double maximum_roundoff_energy_j);
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo
