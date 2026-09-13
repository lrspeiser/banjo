#include "rigid/JoltWorld.hpp"
#include "fracture/ActivationPolicy.hpp"
#include "physics/RigidAttachment.hpp"

#include "material/MaterialCompiler.hpp"

#include <Jolt/Jolt.h>
#include <Jolt/RegisterTypes.h>
#include <Jolt/Core/Factory.h>
#include <Jolt/Core/JobSystemThreadPool.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Body/BodyLock.h>
#include <Jolt/Physics/StateRecorderImpl.h>
#include <Jolt/Physics/Collision/ContactListener.h>
#include <Jolt/Physics/Collision/EstimateCollisionResponse.h>
#include <Jolt/Physics/Collision/TransformedShape.h>
#include <Jolt/Physics/Constraints/ContactConstraintManager.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/MeshShape.h>
#include <Jolt/Physics/Collision/Shape/ConvexHullShape.h>
#include <Jolt/Physics/Collision/Shape/OffsetCenterOfMassShape.h>
#include <Jolt/Physics/Constraints/FixedConstraint.h>
#include <Jolt/Physics/Constraints/DistanceConstraint.h>
#include <Jolt/Physics/Constraints/FixedConstraint.h>
#include <Jolt/Physics/Constraints/HingeConstraint.h>
#include <Jolt/Physics/Constraints/PulleyConstraint.h>
#include <Jolt/Physics/Constraints/SliderConstraint.h>
#include <Jolt/Physics/Collision/Shape/RotatedTranslatedShape.h>
#include <Jolt/Physics/Collision/CastResult.h>
#include <Jolt/Physics/Collision/RayCast.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <Jolt/Physics/Collision/Shape/StaticCompoundShape.h>
#include <Jolt/Physics/PhysicsSystem.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <numbers>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

JPH_SUPPRESS_WARNINGS

namespace banjo {
namespace {

using namespace JPH::literals;

// kSupportSurfaceMatterId now lives in core/Types.hpp, so a scene that
// reports contacts by name can recognise the ground.

namespace Layers {
constexpr JPH::ObjectLayer kNonMoving = 0;
constexpr JPH::ObjectLayer kMoving = 1;
constexpr JPH::ObjectLayer kCount = 2;
} // namespace Layers

namespace BroadPhaseLayers {
const JPH::BroadPhaseLayer kNonMoving{0};
const JPH::BroadPhaseLayer kMoving{1};
constexpr JPH::uint kCount = 2;
} // namespace BroadPhaseLayers

class ObjectLayerPairFilter final : public JPH::ObjectLayerPairFilter {
public:
    [[nodiscard]] bool ShouldCollide(
        JPH::ObjectLayer object1,
        JPH::ObjectLayer object2) const override {
        if (object1 == Layers::kNonMoving) {
            return object2 == Layers::kMoving;
        }
        if (object1 == Layers::kMoving) {
            return true;
        }
        return false;
    }
};

class BroadPhaseLayerInterface final : public JPH::BroadPhaseLayerInterface {
public:
    BroadPhaseLayerInterface() {
        mapping_[Layers::kNonMoving] = BroadPhaseLayers::kNonMoving;
        mapping_[Layers::kMoving] = BroadPhaseLayers::kMoving;
    }

    [[nodiscard]] JPH::uint GetNumBroadPhaseLayers() const override {
        return BroadPhaseLayers::kCount;
    }

    [[nodiscard]] JPH::BroadPhaseLayer GetBroadPhaseLayer(
        JPH::ObjectLayer layer) const override {
        return mapping_[layer];
    }

private:
    JPH::BroadPhaseLayer mapping_[Layers::kCount];
};

class ObjectVsBroadPhaseLayerFilter final : public JPH::ObjectVsBroadPhaseLayerFilter {
public:
    [[nodiscard]] bool ShouldCollide(
        JPH::ObjectLayer object_layer,
        JPH::BroadPhaseLayer broad_phase_layer) const override {
        if (object_layer == Layers::kNonMoving) {
            return broad_phase_layer == BroadPhaseLayers::kMoving;
        }
        if (object_layer == Layers::kMoving) {
            return true;
        }
        return false;
    }
};

[[nodiscard]] Vec3 fromJoltVector(JPH::Vec3Arg value) {
    return {
        static_cast<double>(value.GetX()),
        static_cast<double>(value.GetY()),
        static_cast<double>(value.GetZ()),
    };
}

[[nodiscard]] Vec3 fromJoltPosition(JPH::RVec3Arg value) {
    return {
        static_cast<double>(value.GetX()),
        static_cast<double>(value.GetY()),
        static_cast<double>(value.GetZ()),
    };
}

[[nodiscard]] JPH::Vec3 toJolt(const Vec3 &value) {
    return {
        static_cast<float>(value.x),
        static_cast<float>(value.y),
        static_cast<float>(value.z),
    };
}

[[nodiscard]] JPH::RVec3 toJoltPosition(const Vec3 &value) {
    return JPH::RVec3(
        static_cast<JPH::Real>(value.x),
        static_cast<JPH::Real>(value.y),
        static_cast<JPH::Real>(value.z));
}

[[nodiscard]] JPH::Mat44 toJoltInertia(const Mat3 &inertia) {
    JPH::Mat44 result = JPH::Mat44::sIdentity();
    for (JPH::uint row = 0; row < 3; ++row) {
        for (JPH::uint column = 0; column < 3; ++column) {
            result(row, column) = static_cast<float>(inertia.m[row][column]);
        }
    }
    return result;
}

struct BodyContactState {
    CompiledContactMaterial contact{};
    double radius_m{};
    double sphere_inertia_factor{0.4};
    bool is_sphere{};
    double mass_kg{};
    std::optional<MaterialDefinition> activation_material;
};

[[nodiscard]] CompiledContactMaterial legacyFragmentContact(
    double friction,
    double restitution) {
    CompiledContactMaterial contact;
    contact.static_friction = std::max(0.0, friction);
    contact.dynamic_friction = std::max(0.0, friction);
    contact.rolling_resistance = 0.001;
    contact.restitution = std::clamp(restitution, 0.0, 1.0);
    contact.contact_damping_ratio =
        dampingRatioFromCoefficientOfRestitution(contact.restitution);
    contact.young_modulus_pa = 70.0e9;
    contact.poisson_ratio = 0.22;
    return contact;
}

void traceImpl(const char *format, ...) {
    std::va_list args;
    va_start(args, format);
    char buffer[1024];
    std::vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);
    std::cerr << "[Jolt] " << buffer << '\n';
}

#ifdef JPH_ENABLE_ASSERTS
bool assertFailedImpl(
    const char *expression,
    const char *message,
    const char *file,
    JPH::uint line) {
    std::cerr << file << ':' << line << " (" << expression << ") "
              << (message != nullptr ? message : "") << '\n';
    return true;
}
#endif

class ImpactCollector final : public JPH::ContactListener {
public:
    bool detailed_observations{};
    bool observations_enabled{true};
    // Whether landing on the support surface counts as an impact worth
    // reporting. Off by default, because a body lying on the floor is in
    // contact with it on every step for ever and a lane that does not need
    // those should not pay for them.
    bool surface_observations{};
    std::atomic<unsigned> manifolds{},points{},speculative_manifolds{};
    ImpactCollector(
        std::atomic<std::uint64_t> &tick,
        const std::unordered_map<MatterBodyId, BodyContactState> &contact_states,
        const std::set<std::pair<MatterBodyId,MatterBodyId>> &external_pairs)
        : tick_(tick), contact_states_(contact_states), external_pairs_(external_pairs) {}

    JPH::ValidateResult OnContactValidate(const JPH::Body &a,const JPH::Body &b,JPH::RVec3Arg,const JPH::CollideShapeResult &) override {
        const MatterBodyId first=a.GetUserData(),second=b.GetUserData();const auto key=std::minmax(first,second);
        return external_pairs_.contains(key)?JPH::ValidateResult::RejectAllContactsForThisBodyPair:JPH::ValidateResult::AcceptAllContactsForThisBodyPair;
    }

    void OnContactAdded(
        const JPH::Body &body1,
        const JPH::Body &body2,
        const JPH::ContactManifold &manifold,
        JPH::ContactSettings &settings) override {
        processContact(body1, body2, manifold, settings, true);
    }

    void OnContactPersisted(
        const JPH::Body &body1,
        const JPH::Body &body2,
        const JPH::ContactManifold &manifold,
        JPH::ContactSettings &settings) override {
        processContact(body1, body2, manifold, settings, false);
    }

    [[nodiscard]] std::vector<ImpactEvent> capture() {std::scoped_lock lock(mutex_);if(events_.size()>65536)throw std::runtime_error("trial event queue budget exceeded");return events_;}
    void restore(std::vector<ImpactEvent> events) {std::scoped_lock lock(mutex_);events_.swap(events);}
    [[nodiscard]] std::vector<ImpactEvent> drain() {
        std::scoped_lock lock(mutex_);
        std::vector<ImpactEvent> result;
        result.swap(events_);
        return result;
    }

private:
    void processContact(
        const JPH::Body &body1,
        const JPH::Body &body2,
        const JPH::ContactManifold &manifold,
        JPH::ContactSettings &settings,
        bool record_impact) {
        const MatterBodyId id1 = body1.GetUserData();
        const MatterBodyId id2 = body2.GetUserData();
        const auto state1 = contact_states_.find(id1);
        const auto state2 = contact_states_.find(id2);
        if (state1 == contact_states_.end() || state2 == contact_states_.end()) {
            return;
        }

        const JPH::uint contact_count = manifold.mRelativeContactPointsOn1.size();
        if (contact_count == 0U) {
            return;
        }
        manifolds.fetch_add(1,std::memory_order_relaxed);
        points.fetch_add(contact_count,std::memory_order_relaxed);
        if(manifold.mPenetrationDepth<0)speculative_manifolds.fetch_add(1,std::memory_order_relaxed);

        JPH::RVec3 contact_sum = JPH::RVec3::sZero();
        for (JPH::uint index = 0; index < contact_count; ++index) {
            contact_sum += 0.5_r *
                           (manifold.GetWorldSpaceContactPointOn1(index) +
                            manifold.GetWorldSpaceContactPointOn2(index));
        }
        const JPH::RVec3 contact_point =
            contact_sum / static_cast<float>(contact_count);
        const JPH::Vec3 relative_velocity =
            body2.GetPointVelocity(contact_point) -
            body1.GetPointVelocity(contact_point);
        const double normal_speed =
            static_cast<double>(relative_velocity.Dot(manifold.mWorldSpaceNormal));
        const double closing_speed = std::max(0.0, -normal_speed);
        const JPH::Vec3 tangent_velocity =
            relative_velocity - static_cast<float>(normal_speed) *
                                    manifold.mWorldSpaceNormal;
        const double tangential_speed =
            static_cast<double>(tangent_velocity.Length());

        const CombinedContactMaterial combined = combineContactMaterials(
            state1->second.contact, state2->second.contact);
        const double applied_friction = tangential_speed < 0.05
                                            ? combined.static_friction
                                            : combined.dynamic_friction;
        settings.mCombinedFriction = static_cast<float>(applied_friction);
        settings.mCombinedRestitution =
            static_cast<float>(combined.restitution);

        if (id1 == kInvalidMatterBodyId || id2 == kInvalidMatterBodyId) {
            return;
        }
        // Network worlds consume spring reactions, not these optional impact
        // estimates. Keep material contact settings above and retain activation
        // estimates whenever a deferred-contact law needs them.
        if(!observations_enabled&&!state1->second.activation_material&&!state2->second.activation_material)return;

        JPH::CollisionEstimationResult estimation;
        JPH::EstimateCollisionResponse(
            body1,
            body2,
            manifold,
            estimation,
            settings.mCombinedFriction,
            settings.mCombinedRestitution);
        double estimated_normal_impulse = 0.0;
        for (const float impulse : estimation.mContactImpulse) {
            estimated_normal_impulse += static_cast<double>(impulse);
        }

        const double inverse_mass_1 = body1.IsDynamic()
                                          ? body1.GetMotionProperties()->GetInverseMass()
                                          : 0.0;
        const double inverse_mass_2 = body2.IsDynamic()
                                          ? body2.GetMotionProperties()->GetInverseMass()
                                          : 0.0;
        const double inverse_reduced_mass = inverse_mass_1 + inverse_mass_2;
        const double reduced_mass =
            inverse_reduced_mass > 0.0 ? 1.0 / inverse_reduced_mass : 0.0;

        ImpactEvent event;
        event.fixed_tick = tick_.load(std::memory_order_relaxed);
        event.body_a = id1;
        event.body_b = id2;
        event.contact_point_world_m = fromJoltPosition(contact_point);
        event.normal_a_to_b =
            normalized(fromJoltVector(manifold.mWorldSpaceNormal));
        event.relative_velocity_b_minus_a_m_s =
            fromJoltVector(relative_velocity);
        event.closing_speed_m_s = closing_speed;
        event.tangential_speed_m_s = tangential_speed;
        event.estimated_normal_impulse_n_s = estimated_normal_impulse;
        event.available_normal_energy_j =
            0.5 * reduced_mass * closing_speed * closing_speed;
        event.combined_static_friction = combined.static_friction;
        event.combined_dynamic_friction = combined.dynamic_friction;
        event.applied_friction = applied_friction;
        event.combined_restitution = combined.restitution;
        event.effective_contact_modulus_pa = combined.effective_modulus_pa;

        // The callback changes contact settings only; body lifetime/motion is
        // changed by the experiment after PhysicsSystem::Update has returned.
        const auto should_defer = [&](MatterBodyId id, const BodyContactState &target,
                                      const BodyContactState &other) {
            // This checkpoint supports a rigid sphere against active material.
            // Do not suppress arbitrary support contacts without a matching solver.
            if (!target.activation_material || !other.is_sphere) return false;
            const double reduced_radius = other.is_sphere
                ? target.radius_m * other.radius_m / (target.radius_m + other.radius_m)
                : target.radius_m;
            return ActivationPolicy{}.evaluate(event, {
                .body_id = id, .radius_m = target.radius_m,
                .material = *target.activation_material,
                .reduced_radius_m = reduced_radius,
            }).activate;
        };
        if (should_defer(id1, state1->second, state2->second) ||
            should_defer(id2, state2->second, state1->second)) {
            settings.mIsSensor = true;
            event.response_deferred_to_material = true;
        }
        // A contact with the floor. Suppressed unless a lane has asked for it,
        // and even then only the moment it ARRIVES -- `record_impact` is true
        // for a contact added and false for one that persists, so a thing lying
        // on the floor reports its landing and then says nothing more about it.
        //
        // Without this nothing could ever be damaged by hitting the ground,
        // which is most of what happens to anything: the impact was never
        // reported, so it was never judged, so the lattice never ran. The line
        // in LiveWorld that names an impact's other side "the ground" could not
        // be reached at all.
        const bool surface_contact =
            (id1 == kSupportSurfaceMatterId || id2 == kSupportSurfaceMatterId) &&
            !surface_observations;
        if(!observations_enabled&&!event.response_deferred_to_material)return;
        if (!event.response_deferred_to_material && (!record_impact || surface_contact) && !detailed_observations) return;
        if(detailed_observations && closing_speed<.01) return;
        std::scoped_lock lock(mutex_);
        if(!detailed_observations||events_.size()<65536)events_.push_back(event);
    }

    std::atomic<std::uint64_t> &tick_;
    const std::unordered_map<MatterBodyId, BodyContactState> &contact_states_;
    const std::set<std::pair<MatterBodyId,MatterBodyId>> &external_pairs_;
    std::mutex mutex_;
    std::vector<ImpactEvent> events_;
};

// Factory/type registration belongs to the process, not an individual world.
// A creator reload can prepare a second world before publishing it; destroying
// either world must not invalidate the other's shapes and type registry.
class JoltRuntime {
public:
    JoltRuntime() {
        JPH::RegisterDefaultAllocator();
        JPH::Trace = traceImpl;
#ifdef JPH_ENABLE_ASSERTS
        JPH::AssertFailed = assertFailedImpl;
#endif
        JPH::Factory::sInstance = new JPH::Factory();
        JPH::RegisterTypes();
    }
    ~JoltRuntime() {
        JPH::UnregisterTypes();
        delete JPH::Factory::sInstance;
        JPH::Factory::sInstance = nullptr;
    }
};
void ensureJoltRuntime() { static JoltRuntime runtime; }
} // namespace

class JoltWorld::Impl {
public:
    explicit Impl(int requested_workers=-1,RigidContactCapacity capacity={}) : impact_collector_(tick_, contact_states_,external_pairs_) {
        if(capacity.body_pairs<128||capacity.body_pairs>262144||capacity.constraints<64||capacity.constraints>65536)
            throw std::invalid_argument("contact capacity bounds exceeded");
        contact_diagnostics_.capacity=capacity;
        ensureJoltRuntime();

        // Jolt reserves the full declared contact buffer on every update.
        // Size from this build's actual constraint layout, plus index/alignment
        // space and 32 MiB for the bounded body's other update scratch. Never
        // rely on malloc fallback during a step or a fixed 32 MiB at all caps.
        const std::size_t scratch_bytes=32U*1024U*1024U+std::size_t(capacity.constraints)*
            (JPH::ContactConstraintManager::cMaxConstraintSize+64U);
        if(scratch_bytes>256U*1024U*1024U)
            throw std::invalid_argument("contact capacity exceeds temporary arena budget on this build");
        contact_diagnostics_.temporary_arena_bytes=scratch_bytes;
        temp_allocator_=std::make_unique<JPH::TempAllocatorImpl>(scratch_bytes);
        const unsigned hardware_threads =
            std::max(1U, std::thread::hardware_concurrency());
        const unsigned worker_threads =
            hardware_threads > 1U ? hardware_threads - 1U : 1U;
        job_system_ = std::make_unique<JPH::JobSystemThreadPool>(
            JPH::cMaxPhysicsJobs,
            JPH::cMaxPhysicsBarriers,
            requested_workers<0?int(worker_threads):requested_workers);
        physics_ = std::make_unique<JPH::PhysicsSystem>();
        physics_->Init(
            8192,
            0,
            capacity.body_pairs,
            capacity.constraints,
            broad_phase_interface_,
            object_vs_broad_phase_filter_,
            object_pair_filter_);
        physics_->SetContactListener(&impact_collector_);
        physics_->SetGravity(toJolt(gravity_m_s2_));
    }

    ~Impl() {
        if (physics_) {
            for(auto &[id,spring]:springs_) { (void)id;physics_->RemoveConstraint(spring.constraint); }
            springs_.clear();
            for(auto &[id,constraint]:pins_) { (void)id;physics_->RemoveConstraint(constraint); }
            pins_.clear();
            JPH::BodyInterface &body_interface = physics_->GetBodyInterface();
            for (const auto &[logical_id, body_id] : bodies_) {
                (void)logical_id;
                if (!body_id.IsInvalid()) {
                    body_interface.RemoveBody(body_id);
                    body_interface.DestroyBody(body_id);
                }
            }
            if (!floor_id_.IsInvalid()) {
                body_interface.RemoveBody(floor_id_);
                body_interface.DestroyBody(floor_id_);
            }
        }

        physics_.reset();
        job_system_.reset();
        temp_allocator_.reset();
    }

    void applyRollingResistance(double fixed_dt_s) {
        if (!support_surface_) {
            return;
        }
        const auto surface_state = contact_states_.find(kSupportSurfaceMatterId);
        if (surface_state == contact_states_.end()) {
            return;
        }

        JPH::BodyInterface &body_interface = physics_->GetBodyInterface();
        const SupportPlaneFrame &plane = support_surface_->frame;
        const double normal_gravity =
            std::max(0.0, -dot(gravity_m_s2_, plane.normal_world));
        if (normal_gravity <= 0.0) {
            return;
        }

        for (const auto &[logical_id, body_id] : bodies_) {
            const auto body_state = contact_states_.find(logical_id);
            if (body_state == contact_states_.end() ||
                !body_state->second.is_sphere ||
                body_state->second.radius_m <= 0.0) {
                continue;
            }

            const CombinedContactMaterial combined = combineContactMaterials(
                body_state->second.contact, surface_state->second.contact);
            if (combined.rolling_resistance <= 0.0) {
                continue;
            }

            const Vec3 center = fromJoltPosition(
                body_interface.GetCenterOfMassPosition(body_id));
            const double distance = signedDistanceToPlane(plane, center);
            const double contact_tolerance =
                std::max(0.001, 0.01 * body_state->second.radius_m);
            if (std::abs(distance - body_state->second.radius_m) >
                contact_tolerance) {
                continue;
            }

            if (!insideSupportFootprint(plane, center,
                    support_surface_->half_length_tangent_m,
                    support_surface_->half_length_bitangent_m)) continue;
            const Vec3 linear = fromJoltVector(body_interface.GetLinearVelocity(body_id));
            if (std::abs(dot(linear, plane.normal_world)) > 0.1) continue;
            const Vec3 angular = fromJoltVector(body_interface.GetAngularVelocity(body_id));
            const Vec3 rolling_spin = projectVectorOntoPlane(plane, angular);
            const double speed = length(rolling_spin);
            if (speed <= 1.0e-10) continue;
            const double mass = body_state->second.mass_kg;
            const double radius = body_state->second.radius_m;
            const double inertia = body_state->second.sphere_inertia_factor * mass * radius * radius;
            // tau_rr = mu_rr * N * radius. Static contact friction in Jolt,
            // not a velocity overwrite here, determines rolling vs. sliding.
            const double angular_impulse = std::min(inertia * speed,
                combined.rolling_resistance * mass * normal_gravity * radius * fixed_dt_s);
            body_interface.AddAngularImpulse(body_id,
                toJolt((-angular_impulse / speed) * rolling_spin));
        }
    }

    void requireConfigurationMutable() const {
        if(trial_depth_!=0||spring_trial_depth_!=0)
            throw std::logic_error("configuration/topology changes are forbidden during a trial");
    }
    void requireSpringMutable() const {
        // A general reversible trial nested in a spring trial retains its
        // original no-configuration-mutation contract.
        if(trial_depth_!=0)
            throw std::logic_error("spring changes are forbidden during a reversible trial");
    }
    unsigned trial_depth_{};
    unsigned spring_trial_depth_{};
    BroadPhaseLayerInterface broad_phase_interface_;
    ObjectVsBroadPhaseLayerFilter object_vs_broad_phase_filter_;
    ObjectLayerPairFilter object_pair_filter_;
    std::unique_ptr<JPH::TempAllocatorImpl> temp_allocator_;
    std::unique_ptr<JPH::JobSystemThreadPool> job_system_;
    std::unique_ptr<JPH::PhysicsSystem> physics_;
    std::unordered_map<MatterBodyId, BodyContactState> contact_states_;
    std::set<std::pair<MatterBodyId,MatterBodyId>> external_pairs_;
    std::atomic<std::uint64_t> tick_{0};
    ImpactCollector impact_collector_;
    JPH::BodyID floor_id_;
    std::unordered_map<MatterBodyId,JPH::Ref<JPH::Constraint>> pins_;
    struct Spring { MatterBodyId a,b; JPH::Ref<JPH::DistanceConstraint> constraint; };
    std::unordered_map<unsigned,Spring> springs_;
    unsigned next_spring_{1};
    // Every kind of joint in one table, held as the base class Jolt gives them
    // all. jointsOn(), removeJoint() and the drop that happens when a body is
    // destroyed have to work the same for a pin and a slide -- and for the rope
    // anchors and pulleys that come next -- so the one thing they must not do is
    // be two tables that each half-remember a body.
    struct Joint {
        MatterBodyId a,b;
        JointKind kind;
        JPH::Ref<JPH::TwoBodyConstraint> constraint;
    };
    // How long the last step was. Only jointTension() needs it: Jolt reports a
    // constraint's IMPULSE over the step, and an impulse divided by the step it
    // was applied over is the force -- which is what anybody asking how hard a
    // rope is pulling means.
    double last_dt_s{0.0};
    std::unordered_map<unsigned,Joint> joints_;
    unsigned next_joint_{1};
    std::unordered_map<MatterBodyId, JPH::BodyID> bodies_;
    RigidContactDiagnostics contact_diagnostics_;
    std::optional<RigidSurfaceDescription> support_surface_;
    Vec3 gravity_m_s2_{0.0, -9.81, 0.0};
};

JoltWorld::JoltWorld() : impl_(std::make_unique<Impl>()) {}
JoltWorld::JoltWorld(unsigned workers) {
    if(workers>64)throw std::invalid_argument("worker thread budget exceeded");
    impl_=std::make_unique<Impl>(int(workers));
}
JoltWorld::JoltWorld(unsigned workers,RigidContactCapacity capacity) {
    if(workers>64)throw std::invalid_argument("worker thread budget exceeded");
    impl_=std::make_unique<Impl>(int(workers),capacity);
}
JoltWorld::~JoltWorld() = default;
JoltWorld::JoltWorld(JoltWorld &&) noexcept = default;
JoltWorld &JoltWorld::operator=(JoltWorld &&) noexcept = default;

void JoltWorld::setBodyPairContactCacheEnabled(bool enabled) {
    impl_->requireConfigurationMutable();
    if(!impl_->bodies_.empty()||!impl_->floor_id_.IsInvalid())throw std::logic_error("configure body-pair cache before creating bodies");
    auto settings=impl_->physics_->GetPhysicsSettings();settings.mUseBodyPairContactCache=enabled;impl_->physics_->SetPhysicsSettings(settings);
}

void JoltWorld::setContactSolverIterations(unsigned velocity,unsigned position) {
    impl_->requireConfigurationMutable();
    if(!impl_->bodies_.empty()||!impl_->floor_id_.IsInvalid())throw std::logic_error("configure contact iterations before creating bodies");
    if(velocity<2||velocity>256||position<1||position>64)throw std::invalid_argument("contact solver iteration bounds exceeded");
    auto settings=impl_->physics_->GetPhysicsSettings();settings.mNumVelocitySteps=velocity;settings.mNumPositionSteps=position;impl_->physics_->SetPhysicsSettings(settings);
}

void JoltWorld::setGravity(const Vec3 &gravity_m_s2) {
    impl_->requireConfigurationMutable();
    impl_->gravity_m_s2_ = gravity_m_s2;
    impl_->physics_->SetGravity(toJolt(gravity_m_s2));
}

void JoltWorld::addFloor() {
    impl_->requireConfigurationMutable();
    MaterialDefinition concrete;
    concrete.name = "default_concrete_surface";
    concrete.density_kg_m3 = 2400.0;
    concrete.young_modulus_pa = 30.0e9;
    concrete.poisson_ratio = 0.20;
    concrete.static_friction = 0.75;
    concrete.dynamic_friction = 0.62;
    concrete.friction = concrete.dynamic_friction;
    concrete.rolling_resistance = 0.015;
    concrete.contact_damping_ratio = 0.30;
    concrete.derive_restitution_from_damping = true;
    addSupportSurface({
        .frame = makeSupportPlane({}, {0.0, 1.0, 0.0}),
        .material = concrete,
    });
}

void JoltWorld::addSupportSurface(const RigidSurfaceDescription &description) {
    impl_->requireConfigurationMutable();
    if (!impl_->floor_id_.IsInvalid()) {
        throw std::logic_error("support surface already exists");
    }
    if (description.half_length_tangent_m <= 0.0 ||
        description.half_length_bitangent_m <= 0.0 ||
        description.thickness_m <= 0.0) {
        throw std::invalid_argument("support surface dimensions must be positive");
    }

    RigidSurfaceDescription stored = description;
    stored.frame = makeSupportPlane(
        description.frame.point_world_m,
        description.frame.normal_world,
        description.frame.tangent_world);
    const CompiledContactMaterial contact =
        compileContactMaterial(stored.material);

    const Vec3 center =
        stored.frame.point_world_m -
        0.5 * stored.thickness_m * stored.frame.normal_world;
    const JPH::Quat orientation = JPH::Quat::sFromTo(
        JPH::Vec3::sAxisY(), toJolt(stored.frame.normal_world));
    JPH::BodyCreationSettings settings(
        new JPH::BoxShape(JPH::Vec3(
            static_cast<float>(stored.half_length_tangent_m),
            static_cast<float>(0.5 * stored.thickness_m),
            static_cast<float>(stored.half_length_bitangent_m))),
        toJoltPosition(center),
        orientation,
        JPH::EMotionType::Static,
        Layers::kNonMoving);
    settings.mFriction = static_cast<float>(contact.dynamic_friction);
    settings.mRestitution = static_cast<float>(contact.restitution);
    settings.mUserData = kSupportSurfaceMatterId;

    impl_->floor_id_ = impl_->physics_->GetBodyInterface().CreateAndAddBody(
        settings, JPH::EActivation::DontActivate);
    if (impl_->floor_id_.IsInvalid()) {
        throw std::runtime_error("Jolt could not create support surface");
    }
    impl_->support_surface_ = stored;
    impl_->contact_states_[kSupportSurfaceMatterId] = {
        contact,
        0.0,
        0.0,
        false,
    };
}

void JoltWorld::addTriangleSupport(const std::vector<std::array<Vec3,3>> &triangles,const MaterialDefinition &material) {
    impl_->requireConfigurationMutable();
    if (!impl_->floor_id_.IsInvalid()) throw std::logic_error("support surface already exists");
    if (triangles.empty() || triangles.size()>32768) throw std::invalid_argument("triangle support requires 1..32768 triangles");
    JPH::TriangleList mesh;
    for (const auto &t:triangles) {
        for(const auto &v:t) if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z)||length(v)>100)
            throw std::invalid_argument("support vertex exceeds finite 100 m bounds");
        if(length(cross(t[1]-t[0],t[2]-t[0]))<1e-10) throw std::invalid_argument("degenerate support triangle");
        mesh.emplace_back(JPH::Float3(float(t[0].x),float(t[0].y),float(t[0].z)),
            JPH::Float3(float(t[1].x),float(t[1].y),float(t[1].z)),JPH::Float3(float(t[2].x),float(t[2].y),float(t[2].z)));
    }
    const auto contact=compileContactMaterial(material);
    const auto shape=JPH::MeshShapeSettings(mesh).Create();
    if(shape.HasError()) throw std::invalid_argument(shape.GetError().c_str());
    JPH::BodyCreationSettings settings(shape.Get(),JPH::RVec3::sZero(),JPH::Quat::sIdentity(),JPH::EMotionType::Static,Layers::kNonMoving);
    settings.mFriction=float(contact.dynamic_friction);settings.mRestitution=float(contact.restitution);settings.mUserData=kSupportSurfaceMatterId;
    const auto id=impl_->physics_->GetBodyInterface().CreateAndAddBody(settings,JPH::EActivation::DontActivate);
    if(id.IsInvalid())throw std::runtime_error("Jolt could not create triangle support");
    impl_->floor_id_=id;
    impl_->contact_states_[kSupportSurfaceMatterId]={contact,0,0,false};
}

void JoltWorld::addBall(const RigidBallDescription &description) {
    impl_->requireConfigurationMutable();
    if (description.body_id == kInvalidMatterBodyId ||
        description.body_id == kSupportSurfaceMatterId ||
        description.radius_m <= 0.0 ||
        description.material.density_kg_m3 <= 0.0 ||
        description.sphere_inertia_factor <= 0.0) {
        throw std::invalid_argument("ball requires a valid ID, radius, density, and inertia");
    }
    if (impl_->bodies_.contains(description.body_id)) {
        throw std::logic_error("body ID is already in the Jolt world");
    }

    const CompiledContactMaterial contact =
        compileContactMaterial(description.material);
    const double volume = (4.0 / 3.0) * std::numbers::pi *
                          description.radius_m * description.radius_m *
                          description.radius_m;
    const double computed_mass =
        volume * description.material.density_kg_m3;
    const double mass = description.mass_override_kg > 0.0
                            ? description.mass_override_kg
                            : computed_mass;

    JPH::BodyCreationSettings settings(
        new JPH::SphereShape(static_cast<float>(description.radius_m)),
        toJoltPosition(description.position_world_m),
        JPH::Quat::sIdentity(),
        JPH::EMotionType::Dynamic,
        Layers::kMoving);
    settings.mFriction = static_cast<float>(contact.dynamic_friction);
    settings.mRestitution = static_cast<float>(contact.restitution);
    // Bulk material damping is internal, not aerodynamic drag on a rigid body.
    settings.mLinearDamping = 0.0F;
    settings.mAngularDamping = 0.0F;
    settings.mMaxAngularVelocity = 1000.0F;
    settings.mUserData = description.body_id;
    settings.mOverrideMassProperties =
        JPH::EOverrideMassProperties::CalculateInertia;
    settings.mMassPropertiesOverride.mMass = static_cast<float>(mass);
    settings.mInertiaMultiplier = static_cast<float>(
        description.sphere_inertia_factor / 0.4);

    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    // Finish potentially allocating map growth before publishing a Jolt body.
    impl_->bodies_.reserve(impl_->bodies_.size()+1);
    impl_->contact_states_.reserve(impl_->contact_states_.size()+1);
    const JPH::BodyID body_id =
        body_interface.CreateAndAddBody(settings, JPH::EActivation::Activate);
    if (body_id.IsInvalid()) {
        throw std::runtime_error("Jolt could not create ball body");
    }
    body_interface.SetLinearAndAngularVelocity(
        body_id,
        toJolt(description.linear_velocity_m_s),
        toJolt(description.angular_velocity_rad_s));
    try {
        impl_->bodies_.emplace(description.body_id, body_id);
        impl_->contact_states_.emplace(
        description.body_id,
        BodyContactState{
            contact,
            description.radius_m,
            description.sphere_inertia_factor,
            true,
            mass,
            description.defer_brittle_contacts_to_material &&
                description.material.model == MaterialModel::BrittleBond
                ? std::optional<MaterialDefinition>{description.material} : std::nullopt,
        });
    } catch (...) {
        impl_->bodies_.erase(description.body_id);
        impl_->contact_states_.erase(description.body_id);
        body_interface.RemoveBody(body_id);
        body_interface.DestroyBody(body_id);
        throw;
    }
}

void JoltWorld::addBox(const RigidBoxDescription &description) {
    impl_->requireConfigurationMutable();
    const auto d=description.dimensions_m;
    const auto &s=description.state;
    const auto finite=[](Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);};
    const auto q=s.orientation_world;
    if(description.body_id==kInvalidMatterBodyId||description.body_id==kSupportSurfaceMatterId||
        !finite(d)||d.x<=0||d.y<=0||d.z<=0||
        !std::isfinite(description.material.density_kg_m3)||description.material.density_kg_m3<=0||
        !finite(s.center_of_mass_world_m)||!finite(s.linear_velocity_m_s)||!finite(s.angular_velocity_rad_s)||
        !std::isfinite(q.w+q.x+q.y+q.z)||std::abs(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z-1)>1e-5)
        throw std::invalid_argument("box requires finite positive dimensions/density and valid rigid state");
    if(impl_->bodies_.contains(description.body_id))throw std::logic_error("body ID is already in the Jolt world");
    if(description.fixed&&(lengthSquared(s.linear_velocity_m_s)>0||lengthSquared(s.angular_velocity_rad_s)>0))throw std::invalid_argument("fixed box cannot have initial motion");
    const RigidPrimitive shape{PrimitiveKind::Box,0,d};
    const double mass=shape.volume()*description.material.density_kg_m3;
    const auto inertia=shape.inertia(mass);
    const JPH::Vec3 inverse_diagonal(static_cast<float>(1/inertia.m[0][0]),static_cast<float>(1/inertia.m[1][1]),static_cast<float>(1/inertia.m[2][2]));
    if(!description.fixed&&(!std::isfinite(static_cast<float>(mass))||static_cast<float>(mass)<=0||
        !std::isfinite(inverse_diagonal.GetX())||!std::isfinite(inverse_diagonal.GetY())||!std::isfinite(inverse_diagonal.GetZ())||
        inverse_diagonal.GetX()<=0||inverse_diagonal.GetY()<=0||inverse_diagonal.GetZ()<=0))
        throw std::invalid_argument("box mass/inverse inertia is not representable");
    const auto contact=compileContactMaterial(description.material);
    JPH::BodyCreationSettings settings(new JPH::BoxShape(toJolt(d/2),0.0F),
        toJoltPosition(s.center_of_mass_world_m),
        JPH::Quat(static_cast<float>(q.x),static_cast<float>(q.y),static_cast<float>(q.z),static_cast<float>(q.w)),
        description.fixed?JPH::EMotionType::Static:JPH::EMotionType::Dynamic,description.fixed?Layers::kNonMoving:Layers::kMoving);
    settings.mFriction=static_cast<float>(contact.dynamic_friction);
    settings.mRestitution=static_cast<float>(contact.restitution);
    settings.mLinearDamping=0;settings.mAngularDamping=0;settings.mMaxAngularVelocity=1000;
    settings.mApplyGyroscopicForce=true;
    settings.mMotionQuality=JPH::EMotionQuality::LinearCast;
    settings.mUserData=description.body_id;
    settings.mOverrideMassProperties=JPH::EOverrideMassProperties::MassAndInertiaProvided;
    settings.mMassPropertiesOverride.mMass=static_cast<float>(mass);
    settings.mMassPropertiesOverride.mInertia=toJoltInertia(shape.inertia(mass));
    auto &bodies=impl_->physics_->GetBodyInterface();
    impl_->bodies_.reserve(impl_->bodies_.size()+1);impl_->contact_states_.reserve(impl_->contact_states_.size()+1);
    const auto id=bodies.CreateAndAddBody(settings,description.fixed?JPH::EActivation::DontActivate:JPH::EActivation::Activate);
    if(id.IsInvalid())throw std::runtime_error("Jolt could not create box body");
    try {
        if(!description.fixed) {
            // Jolt's absolute near-zero principal-inertia test substitutes a
            // radius-one sphere for sufficiently small valid boxes. The box
            // principal axes are known analytically; install them directly.
            {
                JPH::BodyLockWrite lock(impl_->physics_->GetBodyLockInterface(),id);
                if(!lock.Succeeded())throw std::runtime_error("cannot lock new box inertia");
                lock.GetBody().GetMotionProperties()->SetInverseInertia(inverse_diagonal,JPH::Quat::sIdentity());
            }
            bodies.SetLinearAndAngularVelocity(id,toJolt(s.linear_velocity_m_s),toJolt(s.angular_velocity_rad_s));
        }
        impl_->bodies_.emplace(description.body_id,id);
        impl_->contact_states_.emplace(description.body_id,BodyContactState{contact,0,0,false,mass,{}});
    }catch(...) {
        impl_->bodies_.erase(description.body_id);impl_->contact_states_.erase(description.body_id);
        bodies.RemoveBody(id);bodies.DestroyBody(id);throw;
    }
}

void JoltWorld::setDetailedImpactObservations(bool enabled){impl_->requireConfigurationMutable();impl_->impact_collector_.detailed_observations=enabled;}

void JoltWorld::addCompound(const RigidCompoundDescription &d){
    impl_->requireConfigurationMutable();
    auto finite=[](Vec3 v){return std::isfinite(lengthSquared(v));};const auto q=d.state.orientation_world;
    if(d.body_id==kInvalidMatterBodyId||d.body_id==kSupportSurfaceMatterId||impl_->bodies_.contains(d.body_id)||d.parts.empty()||d.parts.size()>64||
       !std::isfinite(d.mass_kg)||d.mass_kg<=0||!finite(d.state.center_of_mass_world_m)||!finite(d.state.linear_velocity_m_s)||!finite(d.state.angular_velocity_rad_s)||
       !std::isfinite(q.w+q.x+q.y+q.z)||std::abs(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z-1)>1e-5)
        throw std::invalid_argument("invalid compiled compound description");
    JPH::StaticCompoundShapeSettings compound;
    for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
        if(!std::isfinite(d.inertia_local_kg_m2.m[i][j])||std::abs(d.inertia_local_kg_m2.m[i][j]-d.inertia_local_kg_m2.m[j][i])>1e-10)
            throw std::invalid_argument("compound inertia must be finite and symmetric");
    for(const auto &p:d.parts){if(!finite(p.center_local_m))throw std::invalid_argument("invalid compound point");
        JPH::RefConst<JPH::Shape> shape;
        if(p.geometry.kind==PrimitiveKind::Sphere){if(!std::isfinite(p.geometry.radius_m)||p.geometry.radius_m<=0)throw std::invalid_argument("invalid compound sphere");shape=new JPH::SphereShape(float(p.geometry.radius_m));}
        else {auto v=p.geometry.dimensions_m;if(!finite(v)||std::min({v.x,v.y,v.z})<=0)throw std::invalid_argument("invalid compound box");shape=new JPH::BoxShape(toJolt(v/2),0);}
        compound.AddShape(toJolt(p.center_local_m),JPH::Quat::sIdentity(),shape.GetPtr());
    }
    auto built=compound.Create();if(built.HasError())throw std::invalid_argument(built.GetError().c_str());
    JPH::RefConst<JPH::Shape> inner=built.Get();
    JPH::RefConst<JPH::Shape> centered=new JPH::OffsetCenterOfMassShape(inner.GetPtr(),-inner->GetCenterOfMass());
    const auto contact=compileContactMaterial(d.material);
    JPH::BodyCreationSettings settings(centered.GetPtr(),toJoltPosition(d.state.center_of_mass_world_m),
        JPH::Quat(float(q.x),float(q.y),float(q.z),float(q.w)),JPH::EMotionType::Dynamic,Layers::kMoving);
    settings.mUserData=d.body_id;settings.mLinearDamping=0;settings.mAngularDamping=0;settings.mApplyGyroscopicForce=true;
    settings.mFriction=float(contact.dynamic_friction);settings.mRestitution=float(contact.restitution);settings.mMaxAngularVelocity=1000;
    settings.mMotionQuality=JPH::EMotionQuality::LinearCast;settings.mOverrideMassProperties=JPH::EOverrideMassProperties::MassAndInertiaProvided;
    settings.mMassPropertiesOverride.mMass=float(d.mass_kg);settings.mMassPropertiesOverride.mInertia=toJoltInertia(d.inertia_local_kg_m2);
    // Scale before diagonalization to avoid Jolt's absolute tiny-inertia fallback.
    JPH::MassProperties scaled=settings.mMassPropertiesOverride;scaled.mInertia*=1.0e6F;
    JPH::Mat44 rotation;JPH::Vec3 diagonal;
    if(!scaled.DecomposePrincipalMomentsOfInertia(rotation,diagonal)||diagonal.GetX()<=0||diagonal.GetY()<=0||diagonal.GetZ()<=0)
        throw std::invalid_argument("compound inertia must be positive definite");
    auto &bodies=impl_->physics_->GetBodyInterface();impl_->bodies_.reserve(impl_->bodies_.size()+1);impl_->contact_states_.reserve(impl_->contact_states_.size()+1);
    auto id=bodies.CreateAndAddBody(settings,JPH::EActivation::Activate);if(id.IsInvalid())throw std::runtime_error("compound body budget exhausted");
    try{
        {JPH::BodyLockWrite lock(impl_->physics_->GetBodyLockInterface(),id);if(!lock.Succeeded())throw std::runtime_error("compound inertia lock failed");
            lock.GetBody().GetMotionProperties()->SetInverseInertia(JPH::Vec3::sReplicate(1.0e6F)/diagonal,rotation.GetQuaternion());}
        bodies.SetLinearAndAngularVelocity(id,toJolt(d.state.linear_velocity_m_s),toJolt(d.state.angular_velocity_rad_s));
        impl_->bodies_.emplace(d.body_id,id);impl_->contact_states_.emplace(d.body_id,BodyContactState{contact,0,0,false,d.mass_kg,{}});
    }catch(...){impl_->bodies_.erase(d.body_id);impl_->contact_states_.erase(d.body_id);bodies.RemoveBody(id);bodies.DestroyBody(id);throw;}
}

void JoltWorld::setSurfaceImpactObservations(bool enabled){
    impl_->requireConfigurationMutable();
    impl_->impact_collector_.surface_observations=enabled;
}

void JoltWorld::setImpactObservationsEnabled(bool enabled) {
    impl_->requireConfigurationMutable();impl_->impact_collector_.observations_enabled=enabled;
}
RigidContactDiagnostics JoltWorld::contactDiagnostics() const {
    auto result=impl_->contact_diagnostics_;
    result.speculative_distance_m=impl_->physics_->GetPhysicsSettings().mSpeculativeContactDistance;
    return result;
}
unsigned JoltWorld::contactPairUpperBound() const {
    if(impl_->bodies_.size()>1024)throw std::invalid_argument("contact admission query body budget exceeded");
    std::vector<JPH::AABox> bounds;bounds.reserve(impl_->bodies_.size()+1);
    const auto &bodies=impl_->physics_->GetBodyInterface();
    const float halfMargin=impl_->physics_->GetPhysicsSettings().mSpeculativeContactDistance*.5f+1e-6f;
    auto append=[&](JPH::BodyID id){auto box=bodies.GetTransformedShape(id).GetWorldSpaceBounds();box.ExpandBy(JPH::Vec3::sReplicate(halfMargin));bounds.push_back(box);};
    for(const auto &[id,body]:impl_->bodies_){(void)id;append(body);}
    if(!impl_->floor_id_.IsInvalid())append(impl_->floor_id_);
    std::sort(bounds.begin(),bounds.end(),[](const auto &a,const auto &b){return a.mMin.GetX()<b.mMin.GetX();});
    unsigned count=0;for(std::size_t i=0;i<bounds.size();++i)for(std::size_t j=i+1;j<bounds.size()&&bounds[j].mMin.GetX()<=bounds[i].mMax.GetX();++j)
        count+=bounds[i].Overlaps(bounds[j]);
    return count;
}

void JoltWorld::addConvex(const RigidConvexDescription &d) {
    impl_->requireConfigurationMutable();
    if(d.vertices_local_m.size()<4||d.vertices_local_m.size()>64)throw std::invalid_argument("convex requires 4..64 vertices");
    std::vector<JPH::Vec3> vertices;
    for(auto v:d.vertices_local_m){if(!std::isfinite(lengthSquared(v))||length(v)>10)throw std::invalid_argument("invalid convex vertex");vertices.push_back(toJolt(v));}
    JPH::ConvexHullShapeSettings settings(vertices.data(),int(vertices.size()),0);
    auto built=settings.Create();if(built.HasError())throw std::invalid_argument(built.GetError().c_str());
    JPH::RefConst<JPH::Shape> inner=built.Get();
    JPH::RefConst<JPH::Shape> centered=new JPH::OffsetCenterOfMassShape(inner.GetPtr(),-inner->GetCenterOfMass());
    // Reuse the independent mass/inertia validation and tiny-inertia handling.
    RigidCompoundDescription proxy;proxy.body_id=d.body_id;proxy.material=d.material;proxy.state=d.state;
    proxy.mass_kg=d.mass_kg;proxy.inertia_local_kg_m2=d.inertia_local_kg_m2;proxy.parts={{{PrimitiveKind::Sphere,.01}, {}}};
    addCompound(proxy);
    impl_->physics_->GetBodyInterface().SetShape(impl_->bodies_.at(d.body_id),centered.GetPtr(),false,JPH::EActivation::Activate);
}

namespace {
void validateSpring(double rest,double stiffness,double damping) {
    if(!std::isfinite(rest)||rest<1e-6||rest>10||!std::isfinite(stiffness)||stiffness<=0||stiffness>1e13||
       !std::isfinite(damping)||damping<0||damping>1e10)throw std::invalid_argument("invalid bounded distance spring");
}
}
unsigned JoltWorld::addHinge(const HingeDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.a == d.b || !contains(d.a) || !contains(d.b))
        throw std::invalid_argument("a hinge needs two different bodies that are both in the world");
    if (impl_->joints_.size() >= 4096)
        throw std::invalid_argument("joint budget exceeded");
    const double reach = length(d.axis_world);
    if (!(reach > 1e-9) || !std::isfinite(reach))
        throw std::invalid_argument("a hinge needs an axis with a direction");
    if (!std::isfinite(d.point_world_m.x) || !std::isfinite(d.point_world_m.y) ||
        !std::isfinite(d.point_world_m.z))
        throw std::invalid_argument("a hinge needs a point that is a place");
    constexpr double kPi = 3.14159265358979323846;
    if (!(d.lower_rad >= -kPi - 1e-9 && d.lower_rad <= 1e-9) ||
        !(d.upper_rad >= -1e-9 && d.upper_rad <= kPi + 1e-9) ||
        !(d.lower_rad <= d.upper_rad))
        throw std::invalid_argument("hinge limits must be a lower in [-pi, 0] and an upper in [0, pi]");
    if (!(d.friction_torque_n_m >= 0.0) || !std::isfinite(d.friction_torque_n_m))
        throw std::invalid_argument("hinge friction must be zero or more newton metres");

    const Vec3 axis = (1.0 / reach) * d.axis_world;
    // Something square to the pin, for Jolt to measure the angle from. Which
    // way it points does not matter -- it only has to be perpendicular -- but
    // it must not be parallel to the axis, so the more distant world direction
    // is taken and squared up against it.
    const Vec3 away = std::abs(axis.y) < 0.9 ? Vec3{0.0, 1.0, 0.0} : Vec3{1.0, 0.0, 0.0};
    Vec3 normal = cross(away, axis);
    const double across = length(normal);
    if (!(across > 1e-9)) throw std::runtime_error("could not square up a hinge axis");
    normal = (1.0 / across) * normal;

    JPH::HingeConstraintSettings settings;
    // World space, where the bodies are standing right now. Jolt keeps the
    // frame in each body's own coordinates from here on, which is what lets the
    // whole assembly be moved or turned over afterwards.
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    // RVec3, not Vec3: this build carries world positions in double precision,
    // which is the whole reason a room can be forty metres across and still
    // place a pin to the micrometre.
    settings.mPoint1 = settings.mPoint2 =
        JPH::RVec3(static_cast<JPH::Real>(d.point_world_m.x),
                   static_cast<JPH::Real>(d.point_world_m.y),
                   static_cast<JPH::Real>(d.point_world_m.z));
    settings.mHingeAxis1 = settings.mHingeAxis2 = toJolt(axis);
    settings.mNormalAxis1 = settings.mNormalAxis2 = toJolt(normal);
    settings.mLimitsMin = static_cast<float>(d.lower_rad);
    settings.mLimitsMax = static_cast<float>(d.upper_rad);
    settings.mMaxFrictionTorque = static_cast<float>(d.friction_torque_n_m);

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    if (!raw) throw std::runtime_error("hinge creation failed");
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Hinge,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

bool JoltWorld::hasJoint(unsigned joint) const {
    return impl_->joints_.find(joint) != impl_->joints_.end();
}

JoltWorld::JointReport JoltWorld::jointState(unsigned joint) const {
    const auto &held = impl_->joints_.at(joint);
    JointReport out{};
    out.a = held.a;
    out.b = held.b;
    out.kind = held.kind;
    if (held.kind == JointKind::Elastic) {
        auto *spring = static_cast<JPH::DistanceConstraint *>(held.constraint.GetPtr());
        // The rest length, which is what this layer knows. How far apart the
        // two ATTACHMENT POINTS actually are is a different quantity from how
        // far apart the bodies' centres are -- a bow limb pulls on the END of
        // the limb -- and only the scene above knows where those points are, so
        // it fills `at` in itself.
        out.at = 0.0;
        out.lower = spring->GetMinDistance();
        out.upper = spring->GetMaxDistance();
        out.friction = 0.0;
        return out;
    }
    if (held.kind == JointKind::Fixing) {
        // A fixing holds everything, so there is no degree of freedom to
        // report a position along. What it has instead is what it is carrying,
        // and that is jointLoad's business -- it needs an axis, which only the
        // scene above knows.
        out.at = 0.0;
        out.lower = 0.0;
        out.upper = 0.0;
        out.friction = 0.0;
        return out;
    }
    if (held.kind == JointKind::Pulley) {
        auto *rove = static_cast<JPH::PulleyConstraint *>(held.constraint.GetPtr());
        // The whole run: one side plus the ratio times the other, which is the
        // quantity the constraint actually holds. Jolt measures it between the
        // points the rope is made off at, not the bodies' centres -- checked
        // when the link below turned out to measure centres: a load made off
        // 60 mm to one side, hauled and swinging, read within 0.025 mm of its
        // tie points while its centre was 0.17 m out.
        out.at = rove->GetCurrentLength();
        out.lower = rove->GetMinLength();
        out.upper = rove->GetMaxLength();
        out.friction = 0.0;
        return out;
    }
    if (held.kind == JointKind::Link) {
        auto *link = static_cast<JPH::DistanceConstraint *>(held.constraint.GetPtr());
        // How far apart the two ends actually are: the points the rope is tied
        // to, each carried into the world by its body's pose as it stands now.
        // A rope's state is its length, taut or slack.
        //
        // The ENDS, not the bodies' centres. This used to measure centre to
        // centre, and a 1.00 m rope hauled tight between a post and an iron
        // block read 1.272 m -- exactly how far apart their middles were, with
        // the rope tied at the post's foot and the block's back.
        //
        // The constraint keeps each tie point in its own body's centre-of-mass
        // frame, which is the frame this transform carries into the world.
        auto &bodies = impl_->physics_->GetBodyInterface();
        const JPH::RVec3 a = bodies.GetCenterOfMassTransform(impl_->bodies_.at(held.a)) *
                             link->GetConstraintToBody1Matrix().GetTranslation();
        const JPH::RVec3 b = bodies.GetCenterOfMassTransform(impl_->bodies_.at(held.b)) *
                             link->GetConstraintToBody2Matrix().GetTranslation();
        out.at = static_cast<double>((b - a).Length());
        out.lower = link->GetMinDistance();
        out.upper = link->GetMaxDistance();
        out.friction = 0.0;
        return out;
    }
    if (held.kind == JointKind::Slider) {
        auto *slide = static_cast<JPH::SliderConstraint *>(held.constraint.GetPtr());
        out.at = slide->GetCurrentPosition();
        out.lower = slide->GetLimitsMin();
        out.upper = slide->GetLimitsMax();
        out.friction = slide->GetMaxFrictionForce();
    } else {
        auto *pin = static_cast<JPH::HingeConstraint *>(held.constraint.GetPtr());
        out.at = pin->GetCurrentAngle();
        out.lower = pin->GetLimitsMin();
        out.upper = pin->GetLimitsMax();
        out.friction = pin->GetMaxFrictionTorque();
    }
    return out;
}

void JoltWorld::setJointFriction(unsigned joint, double friction) {
    if (!(friction >= 0.0) || !std::isfinite(friction))
        throw std::invalid_argument("joint friction must be zero or more");
    auto &held = impl_->joints_.at(joint);
    // A rope has no friction to set, and neither has an ideal pulley: it has
    // no wheel to have a bearing. Rather than refusing -- which would make every
    // caller special-case the kind before asking -- this does nothing, because
    // nothing is the true answer.
    if (held.kind == JointKind::Link || held.kind == JointKind::Pulley ||
        held.kind == JointKind::Fixing || held.kind == JointKind::Elastic) return;
    if (held.kind == JointKind::Slider)
        static_cast<JPH::SliderConstraint *>(held.constraint.GetPtr())
            ->SetMaxFrictionForce(static_cast<float>(friction));
    else
        static_cast<JPH::HingeConstraint *>(held.constraint.GetPtr())
            ->SetMaxFrictionTorque(static_cast<float>(friction));
}

unsigned JoltWorld::addLink(const LinkDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.a == d.b || !contains(d.a) || !contains(d.b))
        throw std::invalid_argument("a link needs two different bodies that are both in the world");
    if (impl_->joints_.size() >= 4096)
        throw std::invalid_argument("joint budget exceeded");
    if (!(d.length_m > 0.0) || !std::isfinite(d.length_m))
        throw std::invalid_argument("a link needs a positive length");
    if (!(d.breaking_tension_n >= 0.0) || !std::isfinite(d.breaking_tension_n))
        throw std::invalid_argument("breaking tension must be zero or more newtons");
    for (const Vec3 &point : {d.point_a_world_m, d.point_b_world_m})
        if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z))
            throw std::invalid_argument("a link needs two points that are places");

    JPH::DistanceConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    settings.mPoint1 = toJoltPosition(d.point_a_world_m);
    settings.mPoint2 = toJoltPosition(d.point_b_world_m);
    // Nought to `length`, and that asymmetry is the rope. Inside that range the
    // constraint does nothing at all -- no force, no damping, no quiet
    // stiffness -- so slack really is slack; at the far end it goes taut and
    // pulls. A distance constraint with min == max is a rigid rod, which is
    // what this same class is used for elsewhere in this file, and a rod
    // pushes.
    settings.mMinDistance = 0.0f;
    settings.mMaxDistance = static_cast<float>(d.length_m);

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    if (!raw) throw std::runtime_error("link creation failed");
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Link,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

double JoltWorld::jointTension(unsigned joint) const {
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end()) return 0.0;
    if (found->second.kind == JointKind::Pulley) {
        const double impulse =
            static_cast<JPH::PulleyConstraint *>(found->second.constraint.GetPtr())
                ->GetTotalLambdaPosition();
        const double dt = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 60.0;
        return std::abs(impulse) / dt;
    }
    if (found->second.kind != JointKind::Link) return 0.0;
    // Jolt reports the impulse the constraint applied over the last step, and
    // an impulse over a step is a force. Negative would be a push, which this
    // constraint cannot do, so the sign carries no information -- what a caller
    // wants is how hard the rope is pulling.
    const double impulse =
        static_cast<JPH::DistanceConstraint *>(found->second.constraint.GetPtr())
            ->GetTotalLambdaPosition();
    const double dt = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 60.0;
    return std::abs(impulse) / dt;
}

unsigned JoltWorld::addElastic(const ElasticDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.a == d.b || !contains(d.a) || !contains(d.b))
        throw std::invalid_argument("an elastic needs two different bodies that are both in the world");
    if (impl_->joints_.size() >= 4096)
        throw std::invalid_argument("joint budget exceeded");
    if (!(d.stiffness_n_m > 0.0) || !std::isfinite(d.stiffness_n_m))
        throw std::invalid_argument("an elastic needs a positive stiffness in newtons per metre");
    if (!(d.damping_n_s_m >= 0.0) || !std::isfinite(d.damping_n_s_m))
        throw std::invalid_argument("elastic damping is newton seconds per metre, zero or more");
    if (!(d.rest_m >= 0.0) || !std::isfinite(d.rest_m))
        throw std::invalid_argument("an elastic's rest length is zero (as it stands) or more");
    for (const Vec3 &point : {d.point_a_world_m, d.point_b_world_m})
        if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z))
            throw std::invalid_argument("an elastic needs two points that are places");

    const double apart = length(d.point_b_world_m - d.point_a_world_m);
    const double rest = d.rest_m > 0.0 ? d.rest_m : std::max(apart, 1e-4);

    JPH::DistanceConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    settings.mPoint1 = toJoltPosition(d.point_a_world_m);
    settings.mPoint2 = toJoltPosition(d.point_b_world_m);
    // Min AND max at the rest length, with a spring on the limits: that is what
    // makes it two-way. A rope is nought-to-length and pulls only; this is
    // length-to-length and shoves back when it is squashed, which is what a bow
    // limb does and is the whole reason it is a different kind of joint.
    settings.mMinDistance = settings.mMaxDistance = static_cast<float>(rest);
    settings.mLimitsSpringSettings = {JPH::ESpringMode::StiffnessAndDamping,
                                      static_cast<float>(d.stiffness_n_m),
                                      static_cast<float>(d.damping_n_s_m)};

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    if (!raw) throw std::runtime_error("elastic creation failed");
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Elastic,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

unsigned JoltWorld::addFixing(const FixingDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.a == d.b || !contains(d.a) || !contains(d.b))
        throw std::invalid_argument("a fixing needs two different bodies that are both in the world");
    if (impl_->joints_.size() >= 4096)
        throw std::invalid_argument("joint budget exceeded");
    const double reach = length(d.axis_world);
    if (!(reach > 1e-9) || !std::isfinite(reach))
        throw std::invalid_argument("a fixing needs an axis with a direction");
    if (!std::isfinite(d.point_world_m.x) || !std::isfinite(d.point_world_m.y) ||
        !std::isfinite(d.point_world_m.z))
        throw std::invalid_argument("a fixing needs a point that is a place");
    if (!(d.holds_tension_n >= 0.0) || !std::isfinite(d.holds_tension_n) ||
        !(d.holds_shear_n >= 0.0) || !std::isfinite(d.holds_shear_n))
        throw std::invalid_argument("a fixing's strengths are newtons, zero (never "
                                    "lets go) or more");

    JPH::FixedConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    // Their relative pose right now is the pose they keep. That is the whole of
    // what "defined alignment" means here: it is defined by where they are when
    // the peg goes in, which is also how a peg works.
    settings.mAutoDetectPoint = false;
    settings.mPoint1 = settings.mPoint2 = toJoltPosition(d.point_world_m);
    const Vec3 along = (1.0 / reach) * d.axis_world;
    const Vec3 away = std::abs(along.y) < 0.9 ? Vec3{0.0, 1.0, 0.0} : Vec3{1.0, 0.0, 0.0};
    Vec3 across = cross(away, along);
    const double sideways = length(across);
    if (!(sideways > 1e-9)) throw std::runtime_error("could not square up a fixing axis");
    across = (1.0 / sideways) * across;
    settings.mAxisX1 = settings.mAxisX2 = toJolt(along);
    settings.mAxisY1 = settings.mAxisY2 = toJolt(across);

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    if (!raw) throw std::runtime_error("fixing creation failed");
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Fixing,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

JoltWorld::JointLoad JoltWorld::jointLoad(unsigned joint, const Vec3 &axis_world) const {
    JointLoad out{};
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end()) return out;
    if (found->second.kind != JointKind::Fixing) return out;
    // Jolt reports the impulse the constraint applied over the step as a
    // VECTOR, which is exactly what is needed: a peg pulled straight out and a
    // peg sheared sideways fail at different loads, so the two have to be told
    // apart rather than added into one magnitude.
    const JPH::Vec3 impulse =
        static_cast<JPH::FixedConstraint *>(found->second.constraint.GetPtr())
            ->GetTotalLambdaPosition();
    const double dt = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 60.0;
    const Vec3 force{static_cast<double>(impulse.GetX()) / dt,
                     static_cast<double>(impulse.GetY()) / dt,
                     static_cast<double>(impulse.GetZ()) / dt};
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return out;
    const Vec3 along = (1.0 / reach) * axis_world;
    const double pulled = dot(force, along);
    out.tension_n = std::abs(pulled);
    // What is left once the along-axis part is taken out is across it.
    const Vec3 sideways = force - pulled * along;
    out.shear_n = length(sideways);
    return out;
}

unsigned JoltWorld::addPulley(const PulleyDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.a == d.b || !contains(d.a) || !contains(d.b))
        throw std::invalid_argument("a pulley needs two different bodies that are both in the world");
    if (impl_->joints_.size() >= 4096)
        throw std::invalid_argument("joint budget exceeded");
    if (!(d.ratio > 0.0) || !std::isfinite(d.ratio))
        throw std::invalid_argument("a pulley's ratio must be more than zero");
    if (!(d.length_m >= 0.0) || !std::isfinite(d.length_m))
        throw std::invalid_argument("a pulley's length is zero (as rove) or more");
    for (const Vec3 &point : {d.point_a_world_m, d.point_b_world_m,
                              d.over_a_world_m, d.over_b_world_m})
        if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z))
            throw std::invalid_argument("a pulley needs four points that are places");

    JPH::PulleyConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    settings.mBodyPoint1 = toJoltPosition(d.point_a_world_m);
    settings.mFixedPoint1 = toJoltPosition(d.over_a_world_m);
    settings.mBodyPoint2 = toJoltPosition(d.point_b_world_m);
    settings.mFixedPoint2 = toJoltPosition(d.over_b_world_m);
    settings.mRatio = static_cast<float>(d.ratio);
    // Nought to the rope's length, for the same reason a link is: the rope
    // pulls and does not push, so slack on one side must cost nothing. Bounding
    // it below as well would be an inextensible ROD bent round two corners,
    // which would hold a counterweight up in mid-air.
    settings.mMinLength = 0.0f;
    if (d.length_m > 0.0) {
        settings.mMaxLength = static_cast<float>(d.length_m);
    } else {
        // -1 tells Jolt to measure it from where everything is standing, which
        // is what "as it is rove" means.
        settings.mMaxLength = -1.0f;
    }

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    if (!raw) throw std::runtime_error("pulley creation failed");
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Pulley,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

unsigned JoltWorld::addSlider(const SliderDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.a == d.b || !contains(d.a) || !contains(d.b))
        throw std::invalid_argument("a slide needs two different bodies that are both in the world");
    if (impl_->joints_.size() >= 4096)
        throw std::invalid_argument("joint budget exceeded");
    const double reach = length(d.axis_world);
    if (!(reach > 1e-9) || !std::isfinite(reach))
        throw std::invalid_argument("a slide needs an axis with a direction");
    if (!std::isfinite(d.point_world_m.x) || !std::isfinite(d.point_world_m.y) ||
        !std::isfinite(d.point_world_m.z))
        throw std::invalid_argument("a slide needs a point that is a place");
    if (!(d.lower_m <= 0.0) || !(d.upper_m >= 0.0) || !(d.lower_m <= d.upper_m) ||
        !std::isfinite(d.lower_m) || !std::isfinite(d.upper_m))
        throw std::invalid_argument("slide travel is metres either side of where it is "
                                    "built: a lower of zero or less and an upper of zero "
                                    "or more");
    if (!(d.friction_n >= 0.0) || !std::isfinite(d.friction_n))
        throw std::invalid_argument("slide friction must be zero or more newtons");

    const Vec3 along = (1.0 / reach) * d.axis_world;
    // Something square to the line of travel, for Jolt to measure from. Same
    // reasoning as the hinge's normal: it only has to be perpendicular.
    const Vec3 away = std::abs(along.y) < 0.9 ? Vec3{0.0, 1.0, 0.0} : Vec3{1.0, 0.0, 0.0};
    Vec3 normal = cross(away, along);
    const double across = length(normal);
    if (!(across > 1e-9)) throw std::runtime_error("could not square up a slide axis");
    normal = (1.0 / across) * normal;

    JPH::SliderConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    // RVec3, not Vec3: this build carries positions in double precision, which
    // is the whole reason a room can be forty metres across and still place a
    // slide to the micrometre.
    settings.mPoint1 = settings.mPoint2 = toJoltPosition(d.point_world_m);
    settings.mSliderAxis1 = settings.mSliderAxis2 = toJolt(along);
    settings.mNormalAxis1 = settings.mNormalAxis2 = toJolt(normal);
    settings.mLimitsMin = static_cast<float>(d.lower_m);
    settings.mLimitsMax = static_cast<float>(d.upper_m);
    settings.mMaxFrictionForce = static_cast<float>(d.friction_n);

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    if (!raw) throw std::runtime_error("slide creation failed");
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Slider,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

void JoltWorld::removeJoint(unsigned joint) {
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end()) return;
    impl_->physics_->RemoveConstraint(found->second.constraint.GetPtr());
    impl_->joints_.erase(found);
}

std::vector<unsigned> JoltWorld::jointsOn(MatterBodyId body_id) const {
    std::vector<unsigned> out;
    for (const auto &[id, joint] : impl_->joints_)
        if (joint.a == body_id || joint.b == body_id) out.push_back(id);
    std::sort(out.begin(), out.end());
    return out;
}

unsigned JoltWorld::addDistanceSpring(MatterBodyId a,MatterBodyId b,double rest,double stiffness,double damping) {
    impl_->requireConfigurationMutable();validateSpring(rest,stiffness,damping);
    if(a==b||!contains(a)||!contains(b)||impl_->springs_.size()>=20000)throw std::invalid_argument("invalid spring endpoints or budget");
    JPH::DistanceConstraintSettings settings;settings.mSpace=JPH::EConstraintSpace::LocalToBodyCOM;
    settings.mPoint1=JPH::RVec3::sZero();settings.mPoint2=JPH::RVec3::sZero();
    settings.mMinDistance=settings.mMaxDistance=float(rest);
    settings.mLimitsSpringSettings={JPH::ESpringMode::StiffnessAndDamping,float(stiffness),float(damping)};
    auto *raw=impl_->physics_->GetBodyInterface().CreateConstraint(&settings,impl_->bodies_.at(a),impl_->bodies_.at(b));
    if(!raw)throw std::runtime_error("spring creation failed");
    const auto id=impl_->next_spring_++;
    impl_->springs_.emplace(id,Impl::Spring{a,b,static_cast<JPH::DistanceConstraint*>(raw)});
    impl_->physics_->AddConstraint(raw);return id;
}
void JoltWorld::updateDistanceSpring(unsigned id,double rest,double stiffness,double damping) {
    impl_->requireSpringMutable();validateSpring(rest,stiffness,damping);
    auto &spring=impl_->springs_.at(id);auto *constraint=spring.constraint.GetPtr();
    const float rest_f=float(rest),stiffness_f=float(stiffness),damping_f=float(damping);
    const auto &current=constraint->GetLimitsSpringSettings();
    if(constraint->GetMinDistance()==rest_f&&constraint->GetMaxDistance()==rest_f&&
       current.mMode==JPH::ESpringMode::StiffnessAndDamping&&
       current.mStiffness==stiffness_f&&current.mDamping==damping_f)return;
    constraint->SetDistance(rest_f,rest_f);
    constraint->SetLimitsSpringSettings({JPH::ESpringMode::StiffnessAndDamping,stiffness_f,damping_f});
    // Rest/stiffness changes can make the previous force impulse a poor initial
    // iterate. Jolt only scales it for dt changes; configuration invalidation is
    // explicitly the constraint owner's responsibility.
    constraint->ResetWarmStart();
}
void JoltWorld::removeDistanceSpring(unsigned id) {
    impl_->requireSpringMutable();auto it=impl_->springs_.find(id);if(it==impl_->springs_.end())throw std::invalid_argument("unknown spring");
    impl_->physics_->RemoveConstraint(it->second.constraint);impl_->springs_.erase(it);
}
double JoltWorld::distanceSpringImpulse(unsigned id) const {return impl_->springs_.at(id).constraint->GetTotalLambdaPosition();}

PairContactOwner JoltWorld::pairContactOwner(MatterBodyId a,MatterBodyId b) const {
    if(a==b||!contains(a)||!contains(b))throw std::invalid_argument("contact ownership requires two distinct registered bodies");
    return impl_->external_pairs_.contains(std::minmax(a,b))?PairContactOwner::External:PairContactOwner::Jolt;
}
void JoltWorld::setPairContactOwner(MatterBodyId a,MatterBodyId b,PairContactOwner owner) {
    impl_->requireConfigurationMutable();
    if(owner!=PairContactOwner::External&&owner!=PairContactOwner::Jolt)throw std::invalid_argument("unknown pair contact owner");
    if(pairContactOwner(a,b)==owner)return;
    const std::pair<MatterBodyId,MatterBodyId> key=std::minmax(a,b);
    if(owner==PairContactOwner::External){if(impl_->external_pairs_.size()>=4096)throw std::invalid_argument("external contact pair budget exceeded");impl_->external_pairs_.insert(key);}
    else impl_->external_pairs_.erase(key);
    auto &bodies=impl_->physics_->GetBodyInterface();
    for(auto id:{a,b}){const auto body=impl_->bodies_.at(id);bodies.InvalidateContactCache(body);bodies.ActivateBody(body);}
}
PairImpulseAudit JoltWorld::applyPairImpulse(MatterBodyId a,MatterBodyId b,
    Vec3 point_a_m,Vec3 point_b_m,Vec3 impulse_on_a_n_s,double maximum_roundoff_energy_j) {
    if(pairContactOwner(a,b)!=PairContactOwner::External)
        throw std::invalid_argument("pair impulse requires external contact ownership");
    return applyAuditedPairImpulses(a,b,{{point_a_m,point_b_m,impulse_on_a_n_s}},maximum_roundoff_energy_j);
}
CohesiveTensionKick JoltWorld::applyCohesiveTensionKick(MatterBodyId a,MatterBodyId b,
    Vec3 local_a,Vec3 local_b,double rest,const CohesiveInterfaceLaw &law,
    const CohesiveInterfaceState &history,double duration,double budget) {
    const auto result=applyCohesiveTensionPatchKick(a,b,{{local_a,local_b,rest,law.area_m2,history}},law,duration,budget);
    return {result.interface_increments.front(),result.transfer};
}
CohesiveTensionPatchKick JoltWorld::applyCohesiveTensionPatchKick(MatterBodyId a,MatterBodyId b,
    const std::vector<CohesivePatchSite> &sites,const CohesiveInterfaceLaw &law,double duration,double budget) {
    if(sites.empty()||sites.size()>256)throw std::invalid_argument("tensile patch site count must be 1..256");
    if(positionPrecisionBits()!=64)throw std::invalid_argument("runtime cohesion requires double positions");
    if(pairContactOwner(a,b)!=PairContactOwner::Jolt)throw std::invalid_argument("tensile connector requires Jolt surface ownership");
    for(auto id:{a,b})if(impl_->contact_states_.at(id).activation_material)
        throw std::invalid_argument("tensile connector cannot share deferred material activation contacts");
    const auto finite=[](Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);};
    if(!std::isfinite(duration)||duration<=0||duration>1||law.compression_stiffness_pa_per_m!=0)
        throw std::invalid_argument("invalid tensile duration or duplicate compression response");
    const auto sa=snapshot(a),sb=snapshot(b);
    CohesiveTensionPatchKick result;
    std::vector<AttachmentImpulse> impulses;impulses.reserve(sites.size());
    result.interface_increments.reserve(sites.size());
    for(const auto &site:sites) {
        if(!finite(site.attachment_a_m)||!finite(site.attachment_b_m)||!std::isfinite(site.rest_distance_m)||site.rest_distance_m<=0)
            throw std::invalid_argument("invalid tensile attachment geometry");
        const auto pa=sa.center_of_mass_world_m+sa.orientation_world.rotate(site.attachment_a_m);
        const auto pb=sb.center_of_mass_world_m+sb.orientation_world.rotate(site.attachment_b_m);
        const Vec3 delta=pb-pa;const double distance=length(delta);
        if(!std::isfinite(distance)||distance<=site.rest_distance_m*1e-6)
            throw std::invalid_argument("tensile attachment points coincide or are unresolved");
        auto site_law=law;site_law.area_m2=site.area_m2;
        const auto increment=advanceCohesiveInterface(site_law,site.history,distance-site.rest_distance_m);
        impulses.push_back({pa,pb,(increment.response.force_n*duration)*(delta/distance)});
        result.interface_increments.push_back(increment);
    }
    result.transfer=applyAuditedPairImpulses(a,b,impulses,budget);
    // A caller advancing an external interface owns its sleeping decision.
    // Jolt's velocity-threshold sleep would otherwise discard low-speed KE
    // mid-trajectory. Stop issuing kicks when releasing that responsibility.
    auto &bodies=impl_->physics_->GetBodyInterface();
    for(auto id:{a,b}){bodies.ActivateBody(impl_->bodies_.at(id));bodies.ResetSleepTimer(impl_->bodies_.at(id));}
    return result;
}
PairImpulseAudit JoltWorld::applyAuditedPairImpulses(MatterBodyId a,MatterBodyId b,
    const std::vector<AttachmentImpulse> &impulses,double maximum_roundoff_energy_j) {
    if(!std::isfinite(maximum_roundoff_energy_j)||maximum_roundoff_energy_j<0)
        throw std::invalid_argument("pair impulse requires a finite nonnegative roundoff budget");
    for(auto id:{a,b}) {
        if(impl_->pins_.contains(id))throw std::invalid_argument("pair impulse cannot bypass a world attachment");
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(id));
        if(!lock.Succeeded())throw std::runtime_error("cannot lock impulse body");
        const auto &body=lock.GetBody();
        if(!body.IsDynamic()||body.GetMotionProperties()->GetAllowedDOFs()!=JPH::EAllowedDOFs::All)
            throw std::invalid_argument("pair impulse requires unrestricted dynamic bodies");
    }
    const auto before_a=mechanicalState(a),before_b=mechanicalState(b);
    const auto attachment=[](const RigidMechanicalState &s) {
        auto inertia=s.inertia_world_kg_m2;
        double scale=0;for(const auto &row:inertia.m)for(double x:row)scale=std::max(scale,std::abs(x));
        // Jolt's float world-tensor rotation can introduce a small skew part.
        // Solve with its symmetric part, but retain the raw read-back tensor
        // in the measured ledger so this approximation is not hidden.
        for(unsigned i=0;i<3;++i)for(unsigned k=i+1;k<3;++k) {
            if(std::abs(inertia.m[i][k]-inertia.m[k][i])>1e-6*scale)
                throw std::invalid_argument("runtime inertia skew exceeds float tolerance");
            inertia.m[i][k]=inertia.m[k][i]=.5*(inertia.m[i][k]+inertia.m[k][i]);
        }
        return AttachmentBody{s.mass_kg,inertia,s.motion.center_of_mass_world_m,
            s.motion.linear_velocity_m_s,s.motion.angular_velocity_rad_s};
    };
    const auto solved=applyAttachmentImpulses(attachment(before_a),attachment(before_b),impulses);
    const auto candidate=[&](MatterBodyId id,RigidMechanicalState state,const AttachmentBody &target) {
        const auto representable=[](Vec3 v) {
            const double limit=std::numeric_limits<float>::max();
            return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z)&&
                std::abs(v.x)<=limit&&std::abs(v.y)<=limit&&std::abs(v.z)<=limit;
        };
        if(!representable(target.velocity_m_s)||!representable(target.angular_velocity_rad_s))
            throw std::invalid_argument("pair impulse velocity is not representable");
        const auto v=toJolt(target.velocity_m_s),w=toJolt(target.angular_velocity_rad_s);
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(id));
        if(!lock.Succeeded())throw std::runtime_error("cannot lock impulse candidate");
        const auto *motion=lock.GetBody().GetMotionProperties();
        const float max_v=motion->GetMaxLinearVelocity(),max_w=motion->GetMaxAngularVelocity();
        // Match Jolt's float norm comparison, so an accepted candidate cannot
        // be silently clamped by SetLinearAndAngularVelocity.
        if(!std::isfinite(v.LengthSq())||!std::isfinite(w.LengthSq())||
            v.LengthSq()>max_v*max_v||w.LengthSq()>max_w*max_w)
            throw std::invalid_argument("pair impulse exceeds runtime velocity limits");
        state.motion.linear_velocity_m_s=fromJoltVector(v);
        state.motion.angular_velocity_rad_s=fromJoltVector(w);
        return state;
    };
    const auto after_a=candidate(a,before_a,solved.a),after_b=candidate(b,before_b,solved.b);
    const auto audit=[&](const RigidMechanicalState &sa,const RigidMechanicalState &sb) {
        PairImpulseAudit out;
        out.before=measureRigidMechanics(before_a);out.before+=measureRigidMechanics(before_b);
        out.after=measureRigidMechanics(sa);out.after+=measureRigidMechanics(sb);
        out.impulse_work_j=solved.impulse_work_j;
        out.numerical_energy_change_j=out.after.kinetic_energy_j-out.before.kinetic_energy_j-out.impulse_work_j;
        out.momentum_error_kg_m_s=out.after.linear_momentum_kg_m_s-out.before.linear_momentum_kg_m_s;
        out.applied_couple_kg_m2_s=solved.angular_impulse_kg_m2_s;
        out.angular_momentum_error_kg_m2_s=out.after.angular_momentum_kg_m2_s-out.before.angular_momentum_kg_m2_s-out.applied_couple_kg_m2_s;
        return out;
    };
    const auto predicted=audit(after_a,after_b);
    if(!std::isfinite(predicted.numerical_energy_change_j)||std::abs(predicted.numerical_energy_change_j)>maximum_roundoff_energy_j)
        throw std::invalid_argument("pair impulse exceeds roundoff energy budget");
    auto &bodies=impl_->physics_->GetBodyInterface();
    bodies.SetLinearAndAngularVelocity(impl_->bodies_.at(a),toJolt(after_a.motion.linear_velocity_m_s),toJolt(after_a.motion.angular_velocity_rad_s));
    bodies.SetLinearAndAngularVelocity(impl_->bodies_.at(b),toJolt(after_b.motion.linear_velocity_m_s),toJolt(after_b.motion.angular_velocity_rad_s));
    // Report measured solver state, including actual float mass and inertia.
    return audit(mechanicalState(a),mechanicalState(b));
}

void JoltWorld::pinToWorld(MatterBodyId body_id) {
    impl_->requireConfigurationMutable();
    const auto found=impl_->bodies_.find(body_id);
    if(found==impl_->bodies_.end()||impl_->pins_.contains(body_id))throw std::invalid_argument("missing or already pinned body");
    if(impl_->physics_->GetBodyInterface().GetMotionType(found->second)!=JPH::EMotionType::Dynamic)throw std::invalid_argument("only a dynamic body can be pinned");
    JPH::FixedConstraintSettings settings;settings.mAutoDetectPoint=true;
    auto *constraint=impl_->physics_->GetBodyInterface().CreateConstraint(&settings,JPH::BodyID(),found->second);
    if(!constraint)throw std::runtime_error("cannot create world attachment");
    JPH::Ref<JPH::Constraint> owned=constraint;
    impl_->pins_.emplace(body_id,owned);impl_->physics_->AddConstraint(constraint);
}
void JoltWorld::releaseFromWorld(MatterBodyId body_id) {
    impl_->requireConfigurationMutable();
    const auto found=impl_->pins_.find(body_id);
    if(found==impl_->pins_.end())return;
    impl_->physics_->RemoveConstraint(found->second);impl_->pins_.erase(found);
    impl_->physics_->GetBodyInterface().ActivateBody(impl_->bodies_.at(body_id));
}

RayHit JoltWorld::castRay(const Vec3 &from_world_m,const Vec3 &direction,
                          double max_distance_m) const {
    RayHit out{};
    // A ray with no direction is a question with no answer, and normalising it
    // would divide by zero rather than say so.
    const double reach=banjo::length(direction);
    if(!(reach>0.0)||!(max_distance_m>0.0))return out;
    const Vec3 along=(max_distance_m/reach)*direction;
    const JPH::RRayCast ray{toJoltPosition(from_world_m),toJolt(along)};
    JPH::RayCastResult result;
    // The closest hit, against the real shapes the solver collides -- including
    // a fragment's convex hull -- so the answer cannot disagree with what the
    // body actually does.
    if(!impl_->physics_->GetNarrowPhaseQuery().CastRay(ray,result))return out;
    out.hit=true;
    out.distance_m=static_cast<double>(result.mFraction)*max_distance_m;
    out.point_world_m=from_world_m+static_cast<double>(result.mFraction)*along;
    // Jolt answers with its own body id; the caller speaks in ours. Something
    // with no id of ours still stopped the ray and is still reported.
    for(const auto &[id,body]:impl_->bodies_)
        if(body==result.mBodyID){out.named=true;out.body_id=id;break;}
    return out;
}

void JoltWorld::pushBody(MatterBodyId body_id, const Vec3 &force_n) {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    auto &bodies = impl_->physics_->GetBodyInterface();
    // Scenery cannot be pushed. Not an error: pushing a wall is a thing a
    // caller does, and the answer is that nothing happens.
    if (bodies.GetMotionType(found->second) == JPH::EMotionType::Static) return;
    bodies.AddForce(found->second, toJolt(force_n));
}

void JoltWorld::setMass(MatterBodyId body_id, double mass_kg) {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    if (!(mass_kg > 0.0) || !std::isfinite(mass_kg))
        throw std::invalid_argument("a body's mass is positive and finite");
    JPH::BodyLockWrite lock(impl_->physics_->GetBodyLockInterface(), found->second);
    if (!lock.Succeeded()) throw std::runtime_error("cannot lock a body to change its mass");
    JPH::Body &body = lock.GetBody();
    if (!body.IsDynamic()) return;
    body.GetMotionProperties()->ScaleToMass(static_cast<float>(mass_kg));
}

void JoltWorld::wake(MatterBodyId body_id) {
    const auto found=impl_->bodies_.find(body_id);
    if(found==impl_->bodies_.end())throw std::invalid_argument("rigid body is missing");
    auto &bodies=impl_->physics_->GetBodyInterface();
    // Scenery has nothing to wake. ActivateBody already knows that and does
    // nothing, but ResetSleepTimer goes straight through the body's motion
    // properties -- which a static body does not have -- and takes the process
    // down. Waking the floor is not an unreasonable thing for a caller to do:
    // anything that hangs a door on a wall and then wakes both ends of the pin
    // does it, and that is how this was found.
    if(bodies.GetMotionType(found->second)==JPH::EMotionType::Static)return;
    bodies.ActivateBody(found->second);
    // Clearing the timer as well as activating: a body that is still against
    // the same contacts would otherwise be asleep again within a step or two,
    // before it has had a chance to start moving.
    bodies.ResetSleepTimer(found->second);
}

void JoltWorld::addFragments(
    const std::vector<RigidFragmentDescription> &fragments) {
    impl_->requireConfigurationMutable();
    if (fragments.empty()) {
        return;
    }

    struct PendingBody {
        MatterBodyId logical_id{kInvalidMatterBodyId};
        JPH::BodyID body_id{};
        Vec3 linear_velocity_m_s{};
        Vec3 angular_velocity_rad_s{};
        CompiledContactMaterial contact{};
    };

    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    std::vector<PendingBody> pending;
    std::vector<JPH::BodyID> body_ids;
    pending.reserve(fragments.size());
    body_ids.reserve(fragments.size());

    try {
        for (const RigidFragmentDescription &fragment : fragments) {
            if (fragment.body_id == kInvalidMatterBodyId ||
                fragment.body_id == kSupportSurfaceMatterId ||
                impl_->bodies_.contains(fragment.body_id) ||
                fragment.mass_properties.mass_kg <= 0.0 ||
                fragment.collision_points_local_m.size() < 4U) {
                throw std::invalid_argument("rigid fragment description is invalid");
            }
            if (fragment.collision_points_local_m.size() >
                static_cast<std::size_t>(
                    JPH::ConvexHullShape::cMaxPointsInHull)) {
                throw std::invalid_argument(
                    "rigid fragment exceeds Jolt convex hull point limit");
            }

            std::vector<JPH::Vec3> hull_points;
            hull_points.reserve(fragment.collision_points_local_m.size());
            for (const Vec3 &point : fragment.collision_points_local_m) {
                hull_points.push_back(toJolt(point));
            }

            // An object that has not broken collides as the shape it was
            // authored as. Only a piece that came off something gets the hull
            // of its cells, which is then its real surface.
            JPH::RefConst<JPH::Shape> authored;
            if (fragment.primitive == FragmentPrimitive::Sphere) {
                authored = new JPH::SphereShape(
                    static_cast<float>(0.5 * fragment.primitive_dimensions_m.x));
            } else if (fragment.primitive == FragmentPrimitive::Box) {
                authored = new JPH::BoxShape(toJolt(fragment.primitive_dimensions_m / 2), 0.0F);
            }
            // A tilted slab collides as a tilted slab, not as the staircase its
            // cells make, so a ball rolls down a ramp instead of bouncing on
            // every step of it.
            if (authored != nullptr) {
                const auto &q = fragment.primitive_rotation_wxyz;
                if (q[1] != 0.0 || q[2] != 0.0 || q[3] != 0.0) {
                    authored = new JPH::RotatedTranslatedShape(
                        JPH::Vec3::sZero(),
                        JPH::Quat(static_cast<float>(q[1]), static_cast<float>(q[2]),
                                  static_cast<float>(q[3]), static_cast<float>(q[0])).Normalized(),
                        authored);
                }
            }
            JPH::ConvexHullShapeSettings hull_settings(
                hull_points.data(),
                static_cast<int>(hull_points.size()),
                0.0F);
            const JPH::ShapeSettings::ShapeResult hull_result =
                hull_settings.Create();
            // A hull that cannot be built is not the end of the matter.
            //
            // Some pieces come off nearly flat or nearly in a line, and the hull
            // builder cannot make a shape that contains them: measured, "point
            // 166 had an error of 0.049654" -- five centimetres outside, which
            // is two and a half cells, not a rounding problem. Loosening the
            // tolerance until Jolt accepts it would only mean accepting a shape
            // that is wrong by five centimetres.
            //
            // But the cells are RIGHT THERE, and they are the piece's actual
            // shape rather than an approximation of it. Anchored scenery has
            // always been built that way, for a different reason (a hull cannot
            // be concave, so a bowl would be solid to the touch). The same
            // fallback serves here: when the hull will not build, the piece
            // collides as the cells it is made of.
            //
            // Before this, one shard the builder could not handle refused the
            // whole fracture, and from outside a break simply did not happen.
            const bool hull_failed = hull_result.HasError();
            // Anchored scenery collides as its actual cells. A convex hull
            // cannot be concave, so a bowl built by cutting a cavity out of a
            // sphere is hollow in the lattice and solid to the touch: a bead
            // dropped into it lands on the rim. Static geometry has no reason to
            // be convex, so it becomes a compound of one box per cell, which is
            // the shape it really is. Dynamic pieces keep the hull, where a
            // convex approximation is both reasonable for a tumbling fragment
            // and far cheaper.
            JPH::RefConst<JPH::Shape> concrete;
            if ((fragment.anchored || hull_failed) &&
                !fragment.voxel_centers_local_m.empty() &&
                fragment.voxel_size_m > 0.0) {
                JPH::StaticCompoundShapeSettings compound;
                const JPH::RefConst<JPH::Shape> cell = new JPH::BoxShape(
                    JPH::Vec3::sReplicate(static_cast<float>(0.5 * fragment.voxel_size_m)), 0.0F);
                for (const Vec3 &centre : fragment.voxel_centers_local_m)
                    compound.AddShape(toJolt(centre), JPH::Quat::sIdentity(), cell.GetPtr());
                const JPH::ShapeSettings::ShapeResult built = compound.Create();
                if (built.IsValid()) concrete = built.Get();
            }
            // The authored primitive wins over the per-cell compound, and the
            // hull is the last resort.
            //
            // The compound above exists because a CONCAVE shape cannot be a
            // convex hull: a bowl cut out of a sphere would be solid to the
            // touch. That argument does not reach a body that was authored as
            // one convex primitive. There the cells are an approximation OF the
            // primitive, not the other way round, and preferring them threw
            // away the exact shape in favour of its own staircase.
            //
            // A ramp has to be anchored to be a ramp, so before this every ramp
            // in every scene collided as a staircase of cells and a ball
            // released on a 20 degree slope travelled 29 mm in 1.5 s -- it
            // dropped into the first notch and stopped. Which is what the
            // tilted-slab comment above was written to prevent.
            //
            // Joins, subtractions, cones and broken pieces carry no primitive,
            // so they still get the compound, which is where it was needed.
            if (hull_failed && authored == nullptr && concrete == nullptr) {
                // Nothing left to fall back to: no primitive it was authored as,
                // and no cells to build from.
                const JPH::String &error = hull_result.GetError();
                throw std::runtime_error(
                    "Jolt could not build a fragment convex hull and the piece "
                    "has no cells to fall back to: " +
                    std::string(error.begin(), error.end()));
            }
            const JPH::RefConst<JPH::Shape> inner_shape =
                authored != nullptr ? authored
                                    : (concrete != nullptr ? concrete : hull_result.Get());
            const JPH::RefConst<JPH::Shape> centered_shape =
                new JPH::OffsetCenterOfMassShape(
                    inner_shape.GetPtr(), -inner_shape->GetCenterOfMass());
            const CompiledContactMaterial contact = legacyFragmentContact(
                fragment.friction, fragment.restitution);

            JPH::BodyCreationSettings settings(
                centered_shape.GetPtr(),
                toJoltPosition(
                    fragment.mass_properties.center_of_mass_world_m),
                JPH::Quat::sIdentity(),
                // Scenery is static: a ramp, a table or a wall has nothing under
                // it and otherwise falls to the ground, taking whatever was
                // resting on it with it. Only a whole authored body is ever
                // anchored; break it and its pieces are ordinary dynamic ones.
                fragment.anchored ? JPH::EMotionType::Static : JPH::EMotionType::Dynamic,
                fragment.anchored ? Layers::kNonMoving : Layers::kMoving);
            settings.mFriction =
                static_cast<float>(contact.dynamic_friction);
            settings.mRestitution =
                static_cast<float>(contact.restitution);
            settings.mLinearDamping = 0.02F;
            settings.mAngularDamping = 0.02F;
            // Jolt caps angular velocity at 0.25 * pi * 60 = 47.12 rad/s unless
            // told otherwise, and a rolling ball goes past that at walking pace:
            // 6 m/s on a 60 mm radius needs 100 rad/s. The cap was silently
            // holding every ball at 47.1 rad/s, which reads as a ball that rolls
            // but slips, and is why one travelled 17 m without stopping. The
            // other body paths in this file already raise it.
            settings.mMaxAngularVelocity = 1000.0F;
            settings.mUserData = fragment.body_id;
            settings.mMotionQuality = JPH::EMotionQuality::LinearCast;
            if (!fragment.anchored) {
            settings.mOverrideMassProperties =
                JPH::EOverrideMassProperties::MassAndInertiaProvided;
            settings.mMassPropertiesOverride.mMass =
                static_cast<float>(fragment.mass_properties.mass_kg);
            settings.mMassPropertiesOverride.mInertia =
                toJoltInertia(
                    fragment.mass_properties.inertia_world_kg_m2);
            }

            JPH::Body *body = body_interface.CreateBody(settings);
            if (body == nullptr) {
                throw std::runtime_error(
                    "Jolt ran out of bodies while creating fragments");
            }
            pending.push_back({
                fragment.body_id,
                body->GetID(),
                fragment.mass_properties.linear_velocity_m_s,
                fragment.mass_properties.angular_velocity_rad_s,
                contact,
            });
            body_ids.push_back(body->GetID());
        }

        const JPH::BodyInterface::AddState add_state =
            body_interface.AddBodiesPrepare(
                body_ids.data(), static_cast<int>(body_ids.size()));
        body_interface.AddBodiesFinalize(
            body_ids.data(),
            static_cast<int>(body_ids.size()),
            add_state,
            JPH::EActivation::Activate);

        for (const PendingBody &body : pending) {
            body_interface.SetLinearAndAngularVelocity(
                body.body_id,
                toJolt(body.linear_velocity_m_s),
                toJolt(body.angular_velocity_rad_s));
            impl_->bodies_.emplace(body.logical_id, body.body_id);
            impl_->contact_states_.emplace(
                body.logical_id,
                BodyContactState{body.contact, 0.0, 0.0, false});
        }
    } catch (...) {
        for (const PendingBody &body : pending) {
            if (body_interface.IsAdded(body.body_id)) {
                body_interface.RemoveBody(body.body_id);
            }
            body_interface.DestroyBody(body.body_id);
        }
        throw;
    }
}

unsigned JoltWorld::positionPrecisionBits() noexcept { return 8*sizeof(JPH::Real); }

bool JoltWorld::runReversibleTrial(const std::function<bool()> &trial) {
    if(!trial||impl_->bodies_.size()>2048||impl_->trial_depth_>=16)
        throw std::invalid_argument("invalid reversible trial or body/depth budget exceeded");
    JPH::StateRecorderImpl recorder;impl_->physics_->SaveState(recorder);
    if(recorder.IsFailed()||recorder.GetDataSize()>16U*1024U*1024U)
        throw std::runtime_error("cannot capture bounded Jolt trial state");
    auto events=impl_->impact_collector_.capture();const auto tick=impl_->tick_.load(std::memory_order_relaxed);
    const auto diagnostics=impl_->contact_diagnostics_;
    const auto restore=[&] {
        recorder.Rewind();
        if(!impl_->physics_->RestoreState(recorder)||recorder.IsFailed())
            throw std::runtime_error("Jolt trial restore failed; discard this world");
        impl_->tick_.store(tick,std::memory_order_relaxed);impl_->impact_collector_.restore(std::move(events));
        impl_->contact_diagnostics_=diagnostics;
    };
    ++impl_->trial_depth_;bool accepted=false;
    try {accepted=trial();}catch(...) {--impl_->trial_depth_;restore();throw;}
    --impl_->trial_depth_;if(!accepted)restore();return accepted;
}

bool JoltWorld::runSpringTrial(const std::function<bool()> &trial) {
    constexpr std::size_t kMaximumStateBytes=16U*1024U*1024U;
    constexpr unsigned kMaximumDepth=16;
    if(!trial||impl_->trial_depth_!=0||impl_->bodies_.size()>1024||
       impl_->springs_.size()>20000||impl_->spring_trial_depth_>=kMaximumDepth)
        throw std::invalid_argument("invalid spring trial or body/spring/depth budget exceeded");

    JPH::StateRecorderImpl recorder;impl_->physics_->SaveState(recorder);
    if(recorder.IsFailed()||recorder.GetDataSize()>kMaximumStateBytes)
        throw std::runtime_error("cannot capture bounded Jolt spring trial state");

    // PhysicsSystem::RestoreState addresses constraints by their current
    // indices and DistanceConstraint::SaveState omits configuration. Hold refs
    // to the exact list so removals cannot destroy constraints before rollback.
    const JPH::Constraints constraint_order=impl_->physics_->GetConstraints();
    const auto springs=impl_->springs_;
    struct SpringConfiguration {
        float minimum_distance;
        float maximum_distance;
        JPH::SpringSettings settings;
    };
    std::unordered_map<unsigned,SpringConfiguration> spring_configuration;
    spring_configuration.reserve(springs.size());
    for(const auto &[id,spring]:springs) {
        spring_configuration.emplace(id,SpringConfiguration{
            spring.constraint->GetMinDistance(),spring.constraint->GetMaxDistance(),
            spring.constraint->GetLimitsSpringSettings()});
    }
    auto events=impl_->impact_collector_.capture();
    const auto tick=impl_->tick_.load(std::memory_order_relaxed);
    const auto diagnostics=impl_->contact_diagnostics_;
    const auto next_spring=impl_->next_spring_;

    const auto restore=[&] {
        // Remove/add is intentionally done for the whole list: Jolt removes by
        // swap-with-last, so selectively re-adding removed springs cannot
        // recover the solver order required by the saved state.
        JPH::Constraints current=impl_->physics_->GetConstraints();
        for(const JPH::Ref<JPH::Constraint> &constraint:current)
            impl_->physics_->RemoveConstraint(constraint.GetPtr());
        for(const JPH::Ref<JPH::Constraint> &constraint:constraint_order)
            impl_->physics_->AddConstraint(constraint.GetPtr());
        impl_->springs_=springs;impl_->next_spring_=next_spring;
        for(const auto &[id,configuration]:spring_configuration) {
            auto *constraint=impl_->springs_.at(id).constraint.GetPtr();
            constraint->SetDistance(configuration.minimum_distance,configuration.maximum_distance);
            constraint->SetLimitsSpringSettings(configuration.settings);
        }
        recorder.Rewind();
        if(!impl_->physics_->RestoreState(recorder)||recorder.IsFailed())
            throw std::runtime_error("Jolt spring trial restore failed; discard this world");
        impl_->tick_.store(tick,std::memory_order_relaxed);
        impl_->impact_collector_.restore(std::move(events));
        impl_->contact_diagnostics_=diagnostics;
    };

    ++impl_->spring_trial_depth_;bool accepted=false;
    try {accepted=trial();}catch(...) {--impl_->spring_trial_depth_;restore();throw;}
    --impl_->spring_trial_depth_;if(!accepted)restore();return accepted;
}

void JoltWorld::step(double fixed_dt_s) {
    if (fixed_dt_s <= 0.0) {
        throw std::invalid_argument("Jolt step must be positive");
    }
    impl_->last_dt_s = fixed_dt_s;
    impl_->applyRollingResistance(fixed_dt_s);
    auto &collector=impl_->impact_collector_;collector.manifolds=0;collector.points=0;collector.speculative_manifolds=0;
    impl_->tick_.fetch_add(1U, std::memory_order_relaxed);
    const JPH::EPhysicsUpdateError error = impl_->physics_->Update(
        static_cast<float>(fixed_dt_s),
        1,
        impl_->temp_allocator_.get(),
        impl_->job_system_.get());
    auto &diagnostics=impl_->contact_diagnostics_;
    diagnostics.last_manifolds=collector.manifolds.load(std::memory_order_relaxed);
    diagnostics.last_points=collector.points.load(std::memory_order_relaxed);
    diagnostics.last_speculative_manifolds=collector.speculative_manifolds.load(std::memory_order_relaxed);
    diagnostics.peak_manifolds=std::max(diagnostics.peak_manifolds,diagnostics.last_manifolds);
    diagnostics.peak_points=std::max(diagnostics.peak_points,diagnostics.last_points);
    diagnostics.peak_speculative_manifolds=std::max(diagnostics.peak_speculative_manifolds,diagnostics.last_speculative_manifolds);
    if (error != JPH::EPhysicsUpdateError::None) {
        std::string reason="Jolt physics update exceeded capacity:";
        if((error & JPH::EPhysicsUpdateError::ManifoldCacheFull)!=JPH::EPhysicsUpdateError::None)reason+=" manifold-cache-full";
        if((error & JPH::EPhysicsUpdateError::BodyPairCacheFull)!=JPH::EPhysicsUpdateError::None)reason+=" body-pair-cache-full";
        if((error & JPH::EPhysicsUpdateError::ContactConstraintsFull)!=JPH::EPhysicsUpdateError::None)reason+=" contact-constraints-full";
        throw std::runtime_error(reason+" (flags="+std::to_string(static_cast<unsigned>(error))+"). Some contacts were omitted; the step is not validated.");
    }
}

std::vector<ImpactEvent> JoltWorld::drainImpacts() {
    return impl_->impact_collector_.drain();
}

RigidSnapshot JoltWorld::snapshot(MatterBodyId body_id) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) {
        throw std::out_of_range("body is not in the Jolt world");
    }

    const JPH::BodyInterface &body_interface =
        impl_->physics_->GetBodyInterface();
    const JPH::RVec3 position =
        body_interface.GetCenterOfMassPosition(found->second);
    const JPH::Quat rotation =
        body_interface.GetRotation(found->second);
    return {
        fromJoltPosition(position),
        {
            static_cast<double>(rotation.GetW()),
            static_cast<double>(rotation.GetX()),
            static_cast<double>(rotation.GetY()),
            static_cast<double>(rotation.GetZ()),
        },
        fromJoltVector(body_interface.GetLinearVelocity(found->second)),
        fromJoltVector(body_interface.GetAngularVelocity(found->second)),
    };
}

RigidMechanicalState JoltWorld::mechanicalState(MatterBodyId body_id) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::out_of_range("mechanical body is missing");
    // Read solver state after Update, including the actual float mass/inertia
    // accepted by Jolt. Authored fragment descriptions are not insertion proof.
    const RigidSnapshot motion = snapshot(body_id);
    JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(), found->second);
    if (!lock.Succeeded()) throw std::runtime_error("cannot lock mechanical body");
    const JPH::Body &body = lock.GetBody();
    if (!body.IsDynamic()) return {motion, 0.0, {}};
    const double inverse_mass = body.GetMotionProperties()->GetInverseMass();
    const JPH::Mat44 jolt_inverse = body.GetInverseInertia();
    Mat3 inverse_inertia;
    for (JPH::uint row = 0; row < 3; ++row)
        for (JPH::uint column = 0; column < 3; ++column)
            inverse_inertia.m[row][column] = jolt_inverse(row, column);
    const auto inertia = inverse_inertia.inverse(0.0);
    if (inverse_mass <= 0.0 || !inertia)
        throw std::runtime_error("dynamic body has invalid mass or locked inertia");
    return {motion, 1.0 / inverse_mass, *inertia};
}

MechanicalTotals JoltWorld::mechanicalTotals(const Vec3 &gravity_m_s2) const {
    std::vector<MatterBodyId> ids;
    ids.reserve(impl_->bodies_.size());
    for (const auto &[id, body] : impl_->bodies_) {
        (void)body;
        if (id != kSupportSurfaceMatterId) ids.push_back(id);
    }
    std::sort(ids.begin(), ids.end());
    MechanicalTotals totals;
    for (const auto id : ids) totals += measureRigidMechanics(mechanicalState(id), gravity_m_s2);
    return totals;
}

CoupledSphereState JoltWorld::sphereContactState(MatterBodyId body_id) const {
    const auto it = impl_->contact_states_.find(body_id);
    if (it == impl_->contact_states_.end() || !it->second.is_sphere)
        throw std::invalid_argument("two-way contact currently supports rigid spheres only");
    const auto &state = it->second;
    return {snapshot(body_id), state.radius_m, state.mass_kg,
        state.sphere_inertia_factor * state.mass_kg * state.radius_m * state.radius_m};
}

void JoltWorld::applySphereContactState(MatterBodyId body_id, const CoupledSphereState &state) {
    const auto it = impl_->bodies_.find(body_id);
    if (it == impl_->bodies_.end() || !impl_->contact_states_.at(body_id).is_sphere)
        throw std::invalid_argument("coupled sphere is missing");
    applyRigidState(body_id,state.motion);
}

void JoltWorld::applyRigidState(MatterBodyId body_id,const RigidSnapshot &m) {
    const auto it=impl_->bodies_.find(body_id);
    if(it==impl_->bodies_.end())throw std::invalid_argument("rigid body is missing");
    impl_->physics_->GetBodyInterface().SetPositionRotationAndVelocity(it->second,
        toJoltPosition(m.center_of_mass_world_m),
        JPH::Quat(static_cast<float>(m.orientation_world.x), static_cast<float>(m.orientation_world.y),
                  static_cast<float>(m.orientation_world.z), static_cast<float>(m.orientation_world.w)),
        toJolt(m.linear_velocity_m_s), toJolt(m.angular_velocity_rad_s));
}

bool JoltWorld::contains(MatterBodyId body_id) const {
    return impl_->bodies_.contains(body_id);
}

void JoltWorld::removeAndDestroy(MatterBodyId body_id) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) {
        return;
    }
    releaseFromWorld(body_id);
    std::vector<unsigned> attached;
    for(auto &[id,spring]:impl_->springs_)if(spring.a==body_id||spring.b==body_id)attached.push_back(id);
    for(auto id:attached)removeDistanceSpring(id);
    // And the pins. A joint outliving one of the two bodies it holds is a
    // constraint pointing at nothing, which is how a physics engine crashes
    // rather than misbehaves -- and something that breaks takes its hinges with
    // it, which is the honest outcome anyway: tear a door off its frame and it
    // is no longer hinged to it.
    for (const unsigned id : jointsOn(body_id)) removeJoint(id);
    std::erase_if(impl_->external_pairs_,[&](const auto &pair){return pair.first==body_id||pair.second==body_id;});
    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    body_interface.RemoveBody(found->second);
    body_interface.DestroyBody(found->second);
    impl_->bodies_.erase(found);
    impl_->contact_states_.erase(body_id);
}

} // namespace banjo
