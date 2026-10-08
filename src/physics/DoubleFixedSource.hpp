#pragma once
#include "physics/DoubleRigidDynamics.hpp"
#include "physics/FixedAssemblyContact.hpp"

namespace banjo {
struct DoubleFixedSourceTransfer {
    DoubleRigidTransfer aggregate;
    FixedAssemblyVelocityAudit fixing;
};
// One physical owner of a finite rigid fixed assembly. Member poses and local
// fixing geometry are preserved under compound rigid drift; member velocity
// follows the aggregate Hamiltonian dynamics. No Jolt stepping/projection here.
// Import requires coincident fixing anchors; drifted/native anchors must be
// explicitly reconciled by a separately audited representation transition.
class DoubleFixedSource {
public:
    DoubleFixedSource(const std::vector<RigidMechanicalState> &,const std::vector<FixedVelocityLink> &);
    [[nodiscard]] std::vector<RigidMechanicalState> bodies() const;
    [[nodiscard]] std::vector<FixedVelocityLink> links() const;
    [[nodiscard]] const DoubleRigidState &state() const {return state_;}
    [[nodiscard]] const FixedAssemblyReconciliation &importAudit() const {return import_;}
    [[nodiscard]] double elapsedTime() const {return elapsed_s_;}
    [[nodiscard]] std::uint64_t steps() const {return steps_;}
    // Signed free advance supports reference reversal. Positive coupled steps
    // are enforced by the source/target wrapper. Fully preflighted before write.
    DoubleRigidTransfer advanceFree(double dt_s);
    DoubleFixedSourceTransfer applyImpulse(std::uint32_t member,Vec3 point_world_m,
        Vec3 impulse_n_s,Vec3 free_angular_impulse_kg_m2_s={});
    // Trusted pure contact result, at exactly the current source geometry.
    // Only velocities may change. Candidate rigid compatibility is checked;
    // source transfer roundoff is measured by the coupled wrapper.
    void adoptContact(const std::vector<RigidMechanicalState> &);
private:
    struct Member {double mass{};Vec3 offset{};Quat orientation{};Mat3 inertia{};};
    struct Link {std::uint32_t a{},b{};Vec3 anchor{};};
    DoubleRigidState state_;
    std::vector<Member> members_;
    std::vector<Link> links_;
    FixedAssemblyReconciliation import_;
    double elapsed_s_{};
    std::uint64_t steps_{};
};
} // namespace banjo
