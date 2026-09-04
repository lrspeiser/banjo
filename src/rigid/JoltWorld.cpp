#include "rigid/JoltWorld.hpp"

#include <Jolt/Jolt.h>
#include <Jolt/RegisterTypes.h>
#include <Jolt/Core/Factory.h>
#include <Jolt/Core/JobSystemThreadPool.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Collision/ContactListener.h>
#include <Jolt/Physics/Collision/EstimateCollisionResponse.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/ConvexHullShape.h>
#include <Jolt/Physics/Collision/Shape/OffsetCenterOfMassShape.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <Jolt/Physics/PhysicsSystem.h>

#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <iostream>
#include <memory>
#include <mutex>
#include <numbers>
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
    explicit ImpactCollector(std::atomic<std::uint64_t> &tick) : tick_(tick) {}

    void OnContactAdded(
        const JPH::Body &body1,
        const JPH::Body &body2,
        const JPH::ContactManifold &manifold,
        JPH::ContactSettings &settings) override {
        const MatterBodyId id1 = body1.GetUserData();
        const MatterBodyId id2 = body2.GetUserData();
        if (id1 == kInvalidMatterBodyId || id2 == kInvalidMatterBodyId) {
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
        const JPH::RVec3 contact_point = contact_sum / static_cast<float>(contact_count);
        const JPH::Vec3 relative_velocity =
            body2.GetPointVelocity(contact_point) - body1.GetPointVelocity(contact_point);
        const double closing_speed = std::max(
            0.0,
            -static_cast<double>(relative_velocity.Dot(manifold.mWorldSpaceNormal)));

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
        event.normal_a_to_b = normalized(fromJoltVector(manifold.mWorldSpaceNormal));
        event.relative_velocity_b_minus_a_m_s = fromJoltVector(relative_velocity);
        event.closing_speed_m_s = closing_speed;
        event.estimated_normal_impulse_n_s = estimated_normal_impulse;
        event.available_normal_energy_j = 0.5 * reduced_mass * closing_speed * closing_speed;

        std::scoped_lock lock(mutex_);
        events_.push_back(event);
    }

    [[nodiscard]] std::vector<ImpactEvent> drain() {
        std::scoped_lock lock(mutex_);
        std::vector<ImpactEvent> result;
        result.swap(events_);
        return result;
    }

private:
    std::atomic<std::uint64_t> &tick_;
    std::mutex mutex_;
    std::vector<ImpactEvent> events_;
};

} // namespace

class JoltWorld::Impl {
public:
    Impl() : impact_collector_(tick_) {
        JPH::RegisterDefaultAllocator();
        JPH::Trace = traceImpl;
#ifdef JPH_ENABLE_ASSERTS
        JPH::AssertFailed = assertFailedImpl;
#endif
        JPH::Factory::sInstance = new JPH::Factory();
        JPH::RegisterTypes();

        temp_allocator_ = std::make_unique<JPH::TempAllocatorImpl>(32U * 1024U * 1024U);
        const unsigned hardware_threads = std::max(1U, std::thread::hardware_concurrency());
        const unsigned worker_threads = hardware_threads > 1U ? hardware_threads - 1U : 1U;
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
        physics_->SetGravity(JPH::Vec3(0.0F, -9.81F, 0.0F));
    }

    ~Impl() {
        if (physics_) {
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
        JPH::UnregisterTypes();
        delete JPH::Factory::sInstance;
        JPH::Factory::sInstance = nullptr;
    }

    BroadPhaseLayerInterface broad_phase_interface_;
    ObjectVsBroadPhaseLayerFilter object_vs_broad_phase_filter_;
    ObjectLayerPairFilter object_pair_filter_;
    std::unique_ptr<JPH::TempAllocatorImpl> temp_allocator_;
    std::unique_ptr<JPH::JobSystemThreadPool> job_system_;
    std::unique_ptr<JPH::PhysicsSystem> physics_;
    std::atomic<std::uint64_t> tick_{0};
    ImpactCollector impact_collector_;
    JPH::BodyID floor_id_;
    std::unordered_map<MatterBodyId, JPH::BodyID> bodies_;
};

JoltWorld::JoltWorld() : impl_(std::make_unique<Impl>()) {}
JoltWorld::~JoltWorld() = default;
JoltWorld::JoltWorld(JoltWorld &&) noexcept = default;
JoltWorld &JoltWorld::operator=(JoltWorld &&) noexcept = default;

void JoltWorld::setGravity(const Vec3 &gravity_m_s2) {
    impl_->physics_->SetGravity(toJolt(gravity_m_s2));
}

void JoltWorld::addFloor() {
    if (!impl_->floor_id_.IsInvalid()) {
        throw std::logic_error("floor already exists");
    }

    JPH::BodyCreationSettings settings(
        new JPH::BoxShape(JPH::Vec3(10.0F, 0.25F, 5.0F)),
        JPH::RVec3(0.0_r, -0.25_r, 0.0_r),
        JPH::Quat::sIdentity(),
        JPH::EMotionType::Static,
        Layers::kNonMoving);
    settings.mFriction = 0.65F;
    settings.mRestitution = 0.02F;
    settings.mUserData = kInvalidMatterBodyId;

    impl_->floor_id_ = impl_->physics_->GetBodyInterface().CreateAndAddBody(
        settings, JPH::EActivation::DontActivate);
}

void JoltWorld::addBall(const RigidBallDescription &description) {
    if (description.body_id == kInvalidMatterBodyId || description.radius_m <= 0.0 ||
        description.material.density_kg_m3 <= 0.0) {
        throw std::invalid_argument("ball requires a valid ID, radius, and density");
    }
    if (impl_->bodies_.contains(description.body_id)) {
        throw std::logic_error("body ID is already in the Jolt world");
    }

    const double volume = (4.0 / 3.0) * std::numbers::pi *
                          description.radius_m * description.radius_m * description.radius_m;
    const double computed_mass = volume * description.material.density_kg_m3;
    const double mass =
        description.mass_override_kg > 0.0 ? description.mass_override_kg : computed_mass;

    JPH::BodyCreationSettings settings(
        new JPH::SphereShape(static_cast<float>(description.radius_m)),
        toJoltPosition(description.position_world_m),
        JPH::Quat::sIdentity(),
        JPH::EMotionType::Dynamic,
        Layers::kMoving);
    settings.mFriction = static_cast<float>(description.material.friction);
    settings.mRestitution = static_cast<float>(description.material.restitution);
    settings.mLinearDamping = 0.01F;
    settings.mAngularDamping = 0.01F;
    settings.mUserData = description.body_id;
    settings.mOverrideMassProperties = JPH::EOverrideMassProperties::CalculateInertia;
    settings.mMassPropertiesOverride.mMass = static_cast<float>(mass);

    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    const JPH::BodyID body_id =
        body_interface.CreateAndAddBody(settings, JPH::EActivation::Activate);
    if (body_id.IsInvalid()) {
        throw std::runtime_error("Jolt could not create ball body");
    }
    body_interface.SetLinearAndAngularVelocity(
        body_id,
        toJolt(description.linear_velocity_m_s),
        toJolt(description.angular_velocity_rad_s));
    impl_->bodies_.emplace(description.body_id, body_id);
}

void JoltWorld::addFragments(const std::vector<RigidFragmentDescription> &fragments) {
    if (fragments.empty()) {
        return;
    }

    struct PendingBody {
        MatterBodyId logical_id{kInvalidMatterBodyId};
        JPH::BodyID body_id{};
        Vec3 linear_velocity_m_s{};
        Vec3 angular_velocity_rad_s{};
    };

    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    std::vector<PendingBody> pending;
    std::vector<JPH::BodyID> body_ids;
    pending.reserve(fragments.size());
    body_ids.reserve(fragments.size());

    try {
        for (const RigidFragmentDescription &fragment : fragments) {
            if (fragment.body_id == kInvalidMatterBodyId ||
                impl_->bodies_.contains(fragment.body_id) ||
                fragment.mass_properties.mass_kg <= 0.0 ||
                fragment.collision_points_local_m.size() < 4U) {
                throw std::invalid_argument("rigid fragment description is invalid");
            }
            if (fragment.collision_points_local_m.size() >
                static_cast<std::size_t>(JPH::ConvexHullShape::cMaxPointsInHull)) {
                throw std::invalid_argument("rigid fragment exceeds Jolt convex hull point limit");
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
            const JPH::ShapeSettings::ShapeResult hull_result = hull_settings.Create();
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

            JPH::BodyCreationSettings settings(
                centered_shape.GetPtr(),
                toJoltPosition(fragment.mass_properties.center_of_mass_world_m),
                JPH::Quat::sIdentity(),
                JPH::EMotionType::Dynamic,
                Layers::kMoving);
            settings.mFriction = static_cast<float>(fragment.friction);
            settings.mRestitution = static_cast<float>(fragment.restitution);
            settings.mLinearDamping = 0.02F;
            settings.mAngularDamping = 0.02F;
            settings.mUserData = fragment.body_id;
            settings.mMotionQuality = JPH::EMotionQuality::LinearCast;
            settings.mOverrideMassProperties =
                JPH::EOverrideMassProperties::MassAndInertiaProvided;
            settings.mMassPropertiesOverride.mMass =
                static_cast<float>(fragment.mass_properties.mass_kg);
            settings.mMassPropertiesOverride.mInertia =
                toJoltInertia(fragment.mass_properties.inertia_world_kg_m2);

            JPH::Body *body = body_interface.CreateBody(settings);
            if (body == nullptr) {
                throw std::runtime_error("Jolt ran out of bodies while creating fragments");
            }
            pending.push_back({
                fragment.body_id,
                body->GetID(),
                fragment.mass_properties.linear_velocity_m_s,
                fragment.mass_properties.angular_velocity_rad_s,
            });
            body_ids.push_back(body->GetID());
        }

        const JPH::BodyInterface::AddState add_state = body_interface.AddBodiesPrepare(
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

void JoltWorld::step(double fixed_dt_s) {
    if (fixed_dt_s <= 0.0) {
        throw std::invalid_argument("Jolt step must be positive");
    }
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

    const JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    const JPH::RVec3 position = body_interface.GetCenterOfMassPosition(found->second);
    const JPH::Quat rotation = body_interface.GetRotation(found->second);
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

bool JoltWorld::contains(MatterBodyId body_id) const {
    return impl_->bodies_.contains(body_id);
}

void JoltWorld::removeAndDestroy(MatterBodyId body_id) {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) {
        return;
    }
    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    body_interface.RemoveBody(found->second);
    body_interface.DestroyBody(found->second);
    impl_->bodies_.erase(found);
}

} // namespace banjo
