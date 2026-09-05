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
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/ConvexHullShape.h>
#include <Jolt/Physics/Collision/Shape/OffsetCenterOfMassShape.h>
#include <Jolt/Physics/Constraints/FixedConstraint.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
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

constexpr MatterBodyId kSupportSurfaceMatterId =
    std::numeric_limits<MatterBodyId>::max() - 1U;

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
        const bool surface_contact = id1 == kSupportSurfaceMatterId || id2 == kSupportSurfaceMatterId;
        if (!event.response_deferred_to_material && (!record_impact || surface_contact)) return;
        std::scoped_lock lock(mutex_);
        events_.push_back(event);
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
    Impl() : impact_collector_(tick_, contact_states_,external_pairs_) {
        ensureJoltRuntime();

        temp_allocator_ =
            std::make_unique<JPH::TempAllocatorImpl>(32U * 1024U * 1024U);
        const unsigned hardware_threads =
            std::max(1U, std::thread::hardware_concurrency());
        const unsigned worker_threads =
            hardware_threads > 1U ? hardware_threads - 1U : 1U;
        job_system_ = std::make_unique<JPH::JobSystemThreadPool>(
            JPH::cMaxPhysicsJobs,
            JPH::cMaxPhysicsBarriers,
            worker_threads);
        physics_ = std::make_unique<JPH::PhysicsSystem>();
        physics_->Init(
            8192,
            0,
            16384,
            8192,
            broad_phase_interface_,
            object_vs_broad_phase_filter_,
            object_pair_filter_);
        physics_->SetContactListener(&impact_collector_);
        physics_->SetGravity(toJolt(gravity_m_s2_));
    }

    ~Impl() {
        if (physics_) {
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
        if(trial_depth_!=0)throw std::logic_error("configuration/topology changes are forbidden during a reversible trial");
    }
    unsigned trial_depth_{};
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
    std::unordered_map<MatterBodyId, JPH::BodyID> bodies_;
    std::optional<RigidSurfaceDescription> support_surface_;
    Vec3 gravity_m_s2_{0.0, -9.81, 0.0};
};

JoltWorld::JoltWorld() : impl_(std::make_unique<Impl>()) {}
JoltWorld::~JoltWorld() = default;
JoltWorld::JoltWorld(JoltWorld &&) noexcept = default;
JoltWorld &JoltWorld::operator=(JoltWorld &&) noexcept = default;

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

            JPH::ConvexHullShapeSettings hull_settings(
                hull_points.data(),
                static_cast<int>(hull_points.size()),
                0.0F);
            const JPH::ShapeSettings::ShapeResult hull_result =
                hull_settings.Create();
            if (hull_result.HasError()) {
                const JPH::String &error = hull_result.GetError();
                throw std::runtime_error(
                    "Jolt could not build a fragment convex hull: " +
                    std::string(error.begin(), error.end()));
            }
            const JPH::RefConst<JPH::Shape> inner_shape = hull_result.Get();
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
                JPH::EMotionType::Dynamic,
                Layers::kMoving);
            settings.mFriction =
                static_cast<float>(contact.dynamic_friction);
            settings.mRestitution =
                static_cast<float>(contact.restitution);
            settings.mLinearDamping = 0.02F;
            settings.mAngularDamping = 0.02F;
            settings.mUserData = fragment.body_id;
            settings.mMotionQuality = JPH::EMotionQuality::LinearCast;
            settings.mOverrideMassProperties =
                JPH::EOverrideMassProperties::MassAndInertiaProvided;
            settings.mMassPropertiesOverride.mMass =
                static_cast<float>(fragment.mass_properties.mass_kg);
            settings.mMassPropertiesOverride.mInertia =
                toJoltInertia(
                    fragment.mass_properties.inertia_world_kg_m2);

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
    if(!trial||impl_->bodies_.size()>256||impl_->trial_depth_>=16)
        throw std::invalid_argument("invalid reversible trial or body/depth budget exceeded");
    JPH::StateRecorderImpl recorder;impl_->physics_->SaveState(recorder);
    if(recorder.IsFailed()||recorder.GetDataSize()>16U*1024U*1024U)
        throw std::runtime_error("cannot capture bounded Jolt trial state");
    auto events=impl_->impact_collector_.capture();const auto tick=impl_->tick_.load(std::memory_order_relaxed);
    const auto restore=[&] {
        recorder.Rewind();
        if(!impl_->physics_->RestoreState(recorder)||recorder.IsFailed())
            throw std::runtime_error("Jolt trial restore failed; discard this world");
        impl_->tick_.store(tick,std::memory_order_relaxed);impl_->impact_collector_.restore(std::move(events));
    };
    ++impl_->trial_depth_;bool accepted=false;
    try {accepted=trial();}catch(...) {--impl_->trial_depth_;restore();throw;}
    --impl_->trial_depth_;if(!accepted)restore();return accepted;
}

void JoltWorld::step(double fixed_dt_s) {
    if (fixed_dt_s <= 0.0) {
        throw std::invalid_argument("Jolt step must be positive");
    }
    impl_->applyRollingResistance(fixed_dt_s);
    impl_->tick_.fetch_add(1U, std::memory_order_relaxed);
    const JPH::EPhysicsUpdateError error = impl_->physics_->Update(
        static_cast<float>(fixed_dt_s),
        1,
        impl_->temp_allocator_.get(),
        impl_->job_system_.get());
    if (error != JPH::EPhysicsUpdateError::None) {
        throw std::runtime_error("Jolt physics update reported an error");
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
    std::erase_if(impl_->external_pairs_,[&](const auto &pair){return pair.first==body_id||pair.second==body_id;});
    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    body_interface.RemoveBody(found->second);
    body_interface.DestroyBody(found->second);
    impl_->bodies_.erase(found);
    impl_->contact_states_.erase(body_id);
}

} // namespace banjo
