#include "rigid/JoltWorld.hpp"
#include "fracture/ActivationPolicy.hpp"
#include "physics/RigidAttachment.hpp"

#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"

#include <unordered_set>
#include <Jolt/Jolt.h>
#include <Jolt/RegisterTypes.h>
#include <Jolt/Core/Factory.h>
#include <Jolt/Core/JobSystemThreadPool.h>
#include <Jolt/Core/JobSystemSingleThreaded.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Body/BodyLock.h>
#include <Jolt/Physics/StateRecorder.h>
#include <Jolt/Physics/StateRecorderImpl.h>
#include "rigid/BoundedStateRecorder.hpp"
#include <Jolt/Physics/Body/BodyPair.h>
#include <Jolt/Physics/Collision/ContactListener.h>
#include <Jolt/Physics/Collision/Shape/SubShapeIDPair.h>
#include <Jolt/Physics/Collision/EstimateCollisionResponse.h>
#include <Jolt/Physics/Collision/TransformedShape.h>
#include <Jolt/Physics/Constraints/ContactConstraintManager.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/HeightFieldShape.h>
#include <Jolt/Physics/Collision/Shape/MeshShape.h>
#include <Jolt/Physics/Collision/Shape/ConvexHullShape.h>
#include <Jolt/Physics/Collision/Shape/OffsetCenterOfMassShape.h>
#include <Jolt/Physics/Constraints/FixedConstraint.h>
#include <Jolt/Physics/Constraints/DistanceConstraint.h>
#include <Jolt/Physics/Constraints/FixedConstraint.h>
#include <Jolt/Physics/Constraints/HingeConstraint.h>
#include <Jolt/Physics/Constraints/GearConstraint.h>
#include <Jolt/Physics/Constraints/PulleyConstraint.h>
#include <Jolt/Physics/Constraints/SliderConstraint.h>
#include <Jolt/Physics/Constraints/SixDOFConstraint.h>

#include "rigid/DrumRope.hpp"
#include "rigid/LogFaceSpring.hpp"
#include <Jolt/Physics/Collision/Shape/RotatedTranslatedShape.h>
#include <Jolt/Physics/Collision/CastResult.h>
#include <Jolt/Physics/Collision/RayCast.h>
#include <Jolt/Physics/Collision/CollideShape.h>
#include <Jolt/Physics/Collision/ManifoldBetweenTwoFaces.h>
#include <Jolt/Physics/Collision/CollisionCollectorImpl.h>
#include <Jolt/Physics/Body/BodyFilter.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <Jolt/Physics/Collision/Shape/CylinderShape.h>
#include <Jolt/Physics/Collision/CollisionDispatch.h>
#include <Jolt/Physics/Collision/Shape/StaticCompoundShape.h>
#include <Jolt/Physics/PhysicsSystem.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <numbers>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

JPH_SUPPRESS_WARNINGS

namespace banjo {
namespace {

using namespace JPH::literals;

// Optional, allocation-free timing. Physical calculations never read these
// counters; RAII also accounts for scopes that leave through an exception.
class ExecutionWallTimer {
    using Clock=std::chrono::steady_clock;
    double *destination_;
    Clock::time_point start_;
public:
    explicit ExecutionWallTimer(double *destination):destination_(destination),
        start_(destination?Clock::now():Clock::time_point{}){}
    void finish(){if(destination_){*destination_+=std::chrono::duration<double,std::milli>(Clock::now()-start_).count();destination_=nullptr;}}
    ~ExecutionWallTimer(){finish();}
    ExecutionWallTimer(const ExecutionWallTimer&)=delete;
    ExecutionWallTimer& operator=(const ExecutionWallTimer&)=delete;
};

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
    // One per part of a compound whose parts are not all the body's material --
    // an iron axle in an oak wheelset -- in the order of its parts. Empty when
    // the whole body meets things as `contact`. Each part's leaf shape carries
    // its index + 1 as Jolt user data, which is how a contact finds it.
    std::vector<CompiledContactMaterial> part_contacts;
    // A compound's round parts: each cylinder, which rolls about its own axis
    // where it touches something (resistWheels). An axle is one too; it rolls
    // only if it is what touches.
    struct Wheel {
        JPH::uint64 part{};          // its leaf shape's user data: part index + 1
        Vec3 axis_local{0.0, 1.0, 0.0};
        double radius_m{};
        double own_rolling{};        // its own material's share of the coefficient
    };
    std::vector<Wheel> wheels;
};

// Which of a body's round parts a contact touched, or -1.
int wheelOf(const BodyContactState &state, const JPH::Body &body, const JPH::SubShapeID &part) {
    if (state.wheels.empty()) return -1;
    const JPH::uint64 index = body.GetShape()->GetSubShapeUserData(part);
    for (std::size_t k = 0; k < state.wheels.size(); ++k)
        if (state.wheels[k].part == index) return static_cast<int>(k);
    return -1;
}

// How the part of `body` that a contact touched meets things.
const CompiledContactMaterial &contactOfPart(const BodyContactState &state, const JPH::Body &body,
                                             const JPH::SubShapeID &part) {
    if (state.part_contacts.empty()) return state.contact;
    const JPH::uint64 index = body.GetShape()->GetSubShapeUserData(part);
    return index >= 1 && index <= state.part_contacts.size() ? state.part_contacts[index - 1] : state.contact;
}

// ---- rolling resistance: what is carried from one step to the next ----------

// Below this sideways speed at the contact a ball is rolling rather than
// sliding: the same line the contact callback draws between static and
// dynamic friction.
constexpr double kRollingSlipMS = 0.05;
// A ball further than this from where the last step left it has been moved by
// the host (set down, carried, placed), and is not touching what it touched.
constexpr double kRollingMovedM = 1.0e-3;

// A contact touching a round body, as the narrow phase found it in one step.
// Kept for the next: the solver's normal impulse through it is read once the
// step is over, and the couple it sets is applied before the next step.
struct RollingContact {
    JPH::SubShapeIDPair key;              // the manifold, by Jolt's own name for it
    JPH::BodyID sphere_body;
    JPH::BodyID other_body;
    MatterBodyId sphere{kInvalidMatterBodyId};
    MatterBodyId other{kInvalidMatterBodyId};
    Vec3 normal{};                        // world: out of the other body, into the ball
    Vec3 point_world_m{};
    Vec3 sphere_at_m{};                   // the ball's centre when the step ended
    double normal_force_n{};              // over the step it was found in
    bool from_solver{};
    int wheel{-1};                        // which round part, for a body with wheels; -1 for a ball
};

// A total order over the rolling contacts of one step, for the same reason
// ImpactEvent.hpp has one over impacts: they are pushed from Jolt's worker
// threads under a mutex, so the order they arrive in is a thread-completion
// order and is not the same twice.
//
// It matters here because a ball is reported by both the discrete pass and
// the swept one when it is moving fast enough for CCD, so the same manifold
// arrives twice with two different normals and two different points, and only
// one of them is kept. Keeping "the first" off the arrival order picks a
// different normal from run to run, and the couple that resists the roll is
// built on that normal: measured, a glass plate struck by an iron ball settled
// into one of three different rooms over six runs of the identical world.
//
// The ball and the manifold are what this is sorted BY; everything after them
// is there only to break the tie the same way twice.
[[nodiscard]] inline bool steadiestRollingContactFirst(const RollingContact &a,
                                                       const RollingContact &b) {
    if (a.sphere != b.sphere) return a.sphere < b.sphere;
    if (!(a.key == b.key)) return a.key < b.key;
    if (a.normal.x != b.normal.x) return a.normal.x < b.normal.x;
    if (a.normal.y != b.normal.y) return a.normal.y < b.normal.y;
    if (a.normal.z != b.normal.z) return a.normal.z < b.normal.z;
    if (a.point_world_m.x != b.point_world_m.x) return a.point_world_m.x < b.point_world_m.x;
    if (a.point_world_m.y != b.point_world_m.y) return a.point_world_m.y < b.point_world_m.y;
    if (a.point_world_m.z != b.point_world_m.z) return a.point_world_m.z < b.point_world_m.z;
    if (a.other != b.other) return a.other < b.other;
    return a.wheel < b.wheel;
}

// Jolt keeps, for warm starting, the total normal impulse its solver applied
// at every contact point in the last update, and the only public way to read
// it is the state recorder. This reads the contact section that
// PhysicsSystem::SaveState(EStateRecorderState::Contacts) writes -- Jolt
// 5.6.0's ContactConstraintManager::ManifoldCache::SaveState, field by field --
// and adds up each manifold's normal impulse. It has to account for every byte:
// a layout that does not add up is refused rather than misread, and the caller
// then falls back to the ball's own change of momentum.
struct RecordedContactPoint {JPH::Float3 a,b;float lambda{};};
struct RecordedContactManifold {
    JPH::SubShapeIDPair key;JPH::Float3 normal;
    float friction[2]{},twist{};std::vector<RecordedContactPoint> points;
};
bool readContactRecords(std::string_view data,
                        const std::function<void(const RecordedContactManifold &)> &consume) {
    std::size_t at = 0;
    const auto take = [&](void *into, std::size_t bytes) {
        if (bytes > data.size() - at) return false;
        std::memcpy(into, data.data() + at, bytes);
        at += bytes;
        return true;
    };
    const auto skip = [&](std::size_t bytes) {
        if (bytes > data.size() - at) return false;
        at += bytes;
        return true;
    };
    JPH::uint8 state = 0;
    if (!take(&state, sizeof state) ||
        state != static_cast<JPH::uint8>(JPH::EStateRecorderState::Contacts))
        return false;
    JPH::uint32 pairs = 0;
    if (!take(&pairs, sizeof pairs)) return false;
    for (JPH::uint32 p = 0; p < pairs; ++p) {
        // The body pair's key, and its cached relative position and rotation.
        if (!skip(sizeof(JPH::BodyPair) + 2 * sizeof(JPH::Float3))) return false;
        JPH::uint32 manifolds = 0;
        if (!take(&manifolds, sizeof manifolds)) return false;
        for (JPH::uint32 m = 0; m < manifolds; ++m) {
            RecordedContactManifold record;
            JPH::uint16 points = 0;
            if (!take(&record.key, sizeof record.key) || !take(&points, sizeof points)) return false;
            // The normal (in body 2's frame), two friction impulses, the twist.
            if (!take(&record.normal,sizeof record.normal)||!take(record.friction,sizeof record.friction)||!take(&record.twist,sizeof record.twist))return false;
            if(points>(data.size()-at)/(2*sizeof(JPH::Float3)+sizeof(float)))return false;
            record.points.resize(points);
            for (JPH::uint16 k = 0; k < points; ++k) {
                // The point on each body, then the normal impulse through it.
                auto &point=record.points[k];
                if (!take(&point.a,sizeof point.a)||!take(&point.b,sizeof point.b)||!take(&point.lambda,sizeof point.lambda))return false;
            }
            consume(record);
        }
    }
    JPH::uint32 swept = 0;   // manifolds only reported by the swept pass: keys alone
    if (!take(&swept, sizeof swept)) return false;
    return data.size() - at == static_cast<std::size_t>(swept) * sizeof(JPH::SubShapeIDPair);
}
bool readContactImpulses(std::string_view data,
                         std::vector<std::pair<JPH::SubShapeIDPair, double>> &out) {
    return readContactRecords(data,[&](const RecordedContactManifold &record){
        double total=0;for(const auto &point:record.points)total+=point.lambda;
        out.emplace_back(record.key,total);
    });
}

struct ContactImpulseGeometry {
    JPH::SubShapeIDPair key;MatterBodyId a{},b{};
    JPH::Vec3 normal;std::vector<Vec3> points;std::vector<double> gaps,radii;double friction{};
};

// Saves only the contact pairs a round body is in, so reading the impulses
// costs what the balls cost, not what the whole room does.
class RoundBodyContacts final : public JPH::StateRecorderFilter {
public:
    explicit RoundBodyContacts(std::vector<JPH::BodyID> balls) : balls_(std::move(balls)) {
        std::sort(balls_.begin(), balls_.end());
        balls_.erase(std::unique(balls_.begin(), balls_.end()), balls_.end());
    }
    [[nodiscard]] bool ShouldSaveContact(const JPH::BodyID &a, const JPH::BodyID &b) const override {
        return std::binary_search(balls_.begin(), balls_.end(), a) ||
               std::binary_search(balls_.begin(), balls_.end(), b);
    }

private:
    std::vector<JPH::BodyID> balls_;
};

[[nodiscard]] CompiledContactMaterial legacyFragmentContact(
    double friction,
    double restitution,
    double rolling_resistance) {
    CompiledContactMaterial contact;
    contact.static_friction = std::max(0.0, friction);
    contact.dynamic_friction = std::max(0.0, friction);
    contact.rolling_resistance = std::clamp(rolling_resistance, 0.0, 1.0);
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

// Every edge of a moving box or hull is made a little round: 2 mm, and never
// more than a tenth of its thinnest half. Its outer size is its authored size
// either way -- Jolt puts the radius inside the shape -- so nothing is bigger
// or smaller for it. It is there because of how a fast body is kept from
// passing through things: Jolt sweeps it (EMotionQuality::LinearCast) as its
// shape shrunk by that radius, and a shape with none, lying on something,
// starts its sweep already touching it. The sweep then reports a hit along the
// way the body is going, and the solver stops it dead and bounces it back.
// Measured: a 0.6 m oak box sliding along an oak plank it lay on went from
// 5 m/s to -3.9 in one step, and from 9 to -5.8; the courtyard's arrow, lying
// on its rest, from 5.87 to -2.45, on 13 of 19 draws and stiffnesses. With any
// radius from 0.5 mm to 5 mm, none of them. Turning the sweep off did the same,
// and would let a fast arrow through a plank.
//
// A tenth, and no more, for thin things. On a blade one 10 mm cell thick the
// edge meeting the wood is the whole of what it does, and at two fifths -- 2 mm
// there -- a sword's chop bounced off an oak batten at 1.71 m/s instead of 0.49
// and left a notch the batten could still carry. At a tenth, 0.5 mm, it chops
// as it did.
constexpr float kSweepRadiusM = 0.002F;

float sweepRadius(const JPH::Vec3 &half_extent_m) {
    return std::min(kSweepRadiusM, 0.1F * half_extent_m.ReduceMin());
}

JPH::Quat toJoltRotation(const Quat &q) {
    return JPH::Quat(float(q.x), float(q.y), float(q.z), float(q.w)).Normalized();
}

// The Jolt shape of one part of a compound, in the part's own frame.
//
// A cylinder is Jolt's own, whose axis is its local y like ours. Its sweep
// radius is given explicitly, as a box's is: Jolt's default is 50 mm, which
// would round a 30 mm axle into something else entirely. The radius lies
// inside the shape ("the total cylinder will not grow"), so the part still
// fills exactly the size it was given.
JPH::Ref<JPH::Shape> compoundPartShape(const RigidCompoundPart &p) {
    const Quat q = p.rotation_local;
    if (!std::isfinite(q.w + q.x + q.y + q.z) || std::abs(q.w*q.w + q.x*q.x + q.y*q.y + q.z*q.z - 1) > 1e-6)
        throw std::invalid_argument("compound part rotation must be a unit quaternion");
    const Vec3 v = p.geometry.dimensions_m;
    const bool sized = std::isfinite(lengthSquared(v)) && std::min({v.x, v.y, v.z}) > 0;
    switch (p.geometry.kind) {
    case PrimitiveKind::Sphere:
        if (!std::isfinite(p.geometry.radius_m) || p.geometry.radius_m <= 0)
            throw std::invalid_argument("invalid compound sphere");
        return new JPH::SphereShape(float(p.geometry.radius_m));
    case PrimitiveKind::Box:
        if (!sized) throw std::invalid_argument("invalid compound box");
        return new JPH::BoxShape(toJolt(v / 2), sweepRadius(toJolt(v / 2)));
    case PrimitiveKind::Cylinder: {
        if (!sized || std::abs(v.x - v.z) > 1e-9 * std::max(1.0, v.x))
            throw std::invalid_argument("a compound cylinder is sized {diameter, length, diameter}");
        const float half = float(v.y / 2), radius = float(v.x / 2);
        const float rounding = std::min(std::max(kSweepRadiusM, float(p.edge_rounding_m)), 0.5F * std::min(half, radius));
        return new JPH::CylinderShape(half, radius, p.edge_rounding_m > 0 ? rounding
                                                    : std::min(kSweepRadiusM, 0.1F * std::min(half, radius)));
    }
    }
    throw std::invalid_argument("unknown compound part kind");
}

// A tool's point in the ground, as the contact listener sees it: its region
// and -- for a tool that collides as its cells (setCollisionCells) -- exactly
// which of its cells are point, by the sub-shape ids Jolt names them with. By
// cell, not by where a contact lies: a cell of the point and the next cell up
// the arm share a face, and a contact on that face could be either.
struct GroundSuspension {
    JoltWorld::GroundPointRegion region;
    bool by_cell{};
    std::vector<JPH::SubShapeID::Type> cells;   // sorted
};

// Whether a point in a tool's own frame is in the region its point occupies
// (JoltWorld::GroundPointRegion): from `ahead_m` beyond the tip back along the
// way it points to the end of the point, and near that line.
[[nodiscard]] bool inPointRegion(const JoltWorld::GroundPointRegion &region, const Vec3 &local) {
    const Vec3 from_tip = local - region.tip_local_m;
    const double back = -dot(from_tip, region.pointing_local);
    if (back < -region.ahead_m || back > region.length_m + region.margin_m) return false;
    const Vec3 radial = from_tip + back * region.pointing_local;
    return length(radial) <= region.radius_m + region.margin_m;
}

class ImpactCollector final : public JPH::ContactListener {
public:
    RigidContactRestitution restitution_model{RigidContactRestitution::MaterialCombination};
    std::unordered_map<JPH::uint32,std::pair<Vec3,Vec3>> initial_contact_motion;
    bool contact_impulses_enabled{};
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
        const std::set<std::pair<MatterBodyId,MatterBodyId>> &external_pairs,
        const std::unordered_map<MatterBodyId, GroundSuspension> &ground_suspended)
        : tick_(tick), contact_states_(contact_states), external_pairs_(external_pairs),
          ground_suspended_(ground_suspended) {}
    // Written only between steps, like ground_suspended_.
    std::unordered_set<MatterBodyId> driven;

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
        // After processContact, which sets the combined friction itself.
        if (!driven.empty() && (driven.contains(body1.GetUserData()) || driven.contains(body2.GetUserData())))
            settings.mCombinedFriction = 0.0F;
        configureMidpointContact(body1,body2,settings);
        recordContactGeometry(body1,body2,manifold,settings);
    }

    void OnContactPersisted(
        const JPH::Body &body1,
        const JPH::Body &body2,
        const JPH::ContactManifold &manifold,
        JPH::ContactSettings &settings) override {
        processContact(body1, body2, manifold, settings, false);
        // After processContact, which sets the combined friction itself.
        if (!driven.empty() && (driven.contains(body1.GetUserData()) || driven.contains(body2.GetUserData())))
            settings.mCombinedFriction = 0.0F;
        configureMidpointContact(body1,body2,settings);
        recordContactGeometry(body1,body2,manifold,settings);
    }
    std::vector<ContactImpulseGeometry> takeContactGeometry(){
        std::scoped_lock lock(contact_mutex_);
        if(contact_swept_)throw std::runtime_error("contact impulse audit supports discrete contacts only");
        if(contact_overflow_)throw std::runtime_error("native contact observation budget exceeded");
        std::vector<ContactImpulseGeometry> out;out.swap(contact_geometry_);return out;
    }
    void clearContactGeometry(){std::scoped_lock lock(contact_mutex_);contact_geometry_.clear();contact_overflow_=contact_swept_=false;}

    [[nodiscard]] std::vector<ImpactEvent> capture() {std::scoped_lock lock(mutex_);if(events_.size()>65536)throw std::runtime_error("trial event queue budget exceeded");return events_;}
    void restore(std::vector<ImpactEvent> events) {std::scoped_lock lock(mutex_);events_.swap(events);}
    [[nodiscard]] std::vector<ImpactEvent> drain() {
        std::scoped_lock lock(mutex_);
        std::vector<ImpactEvent> result;
        result.swap(events_);
        return result;
    }
    // The round bodies' contacts the last step found, taken.
    [[nodiscard]] std::vector<RollingContact> takeRolling() {
        std::scoped_lock lock(rolling_mutex_);
        std::vector<RollingContact> result;
        result.swap(rolling_);
        return result;
    }
    void dropRolling() {
        std::scoped_lock lock(rolling_mutex_);
        rolling_.clear();
    }

private:
    void configureMidpointContact(const JPH::Body &a,const JPH::Body &b,JPH::ContactSettings &settings) const {
        if((restitution_model!=RigidContactRestitution::MidpointUnilateral&&restitution_model!=RigidContactRestitution::MidpointBlockFriction)||settings.mIsSensor)return;
        settings.mBanjoMidpointContact=true;
        settings.mBanjoBlockFriction=restitution_model==RigidContactRestitution::MidpointBlockFriction;
        const auto assign=[&](const JPH::Body &body,JPH::Vec3 &v,JPH::Vec3 &w){
            if(body.IsStatic()){v=w=JPH::Vec3::sZero();return;}
            const auto found=initial_contact_motion.find(body.GetID().GetIndexAndSequenceNumber());
            if(found==initial_contact_motion.end())throw std::runtime_error("midpoint contact initial motion missing");
            v=toJolt(found->second.first);w=toJolt(found->second.second);
        };
        assign(a,settings.mBanjoInitialLinear1,settings.mBanjoInitialAngular1);
        assign(b,settings.mBanjoInitialLinear2,settings.mBanjoInitialAngular2);
    }
    void recordContactGeometry(const JPH::Body &a,const JPH::Body &b,const JPH::ContactManifold &manifold,const JPH::ContactSettings &settings){
        if(!contact_impulses_enabled||settings.mIsSensor)return;
        if((!a.IsStatic()&&a.GetMotionProperties()->GetMotionQuality()!=JPH::EMotionQuality::Discrete)||
           (!b.IsStatic()&&b.GetMotionProperties()->GetMotionQuality()!=JPH::EMotionQuality::Discrete)){
            std::scoped_lock lock(contact_mutex_);contact_swept_=true;return;
        }
        ContactImpulseGeometry geometry{JPH::SubShapeIDPair(a.GetID(),manifold.mSubShapeID1,b.GetID(),manifold.mSubShapeID2),a.GetUserData(),b.GetUserData(),manifold.mWorldSpaceNormal,{}};
        geometry.friction=settings.mCombinedFriction;
        JPH::RVec3 friction_point=JPH::RVec3::sZero();
        for(JPH::uint i=0;i<manifold.mRelativeContactPointsOn1.size();++i)
            friction_point+=.5_r*(manifold.GetWorldSpaceContactPointOn1(i)+manifold.GetWorldSpaceContactPointOn2(i));
        friction_point/=JPH::Real(manifold.mRelativeContactPointsOn1.size());
        for(JPH::uint i=0;i<manifold.mRelativeContactPointsOn1.size();++i){
            const auto p1=manifold.GetWorldSpaceContactPointOn1(i),p2=manifold.GetWorldSpaceContactPointOn2(i);
            geometry.points.push_back(fromJoltPosition(.5_r*(p1+p2)));
            geometry.gaps.push_back(-double(JPH::Vec3(p1-p2).Dot(manifold.mWorldSpaceNormal)));
            const JPH::Vec3 delta=JPH::Vec3(.5_r*(p1+p2)-friction_point);
            geometry.radii.push_back(double((delta-delta.Dot(manifold.mWorldSpaceNormal)*manifold.mWorldSpaceNormal).Length()));
        }
        std::scoped_lock lock(contact_mutex_);
        if(contact_geometry_.size()>=65536){contact_overflow_=true;return;}
        contact_geometry_.push_back(std::move(geometry));
    }
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
            contactOfPart(state1->second, body1, manifold.mSubShapeID1),
            contactOfPart(state2->second, body2, manifold.mSubShapeID2));
        const double applied_friction = tangential_speed < 0.05
                                            ? combined.static_friction
                                            : combined.dynamic_friction;
        settings.mCombinedFriction = static_cast<float>(applied_friction);
        settings.mCombinedRestitution =
            restitution_model!=RigidContactRestitution::MaterialCombination?0.0F:static_cast<float>(combined.restitution);

        // A tool's point in the ground is held by its bite, not by the height
        // field: the height field is a surface and lets nothing in. The rest of
        // the tool meets the ground as it always has (suspendGroundContact).
        if (!ground_suspended_.empty() &&
            (id1 == kGroundPatchMatterId || id2 == kGroundPatchMatterId)) {
            const bool tool_is_1 = id2 == kGroundPatchMatterId;
            const auto point = ground_suspended_.find(tool_is_1 ? id1 : id2);
            if (point != ground_suspended_.end()) {
                const GroundSuspension &held = point->second;
                bool in_point = false;
                if (held.by_cell) {
                    const JPH::SubShapeID::Type cell =
                        (tool_is_1 ? manifold.mSubShapeID1 : manifold.mSubShapeID2).GetValue();
                    in_point = std::binary_search(held.cells.begin(), held.cells.end(), cell);
                } else {
                    const JPH::Body &tool = tool_is_1 ? body1 : body2;
                    in_point = inPointRegion(
                        held.region, fromJoltPosition(tool.GetCenterOfMassTransform()
                                                          .InversedRotationTranslation() *
                                                      contact_point));
                }
                if (in_point) {
                    settings.mIsSensor = true;
                    return;
                }
            }
        }

        // A round body's contacts are kept for its rolling resistance: which
        // manifold, which way its normal points and where it is. The solver's
        // impulse through each is read once the step is over.
        // A wheel -- a compound's round part -- is kept the same way, by
        // which part touched.
        const int wheel1 = body1.IsDynamic() ? wheelOf(state1->second, body1, manifold.mSubShapeID1) : -1;
        const int wheel2 = body2.IsDynamic() ? wheelOf(state2->second, body2, manifold.mSubShapeID2) : -1;
        // A body walking under its own controller is not a wheel: its grip is
        // that controller's, and a rolling couple on it was a drag on its walk.
        const bool round1 = ((state1->second.is_sphere && body1.IsDynamic()) || wheel1 >= 0) && !driven.contains(id1);
        const bool round2 = ((state2->second.is_sphere && body2.IsDynamic()) || wheel2 >= 0) && !driven.contains(id2);
        if (round1 || round2) {
            const JPH::SubShapeIDPair key(body1.GetID(), manifold.mSubShapeID1,
                                          body2.GetID(), manifold.mSubShapeID2);
            // Jolt's normal is the way body 2 moves out of body 1.
            const Vec3 normal = normalized(fromJoltVector(manifold.mWorldSpaceNormal));
            const Vec3 point = fromJoltPosition(contact_point);
            std::scoped_lock lock(rolling_mutex_);
            if (round1) {
                rolling_.push_back({key, body1.GetID(), body2.GetID(), id1, id2, -normal, point});
                rolling_.back().wheel = wheel1;
            }
            if (round2) {
                rolling_.push_back({key, body2.GetID(), body1.GetID(), id2, id1, normal, point});
                rolling_.back().wheel = wheel2;
            }
        }

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
        event.combined_restitution = restitution_model!=RigidContactRestitution::MaterialCombination?0.0:combined.restitution;
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
            (id1 == kSupportSurfaceMatterId || id2 == kSupportSurfaceMatterId ||
             id1 == kGroundPatchMatterId || id2 == kGroundPatchMatterId) &&
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
    // Written only between steps; read, never written, while one runs.
    const std::unordered_map<MatterBodyId, GroundSuspension> &ground_suspended_;
    std::mutex mutex_;
    std::vector<ImpactEvent> events_;
    std::mutex rolling_mutex_;
    std::vector<RollingContact> rolling_;
    std::mutex contact_mutex_;bool contact_overflow_{};
    std::vector<ContactImpulseGeometry> contact_geometry_;
    bool contact_swept_{};
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
    explicit Impl(int requested_workers=-1,RigidContactCapacity capacity={},RigidJobExecution execution=RigidJobExecution::ThreadPool) : impact_collector_(tick_, contact_states_,external_pairs_,ground_suspended_) {
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
        if(execution==RigidJobExecution::Inline){
            if(requested_workers!=0)throw std::invalid_argument("inline native jobs require zero workers");
            job_system_=std::make_unique<JPH::JobSystemSingleThreaded>(JPH::cMaxPhysicsJobs);
        }else job_system_ = std::make_unique<JPH::JobSystemThreadPool>(
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
            // A parked body is not in the broadphase: destroyed, not removed.
            for (const auto &[logical_id, body_id] : parked_) {
                (void)logical_id;
                if (!body_id.IsInvalid()) body_interface.DestroyBody(body_id);
            }
            if (!floor_id_.IsInvalid()) {
                body_interface.RemoveBody(floor_id_);
                body_interface.DestroyBody(floor_id_);
            }
            for (const GroundPatch &patch : ground_) {
                body_interface.RemoveBody(patch.body);
                body_interface.DestroyBody(patch.body);
            }
        }

        physics_.reset();
        job_system_.reset();
        temp_allocator_.reset();
    }

    // ---- rolling resistance (docs/rolling-resistance.md) ------------------
    //
    // Before a step, every round body that ended the last one touching
    // something is resisted at each contact by the couple M = c N r, against
    // its turning about axes in the contact plane: c the ball's own
    // coefficient plus the surface's, N the normal force the solver put
    // through that contact over the last step, r the radius. Jolt's own
    // friction then carries the couple into the ball's travel, which is what
    // slows a ball on the level at 5/7 c g.
    //
    // This replaces a version that acted only on the one flat support plane,
    // with N taken as m g n: a live world's bodies are all fragments, never
    // marked round, and the valley's ground is not a plane, so nothing in the
    // playground was ever resisted.
    void applyRollingResistance(double dt) {
        rolling_report_.clear();
        before_step_.clear();
        if (rolling_.empty()) return;
        std::vector<const RollingContact *> order;
        order.reserve(rolling_.size());
        for (const RollingContact &contact : rolling_) order.push_back(&contact);
        std::stable_sort(order.begin(), order.end(),
                         [](const RollingContact *a, const RollingContact *b) { return a->sphere < b->sphere; });
        std::vector<std::pair<JPH::BodyID, Vec3>> pushes;
        std::vector<JPH::BodyID> rolling_balls, not_at_rest;
        for (std::size_t first = 0; first < order.size();) {
            std::size_t last = first + 1;
            while (last < order.size() && order[last]->sphere == order[first]->sphere) ++last;
            const std::vector<const RollingContact *> group(
                order.begin() + static_cast<std::ptrdiff_t>(first),
                order.begin() + static_cast<std::ptrdiff_t>(last));
            if (group.front()->wheel >= 0) resistWheels(group, dt, pushes, rolling_balls, not_at_rest);
            else resistBall(group, dt, pushes, rolling_balls, not_at_rest);
            first = last;
        }
        JPH::BodyInterface &bodies = physics_->GetBodyInterface();
        for (const auto &[body, impulse] : pushes) bodies.AddAngularImpulse(body, toJolt(impulse));
        // Where a ball touches is not a point of the ball: it is wherever the
        // ball is lowest, whichever part of it is there. Jolt's body-pair cache
        // reuses last step's contact while two bodies have moved less than a
        // millimetre and turned less than two degrees, and it carries the
        // contact point round WITH the ball -- so a ball rolling slower than
        // about a quarter of a metre a second is pushed on at a point up to a
        // millimetre behind the one it rests on, a couple that drives it on
        // (N times the lag: 0.008 in coefficient on a 120 mm ball, more than an
        // iron ball's whole rolling resistance). Measured before this: a rubber
        // ball rolled 8% past v^2/2a and an iron one never stopped. So a rolling
        // ball's contacts are found afresh every step.
        for (const JPH::BodyID ball : rolling_balls) bodies.InvalidateContactCache(ball);
        // And a ball the law says is not at rest -- on a slope steeper than
        // atan(c), or rolling on the level -- is not frozen by the solver's
        // sleep rule (still for half a second under 3 cm/s): that stopped a
        // ball just over atan(c) 8 mm down a ramp it should have rolled down.
        for (const JPH::BodyID ball : not_at_rest) bodies.ResetSleepTimer(ball);
    }

    void measureContactImpulses(){
        contact_impulses_.clear();
        if(!impact_collector_.contact_impulses_enabled)return;
        auto frames=impact_collector_.takeContactGeometry();if(frames.empty())return;
        std::map<JPH::SubShapeIDPair,ContactImpulseGeometry> current;
        for(auto &frame:frames)current.try_emplace(frame.key,std::move(frame));
        auto &recorder=contact_recorder_;recorder.Reset();
        physics_->SaveState(recorder,JPH::EStateRecorderState::Contacts);
        if(recorder.IsFailed()||recorder.GetDataSize()>16U*1024U*1024U)throw std::runtime_error("cannot capture bounded native contact impulses");
        const bool parsed=readContactRecords(recorder.GetData(),[&](const RecordedContactManifold &record){
            const auto found=current.find(record.key);if(found==current.end())return;
            const auto &frame=found->second;
            if(frame.points.size()!=record.points.size()||frame.gaps.size()!=record.points.size()||frame.radii.size()!=record.points.size())throw std::runtime_error("native contact geometry/impulse point count differs");
            JoltWorld::ContactImpulseObservation out;out.a=frame.a;out.b=frame.b;
            out.combined_friction=frame.friction;
            out.normal_a_to_b=fromJoltVector(frame.normal);
            const auto tangent=frame.normal.GetNormalizedPerpendicular();
            out.friction_impulse_on_b_n_s=fromJoltVector(record.friction[0]*tangent+record.friction[1]*frame.normal.Cross(tangent));
            out.twist_impulse_on_b_n_m_s=fromJoltVector(record.twist*frame.normal);
            for(unsigned i=0;i<record.points.size();++i){
                out.points.push_back({frame.points[i],record.points[i].lambda,frame.gaps[i],frame.radii[i]});out.friction_point_world_m+=frame.points[i];
            }
            if(!out.points.empty())out.friction_point_world_m*=1./out.points.size();
            contact_impulses_.push_back(std::move(out));current.erase(found);
        });
        if(!parsed||!current.empty())throw std::runtime_error("native contact impulse cache does not match this discrete Update");
    }

    // After a step: the normal force the solver put through every contact of
    // a round body, for the couple the next step applies.
    void measureRolling(double dt) {
        std::vector<RollingContact> found = impact_collector_.takeRolling();
        rolling_.clear();
        if (found.empty()) return;
        // One entry per manifold and ball: a body fast enough for the swept
        // test can be reported by both the discrete and the swept pass, and
        // the two do not agree about where it touches. std::unique keeps the
        // first of each run, so the order has to be total or the scheduler
        // chooses the normal (steadiestRollingContactFirst).
        std::sort(found.begin(), found.end(), steadiestRollingContactFirst);
        found.erase(std::unique(found.begin(), found.end(),
                                [](const RollingContact &a, const RollingContact &b) {
                                    return a.sphere == b.sphere && a.key == b.key;
                                }),
                    found.end());
        std::vector<std::pair<JPH::SubShapeIDPair, double>> impulses;
        bool read = false;
        if (cache_readable_) {
            std::vector<JPH::BodyID> balls;
            balls.reserve(found.size());
            for (const RollingContact &contact : found) balls.push_back(contact.sphere_body);
            const RoundBodyContacts filter(std::move(balls));
            JPH::StateRecorderImpl recorder;
            physics_->SaveState(recorder, JPH::EStateRecorderState::Contacts, &filter);
            read = !recorder.IsFailed() && readContactImpulses(recorder.GetData(), impulses);
            if (!read) {
                cache_readable_ = false;
                std::cerr << "[Jolt] rolling resistance: the contact cache does not read as Jolt 5.6 "
                             "writes it; from now on N is each ball's own change of momentum\n";
            }
        }
        const JPH::BodyInterface &bodies = physics_->GetBodyInterface();
        for (RollingContact &contact : found) {
            contact.sphere_at_m = fromJoltPosition(bodies.GetCenterOfMassPosition(contact.sphere_body));
            if (read) {
                double impulse = 0.0;
                for (const auto &[key, total] : impulses)
                    if (key == contact.key) {
                        impulse = total;
                        break;
                    }
                contact.normal_force_n = std::max(0.0, impulse) / dt;
                contact.from_solver = true;
            } else if (const auto before = before_step_.find(contact.sphere);
                       before != before_step_.end()) {
                // What everything touching it gave the ball over the step, less
                // gravity and the pushes, along this contact's normal: exact for
                // a ball touching one thing, and blind to two things pressing
                // it from opposite sides.
                const Vec3 after = fromJoltVector(bodies.GetLinearVelocity(contact.sphere_body));
                const Vec3 given = before->second.mass * (after - before->second.v) -
                                   dt * (before->second.mass * gravity_m_s2_ + before->second.force);
                contact.normal_force_n = std::max(0.0, dot(given, contact.normal)) / dt;
            }
        }
        rolling_ = std::move(found);
    }

    struct BallState {
        Vec3 x{}, v{}, w{}, force{}, torque{};
        Quat q{};
        double mass{};
        Mat3 inverse_inertia{}, inertia{};
    };
    [[nodiscard]] bool readBall(JPH::BodyID id, BallState &out) const {
        JPH::BodyLockRead lock(physics_->GetBodyLockInterface(), id);
        if (!lock.Succeeded()) return false;
        const JPH::Body &body = lock.GetBody();
        // Asleep, it is at rest and there is nothing to resist; held, or
        // scenery, it is not free to roll.
        if (!body.IsDynamic() || !body.IsActive()) return false;
        const float inverse_mass = body.GetMotionProperties()->GetInverseMass();
        if (!(inverse_mass > 0.0F)) return false;
        out.x = fromJoltPosition(body.GetCenterOfMassPosition());
        const JPH::Quat turned = body.GetRotation();
        out.q = {static_cast<double>(turned.GetW()), static_cast<double>(turned.GetX()),
                 static_cast<double>(turned.GetY()), static_cast<double>(turned.GetZ())};
        out.v = fromJoltVector(body.GetLinearVelocity());
        out.w = fromJoltVector(body.GetAngularVelocity());
        out.force = fromJoltVector(body.GetAccumulatedForce());
        out.torque = fromJoltVector(body.GetAccumulatedTorque());
        out.mass = 1.0 / static_cast<double>(inverse_mass);
        const JPH::Mat44 inverse = body.GetInverseInertia();
        for (JPH::uint row = 0; row < 3; ++row)
            for (JPH::uint column = 0; column < 3; ++column)
                out.inverse_inertia.m[row][column] = static_cast<double>(inverse(row, column));
        const std::optional<Mat3> inertia = out.inverse_inertia.inverse(0.0);
        if (!inertia) return false;
        out.inertia = *inertia;
        return true;
    }
    struct TouchedState {
        bool found{}, moving{}, dynamic{};
        Vec3 w{};
        Mat3 inverse_inertia{};
    };
    [[nodiscard]] TouchedState readTouched(JPH::BodyID id) const {
        TouchedState out;
        JPH::BodyLockRead lock(physics_->GetBodyLockInterface(), id);
        if (!lock.Succeeded()) return out;
        const JPH::Body &body = lock.GetBody();
        out.found = true;
        out.moving = !body.IsStatic();
        out.dynamic = body.IsDynamic();
        if (out.moving) out.w = fromJoltVector(body.GetAngularVelocity());
        if (out.dynamic) {
            const JPH::Mat44 inverse = body.GetInverseInertia();
            for (JPH::uint row = 0; row < 3; ++row)
                for (JPH::uint column = 0; column < 3; ++column)
                    out.inverse_inertia.m[row][column] = static_cast<double>(inverse(row, column));
        }
        return out;
    }
    // The surface's own share of the coefficient: the ground's, by what it is
    // made of where the ball touches it; anything else, by its material.
    [[nodiscard]] double surfaceRolling(const RollingContact &contact) const {
        if (contact.other == kGroundPatchMatterId && ground_rolling_at_)
            return ground_rolling_at_(contact.point_world_m.x, contact.point_world_m.z);
        const auto found = contact_states_.find(contact.other);
        return found == contact_states_.end() ? 0.0 : found->second.contact.rolling_resistance;
    }

    // One ball and everything it touched in the last step.
    void resistBall(const std::vector<const RollingContact *> &contacts, double dt,
                    std::vector<std::pair<JPH::BodyID, Vec3>> &pushes,
                    std::vector<JPH::BodyID> &rolling_balls, std::vector<JPH::BodyID> &not_at_rest) {
        const RollingContact &lead = *contacts.front();
        const auto state = contact_states_.find(lead.sphere);
        if (state == contact_states_.end() || !state->second.is_sphere ||
            !(state->second.radius_m > 0.0))
            return;
        BallState ball;
        if (!readBall(lead.sphere_body, ball)) return;
        rolling_balls.push_back(lead.sphere_body);
        if (!cache_readable_) before_step_[lead.sphere] = {ball.v, ball.force, ball.mass};
        // Moved by the host since the step ended: it is not where it touched.
        if (length(ball.x - lead.sphere_at_m) > kRollingMovedM) return;
        const double r = state->second.radius_m;
        const double own = state->second.contact.rolling_resistance;
        std::vector<double> coefficient(contacts.size(), 0.0);
        std::vector<TouchedState> touched(contacts.size());
        std::vector<bool> fixed(contacts.size(), false);
        // What it rests on that does not move -- the floor, the ground,
        // anchored scenery -- is taken together as one support: its normal the
        // force-weighted mean of theirs, its limit the sum of theirs.
        Vec3 weighted{};
        double limit = 0.0;
        for (std::size_t k = 0; k < contacts.size(); ++k) {
            const RollingContact &contact = *contacts[k];
            coefficient[k] = std::clamp(own + surfaceRolling(contact), 0.0, 1.0);
            touched[k] = readTouched(contact.other_body);
            if (!touched[k].found || touched[k].moving || !(contact.normal_force_n > 0.0)) continue;
            fixed[k] = true;
            weighted += contact.normal_force_n * contact.normal;
            limit += coefficient[k] * contact.normal_force_n * r;
        }
        Vec3 impulse{};
        double applied = 0.0;
        double work = 0.0;
        bool held = false;
        bool supported = false;
        for (const bool on_fixed : fixed) supported = supported || on_fixed;
        if (supported) {
            const Vec3 n = normalized(weighted, lead.normal);
            const double most = limit * dt;
            const Vec3 arm = r * n;                          // from the contact to the centre
            const Vec3 slip = ball.v - cross(ball.w, arm);   // the ball's surface at the contact
            if (length(slip - dot(slip, n) * n) < kRollingSlipMS) {
                // Rolling, or at rest. What turns a ball about the point it
                // touches is its own angular momentum about that point and
                // what gravity and any push add to it over the step -- the
                // contact's forces act AT the point and add nothing. Stop all
                // of that if the couple can: that is a ball staying where it
                // was put on a slope gentler than atan(c). Otherwise take off
                // all the couple can.
                const Vec3 about = ball.inertia * ball.w + cross(arm, ball.mass * ball.v);
                const Vec3 turning = ball.torque + cross(arm, ball.mass * gravity_m_s2_ + ball.force);
                const Vec3 would = about + dt * turning;
                const Vec3 rolling = would - dot(would, n) * n;
                const double need = length(rolling);
                // Turning slower than a ten-thousandth of a radian a second
                // about the point it touches is at rest.
                const double rest = 1.0e-4 * (ball.mass * r * r +
                                              (ball.inertia.m[0][0] + ball.inertia.m[1][1] +
                                               ball.inertia.m[2][2]) / 3.0);
                held = need <= std::max(most, rest);
                if (need > 1.0e-15 && most > 0.0) {
                    applied = std::min(most, need);
                    impulse -= (applied / need) * rolling;
                    // Its work against the rolling it resisted: the couple
                    // times the mean rate over the step, about the point the
                    // ball turns on. Holding a ball still does none.
                    const Vec3 axis = rolling / need;
                    const double about_point = dot(axis, ball.inertia * axis) + ball.mass * r * r;
                    const Vec3 had = about - dot(about, n) * n;
                    const double before = std::max(0.0, dot(had, axis)) / about_point;
                    const double after = (need - applied) / about_point;
                    work = applied * 0.5 * (before + after);
                }
            } else {
                // Sliding. The couple still resists the turning it has, and
                // never turns it the other way; friction does the rest.
                const Vec3 spin = ball.w - dot(ball.w, n) * n;
                const double rate = length(spin);
                if (rate > 1.0e-12 && most > 0.0) {
                    const Vec3 axis = spin / rate;
                    const double give = dot(axis, ball.inverse_inertia * axis);
                    if (give > 0.0) {
                        applied = std::min(most, rate / give);
                        impulse -= applied * axis;
                        work = applied * 0.5 * (rate + std::max(0.0, rate - applied * give));
                    }
                }
            }
            if (!held) not_at_rest.push_back(lead.sphere_body);
        }
        // Something that moves under it: the couple acts on both, against how
        // the two turn relative to each other, and turns neither the other way.
        std::vector<double> applied_moving(contacts.size(), 0.0);
        std::vector<double> work_moving(contacts.size(), 0.0);
        for (std::size_t k = 0; k < contacts.size(); ++k) {
            const RollingContact &contact = *contacts[k];
            if (!touched[k].found || !touched[k].moving || !(contact.normal_force_n > 0.0)) continue;
            const Vec3 relative = ball.w - touched[k].w;
            const Vec3 spin = relative - dot(relative, contact.normal) * contact.normal;
            const double rate = length(spin);
            if (!(rate > 1.0e-12)) continue;
            const Vec3 axis = spin / rate;
            double give = dot(axis, ball.inverse_inertia * axis);
            if (touched[k].dynamic) give += dot(axis, touched[k].inverse_inertia * axis);
            if (!(give > 0.0)) continue;
            applied_moving[k] = std::min(coefficient[k] * contact.normal_force_n * r * dt, rate / give);
            impulse -= applied_moving[k] * axis;
            work_moving[k] = applied_moving[k] * 0.5 * (rate + std::max(0.0, rate - applied_moving[k] * give));
            if (touched[k].dynamic) pushes.emplace_back(contact.other_body, applied_moving[k] * axis);
        }
        if (lengthSquared(impulse) > 0.0) pushes.emplace_back(lead.sphere_body, impulse);
        for (std::size_t k = 0; k < contacts.size(); ++k) {
            const RollingContact &contact = *contacts[k];
            JoltWorld::RollingContactReport said;
            said.sphere = contact.sphere;
            said.other = contact.other;
            said.normal_world = contact.normal;
            said.point_world_m = contact.point_world_m;
            said.normal_force_n = contact.normal_force_n;
            said.from_solver = contact.from_solver;
            said.coefficient = coefficient[k];
            said.limit_n_m = coefficient[k] * contact.normal_force_n * r;
            said.applied_n_m = fixed[k] ? (limit > 0.0 ? (applied / dt) * (said.limit_n_m / limit) : 0.0)
                                        : applied_moving[k] / dt;
            said.held = fixed[k] && held;
            said.loss_j = fixed[k] ? (limit > 0.0 ? work * (said.limit_n_m / limit) : 0.0) : work_moving[k];
            rolling_report_.push_back(said);
        }
        double taken = work;
        for (const double moving_work : work_moving) taken += moving_work;
        rolling_loss_j_ += taken;
        rolling_loss_of_[lead.sphere] += taken;
    }

    // One body's round parts -- a wheelset's two wheels -- and what each
    // touched in the last step.
    //
    // A wheel turns on its axle, not every way as a ball does, so its couple
    // acts about its own axis only: at most c N r, against how it turns on
    // what it touches, and never turning it the other way. c is its own
    // material's share and the surface's, as for a ball.
    //
    // What it takes to stop it is not the wheel's own spin alone. A wheel
    // carries its share of a load -- N/g of mass on the level -- and stopping
    // the wheel stops that rolling too: so "enough to stop it" is its own
    // inertia about the axle plus that mass at its radius, times how fast it
    // turns. Capped at the wheel's spin alone, a light wheel under a heavy cart
    // could never slow it by more than its own few grams; capped this way the
    // couple holds a cart on a slope gentler than atan(c) and lets it roll off
    // a steeper one -- which is what c means.
    void resistWheels(const std::vector<const RollingContact *> &contacts, double dt,
                      std::vector<std::pair<JPH::BodyID, Vec3>> &pushes,
                      std::vector<JPH::BodyID> &rolling_bodies, std::vector<JPH::BodyID> &not_at_rest) {
        const RollingContact &lead = *contacts.front();
        const auto state = contact_states_.find(lead.sphere);
        if (state == contact_states_.end() || state->second.wheels.empty()) return;
        BallState body;
        if (!readBall(lead.sphere_body, body)) return;
        rolling_bodies.push_back(lead.sphere_body);
        if (!cache_readable_) before_step_[lead.sphere] = {body.v, body.force, body.mass};
        // Moved by the host since the step ended: it is not where it touched.
        if (length(body.x - lead.sphere_at_m) > kRollingMovedM) return;
        const double g = length(gravity_m_s2_);
        Vec3 impulse{};
        bool rolling = false;
        double taken = 0.0;
        for (const RollingContact *each : contacts) {
            const RollingContact &contact = *each;
            if (contact.wheel < 0 || static_cast<std::size_t>(contact.wheel) >= state->second.wheels.size()) continue;
            const BodyContactState::Wheel &wheel = state->second.wheels[static_cast<std::size_t>(contact.wheel)];
            const TouchedState touched = readTouched(contact.other_body);
            JoltWorld::RollingContactReport said;
            said.sphere = contact.sphere;
            said.other = contact.other;
            said.normal_world = contact.normal;
            said.point_world_m = contact.point_world_m;
            said.normal_force_n = contact.normal_force_n;
            said.from_solver = contact.from_solver;
            const double c = std::clamp(wheel.own_rolling + surfaceRolling(contact), 0.0, 1.0);
            said.coefficient = c;
            said.limit_n_m = c * contact.normal_force_n * wheel.radius_m;
            if (touched.found && contact.normal_force_n > 0.0) {
                const Vec3 axis = normalized(body.q.rotate(wheel.axis_local), Vec3{0.0, 1.0, 0.0});
                const double spin = dot(body.w - (touched.moving ? touched.w : Vec3{}), axis);
                const double carried = dot(axis, body.inertia * axis) +
                                       (g > 0.0 ? contact.normal_force_n / g : 0.0) * wheel.radius_m * wheel.radius_m;
                const double most = said.limit_n_m * dt;
                const double stop = carried * std::abs(spin);
                const double applied = std::min(most, stop);
                if (applied > 0.0) {
                    const Vec3 against = (spin > 0.0 ? -applied : applied) * axis;
                    impulse += against;
                    if (touched.dynamic) pushes.emplace_back(contact.other_body, -1.0 * against);
                    said.applied_n_m = applied / dt;
                    // Its work against the turning it resisted, at the mean
                    // rate over the step.
                    const double after = carried > 0.0 ? std::max(0.0, std::abs(spin) - applied / carried) : 0.0;
                    said.loss_j = applied * 0.5 * (std::abs(spin) + after);
                    taken += said.loss_j;
                }
                said.held = stop <= most;
                rolling = rolling || !said.held;
            }
            rolling_report_.push_back(said);
        }
        if (lengthSquared(impulse) > 0.0) pushes.emplace_back(lead.sphere_body, impulse);
        if (rolling) not_at_rest.push_back(lead.sphere_body);
        rolling_loss_j_ += taken;
        rolling_loss_of_[lead.sphere] += taken;
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
    bool external_fixed_trial_{};
    void requireFixedContactMutable() const {
        if ((trial_depth_||spring_trial_depth_) &&
            !(external_fixed_trial_&&trial_depth_==1&&spring_trial_depth_==0))
            throw std::logic_error("fixed point contact requires a paired native/target trial");
    }
    unsigned spring_trial_depth_{};
    BroadPhaseLayerInterface broad_phase_interface_;
    ObjectVsBroadPhaseLayerFilter object_vs_broad_phase_filter_;
    ObjectLayerPairFilter object_pair_filter_;
    std::unique_ptr<JPH::TempAllocatorImpl> temp_allocator_;
    std::unique_ptr<JPH::JobSystem> job_system_;
    std::unique_ptr<JPH::PhysicsSystem> physics_;
    std::unordered_map<MatterBodyId, BodyContactState> contact_states_;
    std::set<std::pair<MatterBodyId,MatterBodyId>> external_pairs_;
    // Tools whose point is in the ground, and where on each the point is
    // (suspendGroundContact). Before the collector, which holds a reference.
    std::unordered_map<MatterBodyId, GroundSuspension> ground_suspended_;
    // Bodies that collide as their cells (setCollisionCells): the cell size,
    // and each cell's centre in the body's frame with the sub-shape id Jolt
    // gives it -- read back from the compound, which orders its children as
    // it likes.
    struct CellShape {
        Vec3 centre{};
        JPH::SubShapeID::Type id{};
    };
    std::unordered_map<MatterBodyId, std::pair<double, std::vector<CellShape>>> cell_shapes_;
    std::atomic<std::uint64_t> tick_{0};
    const std::shared_ptr<const int> contact_plan_identity_{std::make_shared<const int>(0)};
    ImpactCollector impact_collector_;
    std::vector<JoltWorld::ContactImpulseObservation> contact_impulses_;
    Vec3 observed_gravity_impulse_{};
    bool force_phase_enabled_{},centered_integration_{};
    std::vector<JoltWorld::ForcePhaseObservation> force_phase_;
    std::unordered_map<JPH::uint32,std::size_t> force_phase_slot_;
    static void observeForcePhase(void *context,const JPH::Body &body,JPH::Vec3Arg v,
        JPH::Vec3Arg w,JPH::Vec3Arg gyro,JPH::Vec3Arg gravity_delta){
        auto &self=*static_cast<Impl *>(context);
        const auto found=self.force_phase_slot_.find(body.GetID().GetIndexAndSequenceNumber());
        if(found==self.force_phase_slot_.end())return;
        auto &out=self.force_phase_[found->second];
        out.before.motion.linear_velocity_m_s=fromJoltVector(v);
        out.before.motion.angular_velocity_rad_s=fromJoltVector(w);
        out.spin_after_gyro_rad_s=fromJoltVector(gyro);
        out.velocity_after_forces_m_s=fromJoltVector(body.GetLinearVelocity());
        out.spin_after_forces_rad_s=fromJoltVector(body.GetAngularVelocity());
        out.gravity_impulse_n_s=fromJoltVector(gravity_delta)/body.GetMotionProperties()->GetInverseMass();
        out.force_scheduled=true;
    }
    static void observeLimitPhase(void *context,const JPH::Body &body,JPH::Vec3Arg v,JPH::Vec3Arg w){
        auto &self=*static_cast<Impl *>(context);
        const auto found=self.force_phase_slot_.find(body.GetID().GetIndexAndSequenceNumber());
        if(found==self.force_phase_slot_.end())return;
        auto &out=self.force_phase_[found->second];
        out.velocity_after_solver_m_s=fromJoltVector(v);out.spin_after_solver_rad_s=fromJoltVector(w);
        out.velocity_after_limit_m_s=fromJoltVector(body.GetLinearVelocity());
        out.spin_after_limit_rad_s=fromJoltVector(body.GetAngularVelocity());out.integration_scheduled=true;
    }
    static JPH::Vec3 centeredMotion(void *context,const JPH::Body &body,bool angular){
        auto &self=*static_cast<Impl *>(context);
        const auto found=self.force_phase_slot_.find(body.GetID().GetIndexAndSequenceNumber());
        if(found==self.force_phase_slot_.end())throw std::runtime_error("centered integration phase missing");
        const auto &before=self.force_phase_[found->second].before.motion;
        return .5F*(toJolt(angular?before.angular_velocity_rad_s:before.linear_velocity_m_s)+(angular?body.GetAngularVelocity():body.GetLinearVelocity()));
    }
    std::uint64_t contact_plan_epoch_{};
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
        // A one-way fixing is a SixDOF constraint rather than a fixed one, and
        // reports its load along its own axes (addFixing, jointLoad).
        bool one_way{false};
        bool log_face{false};
    };
    // How long the last step was. Only jointTension() needs it: Jolt reports a
    // constraint's IMPULSE over the step, and an impulse divided by the step it
    // was applied over is the force -- which is what anybody asking how hard a
    // rope is pulling means.
    double last_dt_s{0.0};
    std::unordered_map<unsigned,Joint> joints_;
    // What each gear's teeth can carry, and the ones that gave way in the last
    // step. A gear that strips is gone: its coupling is removed, and the two
    // wheels turn on their own pins from then on, which is what a drive with
    // its teeth off does.
    std::unordered_map<unsigned,double> gear_strength_;
    std::vector<unsigned> stripped_gears_;
    unsigned next_joint_{1};
    std::unordered_map<MatterBodyId, JPH::BodyID> bodies_;
    // Bodies set aside (park): out of the broadphase and out of bodies_, not
    // destroyed, so each comes back as the body it was (unpark).
    std::unordered_map<MatterBodyId, JPH::BodyID> parked_;
    RigidContactDiagnostics contact_diagnostics_;
    RigidExecutionProfile execution_profile_;
    BoundedStateRecorder contact_recorder_;
    // Keep distinct storage at every permitted depth. Rejected and throwing
    // nested trials cannot overwrite their parent's authoritative snapshot.
    std::array<std::unique_ptr<BoundedStateRecorder>,16> trial_recorders_;
    std::optional<RigidSurfaceDescription> support_surface_;
    Vec3 gravity_m_s2_{0.0, -9.81, 0.0};
    // Patches of height-field ground, in the order they were added.
    struct GroundPatch {
        JPH::BodyID body;
        unsigned count{};
        double spacing{}, origin_x{}, origin_z{};
    };
    std::vector<GroundPatch> ground_;
    // Rolling resistance: the ground's own coefficient by place; the contacts
    // of round bodies the last step found, each with the solver's normal
    // force; what the couple did with them; and each ball's velocity and push
    // just before the step, for the momentum estimate that stands in if
    // Jolt's contact cache stops reading.
    std::function<double(double, double)> ground_rolling_at_;
    std::vector<RollingContact> rolling_;
    std::vector<JoltWorld::RollingContactReport> rolling_report_;
    struct BeforeStep {
        Vec3 v{};
        Vec3 force{};
        double mass{};
    };
    std::unordered_map<MatterBodyId, BeforeStep> before_step_;
    bool cache_readable_{true};
    // What rolling resistance has taken out of the motion, in all and by body.
    double rolling_loss_j_{};
    std::unordered_map<MatterBodyId, double> rolling_loss_of_;
    // SaveState omits constraint configuration, and step may strip gears.
    // Keep the exact native order and strong refs before any tentative step.
    struct TrialConfiguration {
        JPH::Constraints order;
        std::unordered_map<unsigned,Joint> joints;
        std::unordered_map<unsigned,double> gears;
        std::vector<unsigned> stripped;
        struct Link {JPH::Ref<JPH::DistanceConstraint> constraint;float minimum,maximum;};
        std::vector<Link> links;
        double dt{};
        std::unordered_map<MatterBodyId,BeforeStep> before;
        bool cache_readable{};
        unsigned manifolds{},points{},speculative{};
        std::vector<JoltWorld::ContactImpulseObservation> contact_impulses;
        Vec3 gravity_impulse{};
        std::vector<JoltWorld::ForcePhaseObservation> force_phase;
        std::unordered_map<JPH::uint32,std::size_t> force_phase_slot;
    };
    TrialConfiguration captureTrialConfiguration() const {
        TrialConfiguration out{physics_->GetConstraints(),joints_,gear_strength_,stripped_gears_,{},last_dt_s,before_step_,cache_readable_};
        out.manifolds=impact_collector_.manifolds.load(std::memory_order_relaxed);
        out.points=impact_collector_.points.load(std::memory_order_relaxed);
        out.speculative=impact_collector_.speculative_manifolds.load(std::memory_order_relaxed);
        out.contact_impulses=contact_impulses_;
        out.gravity_impulse=observed_gravity_impulse_;
        out.force_phase=force_phase_;
        out.force_phase_slot=force_phase_slot_;
        for (const auto &[id,joint]:joints_) {
            (void)id;
            if (joint.kind!=JointKind::Link) continue;
            auto *link=static_cast<JPH::DistanceConstraint *>(joint.constraint.GetPtr());
            out.links.push_back({link,link->GetMinDistance(),link->GetMaxDistance()});
        }
        return out;
    }
    void restoreTrialConfiguration(TrialConfiguration &saved) {
        const auto current=physics_->GetConstraints();
        for (const auto &constraint:current) physics_->RemoveConstraint(constraint.GetPtr());
        for (const auto &constraint:saved.order) physics_->AddConstraint(constraint.GetPtr());
        joints_=std::move(saved.joints);gear_strength_=std::move(saved.gears);stripped_gears_=std::move(saved.stripped);
        for (const auto &link:saved.links) link.constraint->SetDistance(link.minimum,link.maximum);
        last_dt_s=saved.dt;before_step_=std::move(saved.before);cache_readable_=saved.cache_readable;
        impact_collector_.manifolds.store(saved.manifolds,std::memory_order_relaxed);
        impact_collector_.points.store(saved.points,std::memory_order_relaxed);
        impact_collector_.speculative_manifolds.store(saved.speculative,std::memory_order_relaxed);
        impact_collector_.clearContactGeometry();contact_impulses_=std::move(saved.contact_impulses);
        observed_gravity_impulse_=saved.gravity_impulse;
        force_phase_=std::move(saved.force_phase);
        force_phase_slot_=std::move(saved.force_phase_slot);
    }
};

namespace {
JPH::RefConst<JPH::Shape> groundTriangleShape(const std::vector<std::array<Vec3,3>> &triangles) {
    if(triangles.empty() || triangles.size()>65536)
        throw std::invalid_argument("ground mesh requires 1..65536 triangles per patch");
    JPH::TriangleList mesh;
    for(const auto &t:triangles) {
        for(const auto &v:t) if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z)||length(v)>10000)
            throw std::invalid_argument("ground vertex exceeds finite 10000 m bounds");
        if(length(cross(t[1]-t[0],t[2]-t[0]))<1e-10)
            throw std::invalid_argument("degenerate ground triangle");
        mesh.emplace_back(JPH::Float3(float(t[0].x),float(t[0].y),float(t[0].z)),
            JPH::Float3(float(t[1].x),float(t[1].y),float(t[1].z)),
            JPH::Float3(float(t[2].x),float(t[2].y),float(t[2].z)));
    }
    const auto made=JPH::MeshShapeSettings(mesh).Create();
    if(made.HasError())throw std::runtime_error("Jolt ground mesh: "+std::string(made.GetError().c_str()));
    return made.Get();
}
// A patch of ground as a Jolt height field: absolute heights, holes where a
// height is not finite, compressed to within `max_error`.
JPH::RefConst<JPH::Shape> groundShape(const std::vector<float> &heights, unsigned count,
                                      double spacing, double origin_x, double origin_z,
                                      double max_error) {
    if (count < 4 || heights.size() != static_cast<std::size_t>(count) * count || !(spacing > 0.0))
        throw std::invalid_argument("a ground patch needs count x count heights, count >= 4, and a spacing");
    std::vector<float> samples(heights);
    for (float &h : samples)
        if (!std::isfinite(h)) h = JPH::HeightFieldShapeConstants::cNoCollisionValue;
    JPH::HeightFieldShapeSettings settings(samples.data(),
                                           JPH::Vec3(static_cast<float>(origin_x), 0.0F,
                                                     static_cast<float>(origin_z)),
                                           JPH::Vec3(static_cast<float>(spacing), 1.0F,
                                                     static_cast<float>(spacing)),
                                           count);
    settings.mBlockSize = (count % 4 == 0 && count / 4 >= 2) ? 4 : 2;
    settings.mBitsPerSample = std::max<JPH::uint32>(
        1, settings.CalculateBitsPerSampleForError(static_cast<float>(max_error)));
    const JPH::ShapeSettings::ShapeResult made = settings.Create();
    if (made.HasError()) {
        const JPH::String &error = made.GetError();
        throw std::runtime_error("Jolt could not build a ground patch: " + std::string(error.begin(), error.end()));
    }
    return made.Get();
}
} // namespace

JoltWorld::JoltWorld() : impl_(std::make_unique<Impl>()) {}
JoltWorld::JoltWorld(unsigned workers) {
    if(workers>64)throw std::invalid_argument("worker thread budget exceeded");
    impl_=std::make_unique<Impl>(int(workers));
}
JoltWorld::JoltWorld(unsigned workers,RigidContactCapacity capacity,RigidJobExecution execution) {
    if(workers>64)throw std::invalid_argument("worker thread budget exceeded");
    impl_=std::make_unique<Impl>(int(workers),capacity,execution);
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
    // The catalogue's concrete -- the same friction, damping and stiffness this
    // floor always had -- so it also rolls a ball the way concrete does
    // everywhere else in the engine (docs/rolling-resistance.md).
    MaterialDefinition concrete = makeReferenceMaterial(MaterialPreset::Concrete, 0);
    concrete.name = "default_concrete_surface";
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
    JPH::BodyCreationSettings settings(new JPH::BoxShape(toJolt(d/2),sweepRadius(toJolt(d/2))),
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
    bool mixed=false;
    for(std::size_t index=0;index<d.parts.size();++index){const auto &p=d.parts[index];
        if(!finite(p.center_local_m))throw std::invalid_argument("invalid compound point");
        JPH::Ref<JPH::Shape> shape=compoundPartShape(p);
        // Which part this is, for a contact to find: its index + 1, zero being
        // "no part" in Jolt's own default.
        shape->SetUserData(JPH::uint64(index+1));
        compound.AddShape(toJolt(p.center_local_m),toJoltRotation(p.rotation_local),shape.GetPtr());
        mixed=mixed||p.material.has_value();
    }
    auto built=compound.Create();if(built.HasError())throw std::invalid_argument(built.GetError().c_str());
    JPH::RefConst<JPH::Shape> inner=built.Get();
    // The body's origin is its centre of mass as the caller measured it from
    // each part's own material. Jolt's shape would put it at the middle of the
    // parts' volume, as if every part were the same stuff; this moves Jolt's
    // mark to the caller's without moving any geometry.
    JPH::RefConst<JPH::Shape> centered=new JPH::OffsetCenterOfMassShape(inner.GetPtr(),-inner->GetCenterOfMass());
    const auto contact=compileContactMaterial(d.material);
    std::vector<CompiledContactMaterial> part_contacts;
    if(mixed)for(const auto &p:d.parts)part_contacts.push_back(p.material?compileContactMaterial(*p.material):contact);
    std::vector<BodyContactState::Wheel> wheels;
    for(std::size_t index=0;index<d.parts.size();++index){const auto &p=d.parts[index];
        if(p.geometry.kind!=PrimitiveKind::Cylinder)continue;
        const auto own=p.material?compileContactMaterial(*p.material):contact;
        wheels.push_back({JPH::uint64(index+1),normalized(p.rotation_local.rotate({0.0,1.0,0.0}),Vec3{0.0,1.0,0.0}),
                          p.geometry.dimensions_m.x/2,own.rolling_resistance});
    }
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
        impl_->bodies_.emplace(d.body_id,id);
        impl_->contact_states_.emplace(d.body_id,BodyContactState{contact,0,0,false,d.mass_kg,{},std::move(part_contacts),std::move(wheels)});
    }catch(...){impl_->bodies_.erase(d.body_id);impl_->contact_states_.erase(d.body_id);bodies.RemoveBody(id);bodies.DestroyBody(id);throw;}
}

bool JoltWorld::partsWithin(const RigidCompoundPart &a,const RigidCompoundPart &b,double tolerance_m){
    if(!std::isfinite(tolerance_m)||tolerance_m<0||tolerance_m>0.1)throw std::invalid_argument("part tolerance must be 0..100 mm");
    ensureJoltRuntime();
    const JPH::Ref<JPH::Shape> one=compoundPartShape(a),two=compoundPartShape(b);
    JPH::CollideShapeSettings settings;
    settings.mMaxSeparationDistance=float(tolerance_m);
    settings.mActiveEdgeMode=JPH::EActiveEdgeMode::CollideWithAll;
    settings.mBackFaceMode=JPH::EBackFaceMode::CollideWithBackFaces;
    JPH::AnyHitCollisionCollector<JPH::CollideShapeCollector> hit;
    JPH::CollisionDispatch::sCollideShapeVsShape(one.GetPtr(),two.GetPtr(),JPH::Vec3::sReplicate(1.0F),JPH::Vec3::sReplicate(1.0F),
        JPH::Mat44::sRotationTranslation(toJoltRotation(a.rotation_local),toJolt(a.center_local_m)),
        JPH::Mat44::sRotationTranslation(toJoltRotation(b.rotation_local),toJolt(b.center_local_m)),
        JPH::SubShapeIDCreator(),JPH::SubShapeIDCreator(),settings,hit);
    return hit.HadHit();
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
void JoltWorld::setExecutionProfilingEnabled(bool enabled){
    if(impl_->trial_depth_||impl_->spring_trial_depth_||impl_->external_fixed_trial_)
        throw std::logic_error("execution profile configuration cannot change within a trial");
    impl_->execution_profile_={};impl_->execution_profile_.enabled=enabled;
}
RigidExecutionProfile JoltWorld::executionProfile() const{return impl_->execution_profile_;}
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
    if (!std::isfinite(d.at_rad) || std::abs(d.at_rad) > kPi + 1e-6)
        throw std::invalid_argument("a hinge's reading as it is made is an angle from -pi to pi");
    // Jolt measures the angle between the two bodies' normal axes about the
    // pin, zero as the constraint is made when both are the same. The second
    // body's is turned by the reading it is to have (HingeDescription::at_rad):
    // made that way, it reads that angle now, and its limits are about the
    // same zero the first one's were.
    const Vec3 normal_b = d.at_rad == 0.0 ? normal
                                          : std::cos(d.at_rad) * normal + std::sin(d.at_rad) * cross(axis, normal);

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
    settings.mNormalAxis1 = toJolt(normal);
    settings.mNormalAxis2 = toJolt(normal_b);
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
    if (held.kind == JointKind::Drum) {
        // A drum's rope reads as how much of it is off the drum: the most the
        // span from the drum to the load may be. drumState says the rest.
        const auto *rope = static_cast<const DrumRopeConstraint *>(held.constraint.GetPtr());
        out.at = rope->out();
        out.lower = 0.0;
        out.upper = rope->length();
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
    if (held.kind == JointKind::Kerf || held.kind == JointKind::GroundBite) {
        // An edge in a cut has no one position to report. What it has is
        // what its friction took, and that is kerfImpulse's business -- and a
        // point in the ground likewise, groundBiteImpulse's.
        out.at = 0.0;
        out.lower = 0.0;
        out.upper = 0.0;
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

void JoltWorld::driveHinge(unsigned joint, double target_rad_s, double torque_limit_n_m) {
    impl_->requireConfigurationMutable();
    if (!std::isfinite(target_rad_s) || !(torque_limit_n_m >= 0.0) || !std::isfinite(torque_limit_n_m))
        throw std::invalid_argument("a pin is driven at a finite speed with a torque of zero or more");
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Hinge) return;
    auto *pin = static_cast<JPH::HingeConstraint *>(found->second.constraint.GetPtr());
    if (torque_limit_n_m == 0.0) {
        pin->SetMotorState(JPH::EMotorState::Off);
        return;
    }
    pin->GetMotorSettings().SetTorqueLimit(static_cast<float>(torque_limit_n_m));
    pin->SetTargetAngularVelocity(static_cast<float>(target_rad_s));
    pin->SetMotorState(JPH::EMotorState::Velocity);
    // A body asleep does not feel a motor any more than it feels a push.
    wake(found->second.a);
    wake(found->second.b);
}

void JoltWorld::coastHinge(unsigned joint) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Hinge) return;
    static_cast<JPH::HingeConstraint *>(found->second.constraint.GetPtr())->SetMotorState(JPH::EMotorState::Off);
}

double JoltWorld::hingeMotorImpulse(unsigned joint) const {
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Hinge) return 0.0;
    return static_cast<double>(
        static_cast<const JPH::HingeConstraint *>(found->second.constraint.GetPtr())->GetTotalLambdaMotor());
}

double JoltWorld::hingeRate(unsigned joint) const {
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Hinge) return 0.0;
    const auto *pin = static_cast<const JPH::HingeConstraint *>(found->second.constraint.GetPtr());
    auto &bodies = impl_->physics_->GetBodyInterface();
    const JPH::BodyID one = impl_->bodies_.at(found->second.a);
    const JPH::BodyID two = impl_->bodies_.at(found->second.b);
    // Body 1's axis, carried into the world by body 1's pose: the axis Jolt's
    // motor part acts about (HingeConstraint::CalculateA1AndTheta).
    const JPH::Vec3 axis = bodies.GetRotation(one) * pin->GetLocalSpaceHingeAxis1();
    return static_cast<double>((bodies.GetAngularVelocity(two) - bodies.GetAngularVelocity(one)).Dot(axis));
}

double JoltWorld::inertiaAbout(MatterBodyId body_id, const Vec3 &axis_world) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    const double reach = std::sqrt(axis_world.x * axis_world.x + axis_world.y * axis_world.y +
                                   axis_world.z * axis_world.z);
    if (!(reach > 1e-12)) throw std::invalid_argument("an axis needs a direction");
    // A body that does not move -- anchored scenery is static -- has no motion
    // properties, and Jolt's GetInverseInertia reads them unchecked in Release:
    // asked about the post a hoist stands on, the process died (found through
    // the C API, where it showed as a hang). It is as hard to turn as anything
    // can be.
    {
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(), found->second);
        if (!lock.Succeeded() || !lock.GetBody().IsDynamic()) return HUGE_VAL;
    }
    auto &bodies = impl_->physics_->GetBodyInterface();
    // The world-frame inverse inertia, inverted back. A body that does not
    // turn at all has none to invert.
    const JPH::Mat44 inverse = bodies.GetInverseInertia(found->second);
    if (!(std::abs(inverse.GetDeterminant3x3()) > 1e-30F)) return HUGE_VAL;
    const JPH::Mat44 inertia = inverse.Inversed3x3();
    const JPH::Vec3 n = toJolt(Vec3{axis_world.x / reach, axis_world.y / reach, axis_world.z / reach});
    return static_cast<double>(n.Dot(inertia.Multiply3x3(n)));
}

void JoltWorld::addForce(MatterBodyId body_id, const Vec3 &force_n, const Vec3 &at_world_m) {
    if (!std::isfinite(force_n.x + force_n.y + force_n.z) || !std::isfinite(at_world_m.x + at_world_m.y + at_world_m.z))
        throw std::invalid_argument("a force and where it acts are finite");
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) return;
    impl_->physics_->GetBodyInterface().AddForce(found->second, toJolt(force_n), toJoltPosition(at_world_m),
                                                 JPH::EActivation::Activate);
}

void JoltWorld::addTorque(MatterBodyId body_id, const Vec3 &torque_n_m) {
    if (!std::isfinite(torque_n_m.x + torque_n_m.y + torque_n_m.z))
        throw std::invalid_argument("a torque is finite");
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) return;
    impl_->physics_->GetBodyInterface().AddTorque(found->second, toJolt(torque_n_m), JPH::EActivation::Activate);
}

void JoltWorld::setDamping(MatterBodyId body_id, double linear_per_s, double angular_per_s) {
    impl_->requireConfigurationMutable();
    if (!(linear_per_s >= 0.0) || !(angular_per_s >= 0.0) || !std::isfinite(linear_per_s + angular_per_s))
        throw std::invalid_argument("damping is a share of the speed per second, zero or more");
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) return;
    JPH::BodyLockWrite lock(impl_->physics_->GetBodyLockInterface(), found->second);
    if (!lock.Succeeded() || !lock.GetBody().IsDynamic()) return;
    JPH::MotionProperties *motion = lock.GetBody().GetMotionProperties();
    motion->SetLinearDamping(static_cast<float>(linear_per_s));
    motion->SetAngularDamping(static_cast<float>(angular_per_s));
}

void JoltWorld::setJointFriction(unsigned joint, double friction) {
    impl_->requireConfigurationMutable();
    if (!(friction >= 0.0) || !std::isfinite(friction))
        throw std::invalid_argument("joint friction must be zero or more");
    auto &held = impl_->joints_.at(joint);
    // A rope has no friction to set, and neither has an ideal pulley: it has
    // no wheel to have a bearing. Rather than refusing -- which would make every
    // caller special-case the kind before asking -- this does nothing, because
    // nothing is the true answer. A kerf's friction is the cutting model's to
    // set, every step, from the material; nobody else's.
    if (held.kind == JointKind::Link || held.kind == JointKind::Pulley ||
        held.kind == JointKind::Fixing || held.kind == JointKind::Elastic ||
        held.kind == JointKind::Kerf || held.kind == JointKind::GroundBite ||
        held.kind == JointKind::Drum) return;
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
    settings.mMinDistance = d.taut_at_restore ? static_cast<float>(d.length_m) : 0.0f;
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

unsigned JoltWorld::addDrum(const DrumDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.drum == d.load || !contains(d.drum) || !contains(d.load))
        throw std::invalid_argument("a drum's rope needs a drum and a load, two different bodies in the world");
    if (impl_->joints_.size() >= 4096) throw std::invalid_argument("joint budget exceeded");
    if (!(d.radius_m > 0.0) || !std::isfinite(d.radius_m)) throw std::invalid_argument("a drum needs a radius");
    if (!(d.length_m > 0.0) || !std::isfinite(d.length_m))
        throw std::invalid_argument("a drum's rope needs a length");
    if (!(d.out_m >= 0.0) || !(d.out_m <= d.length_m))
        throw std::invalid_argument("a drum cannot let out more rope than it has");
    const double reach = std::sqrt(d.axis_world.x * d.axis_world.x + d.axis_world.y * d.axis_world.y +
                                   d.axis_world.z * d.axis_world.z);
    if (!(reach > 1e-9)) throw std::invalid_argument("a drum's axle needs a direction");
    for (const Vec3 &point : {d.centre_world_m, d.load_point_world_m})
        if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z))
            throw std::invalid_argument("a drum's rope needs places for its ends");

    auto &bodies = impl_->physics_->GetBodyInterface();
    const JPH::BodyID drum = impl_->bodies_.at(d.drum);
    const JPH::BodyID load = impl_->bodies_.at(d.load);
    // Everything in each body's own centre-of-mass frame, where it stays when
    // the whole winch is carried or turned over.
    const JPH::RMat44 into_drum = bodies.GetCenterOfMassTransform(drum).InversedRotationTranslation();
    const JPH::RMat44 into_load = bodies.GetCenterOfMassTransform(load).InversedRotationTranslation();
    DrumRopeSettings settings;
    settings.rope.centre_local = JPH::Vec3(into_drum * toJoltPosition(d.centre_world_m));
    settings.rope.axis_local = into_drum.Multiply3x3(
        toJolt(Vec3{d.axis_world.x / reach, d.axis_world.y / reach, d.axis_world.z / reach}));
    settings.rope.radius_m = static_cast<float>(d.radius_m);
    settings.rope.load_point_local = JPH::Vec3(into_load * toJoltPosition(d.load_point_world_m));
    settings.rope.winds = d.winds < 0 ? -1.0F : 1.0F;
    settings.rope.length_m = d.length_m;
    settings.rope.wound_m = d.wound_m >= 0.0 ? d.wound_m : d.out_m > 0.0 ? d.length_m - d.out_m : -1.0;
    auto *raw = bodies.CreateConstraint(&settings, drum, load);
    if (!raw) throw std::runtime_error("drum creation failed");
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.drum, d.load, JointKind::Drum, static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

JoltWorld::DrumReport JoltWorld::drumState(unsigned joint) const {
    DrumReport out{};
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Drum) return out;
    const auto *rope = static_cast<const DrumRopeConstraint *>(found->second.constraint.GetPtr());
    // The impulse over the step, over the step: the force. A rope pulls, so its
    // impulse is zero or less (DrumRopeConstraint::totalLambda).
    const double dt = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 60.0;
    out.tension_n = std::max(0.0, -static_cast<double>(rope->totalLambda())) / dt;
    out.out_m = rope->out();
    out.wound_m = rope->wound();
    out.length_m = rope->length();
    out.span_m = rope->span();
    out.leaves_m = fromJoltPosition(rope->leaves());
    out.meets_m = fromJoltPosition(rope->meets());
    return out;
}

double JoltWorld::jointTension(unsigned joint) const {
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end()) return 0.0;
    if (found->second.kind == JointKind::Drum) return drumState(joint).tension_n;
    if (found->second.kind == JointKind::Pulley) {
        const double impulse =
            static_cast<JPH::PulleyConstraint *>(found->second.constraint.GetPtr())
                ->GetTotalLambdaPosition();
        const double dt = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 60.0;
        return std::abs(impulse) / dt;
    }
    if (found->second.kind != JointKind::Link) return 0.0;
    // Jolt reports the impulse the constraint applied over the last step, and
    // an impulse over a step is a force. A pull is negative. A rope held at its
    // length for a step (step()) can push in it, once, as it starts to go
    // slack -- and a push is not tension, so it reads as none.
    const double impulse =
        static_cast<JPH::DistanceConstraint *>(found->second.constraint.GetPtr())
            ->GetTotalLambdaPosition();
    const double dt = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 60.0;
    return std::max(0.0, -impulse) / dt;
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

void JoltWorld::updateElastic(unsigned joint, double stiffness_n_m, double damping_n_s_m) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end()) throw std::invalid_argument("there is no such joint");
    if (found->second.kind != JointKind::Elastic)
        throw std::invalid_argument("only an elastic has a stiffness to change");
    if (!(stiffness_n_m > 0.0) || !std::isfinite(stiffness_n_m))
        throw std::invalid_argument("an elastic needs a positive stiffness in newtons per metre");
    if (!(damping_n_s_m >= 0.0) || !std::isfinite(damping_n_s_m))
        throw std::invalid_argument("elastic damping is newton seconds per metre, zero or more");
    auto *spring = static_cast<JPH::DistanceConstraint *>(found->second.constraint.GetPtr());
    spring->SetLimitsSpringSettings({JPH::ESpringMode::StiffnessAndDamping,
                                     static_cast<float>(stiffness_n_m),
                                     static_cast<float>(damping_n_s_m)});
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
    if (!(d.comes_off_n >= 0.0) || !std::isfinite(d.comes_off_n))
        throw std::invalid_argument("a one-way fixing comes off at newtons, zero (two-way) "
                                    "or more");
    if (d.comes_off_n > 0.0 && d.holds_tension_n > 0.0)
        throw std::invalid_argument("a one-way fixing has no tension strength: what pulls "
                                    "it off is comes_off_n");

    const Vec3 along = (1.0 / reach) * d.axis_world;
    const Vec3 away = std::abs(along.y) < 0.9 ? Vec3{0.0, 1.0, 0.0} : Vec3{1.0, 0.0, 0.0};
    Vec3 across = cross(away, along);
    const double sideways = length(across);
    if (!(sideways > 1e-9)) throw std::runtime_error("could not square up a fixing axis");
    across = (1.0 / sideways) * across;

    // Their relative pose right now is the pose they keep. That is the whole of
    // what "defined alignment" means here: it is defined by where they are when
    // the peg goes in, which is also how a peg works.
    JPH::TwoBodyConstraint *raw = nullptr;
    const bool one_way = d.comes_off_n > 0.0;
    if (one_way) {
        // The axis is X, and along it b may move off a -- towards +X -- and not
        // back. Behind zero the limit is contact, and pushes as hard as it has
        // to; ahead of it, friction holds b with up to comes_off_n and no more,
        // so a harder pull slides it off. Across the axis, and in every turn,
        // it is held as any fixing holds. LiveWorld decides when b has slid far
        // enough to be off, and takes the constraint away.
        using Axis = JPH::SixDOFConstraintSettings::EAxis;
        JPH::SixDOFConstraintSettings settings;
        settings.mSpace = JPH::EConstraintSpace::WorldSpace;
        settings.mPosition1 = settings.mPosition2 = toJoltPosition(d.point_world_m);
        settings.mAxisX1 = settings.mAxisX2 = toJolt(along);
        settings.mAxisY1 = settings.mAxisY2 = toJolt(across);
        settings.SetLimitedAxis(Axis::TranslationX, 0.0F, std::numeric_limits<float>::max());
        settings.MakeFixedAxis(Axis::TranslationY);
        settings.MakeFixedAxis(Axis::TranslationZ);
        settings.MakeFixedAxis(Axis::RotationX);
        settings.MakeFixedAxis(Axis::RotationY);
        settings.MakeFixedAxis(Axis::RotationZ);
        settings.mMaxFriction[Axis::TranslationX] = static_cast<float>(d.comes_off_n);
        raw = impl_->physics_->GetBodyInterface().CreateConstraint(
            &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    } else {
        JPH::FixedConstraintSettings settings;
        settings.mSpace = JPH::EConstraintSpace::WorldSpace;
        settings.mAutoDetectPoint = false;
        settings.mPoint1 = settings.mPoint2 = toJoltPosition(d.point_world_m);
        settings.mAxisX1 = settings.mAxisX2 = toJolt(along);
        settings.mAxisY1 = settings.mAxisY2 = toJolt(across);
        raw = impl_->physics_->GetBodyInterface().CreateConstraint(
            &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    }
    if (!raw) throw std::runtime_error("fixing creation failed");
    // A LIGHT BODY HELD BETWEEN A HEAVY ONE AND ITS SUPPORT: a 32 kg iron gate
    // welded under a 180 g oak peg that is itself fixed into an anchored post.
    // An iterative solver passes an impulse through a light body held between a
    // heavy one and its support at about the ratio of their masses per
    // iteration -- after N the part not yet passed is (1 + m/M)^-N, the same
    // arithmetic as the kerf below -- and with the default ten, measured, that
    // peg sagged 13 degrees under its gate and the load it read was the weight
    // times the cosine of the sag. So when a fixing makes that arrangement --
    // either end of it, in whichever order the two were fixed -- its island gets
    // enough iterations to pass all but 1% of the heavy body's impulse through
    // the light one, up to what Jolt can be asked for (its override is 8 bits).
    //
    // ONLY that arrangement. A light body between two moving ones is left at
    // the default: a bow's nocking point sits between its string and a heavier
    // arrow, and the bow's limbs are soft springs whose behaviour depends on how
    // many times they are iterated -- raising the island's count changed what
    // the bow threw (tests/bow_tests.cpp), which is the bow's own calibration
    // and not this fixing's business.
    {
        const auto inverseMass = [&](MatterBodyId body) {
            JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(), impl_->bodies_.at(body));
            if (!lock.Succeeded() || !lock.GetBody().IsDynamic()) return 0.0;
            return static_cast<double>(lock.GetBody().GetMotionProperties()->GetInverseMass());
        };
        // What a moving body is already joined to: whether any of it does not
        // move, and the heaviest of what does (as its inverse mass).
        const auto joinedTo = [&](MatterBodyId body, double &heaviest_inverse, bool &supported) {
            for (const auto &[id, held] : impl_->joints_) {
                if (held.a != body && held.b != body) continue;
                const double other = inverseMass(held.a == body ? held.b : held.a);
                if (!(other > 0.0)) supported = true;
                else heaviest_inverse = std::min(heaviest_inverse, other);
            }
        };
        const double ia = inverseMass(d.a), ib = inverseMass(d.b);
        double light_over_heavy = 1.0;   // m / M of the light body and the heavy one it carries
        if (ia > 0.0 && ib > 0.0) {
            // Two moving bodies: it matters if the lighter is held by a support.
            const double light = std::max(ia, ib);
            double heaviest = std::min(ia, ib);
            bool supported = false;
            joinedTo(ia >= ib ? d.a : d.b, heaviest, supported);
            if (supported) light_over_heavy = heaviest / light;
        } else if (ia > 0.0 || ib > 0.0) {
            // A moving body onto a support: it matters if it already carries
            // something heavier than itself.
            const double light = std::max(ia, ib);
            double heaviest = light;
            bool supported = true;
            joinedTo(ia > 0.0 ? d.a : d.b, heaviest, supported);
            light_over_heavy = heaviest / light;
        }
        if (light_over_heavy < 1.0) {
            const int steps = static_cast<int>(std::ceil(std::log(100.0) / std::log1p(light_over_heavy)));
            if (steps > 10) {
                raw->SetNumVelocityStepsOverride(static_cast<JPH::uint>(std::min(steps, 255)));
                raw->SetNumPositionStepsOverride(static_cast<JPH::uint>(std::min(std::max(steps / 10, 2), 32)));
            }
        }
    }
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Fixing, raw, one_way});
    impl_->physics_->AddConstraint(raw);
    return id;
}

namespace {
// Solver iterations for the island an engaged edge is in: a new kerf's first
// step up to the cold cap, every later step the warm count. See addKerf.
constexpr int kWarmKerfSteps = 40;
constexpr int kColdKerfStepsMax = 400;
}  // namespace

unsigned JoltWorld::addKerf(const KerfDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.blade == d.target || !contains(d.blade) || !contains(d.target))
        throw std::invalid_argument("a kerf needs a blade and a target that are both in the world");
    if (impl_->joints_.size() >= 4096)
        throw std::invalid_argument("joint budget exceeded");
    const double facing = length(d.facing_world);
    const double flat = length(d.flat_world);
    if (!(facing > 1e-9) || !(flat > 1e-9) || !std::isfinite(facing) || !std::isfinite(flat))
        throw std::invalid_argument("a kerf needs a facing and a flat normal with a direction");
    if (!(d.resist_facing_n >= 0.0) || !(d.resist_along_n >= 0.0) ||
        !std::isfinite(d.resist_facing_n) || !std::isfinite(d.resist_along_n))
        throw std::invalid_argument("a kerf's resistance is newtons, zero or more");
    const Vec3 n = (1.0 / facing) * d.facing_world;
    // Square the flat normal up against the facing, so the frame is exact
    // however the caller's two vectors were rounded.
    Vec3 f = d.flat_world - dot(d.flat_world, n) * n;
    const double across = length(f);
    if (!(across > 1e-9)) throw std::invalid_argument("a kerf's facing and flat normal are parallel");
    f = (1.0 / across) * f;

    using Axis = JPH::SixDOFConstraintSettings::EAxis;
    JPH::SixDOFConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    settings.mPosition1 = settings.mPosition2 = toJoltPosition(d.point_world_m);
    // X is the normal to the flats and Y is the facing, so Z runs along the
    // edge. X is chosen deliberately: Jolt's rotation about X is TWIST, handled
    // apart from the two swing axes, and turning in the blade's own plane --
    // about the flat normal -- is the one rotation that must always be free.
    // With it on X the two locked rotations are both swing, and a swing locked
    // on both axes has no cone-versus-pyramid question to answer.
    settings.mAxisX1 = settings.mAxisX2 = toJolt(f);
    settings.mAxisY1 = settings.mAxisY2 = toJolt(n);
    settings.mSwingType = JPH::ESwingType::Pyramid;
    settings.MakeFreeAxis(Axis::TranslationY);   // into the material: a one-sided motor
    settings.MakeFreeAxis(Axis::TranslationZ);   // along the edge: friction only
    settings.MakeFreeAxis(Axis::RotationX);      // turning in its own plane
    if (d.embedded) {
        // The kerf's walls: no sliding across the flats, no twisting in the cut.
        settings.MakeFixedAxis(Axis::TranslationX);
        settings.MakeFixedAxis(Axis::RotationY);
        settings.MakeFixedAxis(Axis::RotationZ);
    } else {
        settings.MakeFreeAxis(Axis::TranslationX);
        settings.MakeFreeAxis(Axis::RotationY);
        settings.MakeFreeAxis(Axis::RotationZ);
    }
    settings.mMaxFriction[Axis::TranslationZ] = static_cast<float>(d.resist_along_n);

    // How light the target is against the blade, for the iterations below.
    const auto inverseMass = [&](auto body) {
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(), impl_->bodies_.at(body));
        if (!lock.Succeeded() || !lock.GetBody().IsDynamic()) return 0.0;
        return static_cast<double>(lock.GetBody().GetMotionProperties()->GetInverseMass());
    };
    const double inverse_blade = inverseMass(d.blade);
    const double inverse_target = inverseMass(d.target);

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.blade), impl_->bodies_.at(d.target));
    if (!raw) throw std::runtime_error("kerf creation failed");
    auto *kerf = static_cast<JPH::SixDOFConstraint *>(raw);
    // Into the material the kerf is a velocity motor driven to no relative
    // motion, whose force may push the edge back out and may not pull it in:
    // [0, R L]. It holds an edge pressed into it with up to R L, gives way to
    // more, and lets an edge be drawn out freely -- cut material does not grip
    // the steel. (A friction resists both ways, so something had to switch it
    // off for a retreating edge, and a solver bounce then switched it off
    // under a pressing one.) Body 1 is the blade and the axis is the facing,
    // so a positive impulse pushes the blade back and the target on.
    kerf->GetMotorSettings(Axis::TranslationY)
        .SetForceLimits(0.0F, static_cast<float>(d.resist_facing_n));
    kerf->SetTargetVelocityCS(JPH::Vec3::sZero());
    kerf->SetMotorState(Axis::TranslationY, JPH::EMotorState::Velocity);
    // An edge is usually heavy steel pressed into something light -- a 2 kg
    // blade on a 28 g batten lying on the floor -- and an iterative solver
    // passes an impulse through a light body held between a heavy one and its
    // support at about the ratio of their masses per iteration: after N
    // iterations the part not yet passed is (1 + m/M)^-N. Measured with forty,
    // a new kerf held back only two thirds of a 219 N press in its first step
    // and the blade sank into matter nobody had cut. A kerf starts with none
    // of its impulse, so its first step gets what passes all but 1% of it, up
    // to a cap; from then on it starts each step from the last one's impulse
    // and needs far fewer (updateKerf).
    int cold = kWarmKerfSteps;
    if (inverse_blade > 0.0 && inverse_target > inverse_blade) {
        const double light_over_heavy = inverse_blade / inverse_target;   // m / M
        cold = static_cast<int>(std::ceil(std::log(100.0) / std::log1p(light_over_heavy)));
        cold = std::min(std::max(cold, kWarmKerfSteps), kColdKerfStepsMax);
    }
    raw->SetNumVelocityStepsOverride(static_cast<JPH::uint>(cold));
    raw->SetNumPositionStepsOverride(6);
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.blade, d.target, JointKind::Kerf,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    return id;
}

void JoltWorld::updateKerf(unsigned joint, double resist_facing_n, double resist_along_n) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Kerf) return;
    if (!(resist_facing_n >= 0.0) || !(resist_along_n >= 0.0) ||
        !std::isfinite(resist_facing_n) || !std::isfinite(resist_along_n))
        throw std::invalid_argument("a kerf's resistance is newtons, zero or more");
    using Axis = JPH::SixDOFConstraintSettings::EAxis;
    auto *kerf = static_cast<JPH::SixDOFConstraint *>(found->second.constraint.GetPtr());
    kerf->GetMotorSettings(Axis::TranslationY)
        .SetForceLimits(0.0F, static_cast<float>(resist_facing_n));
    kerf->SetMaxFriction(Axis::TranslationZ, static_cast<float>(resist_along_n));
    // It has been solved at least once, so it starts from its last impulse.
    kerf->SetNumVelocityStepsOverride(static_cast<JPH::uint>(kWarmKerfSteps));
}

JoltWorld::KerfImpulse JoltWorld::kerfImpulse(unsigned joint) const {
    KerfImpulse out{};
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Kerf) return out;
    // The facing's one-sided motor and the edge's friction are both Jolt's
    // translation MOTOR parts, bounded by their force times the step. Y is the
    // facing and Z the edge; see addKerf for why the frame is laid out that way.
    const JPH::Vec3 impulse =
        static_cast<JPH::SixDOFConstraint *>(found->second.constraint.GetPtr())
            ->GetTotalLambdaMotorTranslation();
    out.facing_n_s = static_cast<double>(impulse.GetY());
    out.along_n_s = static_cast<double>(impulse.GetZ());
    return out;
}

JoltWorld::JointLoad JoltWorld::jointLoad(unsigned joint, const Vec3 &axis_world) const {
    JointLoad out{};
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end()) return out;
    if (found->second.kind != JointKind::Fixing) return out;
    const double dt = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 60.0;
    if (found->second.one_way) {
        // A one-way fixing is solved along its own axes and reports along
        // them. X is the fixing's axis, where the push (the limit) and the
        // hold (the friction) are two parts of one force; Y and Z are across
        // it. Jolt's impulse is the one on b, so positive pushes b off a.
        const auto *seat =
            static_cast<const JPH::SixDOFConstraint *>(found->second.constraint.GetPtr());
        const JPH::Vec3 held = seat->GetTotalLambdaPosition();
        const JPH::Vec3 friction = seat->GetTotalLambdaMotorTranslation();
        out.axial_n = static_cast<double>(held.GetX() + friction.GetX()) / dt;
        out.tension_n = std::abs(out.axial_n);
        out.shear_n = std::hypot(static_cast<double>(held.GetY()),
                                 static_cast<double>(held.GetZ())) / dt;
        return out;
    }
    // Jolt reports the impulse the constraint applied over the step as a
    // VECTOR, which is exactly what is needed: a peg pulled straight out and a
    // peg sheared sideways fail at different loads, so the two have to be told
    // apart rather than added into one magnitude. It is the impulse on b.
    const JPH::Vec3 impulse =
        static_cast<JPH::FixedConstraint *>(found->second.constraint.GetPtr())
            ->GetTotalLambdaPosition();
    const JPH::Vec3 angular =
        static_cast<JPH::FixedConstraint *>(found->second.constraint.GetPtr())
            ->GetTotalLambdaRotation();
    out.moment_n_m = {static_cast<double>(angular.GetX()) / dt,
                     static_cast<double>(angular.GetY()) / dt,
                     static_cast<double>(angular.GetZ()) / dt};
    const Vec3 force{static_cast<double>(impulse.GetX()) / dt,
                     static_cast<double>(impulse.GetY()) / dt,
                     static_cast<double>(impulse.GetZ()) / dt};
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return out;
    const Vec3 along = (1.0 / reach) * axis_world;
    const double pulled = dot(force, along);
    out.axial_n = pulled;
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

unsigned JoltWorld::addGear(const GearDescription &d) {
    impl_->requireConfigurationMutable();
    if (d.a == d.b || !contains(d.a) || !contains(d.b))
        throw std::invalid_argument("a gear needs two different wheels that are both in the world");
    if (impl_->joints_.size() >= 4096) throw std::invalid_argument("joint budget exceeded");
    if (d.teeth_a == 0 || d.teeth_b == 0)
        throw std::invalid_argument("a gear's wheels each need at least one tooth");
    if (!(d.strips_at_n_m >= 0.0) || !std::isfinite(d.strips_at_n_m))
        throw std::invalid_argument("a gear strips at zero newton metres or more");
    // The pins, which must be pins: Jolt solves a gear as a relationship
    // between two hinge constraints, so there is nothing to couple without
    // them. Saying so here names the mistake where it is made.
    const auto pin_a = impl_->joints_.find(d.pin_a);
    const auto pin_b = impl_->joints_.find(d.pin_b);
    if (pin_a == impl_->joints_.end() || pin_b == impl_->joints_.end())
        throw std::invalid_argument("a gear coupless two pins that exist");
    if (pin_a->second.kind != JointKind::Hinge || pin_b->second.kind != JointKind::Hinge)
        throw std::invalid_argument("a gear couples two PINS: each wheel turns on one");
    if (d.pin_a == d.pin_b)
        throw std::invalid_argument("a gear couples two different pins");

    JPH::GearConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    // Jolt's ratio is signed: Gear1Rotation = -ratio * Gear2Rotation, so a
    // POSITIVE ratio is two wheels turning opposite ways, which is what teeth
    // in mesh do. A chain runs round both sprockets the same way round, so it
    // turns them the same way, which is the sign flipped. That one sign is the
    // whole difference between the two things this joint can be.
    const double ratio = static_cast<double>(d.teeth_b) / static_cast<double>(d.teeth_a);
    settings.mRatio = static_cast<float>(d.chain ? -ratio : ratio);
    // The axes each wheel turns about, which are its pin's.
    settings.mHingeAxis1 = static_cast<JPH::HingeConstraint *>(pin_a->second.constraint.GetPtr())->GetLocalSpaceHingeAxis1();
    settings.mHingeAxis2 = static_cast<JPH::HingeConstraint *>(pin_b->second.constraint.GetPtr())->GetLocalSpaceHingeAxis1();

    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(
        &settings, impl_->bodies_.at(d.a), impl_->bodies_.at(d.b));
    if (!raw) throw std::runtime_error("gear creation failed");
    auto *gear = static_cast<JPH::GearConstraint *>(raw);
    gear->SetConstraints(pin_a->second.constraint.GetPtr(), pin_b->second.constraint.GetPtr());
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.a, d.b, JointKind::Gear,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->gear_strength_.emplace(id, d.strips_at_n_m);
    impl_->physics_->AddConstraint(raw);
    return id;
}

double JoltWorld::gearTorque(unsigned joint) const {
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::Gear) return 0.0;
    // Jolt accumulates an ANGULAR IMPULSE over the step; the torque is that
    // impulse over the step it was applied in, the same way jointTension turns
    // a constraint's impulse into a force.
    const auto *gear = static_cast<const JPH::GearConstraint *>(found->second.constraint.GetPtr());
    if (!(impl_->last_dt_s > 0.0)) return 0.0;
    return std::abs(static_cast<double>(gear->GetTotalLambda())) / impl_->last_dt_s;
}

std::vector<unsigned> JoltWorld::strippedGears() const { return impl_->stripped_gears_; }

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
    if (!std::isfinite(d.at_m))
        throw std::invalid_argument("a slide's reading as it is made is a number of metres");

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
    // Jolt reads a slide as how far the second body's point is along the axis
    // from the first's. Both are the same point for a slide made where the two
    // stand; one to read at_m as it is made has the first's that far back.
    settings.mPoint1 = toJoltPosition(d.point_world_m - d.at_m * along);
    settings.mPoint2 = toJoltPosition(d.point_world_m);
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
    impl_->requireConfigurationMutable();
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
void JoltWorld::configureVoxelContacts(double feature) {
    impl_->requireConfigurationMutable();
    if(!std::isfinite(feature)||feature<1e-5||feature>1)throw std::invalid_argument("invalid voxel contact scale");
    auto settings=impl_->physics_->GetPhysicsSettings();
    settings.mSpeculativeContactDistance=float(feature*.1);
    settings.mPenetrationSlop=float(feature*.01);
    settings.mManifoldTolerance=float(feature*.05);
    settings.mMaxPenetrationDistance=float(feature*.25);
    settings.mContactPointPreserveLambdaMaxDistSq=float(feature*feature*.0625);
    // Do not project contact positions behind the material solver's back:
    // that projection stretches stiff interfaces without supplying work.
    settings.mBaumgarte=0;
    impl_->physics_->SetPhysicsSettings(settings);
}
void JoltWorld::setContinuousCollision(MatterBodyId id,bool enabled) {
    impl_->requireConfigurationMutable();
    if(enabled&&impl_->centered_integration_)throw std::invalid_argument("centered integration requires discrete collision; CCD is not coupled");
    impl_->physics_->GetBodyInterface().SetMotionQuality(impl_->bodies_.at(id),enabled?JPH::EMotionQuality::LinearCast:JPH::EMotionQuality::Discrete);
}
unsigned JoltWorld::addFaceSpring(const FaceSpringDescription &d) {
    impl_->requireConfigurationMutable();
    const auto valid=[](Vec3 v,bool positive){return std::isfinite(v.x+v.y+v.z)&&std::min({v.x,v.y,v.z})>=(positive?1e-12:0);};
    if(d.a==d.b||!contains(d.a)||!contains(d.b)||impl_->joints_.size()>=4096||
       !valid(d.translation_stiffness_n_m,true)||!valid(d.rotation_stiffness_n_m_rad,true)||
       !valid(d.translation_damping_n_s_m,false)||!valid(d.rotation_damping_n_m_s_rad,false)||
       !std::isfinite(lengthSquared(d.anchor_world_m))||std::abs(length(d.normal_world)-1)>1e-8||
       std::abs(length(d.tangent_world)-1)>1e-8||std::abs(dot(d.normal_world,d.tangent_world))>1e-8)
        throw std::invalid_argument("invalid passive face spring");
    if(d.centered_integration!=impl_->centered_integration_)throw std::invalid_argument("face integration must match world pose integration");
    if(d.log_rotation_gradient||d.centered_integration){
        const auto settings=logFaceSpringSettings(d);
        auto *raw=impl_->physics_->GetBodyInterface().CreateConstraint(settings.GetPtr(),impl_->bodies_.at(d.a),impl_->bodies_.at(d.b));
        if(!raw)throw std::runtime_error("log face spring creation failed");
        const auto id=impl_->next_joint_++;impl_->joints_.emplace(id,Impl::Joint{d.a,d.b,JointKind::FaceSpring,raw,false,true});
        impl_->physics_->AddConstraint(raw);return id;
    }
    JPH::SixDOFConstraintSettings s;s.mSpace=JPH::EConstraintSpace::WorldSpace;
    s.mPosition1=s.mPosition2=toJoltPosition(d.anchor_world_m);
    s.mAxisX1=s.mAxisX2=toJolt(d.normal_world);s.mAxisY1=s.mAxisY2=toJolt(d.tangent_world);
    const double k[]{d.translation_stiffness_n_m.x,d.translation_stiffness_n_m.y,d.translation_stiffness_n_m.z,
        d.rotation_stiffness_n_m_rad.x,d.rotation_stiffness_n_m_rad.y,d.rotation_stiffness_n_m_rad.z};
    const double c[]{d.translation_damping_n_s_m.x,d.translation_damping_n_s_m.y,d.translation_damping_n_s_m.z,
        d.rotation_damping_n_m_s_rad.x,d.rotation_damping_n_m_s_rad.y,d.rotation_damping_n_m_s_rad.z};
    for(unsigned i=0;i<6;++i)s.mMotorSettings[i].mSpringSettings={JPH::ESpringMode::StiffnessAndDamping,float(k[i]),float(c[i])};
    auto *raw=static_cast<JPH::SixDOFConstraint*>(impl_->physics_->GetBodyInterface().CreateConstraint(&s,impl_->bodies_.at(d.a),impl_->bodies_.at(d.b)));
    if(!raw)throw std::runtime_error("face spring creation failed");
    for(unsigned i=0;i<6;++i)raw->SetMotorState(static_cast<JPH::SixDOFConstraint::EAxis>(i),JPH::EMotorState::Position);
    raw->SetTargetPositionCS(JPH::Vec3::sZero());raw->SetTargetOrientationCS(JPH::Quat::sIdentity());
    const auto id=impl_->next_joint_++;impl_->joints_.emplace(id,Impl::Joint{d.a,d.b,JointKind::FaceSpring,raw});
    impl_->physics_->AddConstraint(raw);return id;
}
JoltWorld::FaceSpringObservation JoltWorld::faceSpringObservation(unsigned id) const {
    const auto fromJoltVector=[](JPH::Vec3Arg x){return Vec3{x.GetX(),x.GetY(),x.GetZ()};};
    const auto &j=impl_->joints_.at(id);if(j.kind!=JointKind::FaceSpring)throw std::invalid_argument("not a face spring");
    const auto observed=[&](FaceSpringObservation out){
        if(impl_->force_phase_enabled_){
            bool scheduled=false;
            for(const auto body:{j.a,j.b}){
                const auto slot=impl_->force_phase_slot_.find(impl_->bodies_.at(body).GetIndexAndSequenceNumber());
                if(slot!=impl_->force_phase_slot_.end())scheduled|=impl_->force_phase_[slot->second].integration_scheduled;
            }
            out.solver_scheduled=j.constraint->GetEnabled()&&scheduled;
        }
        return out;
    };
    if(j.log_face)return observed(observeLogFaceSpring(*j.constraint.GetPtr()));
    const auto *c=static_cast<const JPH::SixDOFConstraint*>(j.constraint.GetPtr());
    // Between Updates the constraint holds the native bodies the solver uses.
    // Read each transform once, rather than taking eight BodyInterface locks
    // per face. Retain native frame arithmetic and double world positions.
    const auto a=c->GetBody1()->GetCenterOfMassTransform()*c->GetConstraintToBody1Matrix();
    const auto b=c->GetBody2()->GetCenterOfMassTransform()*c->GetConstraintToBody2Matrix();
    const auto pa=fromJoltPosition(a.GetTranslation()),pb=fromJoltPosition(b.GetTranslation());
    const auto x=fromJoltVector(a.GetAxisX()),y=fromJoltVector(a.GetAxisY()),z=fromJoltVector(a.GetAxisZ());
    const auto delta=pb-pa;const auto q=c->GetRotationInConstraintSpace();
    const double angle=2*std::atan2(std::sqrt(double(q.GetX())*q.GetX()+double(q.GetY())*q.GetY()+double(q.GetZ())*q.GetZ()),std::abs(double(q.GetW())));
    const auto axis=Vec3{q.GetX(),q.GetY(),q.GetZ()}*(q.GetW()<0?-1.:1.);
    const auto rotation=length(axis)>1e-12?axis*(angle/length(axis)):Vec3{};
    return observed({{dot(delta,x),dot(delta,y),dot(delta,z)},rotation,fromJoltVector(c->GetTotalLambdaMotorTranslation()),fromJoltVector(c->GetTotalLambdaMotorRotation()),
        pb,Vec3{q.GetX(),q.GetY(),q.GetZ()}*(q.GetW()>0?2.:-2.),{x,y,z},
        {fromJoltVector(b.GetAxisX()),fromJoltVector(b.GetAxisY()),fromJoltVector(b.GetAxisZ())}});
}

void JoltWorld::setFacePlasticRest(unsigned id,Vec3 p,Vec3 r){
    if(!std::isfinite(lengthSquared(p))||!std::isfinite(lengthSquared(r))||length(p)>10||length(r)>=std::acos(-1.))
        throw std::invalid_argument("face plastic rest exceeds finite 10 m / pi rad native bounds");
    const auto &joint=impl_->joints_.at(id);
    if(joint.kind!=JointKind::FaceSpring||!joint.log_face)throw std::invalid_argument("plastic rest needs a log-gradient face");
    setLogFacePlasticRest(*joint.constraint.GetPtr(),p,r);
    auto &bodies=impl_->physics_->GetBodyInterface();
    for(const auto body:{joint.a,joint.b})bodies.ActivateBody(impl_->bodies_.at(body));
}

void JoltWorld::setContactRestitutionModel(RigidContactRestitution model) {
    impl_->requireConfigurationMutable();
    if(!impl_->bodies_.empty()||!impl_->floor_id_.IsInvalid())throw std::logic_error("configure restitution model before creating bodies");
    if(model!=RigidContactRestitution::MaterialCombination&&model!=RigidContactRestitution::ResolvedDeformation&&model!=RigidContactRestitution::MidpointUnilateral&&model!=RigidContactRestitution::MidpointBlockFriction)
        throw std::invalid_argument("unsupported contact restitution model");
    if((model==RigidContactRestitution::MidpointUnilateral||model==RigidContactRestitution::MidpointBlockFriction)&&!impl_->centered_integration_)throw std::invalid_argument("midpoint contact requires centered integration");
    impl_->impact_collector_.restitution_model=model;
}
void JoltWorld::setCenteredIntegration(bool enabled){
    impl_->requireConfigurationMutable();
    if(!impl_->bodies_.empty()||!impl_->floor_id_.IsInvalid())throw std::logic_error("configure centered integration before bodies");
    if(!enabled&&(impl_->impact_collector_.restitution_model==RigidContactRestitution::MidpointUnilateral||impl_->impact_collector_.restitution_model==RigidContactRestitution::MidpointBlockFriction))throw std::logic_error("midpoint contact requires centered integration");
    impl_->centered_integration_=enabled;
    // Native displacement-based sleep can zero a still-oscillating elastic
    // body after 0.5 s; the centered reference retains that mechanical energy.
    auto settings=impl_->physics_->GetPhysicsSettings();
    settings.mTimeBeforeSleep=enabled?std::numeric_limits<float>::max():JPH::PhysicsSettings{}.mTimeBeforeSleep;
    impl_->physics_->SetPhysicsSettings(settings);
    if(enabled)setForcePhaseObservationsEnabled(true);
    impl_->physics_->SetBanjoCenteredMotion(enabled?&Impl::centeredMotion:nullptr,impl_.get());
}
void JoltWorld::setContactImpulseObservationsEnabled(bool enabled){
    impl_->requireConfigurationMutable();impl_->impact_collector_.contact_impulses_enabled=enabled;
    impl_->impact_collector_.clearContactGeometry();impl_->contact_impulses_.clear();
}
std::span<const JoltWorld::ContactImpulseObservation> JoltWorld::contactImpulseObservations() const {return impl_->contact_impulses_;}
Vec3 JoltWorld::observedGravityImpulseN_s() const {return impl_->observed_gravity_impulse_;}
void JoltWorld::setForcePhaseObservationsEnabled(bool enabled){
    impl_->requireConfigurationMutable();
    if(!enabled&&impl_->centered_integration_)throw std::logic_error("centered integration needs native phases");
    impl_->force_phase_enabled_=enabled;
    impl_->force_phase_.clear();impl_->force_phase_slot_.clear();
    impl_->physics_->SetBanjoForceObserver(enabled?&Impl::observeForcePhase:nullptr,impl_.get());
    impl_->physics_->SetBanjoLimitObserver(enabled?&Impl::observeLimitPhase:nullptr,impl_.get());
}
std::span<const JoltWorld::ForcePhaseObservation> JoltWorld::forcePhaseObservations() const {return impl_->force_phase_;}

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
PointContactKick JoltWorld::applyExternalPointContact(MatterBodyId proxy,MatterBodyId striker,
    ActiveNodeState &point,Vec3 normal,double gap,double duration,
    const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget) {
    // External point state is not included in Jolt's trial recorder.
    impl_->requireConfigurationMutable();
    if(pairContactOwner(proxy,striker)!=PairContactOwner::External)
        throw std::invalid_argument("point contact requires external pair ownership");
    for(double limit:{budget.energy_j,budget.linear_impulse_n_s,budget.angular_impulse_kg_m2_s})
        if(!std::isfinite(limit)||limit<0)throw std::invalid_argument("invalid point contact roundoff budget");
    if(impl_->pins_.contains(striker))throw std::invalid_argument("point contact cannot bypass a world attachment");
    {
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(striker));
        if(!lock.Succeeded())throw std::runtime_error("cannot lock point contact striker");
        const auto &body=lock.GetBody();
        if(!body.IsDynamic()||body.GetMotionProperties()->GetAllowedDOFs()!=JPH::EAllowedDOFs::All)
            throw std::invalid_argument("point contact requires an unrestricted dynamic striker");
    }
    const auto before=mechanicalState(striker);
    auto symmetric=before;
    double tensor_scale=0;
    for(const auto &row:before.inertia_world_kg_m2.m)for(double entry:row)
        tensor_scale=std::max(tensor_scale,std::abs(entry));
    for(unsigned i=0;i<3;++i)for(unsigned j=i+1;j<3;++j) {
        const double a=before.inertia_world_kg_m2.m[i][j],b=before.inertia_world_kg_m2.m[j][i];
        if(std::abs(a-b)>1e-6*tensor_scale)
            throw std::invalid_argument("point contact runtime inertia skew exceeds float tolerance");
        symmetric.inertia_world_kg_m2.m[i][j]=symmetric.inertia_world_kg_m2.m[j][i]=.5*(a+b);
    }
    PointContactKick out;
    out.contact=evaluatePointRigidContact(point,symmetric,normal,gap,duration,settings);
    out.delivered_rigid=before;
    out.delivered_normal_speed_m_s=out.contact.relative_normal_after_m_s;
    out.delivered_slip_m_s=out.contact.slip_after_m_s;
    if(!out.contact.applied)return out;
    const auto representable=[](Vec3 value) {
        const double limit=std::numeric_limits<float>::max();
        return std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z)&&
            std::abs(value.x)<=limit&&std::abs(value.y)<=limit&&std::abs(value.z)<=limit;
    };
    const auto &candidate=out.contact.rigid.motion;
    if(!representable(candidate.linear_velocity_m_s)||!representable(candidate.angular_velocity_rad_s))
        throw std::invalid_argument("point contact velocity is not representable");
    const auto velocity=toJolt(candidate.linear_velocity_m_s),spin=toJolt(candidate.angular_velocity_rad_s);
    {
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(striker));
        if(!lock.Succeeded())throw std::runtime_error("cannot lock point contact candidate");
        const auto *motion=lock.GetBody().GetMotionProperties();
        if(!std::isfinite(velocity.LengthSq())||!std::isfinite(spin.LengthSq())||
            velocity.LengthSq()>motion->GetMaxLinearVelocity()*motion->GetMaxLinearVelocity()||
            spin.LengthSq()>motion->GetMaxAngularVelocity()*motion->GetMaxAngularVelocity())
            throw std::invalid_argument("point contact exceeds runtime velocity limits");
    }
    auto delivered=before;
    delivered.motion.linear_velocity_m_s=fromJoltVector(velocity);
    delivered.motion.angular_velocity_rad_s=fromJoltVector(spin);
    const auto audit=[&](const RigidMechanicalState &state) {
        out.delivered_rigid=state;
        const Vec3 point_j=point.mass_kg*(out.contact.node_velocity_m_s-point.velocity_m_s);
        const Vec3 source_j=before.mass_kg*(state.motion.linear_velocity_m_s-before.motion.linear_velocity_m_s);
        out.momentum_error_kg_m_s=point_j+source_j;
        out.angular_momentum_error_kg_m2_s=cross(point.position_world_m,point_j)+
            cross(before.motion.center_of_mass_world_m,source_j)+before.inertia_world_kg_m2*
            (state.motion.angular_velocity_rad_s-before.motion.angular_velocity_rad_s);
        const double point_change=.5*point.mass_kg*
            dot(out.contact.node_velocity_m_s-point.velocity_m_s,out.contact.node_velocity_m_s+point.velocity_m_s);
        out.numerical_energy_change_j=point_change+measureRigidMechanics(state).kinetic_energy_j-
            measureRigidMechanics(before).kinetic_energy_j-out.contact.impulse_work_j;
        const Vec3 relative=out.contact.node_velocity_m_s-state.motion.linear_velocity_m_s-
            cross(state.motion.angular_velocity_rad_s,point.position_world_m-state.motion.center_of_mass_world_m);
        const Vec3 unit=normal/length(normal);
        out.delivered_normal_speed_m_s=dot(relative,unit);
        out.delivered_slip_m_s=length(relative-out.delivered_normal_speed_m_s*unit);
    };
    audit(delivered);
    const auto finite=[](Vec3 value){return std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z);};
    if(!std::isfinite(out.numerical_energy_change_j)||!finite(out.momentum_error_kg_m_s)||
        !finite(out.angular_momentum_error_kg_m2_s)||
        std::abs(out.numerical_energy_change_j)>budget.energy_j||
        length(out.momentum_error_kg_m_s)>budget.linear_impulse_n_s||
        length(out.angular_momentum_error_kg_m2_s)>budget.angular_impulse_kg_m2_s)
        throw std::invalid_argument("point contact exceeds runtime roundoff budget");
    auto &bodies=impl_->physics_->GetBodyInterface();
    bodies.SetLinearAndAngularVelocity(impl_->bodies_.at(striker),velocity,spin);
    audit(mechanicalState(striker));
    point.velocity_m_s=out.contact.node_velocity_m_s;
    return out;
}
struct PreparedFixedPointContact::Data {
    std::shared_ptr<const int> identity;
    std::uint64_t tick{};
    std::uint64_t epoch{};
    MatterBodyId proxy{},striker{};
    JPH::BodyID native_proxy;
    std::vector<JPH::BodyID> native_bodies;
    std::vector<JPH::RefConst<JPH::Shape>> shapes;
    std::vector<RigidMechanicalState> before;
    ActiveNodeState point;
    Vec3 normal{};double gap{},duration{};
    PointRigidContactSettings settings;
    PointContactRoundoffBudget budget;
    FixedPointContactKick receipt;
};
const FixedPointContactKick &PreparedFixedPointContact::receipt() const {
    if(!data_)throw std::invalid_argument("empty prepared fixed contact");
    return data_->receipt;
}
std::shared_ptr<PreparedFixedPointContact::Data> JoltWorld::prepareExternalFixedAssembly(
    MatterBodyId proxy,MatterBodyId striker,double duration,const PointContactRoundoffBudget &budget) const {
    impl_->requireFixedContactMutable();
    if(!std::isfinite(duration)||duration<=0)throw std::invalid_argument("invalid fixed assembly contact duration");
    if(!contains(proxy)||!contains(striker)||proxy==striker)
        throw std::invalid_argument("fixed point contact needs distinct existing source and target proxy");
    for(double limit:{budget.energy_j,budget.linear_impulse_n_s,budget.angular_impulse_kg_m2_s})
        if(!std::isfinite(limit)||limit<0)throw std::invalid_argument("invalid fixed contact roundoff budget");
    std::unordered_map<MatterBodyId,std::vector<unsigned>> adjacent;
    for(const auto &[id,joint]:impl_->joints_) {
        adjacent[joint.a].push_back(id);adjacent[joint.b].push_back(id);
    }
    std::set<MatterBodyId> members{striker};std::set<unsigned> joint_ids;
    std::vector<MatterBodyId> queue{striker};
    for(std::size_t k=0;k<queue.size();++k) {
        const auto at=queue[k];
        for(auto id:adjacent[at]) {
            const auto &joint=impl_->joints_.at(id);
            if(joint.kind!=JointKind::Fixing||joint.one_way||!joint.constraint->GetEnabled())
                throw std::invalid_argument("fixed contact encountered an unsupported joint");
            if(pairContactOwner(joint.a,joint.b)!=PairContactOwner::External)
                throw std::invalid_argument("fixed contact seam has duplicate native surface ownership");
            joint_ids.insert(id);
            const auto next=joint.a==at?joint.b:joint.a;
            if(next==proxy)throw std::invalid_argument("target proxy belongs to the striker assembly");
            if(members.insert(next).second)queue.push_back(next);
            if(members.size()>256)throw std::invalid_argument("fixed contact assembly exceeds 256 bodies");
        }
    }
    for(const auto &[id,spring]:impl_->springs_) {
        (void)id;
        if(members.contains(spring.a)||members.contains(spring.b))
            throw std::invalid_argument("fixed contact cannot bypass a native distance spring");
    }
    FixedPointContactKick out;out.body_ids.assign(members.begin(),members.end());
    out.joint_ids.assign(joint_ids.begin(),joint_ids.end());
    std::unordered_map<MatterBodyId,std::uint32_t> index;
    std::vector<RigidMechanicalState> before;
    for(std::uint32_t i=0;i<out.body_ids.size();++i) {
        const auto id=out.body_ids[i];index.emplace(id,i);
        if(pairContactOwner(proxy,id)!=PairContactOwner::External||impl_->pins_.contains(id))
            throw std::invalid_argument("fixed contact requires unpinned external target ownership for every member");
        {
            JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(id));
            if(!lock.Succeeded())throw std::runtime_error("cannot lock fixed contact member");
            const auto &body=lock.GetBody();
            if(!body.IsDynamic()||body.GetMotionProperties()->GetAllowedDOFs()!=JPH::EAllowedDOFs::All)
                throw std::invalid_argument("fixed contact requires unrestricted dynamic members");
        }
        before.push_back(mechanicalState(id));const auto &state=before.back();
        double scale=0;for(const auto &row:state.inertia_world_kg_m2.m)for(double entry:row)scale=std::max(scale,std::abs(entry));
        for(unsigned a=0;a<3;++a)for(unsigned b=a+1;b<3;++b) {
            const double x=state.inertia_world_kg_m2.m[a][b],y=state.inertia_world_kg_m2.m[b][a];
            if(std::abs(x-y)>1e-6*scale)throw std::invalid_argument("fixed contact runtime tensor skew exceeds float tolerance");
        }
    }
    for(auto id:out.joint_ids) {
        const auto &joint=impl_->joints_.at(id);
        const auto *fixed=static_cast<const JPH::FixedConstraint *>(joint.constraint.GetPtr());
        const auto a=index.at(joint.a),b=index.at(joint.b);
        const auto attachment=[](const RigidMechanicalState &body,JPH::Vec3Arg local) {
            return body.motion.center_of_mass_world_m+body.motion.orientation_world.rotate(fromJoltVector(local));
        };
        out.links.push_back({a,b,attachment(before[a],fixed->GetConstraintToBody1Matrix().GetTranslation()),
            attachment(before[b],fixed->GetConstraintToBody2Matrix().GetTranslation())});
    }
    auto data=std::make_shared<PreparedFixedPointContact::Data>();
    data->identity=impl_->contact_plan_identity_;data->tick=impl_->tick_.load(std::memory_order_relaxed);
    data->epoch=impl_->contact_plan_epoch_;data->proxy=proxy;data->striker=striker;
    data->native_proxy=impl_->bodies_.at(proxy);data->before=before;data->duration=duration;
    data->budget=budget;data->receipt=out;
    for(auto id:out.body_ids) {
        data->native_bodies.push_back(impl_->bodies_.at(id));
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(id));
        if(!lock.Succeeded())throw std::runtime_error("cannot lock prepared fixed assembly shape");
        data->shapes.emplace_back(lock.GetBody().GetShape());
    }
    return data;
}
PreparedFixedPointContact JoltWorld::prepareExternalFixedPointContact(MatterBodyId proxy,MatterBodyId striker,
    const ActiveNodeState &point,Vec3 normal,double gap,double duration,
    const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget) const {
    auto data=prepareExternalFixedAssembly(proxy,striker,duration,budget);
    const auto &before=data->before;auto out=data->receipt;auto symmetric=before;
    for(auto &body:symmetric)for(unsigned a=0;a<3;++a)for(unsigned b=a+1;b<3;++b)
        body.inertia_world_kg_m2.m[a][b]=body.inertia_world_kg_m2.m[b][a]=
            .5*(body.inertia_world_kg_m2.m[a][b]+body.inertia_world_kg_m2.m[b][a]);
    const auto striker_index=static_cast<std::uint32_t>(std::find(out.body_ids.begin(),out.body_ids.end(),striker)-out.body_ids.begin());
    out.contact=evaluatePointFixedAssemblyContact(point,symmetric,out.links,striker_index,normal,gap,duration,settings);
    out.delivered_bodies=before;
    out.delivered_normal_speed_m_s=out.contact.modal_contact.relative_normal_after_m_s;
    out.delivered_slip_m_s=out.contact.modal_contact.slip_after_m_s;
    const auto finish=[&]() {
        data->point=point;data->normal=normal;data->gap=gap;
        data->settings=settings;data->receipt=out;
        PreparedFixedPointContact prepared;prepared.data_=data;return prepared;
    };
    if(!out.contact.modal_contact.applied)return finish();
    const auto representable=[](Vec3 v) {
        const double limit=std::numeric_limits<float>::max();
        return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z)&&
            std::abs(v.x)<=limit&&std::abs(v.y)<=limit&&std::abs(v.z)<=limit;
    };
    for(std::size_t i=0;i<out.body_ids.size();++i) {
        const auto &candidate=out.contact.bodies[i].motion;
        if(!representable(candidate.linear_velocity_m_s)||!representable(candidate.angular_velocity_rad_s))
            throw std::invalid_argument("fixed contact velocity is not representable");
        const auto velocity=toJolt(candidate.linear_velocity_m_s),spin=toJolt(candidate.angular_velocity_rad_s);
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(out.body_ids[i]));
        if(!lock.Succeeded())throw std::runtime_error("cannot lock fixed contact candidate");
        const auto *motion=lock.GetBody().GetMotionProperties();
        if(!std::isfinite(velocity.LengthSq())||!std::isfinite(spin.LengthSq())||
            velocity.LengthSq()>motion->GetMaxLinearVelocity()*motion->GetMaxLinearVelocity()||
            spin.LengthSq()>motion->GetMaxAngularVelocity()*motion->GetMaxAngularVelocity())
            throw std::invalid_argument("fixed contact exceeds runtime velocity limits");
        out.delivered_bodies[i].motion.linear_velocity_m_s=fromJoltVector(velocity);
        out.delivered_bodies[i].motion.angular_velocity_rad_s=fromJoltVector(spin);
    }
    const auto audit=[&]() {
        const Vec3 point_j=point.mass_kg*(out.contact.modal_contact.node_velocity_m_s-point.velocity_m_s);
        out.momentum_error_kg_m_s=point_j;
        out.angular_momentum_error_kg_m2_s=cross(point.position_world_m,point_j)-out.contact.geometry_couple_kg_m2_s;
        double source_change=0;
        for(std::size_t i=0;i<before.size();++i) {
            const auto &state=out.delivered_bodies[i];const auto &old=before[i];
            const Vec3 j=old.mass_kg*(state.motion.linear_velocity_m_s-old.motion.linear_velocity_m_s);
            out.momentum_error_kg_m_s+=j;
            out.angular_momentum_error_kg_m2_s+=cross(old.motion.center_of_mass_world_m,j)+old.inertia_world_kg_m2*
                (state.motion.angular_velocity_rad_s-old.motion.angular_velocity_rad_s);
            source_change+=measureRigidMechanics(state).kinetic_energy_j-measureRigidMechanics(old).kinetic_energy_j;
        }
        const double point_change=.5*point.mass_kg*dot(out.contact.modal_contact.node_velocity_m_s-point.velocity_m_s,
            out.contact.modal_contact.node_velocity_m_s+point.velocity_m_s);
        out.numerical_energy_change_j=source_change+point_change+out.contact.reconciliation_loss_j+
            out.contact.modal_contact.dissipated_energy_j;
        const auto &source=out.delivered_bodies[striker_index].motion;
        const Vec3 relative=out.contact.modal_contact.node_velocity_m_s-source.linear_velocity_m_s-
            cross(source.angular_velocity_rad_s,point.position_world_m-source.center_of_mass_world_m);
        const Vec3 unit=normal/length(normal);out.delivered_normal_speed_m_s=dot(relative,unit);
        out.delivered_slip_m_s=length(relative-out.delivered_normal_speed_m_s*unit);
    };
    audit();
    const auto finite=[](Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);};
    if(!std::isfinite(out.numerical_energy_change_j)||!finite(out.momentum_error_kg_m_s)||!finite(out.angular_momentum_error_kg_m2_s)||
        std::abs(out.numerical_energy_change_j)>budget.energy_j||length(out.momentum_error_kg_m_s)>budget.linear_impulse_n_s||
        length(out.angular_momentum_error_kg_m2_s)>budget.angular_impulse_kg_m2_s)
        throw std::invalid_argument("fixed contact exceeds runtime roundoff budget");
    return finish();
}
FixedPointContactKick JoltWorld::commitExternalFixedPointContact(const PreparedFixedPointContact &prepared,ActiveNodeState &point) {
    impl_->requireFixedContactMutable();
    if(!prepared.data_||prepared.data_->identity!=impl_->contact_plan_identity_||
        prepared.data_->tick!=impl_->tick_.load(std::memory_order_relaxed)||prepared.data_->epoch!=impl_->contact_plan_epoch_)
        throw std::invalid_argument("prepared fixed contact belongs to another world, elapsed tick or abandoned trial");
    const auto equal=[](Vec3 a,Vec3 b){return a.x==b.x&&a.y==b.y&&a.z==b.z;};
    const auto &saved=*prepared.data_;
    if(!equal(point.position_world_m,saved.point.position_world_m)||!equal(point.previous_position_world_m,saved.point.previous_position_world_m)||
        !equal(point.velocity_m_s,saved.point.velocity_m_s)||!equal(point.spin_angular_velocity_rad_s,saved.point.spin_angular_velocity_rad_s)||
        point.mass_kg!=saved.point.mass_kg)
        throw std::invalid_argument("prepared fixed contact target point changed");
    // Recompute admission and numerical preflight against current native inputs.
    const auto checked=prepareExternalFixedPointContact(saved.proxy,saved.striker,point,saved.normal,saved.gap,saved.duration,saved.settings,saved.budget);
    const auto &now=*checked.data_;
    if(saved.native_proxy!=now.native_proxy||saved.native_bodies!=now.native_bodies||
        saved.receipt.body_ids!=now.receipt.body_ids||saved.receipt.joint_ids!=now.receipt.joint_ids)
        throw std::invalid_argument("prepared fixed contact topology or proxy changed");
    for(std::size_t i=0;i<saved.before.size();++i) {
        const auto &a=saved.before[i],&b=now.before[i];const auto &qa=a.motion.orientation_world,&qb=b.motion.orientation_world;
        if(saved.shapes[i].GetPtr()!=now.shapes[i].GetPtr()||a.mass_kg!=b.mass_kg||a.inertia_world_kg_m2.m!=b.inertia_world_kg_m2.m||
            !equal(a.motion.center_of_mass_world_m,b.motion.center_of_mass_world_m)||!equal(a.motion.linear_velocity_m_s,b.motion.linear_velocity_m_s)||
            !equal(a.motion.angular_velocity_rad_s,b.motion.angular_velocity_rad_s)||qa.w!=qb.w||qa.x!=qb.x||qa.y!=qb.y||qa.z!=qb.z)
            throw std::invalid_argument("prepared fixed contact source motion, mass or shape changed");
    }
    for(std::size_t i=0;i<saved.receipt.links.size();++i) {
        const auto &a=saved.receipt.links[i],&b=now.receipt.links[i];
        if(a.a!=b.a||a.b!=b.b||!equal(a.point_a_world_m,b.point_a_world_m)||!equal(a.point_b_world_m,b.point_b_world_m))
            throw std::invalid_argument("prepared fixed contact attachment changed");
    }
    auto out=now.receipt;
    if(!out.contact.modal_contact.applied)return out;
    auto &bodies=impl_->physics_->GetBodyInterface();
    for(std::size_t i=0;i<out.body_ids.size();++i)
        bodies.SetLinearAndAngularVelocity(impl_->bodies_.at(out.body_ids[i]),toJolt(out.delivered_bodies[i].motion.linear_velocity_m_s),
            toJolt(out.delivered_bodies[i].motion.angular_velocity_rad_s));
    for(std::size_t i=0;i<out.body_ids.size();++i)out.delivered_bodies[i]=mechanicalState(out.body_ids[i]);
    point.velocity_m_s=out.contact.modal_contact.node_velocity_m_s;
    return out;
}
struct PreparedFixedSurfaceManifold::Data {
    PreparedFixedPointContact assembly;
    std::vector<ActiveNodeState> nodes;
    std::vector<FixedSurfaceContact> contacts;
    PointContactRoundoffBudget budget;
    FixedSurfaceManifoldKick receipt;
};
const FixedSurfaceManifoldKick &PreparedFixedSurfaceManifold::receipt() const {
    if(!data_)throw std::invalid_argument("empty prepared fixed manifold");return data_->receipt;
}
PreparedFixedSurfaceManifold JoltWorld::prepareExternalFixedSurfaceManifold(MatterBodyId proxy,MatterBodyId striker,
    std::span<const ActiveNodeState> nodes,const std::vector<FixedSurfaceContact> &contacts,double dt,
    const PointContactRoundoffBudget &budget) const {
    impl_->requireFixedContactMutable();
    if(contacts.empty()||contacts.size()>64||nodes.size()<4||nodes.size()>64)
        throw std::invalid_argument("invalid native manifold node/contact count");
    // Inspect actual ownership/tree/shape metadata without inventing an
    // isolated first-contact response. Only the full manifold is solved.
    auto data=std::make_shared<PreparedFixedSurfaceManifold::Data>();
    auto assembly_data=prepareExternalFixedAssembly(proxy,striker,dt,budget);
    data->assembly.data_=std::move(assembly_data);
    data->nodes.assign(nodes.begin(),nodes.end());data->contacts=contacts;data->budget=budget;
    const auto &assembly=*data->assembly.data_;
    auto source=assembly.before;
    for(auto &body:source)for(unsigned a=0;a<3;++a)for(unsigned b=a+1;b<3;++b)
        body.inertia_world_kg_m2.m[a][b]=body.inertia_world_kg_m2.m[b][a]=
            .5*(body.inertia_world_kg_m2.m[a][b]+body.inertia_world_kg_m2.m[b][a]);
    auto &out=data->receipt;out.body_ids=assembly.receipt.body_ids;
    out.joint_ids=assembly.receipt.joint_ids;out.links=assembly.receipt.links;
    const auto at=std::find(out.body_ids.begin(),out.body_ids.end(),striker)-out.body_ids.begin();
    out.contact=evaluateFixedSurfaceManifold(nodes,contacts,source,assembly.receipt.links,static_cast<std::uint32_t>(at),dt);
    out.delivered_bodies=assembly.before;
    if(out.contact.active_contacts)for(std::size_t i=0;i<out.body_ids.size();++i) {
        const auto &candidate=out.contact.bodies[i].motion;
        const auto velocity=toJolt(candidate.linear_velocity_m_s),spin=toJolt(candidate.angular_velocity_rad_s);
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),impl_->bodies_.at(out.body_ids[i]));
        if(!lock.Succeeded())throw std::runtime_error("cannot lock manifold source candidate");
        const auto *motion=lock.GetBody().GetMotionProperties();
        if(!std::isfinite(velocity.LengthSq())||!std::isfinite(spin.LengthSq())||
            velocity.LengthSq()>motion->GetMaxLinearVelocity()*motion->GetMaxLinearVelocity()||
            spin.LengthSq()>motion->GetMaxAngularVelocity()*motion->GetMaxAngularVelocity())
            throw std::invalid_argument("manifold exceeds runtime velocity limits");
        out.delivered_bodies[i].motion.linear_velocity_m_s=fromJoltVector(velocity);
        out.delivered_bodies[i].motion.angular_velocity_rad_s=fromJoltVector(spin);
    }
    double energy=out.contact.dissipated_energy_j+out.contact.reconciliation_loss_j;
    for(std::size_t i=0;i<nodes.size();++i) {
        const auto j=nodes[i].mass_kg*(out.contact.node_velocities_m_s[i]-nodes[i].velocity_m_s);
        out.momentum_error_kg_m_s+=j;out.angular_momentum_error_kg_m2_s+=cross(nodes[i].position_world_m,j);
        energy+=.5*dot(j,out.contact.node_velocities_m_s[i]+nodes[i].velocity_m_s);
    }
    out.angular_momentum_error_kg_m2_s-=out.contact.geometry_couple_kg_m2_s;
    for(std::size_t i=0;i<source.size();++i) {
        const auto &old=assembly.before[i];const auto &body=out.delivered_bodies[i];
        const auto j=old.mass_kg*(body.motion.linear_velocity_m_s-old.motion.linear_velocity_m_s);
        out.momentum_error_kg_m_s+=j;
        out.angular_momentum_error_kg_m2_s+=cross(old.motion.center_of_mass_world_m,j)+
            old.inertia_world_kg_m2*(body.motion.angular_velocity_rad_s-old.motion.angular_velocity_rad_s);
        energy+=measureRigidMechanics(body).kinetic_energy_j-measureRigidMechanics(old).kinetic_energy_j;
    }
    out.numerical_energy_change_j=energy;
    if(!std::isfinite(energy)||std::abs(energy)>budget.energy_j||
        length(out.momentum_error_kg_m_s)>budget.linear_impulse_n_s||
        length(out.angular_momentum_error_kg_m2_s)>budget.angular_impulse_kg_m2_s)
        throw std::invalid_argument("manifold exceeds native roundoff budget");
    PreparedFixedSurfaceManifold prepared;prepared.data_=std::move(data);return prepared;
}
FixedSurfaceManifoldKick JoltWorld::commitExternalFixedSurfaceManifold(const PreparedFixedSurfaceManifold &prepared) {
    impl_->requireFixedContactMutable();
    if(!prepared.data_)throw std::invalid_argument("empty prepared native manifold");
    const auto &saved=*prepared.data_;const auto &before=*saved.assembly.data_;
    if(before.identity!=impl_->contact_plan_identity_||before.tick!=impl_->tick_.load(std::memory_order_relaxed)||
        before.epoch!=impl_->contact_plan_epoch_)throw std::invalid_argument("stale native manifold owner/tick/trial");
    const auto checked=prepareExternalFixedSurfaceManifold(before.proxy,before.striker,saved.nodes,saved.contacts,before.duration,saved.budget);
    const auto &now=*checked.data_->assembly.data_;
    if(before.native_proxy!=now.native_proxy||before.native_bodies!=now.native_bodies||
        before.receipt.joint_ids!=now.receipt.joint_ids||before.receipt.body_ids!=now.receipt.body_ids)
        throw std::invalid_argument("prepared manifold topology changed");
    const auto equal=[](Vec3 a,Vec3 b){return a.x==b.x&&a.y==b.y&&a.z==b.z;};
    for(std::size_t i=0;i<before.before.size();++i) {
        const auto &a=before.before[i],&b=now.before[i];const auto &qa=a.motion.orientation_world,&qb=b.motion.orientation_world;
        if(before.shapes[i].GetPtr()!=now.shapes[i].GetPtr()||a.mass_kg!=b.mass_kg||a.inertia_world_kg_m2.m!=b.inertia_world_kg_m2.m||
            !equal(a.motion.center_of_mass_world_m,b.motion.center_of_mass_world_m)||!equal(a.motion.linear_velocity_m_s,b.motion.linear_velocity_m_s)||
            !equal(a.motion.angular_velocity_rad_s,b.motion.angular_velocity_rad_s)||qa.w!=qb.w||qa.x!=qb.x||qa.y!=qb.y||qa.z!=qb.z)
            throw std::invalid_argument("prepared manifold source/shape changed");
    }
    for(std::size_t i=0;i<before.receipt.links.size();++i) {
        const auto &a=before.receipt.links[i],&b=now.receipt.links[i];
        if(a.a!=b.a||a.b!=b.b||!equal(a.point_a_world_m,b.point_a_world_m)||!equal(a.point_b_world_m,b.point_b_world_m))
            throw std::invalid_argument("prepared manifold attachment changed");
    }
    auto out=checked.receipt();
    if(out.contact.active_contacts) {
        auto &native=impl_->physics_->GetBodyInterface();
        for(std::size_t i=0;i<out.body_ids.size();++i)
            native.SetLinearAndAngularVelocity(impl_->bodies_.at(out.body_ids[i]),
                toJolt(out.delivered_bodies[i].motion.linear_velocity_m_s),toJolt(out.delivered_bodies[i].motion.angular_velocity_rad_s));
        for(std::size_t i=0;i<out.body_ids.size();++i)out.delivered_bodies[i]=mechanicalState(out.body_ids[i]);
    }
    return out;
}
FixedPointContactKick JoltWorld::applyExternalFixedPointContact(MatterBodyId proxy,MatterBodyId striker,
    ActiveNodeState &point,Vec3 normal,double gap,double duration,
    const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget) {
    return commitExternalFixedPointContact(prepareExternalFixedPointContact(proxy,striker,point,normal,gap,duration,settings,budget),point);
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
                          double max_distance_m, std::optional<MatterBodyId> ignore_body) const {
    return castRayIgnoring(from_world_m, direction, max_distance_m,
                          ignore_body ? std::span<const MatterBodyId>(&*ignore_body, 1) : std::span<const MatterBodyId>{});
}

RayHit JoltWorld::castRayIgnoring(const Vec3 &from_world_m, const Vec3 &direction,
                                 double max_distance_m, std::span<const MatterBodyId> ignore_bodies) const {
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
    JPH::IgnoreMultipleBodiesFilter filter;
    for (const auto id : ignore_bodies)
        if (const auto ignored = impl_->bodies_.find(id); ignored != impl_->bodies_.end())
            filter.IgnoreBody(ignored->second);
    if(!impl_->physics_->GetNarrowPhaseQuery().CastRay(ray,result, {}, {}, filter))return out;
    out.hit=true;
    out.distance_m=static_cast<double>(result.mFraction)*max_distance_m;
    out.point_world_m=from_world_m+static_cast<double>(result.mFraction)*along;
    // Jolt answers with its own body id; the caller speaks in ours. Something
    // with no id of ours still stopped the ray and is still reported.
    for(const auto &[id,body]:impl_->bodies_)
        if(body==result.mBodyID){out.named=true;out.body_id=id;break;}
    return out;
}

namespace {
// A body's shape, read under the body's lock and held after it: the queries
// that use it take locks of their own, and asking them while holding this one
// could wait on itself.
[[nodiscard]] JPH::RefConst<JPH::Shape> shapeOf(const JPH::PhysicsSystem &physics, JPH::BodyID id) {
    JPH::BodyLockRead lock(physics.GetBodyLockInterface(), id);
    if (!lock.Succeeded()) throw std::runtime_error("rigid body is not readable");
    return lock.GetBody().GetShape();
}
[[nodiscard]] JPH::Quat joltTurn(const Quat &q) {
    return JPH::Quat(static_cast<float>(q.x), static_cast<float>(q.y), static_cast<float>(q.z),
                     static_cast<float>(q.w)).Normalized();
}
}  // namespace

std::pair<Vec3, Vec3> JoltWorld::shapeBoundsTurned(MatterBodyId body_id,
                                                   const Quat &orientation_world) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    const JPH::RefConst<JPH::Shape> shape = shapeOf(*impl_->physics_, found->second);
    const JPH::AABox box = shape->GetWorldSpaceBounds(JPH::Mat44::sRotation(joltTurn(orientation_world)),
                                                      JPH::Vec3::sReplicate(1.0f));
    return {Vec3{box.mMin.GetX(), box.mMin.GetY(), box.mMin.GetZ()},
            Vec3{box.mMax.GetX(), box.mMax.GetY(), box.mMax.GetZ()}};
}

PointShapeQuery JoltWorld::pointShapeContacts(MatterBodyId body_id,Vec3 point,
    double radius,double separation,unsigned maximum_contacts) const {
    auto shapes=materialShapeContacts(body_id,point,{PrimitiveKind::Sphere,radius,{}},{},separation,maximum_contacts);
    return {shapes.geometry.radius_m,shapes.separation_limit_m,std::move(shapes.contacts)};
}

struct MaterialShapeBinding::Data {
    std::shared_ptr<const int> identity;
    std::uint64_t tick{},epoch{};
    MatterBodyId body{};
    JPH::BodyID native_body;
    JPH::RefConst<JPH::Shape> shape;
    RigidMechanicalState state;
    CompiledContactMaterial contact;
    std::vector<CompiledContactMaterial> part_contacts;
};
MaterialShapeBinding JoltWorld::bindMaterialShape(MatterBodyId body_id) const {
    const auto found=impl_->bodies_.find(body_id);
    if(found==impl_->bodies_.end())throw std::invalid_argument("material geometry binding body is missing");
    auto data=std::make_shared<MaterialShapeBinding::Data>();
    data->identity=impl_->contact_plan_identity_;data->tick=stepCount();data->epoch=impl_->contact_plan_epoch_;
    data->body=body_id;data->native_body=found->second;data->shape=shapeOf(*impl_->physics_,found->second);
    data->state=mechanicalState(body_id);
    const auto &material=impl_->contact_states_.at(body_id);
    data->contact=material.contact;data->part_contacts=material.part_contacts;
    MaterialShapeBinding out;out.data_=std::move(data);return out;
}
MaterialShapeQuery JoltWorld::materialShapeContacts(MatterBodyId body_id,Vec3 point,
    const RigidPrimitive &geometry,Quat orientation,double separation,unsigned maximum_contacts,
    MaterialContactGeometry contact_geometry) const {
    return materialShapeContactsImpl(body_id,point,geometry,orientation,separation,maximum_contacts,contact_geometry,nullptr,nullptr);
}
MaterialShapeQuery JoltWorld::materialShapeContactsAtPose(const MaterialShapeBinding &binding,
    RigidShapePose pose,Vec3 point,const RigidPrimitive &geometry,Quat orientation,double separation,
    unsigned maximum_contacts,MaterialContactGeometry contact_geometry) const {
    if(!binding.data_)throw std::invalid_argument("empty material geometry binding");
    return materialShapeContactsImpl(binding.data_->body,point,geometry,orientation,separation,maximum_contacts,contact_geometry,&binding,&pose);
}
MaterialShapeQuery JoltWorld::materialShapeContactsImpl(MatterBodyId body_id,Vec3 point,
    const RigidPrimitive &geometry,Quat orientation,double separation,unsigned maximum_contacts,
    MaterialContactGeometry contact_geometry,const MaterialShapeBinding *binding,const RigidShapePose *pose) const {
    const auto finite=[](Vec3 value){return std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z);};
    const double q2=orientation.w*orientation.w+orientation.x*orientation.x+orientation.y*orientation.y+orientation.z*orientation.z;
    if(!finite(point)||!std::isfinite(q2)||std::abs(q2-1)>1e-6||
        !std::isfinite(separation)||separation<0||separation>1||maximum_contacts==0||maximum_contacts>256||
        (contact_geometry!=MaterialContactGeometry::ClosestPoint&&contact_geometry!=MaterialContactGeometry::ClippedFace))
        throw std::invalid_argument("invalid material native shape query or budget");
    if(pose) {
        const auto q=pose->orientation_world;
        const double norm=q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z;
        if(!finite(pose->center_of_mass_world_m)||!std::isfinite(norm)||std::abs(norm-1)>1e-10)
            throw std::invalid_argument("invalid external material shape pose");
    }
    MaterialShapeQuery result;result.geometry=geometry;result.contact_geometry=contact_geometry;
    const auto envelope_turn=joltTurn(orientation);
    result.orientation_world={double(envelope_turn.GetW()),double(envelope_turn.GetX()),
        double(envelope_turn.GetY()),double(envelope_turn.GetZ())};
    JPH::RefConst<JPH::Shape> envelope;
    if(geometry.kind==PrimitiveKind::Sphere) {
        if(!std::isfinite(geometry.radius_m)||geometry.radius_m<1e-6||geometry.radius_m>100)
            throw std::invalid_argument("invalid material sphere envelope");
        result.geometry.radius_m=double(float(geometry.radius_m));
        envelope=new JPH::SphereShape(float(result.geometry.radius_m));
    } else if(geometry.kind==PrimitiveKind::Box) {
        const auto d=geometry.dimensions_m;
        if(!finite(d)||std::min({d.x,d.y,d.z})<2e-6||std::max({d.x,d.y,d.z})>200)
            throw std::invalid_argument("invalid material cuboid envelope");
        const auto half=toJolt(d/2);result.geometry.dimensions_m=2*fromJoltVector(half);
        envelope=new JPH::BoxShape(half,0); // Occupied sharp cell, not an inscribed sphere.
    } else throw std::invalid_argument("unsupported material envelope kind");
    const auto found=impl_->bodies_.find(body_id);
    if(found==impl_->bodies_.end())throw std::invalid_argument("point shape query body is missing");
    JPH::TransformedShape source;
    {
        JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),found->second);
        if(!lock.Succeeded())throw std::runtime_error("cannot lock point query shape");
        source=lock.GetBody().GetTransformedShape();
    }
    if(binding) {
        const auto &data=*binding->data_;
        if(data.identity!=impl_->contact_plan_identity_||data.tick!=stepCount()||data.epoch!=impl_->contact_plan_epoch_||
            data.native_body!=found->second||data.shape.GetPtr()!=source.mShape.GetPtr())
            throw std::invalid_argument("stale or foreign material geometry binding");
        const auto state=mechanicalState(body_id);const auto &a=data.state.motion,&b=state.motion;
        const auto p=a.orientation_world,q=b.orientation_world;
        if(state.mass_kg!=data.state.mass_kg||state.inertia_world_kg_m2.m!=data.state.inertia_world_kg_m2.m||
            length(a.center_of_mass_world_m-b.center_of_mass_world_m)!=0||
            length(a.linear_velocity_m_s-b.linear_velocity_m_s)!=0||length(a.angular_velocity_rad_s-b.angular_velocity_rad_s)!=0||
            p.w!=q.w||p.x!=q.x||p.y!=q.y||p.z!=q.z)
            throw std::invalid_argument("bound native dynamics changed during external geometry ownership");
        const auto key=[](const CompiledContactMaterial &c){return std::tie(c.static_friction,c.dynamic_friction,c.rolling_resistance,
            c.restitution,c.contact_damping_ratio,c.young_modulus_pa,c.poisson_ratio);};
        const auto &material=impl_->contact_states_.at(body_id);
        if(key(data.contact)!=key(material.contact)||data.part_contacts.size()!=material.part_contacts.size())
            throw std::invalid_argument("bound material identity changed");
        for(std::size_t i=0;i<data.part_contacts.size();++i)if(key(data.part_contacts[i])!=key(material.part_contacts[i]))
            throw std::invalid_argument("bound leaf material identity changed");
    }
    const Vec3 source_com=pose?pose->center_of_mass_world_m:fromJoltPosition(source.mShapePositionCOM);
    if(pose)source.mShapeRotation=joltTurn(pose->orientation_world);
    result.external_source_pose=pose!=nullptr;
    result.source_pose_world={source_com,{double(source.mShapeRotation.GetW()),double(source.mShapeRotation.GetX()),
        double(source.mShapeRotation.GetY()),double(source.mShapeRotation.GetZ())}};
    // Subtract the double world origin before converting the local collision
    // frame to float. A distant world must not collapse centimetre geometry.
    const Vec3 offset=source_com-point;
    const double relative_limit=std::sqrt(double(std::numeric_limits<float>::max()))/8;
    if(!finite(offset)||std::hypot(offset.x,offset.y,offset.z)>relative_limit)
        throw std::invalid_argument("point shape query exceeds native relative range");
    result.source_offset_roundoff_m=fromJoltVector(toJolt(offset))-offset;
    float search=float(separation);
    if(double(search)<separation)search=std::nextafter(search,std::numeric_limits<float>::infinity());
    result.separation_limit_m=double(search);
    JPH::CollideShapeSettings settings;
    settings.mMaxSeparationDistance=search;
    if(contact_geometry==MaterialContactGeometry::ClippedFace)
        settings.mCollectFacesMode=JPH::ECollectFacesMode::CollectFaces;
    settings.mActiveEdgeMode=JPH::EActiveEdgeMode::CollideWithAll;
    settings.mBackFaceMode=JPH::EBackFaceMode::CollideWithBackFaces;
    class BoundedCollector final : public JPH::CollideShapeCollector {
    public:
        explicit BoundedCollector(unsigned limit):limit_(limit) {hits.reserve(limit);}
        void AddHit(const JPH::CollideShapeResult &hit) override {
            if(hits.size()==limit_) {overflow=true;ForceEarlyOut();return;}
            hits.push_back(hit);
        }
        std::vector<JPH::CollideShapeResult> hits;
        bool overflow{};
    private:
        unsigned limit_;
    } collector(maximum_contacts);
    JPH::CollisionDispatch::sCollideShapeVsShape(envelope.GetPtr(),source.mShape.GetPtr(),
        JPH::Vec3::sReplicate(1),source.GetShapeScale(),JPH::Mat44::sRotation(envelope_turn),
        JPH::Mat44::sRotationTranslation(source.mShapeRotation,toJolt(offset)),
        JPH::SubShapeIDCreator(),source.mSubShapeIDCreator,settings,collector);
    if(collector.overflow)throw std::length_error("material-point native contact witness budget exceeded");
    const auto &material=impl_->contact_states_.at(body_id);
    result.contacts.reserve(collector.hits.size());
    for(const auto &hit:collector.hits) {
        const Vec3 axis=fromJoltVector(hit.mPenetrationAxis);
        const double axis_length=std::hypot(axis.x,axis.y,axis.z);
        const Vec3 on_source=fromJoltVector(hit.mContactPointOn2),on_envelope=fromJoltVector(hit.mContactPointOn1);
        if(!finite(axis)||!std::isfinite(axis_length)||axis_length<=0||!finite(on_source)||!finite(on_envelope)||
            !std::isfinite(hit.mPenetrationDepth))
            throw std::domain_error("native material-point witness is unresolved");
        PointShapeContact contact;
        contact.gap_m=-double(hit.mPenetrationDepth);
        contact.normal_world=-axis/axis_length;
        contact.point_on_body_world_m=point+on_source;
        contact.point_on_envelope_world_m=point+on_envelope;
        contact.sub_shape_id=hit.mSubShapeID2.GetValue();
        contact.shape_user_data=source.GetSubShapeUserData(hit.mSubShapeID2);
        contact.body_contact=material.contact;
        if(!material.part_contacts.empty()) {
            const auto index=contact.shape_user_data;
            if(index<1||index>material.part_contacts.size())
                throw std::domain_error("native contact leaf has no declared material");
            contact.body_contact=material.part_contacts[std::size_t(index-1)];
        }
        const auto append=[&](Vec3 body_point,Vec3 envelope_point,double gap) {
            auto candidate=contact;candidate.point_on_body_world_m=point+body_point;
            candidate.point_on_envelope_world_m=point+envelope_point;candidate.gap_m=gap;
            if(!finite(candidate.point_on_body_world_m)||!finite(candidate.point_on_envelope_world_m)||!std::isfinite(gap))
                throw std::invalid_argument("native contact world witness exceeds finite range");
            if(result.contacts.size()==maximum_contacts)
                throw std::length_error("material native face contact witness budget exceeded");
            result.contacts.push_back(candidate);
        };
        if(contact_geometry==MaterialContactGeometry::ClosestPoint)append(on_source,on_envelope,contact.gap_m);
        else {
            JPH::ContactPoints on1,on2;
            // Use the same native supporting faces and clipping as Jolt's
            // manifold construction. Include every clipped point (no pruning
            // or centroid substitution); each retains its own signed gap.
            // Native single-point fallback remains explicit for curved/edge
            // cases whose supporting faces do not span a patch.
            JPH::ManifoldBetweenTwoFaces(hit.mContactPointOn1,hit.mContactPointOn2,hit.mPenetrationAxis,
                std::max(search,std::numeric_limits<float>::min()),hit.mShape1Face,hit.mShape2Face,on1,on2
                JPH_IF_DEBUG_RENDERER(,toJoltPosition(point)));
            if(on1.size()!=on2.size()||on1.empty())throw std::domain_error("native face clipping returned invalid points");
            for(JPH::ContactPoints::size_type i=0;i<on1.size();++i) {
                const auto envelope_point=fromJoltVector(on1[i]),body_point=fromJoltVector(on2[i]);
                append(body_point,envelope_point,dot(envelope_point-body_point,contact.normal_world));
            }
        }
    }
    std::sort(result.contacts.begin(),result.contacts.end(),[](const PointShapeContact &a,const PointShapeContact &b) {
        if(a.shape_user_data!=b.shape_user_data)return a.shape_user_data<b.shape_user_data;
        if(a.sub_shape_id!=b.sub_shape_id)return a.sub_shape_id<b.sub_shape_id;
        if(a.gap_m!=b.gap_m)return a.gap_m<b.gap_m;
        if(a.normal_world.x!=b.normal_world.x)return a.normal_world.x<b.normal_world.x;
        if(a.normal_world.y!=b.normal_world.y)return a.normal_world.y<b.normal_world.y;
        if(a.normal_world.z!=b.normal_world.z)return a.normal_world.z<b.normal_world.z;
        return std::tie(a.point_on_body_world_m.x,a.point_on_body_world_m.y,a.point_on_body_world_m.z,
            a.point_on_envelope_world_m.x,a.point_on_envelope_world_m.y,a.point_on_envelope_world_m.z)<
            std::tie(b.point_on_body_world_m.x,b.point_on_body_world_m.y,b.point_on_body_world_m.z,
            b.point_on_envelope_world_m.x,b.point_on_envelope_world_m.y,b.point_on_envelope_world_m.z);
    });
    return result;
}

std::vector<PlacementOverlap> JoltWorld::overlapsAt(MatterBodyId body_id, const Vec3 &center_of_mass_world_m,
                                                    const Quat &orientation_world, double tolerance_m) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    const JPH::RefConst<JPH::Shape> shape = shapeOf(*impl_->physics_, found->second);
    const JPH::RVec3 at = toJoltPosition(center_of_mass_world_m);
    JPH::CollideShapeSettings settings;
    JPH::AllHitCollisionCollector<JPH::CollideShapeCollector> collector;
    const JPH::IgnoreSingleBodyFilter itself(found->second);
    impl_->physics_->GetNarrowPhaseQuery().CollideShape(
        shape.GetPtr(), JPH::Vec3::sReplicate(1.0f),
        JPH::RMat44::sRotationTranslation(joltTurn(orientation_world), at), settings, at, collector,
        {}, {}, itself);
    // One entry per thing it meets: the deepest meeting with it.
    std::vector<PlacementOverlap> out;
    for (const JPH::CollideShapeResult &hit : collector.mHits) {
        const double depth = static_cast<double>(hit.mPenetrationDepth);
        if (!(depth > tolerance_m)) continue;
        PlacementOverlap met{};
        met.depth_m = depth;
        met.point_world_m = center_of_mass_world_m + Vec3{hit.mContactPointOn2.GetX(),
                                                          hit.mContactPointOn2.GetY(),
                                                          hit.mContactPointOn2.GetZ()};
        for (const auto &[id, body] : impl_->bodies_)
            if (body == hit.mBodyID2) { met.named = true; met.body_id = id; break; }
        const auto same = std::find_if(out.begin(), out.end(), [&](const PlacementOverlap &o) {
            return o.named == met.named && o.body_id == met.body_id;
        });
        if (same == out.end()) out.push_back(met);
        else if (met.depth_m > same->depth_m) *same = met;
    }
    std::sort(out.begin(), out.end(),
              [](const PlacementOverlap &a, const PlacementOverlap &b) { return a.depth_m > b.depth_m; });
    return out;
}

void JoltWorld::setDrivenContact(MatterBodyId body_id, bool driven) {
    if (driven) impl_->impact_collector_.driven.insert(body_id);
    else impl_->impact_collector_.driven.erase(body_id);
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

unsigned JoltWorld::addGroundPatch(const std::vector<float> &heights, unsigned count, double spacing_m,
                                   double origin_x_m, double origin_z_m,
                                   const MaterialDefinition &material, double max_error_m) {
    impl_->requireConfigurationMutable();
    const JPH::RefConst<JPH::Shape> shape =
        groundShape(heights, count, spacing_m, origin_x_m, origin_z_m, max_error_m);
    const CompiledContactMaterial contact = compileContactMaterial(material);
    JPH::BodyCreationSettings settings(shape.GetPtr(), JPH::RVec3::sZero(), JPH::Quat::sIdentity(),
                                       JPH::EMotionType::Static, Layers::kNonMoving);
    settings.mFriction = static_cast<float>(contact.dynamic_friction);
    settings.mRestitution = static_cast<float>(contact.restitution);
    settings.mUserData = kGroundPatchMatterId;
    const JPH::BodyID id =
        impl_->physics_->GetBodyInterface().CreateAndAddBody(settings, JPH::EActivation::DontActivate);
    if (id.IsInvalid()) throw std::runtime_error("Jolt could not create a ground patch");
    impl_->ground_.push_back({id, count, spacing_m, origin_x_m, origin_z_m});
    impl_->contact_states_[kGroundPatchMatterId] = {contact, 0.0, 0.0, false};
    return static_cast<unsigned>(impl_->ground_.size());
}

unsigned JoltWorld::addGroundTriangles(const std::vector<std::array<Vec3,3>> &triangles,
                                      const MaterialDefinition &material) {
    impl_->requireConfigurationMutable();
    const auto shape=groundTriangleShape(triangles);
    const auto contact=compileContactMaterial(material);
    JPH::BodyCreationSettings settings(shape.GetPtr(),JPH::RVec3::sZero(),JPH::Quat::sIdentity(),
                                       JPH::EMotionType::Static,Layers::kNonMoving);
    settings.mFriction=float(contact.dynamic_friction);settings.mRestitution=float(contact.restitution);
    settings.mUserData=kGroundPatchMatterId;
    const auto id=impl_->physics_->GetBodyInterface().CreateAndAddBody(settings,JPH::EActivation::DontActivate);
    if(id.IsInvalid())throw std::runtime_error("Jolt could not create ground mesh");
    impl_->ground_.push_back({id,0,0,0,0});
    impl_->contact_states_[kGroundPatchMatterId]={contact,0,0,false};
    return unsigned(impl_->ground_.size());
}

void JoltWorld::replaceGroundTriangles(unsigned patch,const std::vector<std::array<Vec3,3>> &triangles) {
    impl_->requireConfigurationMutable();
    if(patch==0 || patch>impl_->ground_.size() || impl_->ground_[patch-1].count!=0)
        throw std::invalid_argument("there is no such ground mesh patch");
    const auto shape=groundTriangleShape(triangles);
    impl_->physics_->GetBodyInterface().SetShape(impl_->ground_[patch-1].body,shape.GetPtr(),false,
                                                 JPH::EActivation::DontActivate);
}

void JoltWorld::replaceGroundPatch(unsigned patch, const std::vector<float> &heights, double max_error_m) {
    impl_->requireConfigurationMutable();
    if (patch == 0 || patch > impl_->ground_.size()) throw std::invalid_argument("there is no such ground patch");
    const Impl::GroundPatch &ground = impl_->ground_[patch - 1];
    const JPH::RefConst<JPH::Shape> shape =
        groundShape(heights, ground.count, ground.spacing, ground.origin_x, ground.origin_z, max_error_m);
    // A new shape swapped in whole: the old one is released when nothing holds
    // it any more, so a query that had it keeps a shape that is still valid.
    impl_->physics_->GetBodyInterface().SetShape(ground.body, shape.GetPtr(), false,
                                                 JPH::EActivation::DontActivate);
}

unsigned JoltWorld::addRoofPatch(const std::vector<float> &down_from, unsigned count,
                                 double spacing_m, double origin_x_m, double origin_z_m,
                                 double hang_from_m, const MaterialDefinition &material,
                                 double max_error_m) {
    impl_->requireConfigurationMutable();
    const JPH::RefConst<JPH::Shape> shape = groundShape(down_from, count, spacing_m, 0.0, 0.0, max_error_m);
    const CompiledContactMaterial contact = compileContactMaterial(material);
    // Half a turn about X takes (x, y, z) to (x, -y, -z): the surface faces
    // down, and the patch's own z runs backwards, which is why the caller hands
    // the rows over backwards too.
    const JPH::Quat turned = JPH::Quat::sRotation(JPH::Vec3::sAxisX(), 3.14159265358979323846F);
    JPH::BodyCreationSettings settings(
        shape.GetPtr(),
        JPH::RVec3(origin_x_m, hang_from_m, origin_z_m + (count - 1) * spacing_m), turned,
        JPH::EMotionType::Static, Layers::kNonMoving);
    settings.mFriction = static_cast<float>(contact.dynamic_friction);
    settings.mRestitution = static_cast<float>(contact.restitution);
    settings.mUserData = kGroundPatchMatterId;
    const JPH::BodyID id =
        impl_->physics_->GetBodyInterface().CreateAndAddBody(settings, JPH::EActivation::DontActivate);
    if (id.IsInvalid()) throw std::runtime_error("Jolt could not create a roof patch");
    impl_->ground_.push_back({id, count, spacing_m, origin_x_m, origin_z_m});
    impl_->contact_states_[kGroundPatchMatterId] = {contact, 0.0, 0.0, false};
    return static_cast<unsigned>(impl_->ground_.size());
}

void JoltWorld::replaceRoofPatch(unsigned patch, const std::vector<float> &down_from,
                                 double max_error_m) {
    impl_->requireConfigurationMutable();
    if (patch == 0 || patch > impl_->ground_.size()) throw std::invalid_argument("there is no such ground patch");
    const Impl::GroundPatch &ground = impl_->ground_[patch - 1];
    const JPH::RefConst<JPH::Shape> shape = groundShape(down_from, ground.count, ground.spacing, 0.0, 0.0, max_error_m);
    impl_->physics_->GetBodyInterface().SetShape(ground.body, shape.GetPtr(), false,
                                                 JPH::EActivation::DontActivate);
}

std::size_t JoltWorld::groundPatchCount() const { return impl_->ground_.size(); }

unsigned JoltWorld::wakeBodiesIn(const Vec3 &low_world_m, const Vec3 &high_world_m) {
    const JPH::uint32 before = impl_->physics_->GetNumActiveBodies(JPH::EBodyType::RigidBody);
    impl_->physics_->GetBodyInterface().ActivateBodiesInAABox(
        JPH::AABox(toJolt(low_world_m), toJolt(high_world_m)), {}, {});
    const JPH::uint32 after = impl_->physics_->GetNumActiveBodies(JPH::EBodyType::RigidBody);
    return after > before ? after - before : 0U;
}

unsigned JoltWorld::awakeBodies() const {
    return impl_->physics_->GetNumActiveBodies(JPH::EBodyType::RigidBody);
}

bool JoltWorld::isAwake(MatterBodyId body_id) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) return false;
    return impl_->physics_->GetBodyInterface().IsActive(found->second);
}

// ---- a tool's point in the ground (docs/ground-work.md) ---------------------

void JoltWorld::suspendGroundContact(MatterBodyId body_id, const GroundPointRegion &region) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    const double along = length(region.pointing_local);
    if (!(along > 1e-9) || !std::isfinite(along) || !(region.length_m >= 0.0) ||
        !(region.radius_m >= 0.0) || !(region.margin_m >= 0.0) || !(region.ahead_m >= 0.0))
        throw std::invalid_argument("a point's region needs a direction and sizes of zero or more");
    GroundSuspension kept;
    kept.region = region;
    kept.region.pointing_local = (1.0 / along) * region.pointing_local;
    // A tool made of cells has its point picked out cell by cell: every cell
    // whose centre lies within the point -- no further back from the tip than
    // its length less half a cell, near its line -- and no other. A quarter
    // of a cell of slack each way, so a centre on the line is not lost to
    // rounding.
    if (const auto cells = impl_->cell_shapes_.find(body_id); cells != impl_->cell_shapes_.end()) {
        const double cell = cells->second.first;
        const GroundPointRegion &r = kept.region;
        kept.by_cell = true;
        for (const Impl::CellShape &c : cells->second.second) {
            const Vec3 from_tip = c.centre - r.tip_local_m;
            const double back = -dot(from_tip, r.pointing_local);
            const Vec3 radial = from_tip + back * r.pointing_local;
            if (back >= -0.75 * cell && back <= r.length_m - 0.25 * cell &&
                length(radial) <= r.radius_m + 0.25 * cell)
                kept.cells.push_back(c.id);
        }
        std::sort(kept.cells.begin(), kept.cells.end());
    }
    const bool fresh = !impl_->ground_suspended_.contains(body_id);
    impl_->ground_suspended_[body_id] = std::move(kept);
    // A manifold the cache kept from before was judged without the region.
    if (fresh) impl_->physics_->GetBodyInterface().InvalidateContactCache(found->second);
}

void JoltWorld::restoreGroundContact(MatterBodyId body_id) {
    impl_->requireConfigurationMutable();
    if (impl_->ground_suspended_.erase(body_id) == 0) return;
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) return;
    auto &bodies = impl_->physics_->GetBodyInterface();
    bodies.InvalidateContactCache(found->second);
    bodies.ActivateBody(found->second);
}

bool JoltWorld::groundContactSuspended(MatterBodyId body_id) const {
    return impl_->ground_suspended_.contains(body_id);
}

void JoltWorld::setManifoldReduction(MatterBodyId body_id, bool enabled) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    impl_->physics_->GetBodyInterface().SetUseManifoldReduction(found->second, enabled);
}

void JoltWorld::setCollisionCells(MatterBodyId body_id, const std::vector<Vec3> &cells_local_m,
                                  double cell_m) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    if (cells_local_m.empty() || !(cell_m > 0.0) || !std::isfinite(cell_m))
        throw std::invalid_argument("a body collides as at least one cell of positive size");
    auto &bodies = impl_->physics_->GetBodyInterface();
    // Scenery already collides as its cells (addFragments).
    if (bodies.GetMotionType(found->second) != JPH::EMotionType::Dynamic) return;
    // Round like every other moving box (kSweepRadiusM), so a tool lying on
    // something does not start its sweep already touching it.
    const JPH::Vec3 half = JPH::Vec3::sReplicate(static_cast<float>(0.5 * cell_m));
    const JPH::RefConst<JPH::Shape> cell = new JPH::BoxShape(half, sweepRadius(half));
    JPH::StaticCompoundShapeSettings compound;
    for (const Vec3 &centre : cells_local_m)
        compound.AddShape(toJolt(centre), JPH::Quat::sIdentity(), cell.GetPtr());
    const JPH::ShapeSettings::ShapeResult built = compound.Create();
    if (!built.IsValid()) {
        const JPH::String &error = built.GetError();
        throw std::runtime_error("Jolt could not build a body from its cells: " +
                                 std::string(error.begin(), error.end()));
    }
    const JPH::RefConst<JPH::Shape> inner = built.Get();
    // The cells are placed about the body's centre of mass, which is where the
    // body's own frame is; the shape's centre is put there too, so swapping it
    // moves nothing.
    const JPH::RefConst<JPH::Shape> shape =
        new JPH::OffsetCenterOfMassShape(inner.GetPtr(), -inner->GetCenterOfMass());
    bodies.SetShape(found->second, shape.GetPtr(), false, JPH::EActivation::Activate);
    bodies.InvalidateContactCache(found->second);
    // Where each cell ended up in the compound and what Jolt calls it. The
    // decorator passes sub-shape ids straight through to the compound.
    const auto *cells = static_cast<const JPH::CompoundShape *>(inner.GetPtr());
    const JPH::Vec3 centre = inner->GetCenterOfMass();
    std::vector<Impl::CellShape> named;
    named.reserve(cells->GetNumSubShapes());
    for (JPH::uint i = 0; i < cells->GetNumSubShapes(); ++i)
        named.push_back({fromJoltVector(cells->GetSubShape(i).GetPositionCOM() + centre),
                         cells->GetSubShapeIDFromIndex(static_cast<int>(i), JPH::SubShapeIDCreator())
                             .GetID()
                             .GetValue()});
    impl_->cell_shapes_[body_id] = {cell_m, std::move(named)};
}

unsigned JoltWorld::addGroundBite(const GroundBiteDescription &d) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(d.tool);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("a bite needs its tool in the world");
    if (impl_->joints_.size() >= 4096) throw std::invalid_argument("joint budget exceeded");
    const double into = length(d.into_world);
    if (!(into > 1e-9) || !std::isfinite(into))
        throw std::invalid_argument("a bite needs the way the point goes in");
    if (!(d.resist_into_n >= 0.0) || !(d.resist_x_n >= 0.0) || !(d.resist_z_n >= 0.0) ||
        !std::isfinite(d.resist_into_n + d.resist_x_n + d.resist_z_n))
        throw std::invalid_argument("a bite's resistance is newtons, zero or more");
    const Vec3 y = (1.0 / into) * d.into_world;
    // Squared up against the way in, so "roughly across" is enough.
    Vec3 x = d.across_x_world - dot(d.across_x_world, y) * y;
    if (!(length(x) > 1e-6)) x = cross(y, Vec3{0.0, 1.0, 0.0});
    if (!(length(x) > 1e-6)) x = cross(y, Vec3{1.0, 0.0, 0.0});
    x = normalized(x);

    using Axis = JPH::SixDOFConstraintSettings::EAxis;
    JPH::SixDOFConstraintSettings settings;
    settings.mSpace = JPH::EConstraintSpace::WorldSpace;
    settings.mPosition1 = settings.mPosition2 = toJoltPosition(d.point_world_m);
    settings.mAxisX1 = settings.mAxisX2 = toJolt(x);
    settings.mAxisY1 = settings.mAxisY2 = toJolt(y);
    settings.mSwingType = JPH::ESwingType::Pyramid;
    for (const Axis axis : {Axis::TranslationX, Axis::TranslationY, Axis::TranslationZ,
                            Axis::RotationX, Axis::RotationY, Axis::RotationZ})
        settings.MakeFreeAxis(axis);
    settings.mMaxFriction[Axis::TranslationX] = static_cast<float>(d.resist_x_n);
    settings.mMaxFriction[Axis::TranslationZ] = static_cast<float>(d.resist_z_n);
    // Body 1 is the tool and body 2 the world, so Jolt's constraint velocity
    // along Y is the world's less the tool's: a tool going in is negative, and
    // a motor driving it to zero pushes with a positive impulse -- the tool
    // back out along -Y. The force limits [0, R] let it push out with up to R
    // and never pull in.
    auto *raw = impl_->physics_->GetBodyInterface().CreateConstraint(&settings, found->second,
                                                                      JPH::BodyID());
    if (!raw) throw std::runtime_error("a bite could not be made");
    auto *bite = static_cast<JPH::SixDOFConstraint *>(raw);
    bite->GetMotorSettings(Axis::TranslationY)
        .SetForceLimits(0.0F, static_cast<float>(d.resist_into_n));
    bite->SetTargetVelocityCS(JPH::Vec3::sZero());
    bite->SetMotorState(Axis::TranslationY, JPH::EMotorState::Velocity);
    // Against the world, which does not move, so no light-body correction is
    // needed (see addKerf); enough iterations to deliver the limit exactly.
    raw->SetNumVelocityStepsOverride(static_cast<JPH::uint>(kWarmKerfSteps));
    raw->SetNumPositionStepsOverride(6);
    const auto id = impl_->next_joint_++;
    impl_->joints_.emplace(id, Impl::Joint{d.tool, kGroundPatchMatterId, JointKind::GroundBite,
                                           static_cast<JPH::TwoBodyConstraint *>(raw)});
    impl_->physics_->AddConstraint(raw);
    impl_->physics_->GetBodyInterface().ActivateBody(found->second);
    return id;
}

void JoltWorld::updateGroundBite(unsigned joint, double resist_into_n, double resist_x_n,
                                 double resist_z_n) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::GroundBite) return;
    if (!(resist_into_n >= 0.0) || !(resist_x_n >= 0.0) || !(resist_z_n >= 0.0) ||
        !std::isfinite(resist_into_n + resist_x_n + resist_z_n))
        throw std::invalid_argument("a bite's resistance is newtons, zero or more");
    using Axis = JPH::SixDOFConstraintSettings::EAxis;
    auto *bite = static_cast<JPH::SixDOFConstraint *>(found->second.constraint.GetPtr());
    bite->GetMotorSettings(Axis::TranslationY).SetForceLimits(0.0F, static_cast<float>(resist_into_n));
    bite->SetMaxFriction(Axis::TranslationX, static_cast<float>(resist_x_n));
    bite->SetMaxFriction(Axis::TranslationZ, static_cast<float>(resist_z_n));
}

Vec3 JoltWorld::groundBiteImpulse(unsigned joint) const {
    const auto found = impl_->joints_.find(joint);
    if (found == impl_->joints_.end() || found->second.kind != JointKind::GroundBite) return {};
    // The motor along Y and the frictions along X and Z are all Jolt's
    // translation MOTOR parts, as the kerf's are (kerfImpulse).
    const JPH::Vec3 impulse = static_cast<const JPH::SixDOFConstraint *>(found->second.constraint.GetPtr())
                                  ->GetTotalLambdaMotorTranslation();
    return {static_cast<double>(impulse.GetX()), static_cast<double>(impulse.GetY()),
            static_cast<double>(impulse.GetZ())};
}

void JoltWorld::setGroundRollingResistance(std::function<double(double, double)> surface_at) {
    impl_->requireConfigurationMutable();
    impl_->ground_rolling_at_ = std::move(surface_at);
}

std::vector<JoltWorld::RollingContactReport> JoltWorld::rollingContacts() const {
    return impl_->rolling_report_;
}

double JoltWorld::rollingLossJ() const { return impl_->rolling_loss_j_; }

double JoltWorld::rollingLossJ(MatterBodyId body_id) const {
    const auto found = impl_->rolling_loss_of_.find(body_id);
    return found == impl_->rolling_loss_of_.end() ? 0.0 : found->second;
}

void JoltWorld::setMass(MatterBodyId body_id, double mass_kg) {
    impl_->requireConfigurationMutable();
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

void JoltWorld::reshapePrimitive(MatterBodyId body_id, bool sphere, const Vec3 &d,
                                 const double rotation_wxyz[4], double mass_kg, const Vec3 &inertia,
                                 bool activate) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    const bool sized = std::isfinite(d.x) && d.x > 0.0 &&
                       (sphere || (std::isfinite(d.y) && d.y > 0.0 && std::isfinite(d.z) && d.z > 0.0));
    if (!sized) throw std::invalid_argument("a reshaped body needs a positive, finite size");
    JPH::RefConst<JPH::Shape> authored;
    if (sphere) {
        authored = new JPH::SphereShape(static_cast<float>(0.5 * d.x));
    } else {
        const JPH::Vec3 half = toJolt(d / 2);
        authored = new JPH::BoxShape(half, sweepRadius(half));
    }
    JPH::Quat turn = JPH::Quat::sIdentity();
    if (rotation_wxyz != nullptr &&
        (rotation_wxyz[1] != 0.0 || rotation_wxyz[2] != 0.0 || rotation_wxyz[3] != 0.0)) {
        turn = JPH::Quat(static_cast<float>(rotation_wxyz[1]), static_cast<float>(rotation_wxyz[2]),
                         static_cast<float>(rotation_wxyz[3]), static_cast<float>(rotation_wxyz[0]))
                   .Normalized();
        authored = new JPH::RotatedTranslatedShape(JPH::Vec3::sZero(), turn, authored);
    }
    // Centred on the body's centre of mass, as every authored shape here is.
    const JPH::RefConst<JPH::Shape> centred =
        new JPH::OffsetCenterOfMassShape(authored.GetPtr(), -authored->GetCenterOfMass());
    JPH::BodyInterface &bodies = impl_->physics_->GetBodyInterface();
    bodies.SetShape(found->second, centred.GetPtr(), false,
                    activate ? JPH::EActivation::Activate : JPH::EActivation::DontActivate);
    const auto state = impl_->contact_states_.find(body_id);
    if (state != impl_->contact_states_.end() && state->second.is_sphere) state->second.radius_m = 0.5 * d.x;
    if (bodies.GetMotionType(found->second) == JPH::EMotionType::Static) return;
    if (!(mass_kg > 0.0) || !std::isfinite(mass_kg) || !(inertia.x > 0.0) || !(inertia.y > 0.0) ||
        !(inertia.z > 0.0) || !std::isfinite(inertia.x + inertia.y + inertia.z))
        throw std::invalid_argument("a reshaped body's mass and inertia are positive and finite");
    JPH::BodyLockWrite lock(impl_->physics_->GetBodyLockInterface(), found->second);
    if (!lock.Succeeded()) throw std::runtime_error("cannot lock a body to reshape it");
    JPH::MotionProperties *motion = lock.GetBody().GetMotionProperties();
    // Installed directly, as addBox does: the principal axes are known, and
    // Jolt's own diagonalisation substitutes a unit sphere for small inertias.
    motion->SetInverseMass(static_cast<float>(1.0 / mass_kg));
    motion->SetInverseInertia(JPH::Vec3(static_cast<float>(1.0 / inertia.x), static_cast<float>(1.0 / inertia.y),
                                        static_cast<float>(1.0 / inertia.z)),
                              turn);
    if (state != impl_->contact_states_.end()) state->second.mass_kg = mass_kg;
}

void JoltWorld::pushBodyAt(MatterBodyId body_id, const Vec3 &force_n, const Vec3 &point_world_m) {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    auto &bodies = impl_->physics_->GetBodyInterface();
    if (bodies.GetMotionType(found->second) == JPH::EMotionType::Static) return;
    bodies.AddForce(found->second, toJolt(force_n), toJoltPosition(point_world_m));
}

void JoltWorld::twistBody(MatterBodyId body_id, const Vec3 &torque_n_m) {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    auto &bodies = impl_->physics_->GetBodyInterface();
    if (bodies.GetMotionType(found->second) == JPH::EMotionType::Static) return;
    bodies.AddTorque(found->second, toJolt(torque_n_m));
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

void JoltWorld::sleep(MatterBodyId body_id) {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    auto &bodies = impl_->physics_->GetBodyInterface();
    // Scenery is never awake, and has no motion to stop.
    if (bodies.GetMotionType(found->second) == JPH::EMotionType::Static) return;
    bodies.DeactivateBody(found->second);
}

JoltWorld::BodySurface JoltWorld::surfaceOf(MatterBodyId body_id) const {
    const auto found = impl_->contact_states_.find(body_id);
    if (found == impl_->contact_states_.end()) throw std::invalid_argument("rigid body is missing");
    const CompiledContactMaterial &contact = found->second.contact;
    return {contact.dynamic_friction, contact.restitution, contact.rolling_resistance};
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
        bool round{};
        double radius_m{};
        double mass_kg{};
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
                const JPH::Vec3 half = toJolt(fragment.primitive_dimensions_m / 2);
                authored = new JPH::BoxShape(half, sweepRadius(half));
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
            // Round like a box (kSweepRadiusM); Jolt takes less off a hull too
            // thin for it.
            JPH::ConvexHullShapeSettings hull_settings(
                hull_points.data(),
                static_cast<int>(hull_points.size()),
                kSweepRadiusM);
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
                fragment.friction, fragment.restitution, fragment.rolling_resistance);
            // A whole ball is round: it rolls, and rolling resistance acts on
            // it (docs/rolling-resistance.md). Nothing else is -- a box does
            // not roll, and a broken piece is a hull whose rolling is its own
            // shape's business: it has to lift itself over each edge.
            const bool round = fragment.primitive == FragmentPrimitive::Sphere &&
                               !fragment.anchored && fragment.primitive_dimensions_m.x > 0.0;

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
            // A whole ball carries no velocity damping. Rolling resistance is
            // what stops it now, and 0.02/s of damping was a drag of 0.02 v on
            // it besides: a quarter of a rubber ball's rolling resistance at
            // 1 m/s on the floor, and twice an iron ball's.
            settings.mLinearDamping = round ? 0.0F : 0.02F;
            settings.mAngularDamping = round ? 0.0F : 0.02F;
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
            // The inertia the piece was given, not the one Jolt would rather
            // it had.
            //
            // Jolt diagonalises the inertia it is handed, and its
            // decomposition substitutes a UNIT SPHERE for anything below its
            // epsilon. A small piece is far below it: measured, a 20 mm oak
            // chip asking for 3.73e-7 kg m2 was made with 0.00224 -- six
            // thousand times harder to turn than the matter it is made of.
            //
            // Nothing could then stop such a piece turning. Friction at its
            // contact, a knock from another piece, the rolling couple: each
            // moves it by a six-thousandth of what it should, so a chip that
            // comes off a break rolls away and keeps rolling (the owner,
            // 2026-09-22: "little pieces seem to roll forever"). Measured on
            // one set going at 0.49 m/s and 42 rad/s across concrete, which is
            // what the break room's chips do: it travelled 4.2 m in ten
            // seconds and still had three quarters of its speed. With its own
            // inertia it stops in 21 mm. It also carried rotational energy
            // that was not there -- 2 J in a 5.6 g chip, where its own matter
            // holds 0.33 mJ.
            //
            // Scaling before the decomposition and back after is what the
            // compound and reshape paths already do for exactly this reason;
            // pieces did not, and every broken piece comes through here.
            if (!fragment.anchored) {
                JPH::MassProperties scaled = settings.mMassPropertiesOverride;
                scaled.mInertia *= 1.0e6F;
                JPH::Mat44 rotation;
                JPH::Vec3 diagonal;
                if (scaled.DecomposePrincipalMomentsOfInertia(rotation, diagonal) &&
                    diagonal.GetX() > 0.0F && diagonal.GetY() > 0.0F && diagonal.GetZ() > 0.0F)
                    body->GetMotionProperties()->SetInverseInertia(
                        JPH::Vec3::sReplicate(1.0e6F) / diagonal, rotation.GetQuaternion());
            }
            pending.push_back({
                fragment.body_id,
                body->GetID(),
                fragment.mass_properties.linear_velocity_m_s,
                fragment.mass_properties.angular_velocity_rad_s,
                contact,
                round,
                0.5 * fragment.primitive_dimensions_m.x,
                fragment.mass_properties.mass_kg,
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
                BodyContactState{body.contact, body.round ? body.radius_m : 0.0, 0.4,
                                 body.round, body.mass_kg, std::nullopt});
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
const char *JoltWorld::rotationIntegrationProfile() noexcept {
#ifdef BANJO_JOLT_CONTINUOUS_SMALL_ROTATION
    return "jolt-continuous-small-rotation-v1";
#else
    return "jolt-angular-dead-zone-v1";
#endif
}

bool JoltWorld::runReversibleTrial(const std::function<bool()> &trial) {
    if (impl_->external_fixed_trial_&&impl_->trial_depth_)
        throw std::invalid_argument("native trial nesting is forbidden during a paired target trial");
    if(!trial||impl_->bodies_.size()>2048||impl_->trial_depth_>=16||
       impl_->contact_plan_epoch_>std::numeric_limits<std::uint64_t>::max()-32)
        throw std::invalid_argument("invalid reversible trial or body/depth budget exceeded");
    auto &profile=impl_->execution_profile_;
    if(profile.enabled)++profile.trial_calls;
    ExecutionWallTimer capture(profile.enabled?&profile.trial_capture_ms:nullptr);
    auto &slot=impl_->trial_recorders_[impl_->trial_depth_];
    if(!slot)slot=std::make_unique<BoundedStateRecorder>();
    auto &recorder=*slot;recorder.Reset();impl_->physics_->SaveState(recorder);
    if(recorder.IsFailed()||recorder.GetDataSize()>16U*1024U*1024U)
        throw std::runtime_error("cannot capture bounded Jolt trial state");
    auto events=impl_->impact_collector_.capture();const auto tick=impl_->tick_.load(std::memory_order_relaxed);
    const auto diagnostics=impl_->contact_diagnostics_;
    auto configuration=impl_->captureTrialConfiguration();
    // What rolling resistance carries into the next step goes back with the
    // world: a step taken back found none of the contacts it recorded.
    auto rolling=impl_->rolling_;auto rolling_report=impl_->rolling_report_;
    const double rolling_loss=impl_->rolling_loss_j_;auto rolling_loss_of=impl_->rolling_loss_of_;
    const auto restore=[&] {
        if(profile.enabled)++profile.trial_restores;
        ExecutionWallTimer restore_timer(profile.enabled?&profile.trial_restore_ms:nullptr);
        impl_->restoreTrialConfiguration(configuration);
        ++impl_->contact_plan_epoch_;
        recorder.Rewind();
        if(!impl_->physics_->RestoreState(recorder)||recorder.IsFailed())
            throw std::runtime_error("Jolt trial restore failed; discard this world");
        impl_->tick_.store(tick,std::memory_order_relaxed);impl_->impact_collector_.restore(std::move(events));
        impl_->contact_diagnostics_=diagnostics;
        impl_->rolling_=std::move(rolling);impl_->rolling_report_=std::move(rolling_report);
        impl_->rolling_loss_j_=rolling_loss;impl_->rolling_loss_of_=std::move(rolling_loss_of);
        impl_->impact_collector_.dropRolling();
    };
    capture.finish();
    ++impl_->trial_depth_;bool accepted=false;
    try {accepted=trial();}catch(...) {--impl_->trial_depth_;restore();throw;}
    --impl_->trial_depth_;if(!accepted)restore();return accepted;
}

bool JoltWorld::runExternalFixedTrial(const std::function<bool()> &trial) {
    if (!trial||impl_->external_fixed_trial_||impl_->trial_depth_||impl_->spring_trial_depth_)
        throw std::invalid_argument("paired fixed contact trial cannot nest in another native trial");
    impl_->external_fixed_trial_=true;
    try {
        const bool accepted=runReversibleTrial(trial);
        impl_->external_fixed_trial_=false;return accepted;
    } catch (...) {impl_->external_fixed_trial_=false;throw;}
}

bool JoltWorld::runSpringTrial(const std::function<bool()> &trial) {
    constexpr std::size_t kMaximumStateBytes=16U*1024U*1024U;
    constexpr unsigned kMaximumDepth=16;
    if(!trial||impl_->trial_depth_!=0||impl_->bodies_.size()>1024||
       impl_->springs_.size()>20000||impl_->spring_trial_depth_>=kMaximumDepth||
       impl_->contact_plan_epoch_>std::numeric_limits<std::uint64_t>::max()-32)
        throw std::invalid_argument("invalid spring trial or body/spring/depth budget exceeded");

    JPH::StateRecorderImpl recorder;impl_->physics_->SaveState(recorder);
    if(recorder.IsFailed()||recorder.GetDataSize()>kMaximumStateBytes)
        throw std::runtime_error("cannot capture bounded Jolt spring trial state");

    // PhysicsSystem::RestoreState addresses constraints by their current
    // indices and DistanceConstraint::SaveState omits configuration. Hold refs
    // to the exact list so removals cannot destroy constraints before rollback.
    auto configuration=impl_->captureTrialConfiguration();
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
    auto rolling=impl_->rolling_;
    auto rolling_report=impl_->rolling_report_;
    const double rolling_loss=impl_->rolling_loss_j_;
    auto rolling_loss_of=impl_->rolling_loss_of_;

    const auto restore=[&] {
        // Remove/add is intentionally done for the whole list: Jolt removes by
        // swap-with-last, so selectively re-adding removed springs cannot
        // recover the solver order required by the saved state.
        impl_->restoreTrialConfiguration(configuration);
        ++impl_->contact_plan_epoch_;
        impl_->springs_=springs;impl_->next_spring_=next_spring;
        for(const auto &[id,spring_settings]:spring_configuration) {
            auto *constraint=impl_->springs_.at(id).constraint.GetPtr();
            constraint->SetDistance(spring_settings.minimum_distance,spring_settings.maximum_distance);
            constraint->SetLimitsSpringSettings(spring_settings.settings);
        }
        recorder.Rewind();
        if(!impl_->physics_->RestoreState(recorder)||recorder.IsFailed())
            throw std::runtime_error("Jolt spring trial restore failed; discard this world");
        impl_->tick_.store(tick,std::memory_order_relaxed);
        impl_->impact_collector_.restore(std::move(events));
        impl_->contact_diagnostics_=diagnostics;
        impl_->rolling_=std::move(rolling);
        impl_->rolling_report_=std::move(rolling_report);
        impl_->rolling_loss_j_=rolling_loss;
        impl_->rolling_loss_of_=std::move(rolling_loss_of);
        impl_->impact_collector_.dropRolling();
    };

    ++impl_->spring_trial_depth_;bool accepted=false;
    try {accepted=trial();}catch(...) {--impl_->spring_trial_depth_;restore();throw;}
    --impl_->spring_trial_depth_;if(!accepted)restore();return accepted;
}

void JoltWorld::step(double fixed_dt_s) {
    if (!std::isfinite(fixed_dt_s)||fixed_dt_s <= 0.0||
        fixed_dt_s>std::numeric_limits<float>::max()||static_cast<float>(fixed_dt_s)==0.0F) {
        throw std::invalid_argument("Jolt step must be finite, positive and representable");
    }
    auto &profile=impl_->execution_profile_;
    if(profile.enabled)++profile.step_calls;
    ExecutionWallTimer prepare(profile.enabled?&profile.step_prepare_ms:nullptr);
    impl_->last_dt_s = fixed_dt_s;
    impl_->applyRollingResistance(fixed_dt_s);
    // A rope that is pulling stays pulling for the step. Jolt's distance limit
    // engages only when the two ends are AT or past the rope's length as the
    // step starts, and a rope hauled tight sits right on that line: nudged a
    // hair inside it by whatever else is being corrected, it does nothing for a
    // whole step. Measured on the courtyard bow, a string rope carrying 110.7 N
    // read 0 for one step while the 45 g limb tip it held back against a 307 N
    // limb spring left at 6.8 m/s, and the string lurched back 1.25 m/s under the
    // hand -- every few dozen steps, with nobody touching anything.
    //
    // So a rope that pulled on the last step, is within a millimetre of its
    // length, and is not being closed faster than 5 cm/s, is held AT its length
    // for this step. Anything else is left to be slack, as a rope is. If held
    // like that it has to push -- its ends being brought together -- that push
    // shows as the step's impulse, and on the next step it is slack again: a
    // rope that has started to go slack goes slack a step late, never not at
    // all. What decides is the constraint's own impulse from the last step,
    // which is part of the state a refused trial is put back to.
    constexpr float kRopeSlackM = 0.001F;
    constexpr float kRopeClosingMS = 0.05F;
    for (auto &[id, joint] : impl_->joints_) {
        if (joint.kind != JointKind::Link) continue;
        auto *rope = static_cast<JPH::DistanceConstraint *>(joint.constraint.GetPtr());
        const float length = rope->GetMaxDistance();
        const JPH::Body *one = rope->GetBody1();
        const JPH::Body *two = rope->GetBody2();
        const JPH::RVec3 here =
            one->GetCenterOfMassTransform() * rope->GetConstraintToBody1Matrix().GetTranslation();
        const JPH::RVec3 there =
            two->GetCenterOfMassTransform() * rope->GetConstraintToBody2Matrix().GetTranslation();
        const JPH::Vec3 apart(there - here);
        const float distance = apart.Length();
        bool taut = false;
        if (distance > 1e-6F && distance >= length - kRopeSlackM &&
            rope->GetTotalLambdaPosition() < 0.0F) {
            const JPH::Vec3 closing =
                two->GetPointVelocityCOM(JPH::Vec3(there - two->GetCenterOfMassPosition())) -
                one->GetPointVelocityCOM(JPH::Vec3(here - one->GetCenterOfMassPosition()));
            taut = -closing.Dot(apart / distance) < kRopeClosingMS;
        }
        rope->SetDistance(taut ? length : 0.0F, length);
    }
    auto &collector=impl_->impact_collector_;collector.manifolds=0;collector.points=0;collector.speculative_manifolds=0;
    collector.clearContactGeometry();
    impl_->observed_gravity_impulse_={};
    if(impl_->force_phase_enabled_){
        if(impl_->bodies_.size()>2048)throw std::runtime_error("native force phase observation exceeds body budget");
        impl_->force_phase_.clear();impl_->force_phase_slot_.clear();
        for(const auto id:activeBodyIds()){
            const auto state=mechanicalState(id);if(state.mass_kg==0)continue;
            const auto index=impl_->force_phase_.size();
            impl_->force_phase_slot_.emplace(impl_->bodies_.at(id).GetIndexAndSequenceNumber(),index);
            impl_->force_phase_.push_back({id,state,state.motion.angular_velocity_rad_s,state.motion.linear_velocity_m_s,state.motion.angular_velocity_rad_s,{},false});
        }
    }
    if(collector.contact_impulses_enabled){
        JPH::BodyIDVector active;impl_->physics_->GetActiveBodies(JPH::EBodyType::RigidBody,active);
        std::sort(active.begin(),active.end());
        for(const auto id:active){
            JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),id);
            if(!lock.Succeeded())throw std::runtime_error("cannot lock active gravity audit body");
            const auto &body=lock.GetBody();if(!body.IsDynamic())continue;
            const auto *motion=body.GetMotionProperties();
            const auto delta=(motion->GetGravityFactor()*impl_->physics_->GetGravity())*static_cast<float>(fixed_dt_s);
            impl_->observed_gravity_impulse_+=fromJoltVector(delta)/motion->GetInverseMass();
        }
    }
    if(impl_->centered_integration_){
        if(!impl_->springs_.empty()||!impl_->pins_.empty())throw std::logic_error("unsupported centered world constraints");
        for(const auto &[id,joint]:impl_->joints_){
            (void)id;
            if(joint.kind!=JointKind::FaceSpring||!joint.log_face)throw std::logic_error("unsupported centered world joint");
            const auto a=snapshot(joint.a),b=snapshot(joint.b);
            prepareCenteredFaceSpring(*joint.constraint.GetPtr(),a.linear_velocity_m_s,a.angular_velocity_rad_s,b.linear_velocity_m_s,b.angular_velocity_rad_s);
        }
        for(const auto &[id,native]:impl_->bodies_){
            (void)id;JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(),native);
            if(!lock.Succeeded()||(!lock.GetBody().IsStatic()&&(!lock.GetBody().IsDynamic()||lock.GetBody().GetMotionProperties()->GetMotionQuality()!=JPH::EMotionQuality::Discrete)))throw std::logic_error("centered integration requires static or discrete dynamic bodies");
        }
    }
    collector.initial_contact_motion.clear();
    if((collector.restitution_model==RigidContactRestitution::MidpointUnilateral||collector.restitution_model==RigidContactRestitution::MidpointBlockFriction)){
        for(const auto &phase:impl_->force_phase_)
            collector.initial_contact_motion.emplace(impl_->bodies_.at(phase.body).GetIndexAndSequenceNumber(),
                std::pair{phase.before.motion.linear_velocity_m_s,phase.before.motion.angular_velocity_rad_s});
    }
    impl_->tick_.fetch_add(1U, std::memory_order_relaxed);
    prepare.finish();
    ExecutionWallTimer update(profile.enabled?&profile.native_update_ms:nullptr);
    const JPH::EPhysicsUpdateError error = impl_->physics_->Update(
        static_cast<float>(fixed_dt_s),
        1,
        impl_->temp_allocator_.get(),
        impl_->job_system_.get());
    update.finish();
    {
        ExecutionWallTimer observation(profile.enabled?&profile.contact_observation_ms:nullptr);
        impl_->measureContactImpulses();
    }
    ExecutionWallTimer post(profile.enabled?&profile.post_step_ms:nullptr);
    impl_->measureRolling(fixed_dt_s);
    // Teeth that could not carry what was put through them. Read after the
    // solve, because the impulse this asks about is the one the solve just
    // applied; a gear that gives way is taken out here and is gone, so the
    // next step has two wheels turning on their own pins with nothing between
    // them, which is what a stripped drive is.
    impl_->stripped_gears_.clear();
    for (const auto &[id, limit] : impl_->gear_strength_) {
        if (!(limit > 0.0)) continue;
        const auto found = impl_->joints_.find(id);
        if (found == impl_->joints_.end()) continue;
        const auto *gear = static_cast<const JPH::GearConstraint *>(found->second.constraint.GetPtr());
        const double carried = std::abs(static_cast<double>(gear->GetTotalLambda())) / fixed_dt_s;
        if (carried > limit) impl_->stripped_gears_.push_back(id);
    }
    // In its own order, not the map's, so the same overload strips the same
    // teeth in the same order on every run (ImpactEvent.hpp says the same
    // about contacts, and for the same reason).
    std::sort(impl_->stripped_gears_.begin(), impl_->stripped_gears_.end());
    for (const unsigned id : impl_->stripped_gears_) {
        const auto found = impl_->joints_.find(id);
        if (found == impl_->joints_.end()) continue;
        impl_->physics_->RemoveConstraint(found->second.constraint.GetPtr());
        impl_->joints_.erase(found);
        impl_->gear_strength_.erase(id);
    }
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

std::vector<MatterBodyId> JoltWorld::activeBodyIds() const {
    std::vector<MatterBodyId> ids;ids.reserve(impl_->bodies_.size());
    for(const auto &[id,body]:impl_->bodies_) {(void)body;ids.push_back(id);}
    std::sort(ids.begin(),ids.end());return ids;
}
std::uint64_t JoltWorld::stepCount() const {
    return impl_->tick_.load(std::memory_order_relaxed);
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

double JoltWorld::linearDamping(MatterBodyId body_id) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::out_of_range("damped body is missing");
    JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(), found->second);
    if (!lock.Succeeded()) throw std::runtime_error("cannot lock damped body");
    const JPH::Body &body = lock.GetBody();
    return body.IsDynamic() ? static_cast<double>(body.GetMotionProperties()->GetLinearDamping())
                            : 0.0;
}

double JoltWorld::angularDamping(MatterBodyId body_id) const {
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) throw std::out_of_range("damped body is missing");
    JPH::BodyLockRead lock(impl_->physics_->GetBodyLockInterface(), found->second);
    if (!lock.Succeeded()) throw std::runtime_error("cannot lock damped body");
    const JPH::Body &body = lock.GetBody();
    return body.IsDynamic() ? static_cast<double>(body.GetMotionProperties()->GetAngularDamping())
                            : 0.0;
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

void JoltWorld::translateBody(MatterBodyId body_id, const Vec3 &by_m) {
    const auto it = impl_->bodies_.find(body_id);
    if (it == impl_->bodies_.end()) throw std::invalid_argument("rigid body is missing");
    JPH::BodyInterface &bodies = impl_->physics_->GetBodyInterface();
    bodies.SetPosition(it->second, toJoltPosition(fromJoltPosition(bodies.GetPosition(it->second)) + by_m),
                       JPH::EActivation::DontActivate);
}

bool JoltWorld::contains(MatterBodyId body_id) const {
    return impl_->bodies_.contains(body_id);
}

void JoltWorld::removeAndDestroy(MatterBodyId body_id) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) {
        // A body set aside (park) is not in the broadphase, so it is destroyed
        // and not removed. Nothing is joined to it: park refuses a body that
        // has anything on it, and nothing can be joined to one that is not in
        // the world. Its shape and its contact settings go with it.
        if (const auto set_aside = impl_->parked_.find(body_id); set_aside != impl_->parked_.end()) {
            impl_->physics_->GetBodyInterface().DestroyBody(set_aside->second);
            impl_->parked_.erase(set_aside);
            impl_->cell_shapes_.erase(body_id);
            impl_->contact_states_.erase(body_id);
        }
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
    std::erase_if(impl_->rolling_,[&](const RollingContact &c){return c.sphere==body_id||c.other==body_id;});
    impl_->ground_suspended_.erase(body_id);
    impl_->cell_shapes_.erase(body_id);
    JPH::BodyInterface &body_interface = impl_->physics_->GetBodyInterface();
    body_interface.RemoveBody(found->second);
    body_interface.DestroyBody(found->second);
    impl_->bodies_.erase(found);
    impl_->contact_states_.erase(body_id);
}

bool JoltWorld::park(MatterBodyId body_id, std::string &why) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->bodies_.find(body_id);
    if (found == impl_->bodies_.end()) {
        why = impl_->parked_.contains(body_id) ? "it is already set aside" : "rigid body is missing";
        return false;
    }
    const bool sprung = std::any_of(impl_->springs_.begin(), impl_->springs_.end(), [&](const auto &entry) {
        return entry.second.a == body_id || entry.second.b == body_id;
    });
    if (impl_->pins_.contains(body_id) || sprung || !jointsOn(body_id).empty()) {
        why = "it is fixed or joined to something: set aside, what holds it would be holding nothing";
        return false;
    }
    // What only means anything while it is in the world goes; what it IS --
    // the cells it collides as, how it meets things -- stays with it.
    std::erase_if(impl_->external_pairs_,
                  [&](const auto &pair) { return pair.first == body_id || pair.second == body_id; });
    std::erase_if(impl_->rolling_,
                  [&](const RollingContact &c) { return c.sphere == body_id || c.other == body_id; });
    impl_->ground_suspended_.erase(body_id);
    impl_->before_step_.erase(body_id);
    impl_->physics_->GetBodyInterface().RemoveBody(found->second);
    impl_->parked_.emplace(body_id, found->second);
    impl_->bodies_.erase(found);
    return true;
}

bool JoltWorld::unpark(MatterBodyId body_id, const RigidSnapshot &pose, std::string &why) {
    impl_->requireConfigurationMutable();
    const auto found = impl_->parked_.find(body_id);
    if (found == impl_->parked_.end()) {
        why = impl_->bodies_.contains(body_id) ? "it is not set aside" : "rigid body is missing";
        return false;
    }
    JPH::BodyInterface &bodies = impl_->physics_->GetBodyInterface();
    // At rest: with no velocity given, Jolt does not try to wake a body that is
    // not in the broadphase yet. AddBody puts it there, awake.
    bodies.SetPositionRotationAndVelocity(
        found->second, toJoltPosition(pose.center_of_mass_world_m),
        JPH::Quat(static_cast<float>(pose.orientation_world.x), static_cast<float>(pose.orientation_world.y),
                  static_cast<float>(pose.orientation_world.z), static_cast<float>(pose.orientation_world.w)),
        JPH::Vec3::sZero(), JPH::Vec3::sZero());
    bodies.AddBody(found->second, JPH::EActivation::Activate);
    impl_->bodies_.emplace(body_id, found->second);
    impl_->parked_.erase(found);
    return true;
}

bool JoltWorld::parked(MatterBodyId body_id) const { return impl_->parked_.contains(body_id); }

} // namespace banjo
