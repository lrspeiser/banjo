// SPIKE, not a feature: can a tunnel be made of Jolt height fields?
//
// The plan (docs/earth-and-mining-plan.md, 4.5) wants a void in the ground held
// up to the solver by the machinery that already exists -- height-field patches,
// built and swapped between steps. A column with one void needs THREE surfaces,
// not two:
//
//     y=5   ----------------****----------------    (a) the hill you walk on,
//                            ||                         with a HOLE at the shaft
//     y=2   --------++++++++++  ++++++++++-------    (c) the tunnel's ceiling:
//                   |                      |             a height field UPSIDE
//     y=1   --------++++++++++++++++++++++++-----    (b) the tunnel's floor
//
// (a) is today's ground patch with holes. (b) is an ordinary height field that
// exists only over the void. (c) is the question: the same shape on a static
// body turned half a turn about X, so its surface faces DOWN.
//
// Mirrors JoltWorld::groundShape exactly: offset (x0, 0, z0), scale (dx, 1, dx),
// cNoCollisionValue for a hole, the same block size and bits-per-sample rule.
//
// Five checks, and it prints what it measured.
#include <Jolt/Jolt.h>

#include <Jolt/Core/Factory.h>
#include <Jolt/Core/JobSystemThreadPool.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Collision/Shape/HeightFieldShape.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <Jolt/Physics/PhysicsSettings.h>
#include <Jolt/Physics/PhysicsSystem.h>
#include <Jolt/RegisterTypes.h>

#include <cmath>
#include <cstdio>

#include <vector>

#define MARK(x) do { std::printf("  .. %s\n", x); std::fflush(stdout); } while (0)

namespace Layers {
static constexpr JPH::ObjectLayer kNonMoving = 0;
static constexpr JPH::ObjectLayer kMoving = 1;
static constexpr JPH::uint kCount = 2;
} // namespace Layers

namespace BroadPhase {
static constexpr JPH::BroadPhaseLayer kNonMoving(0);
static constexpr JPH::BroadPhaseLayer kMoving(1);
static constexpr JPH::uint kCount = 2;
} // namespace BroadPhase

class Layout final : public JPH::BroadPhaseLayerInterface {
public:
    JPH::uint GetNumBroadPhaseLayers() const override { return BroadPhase::kCount; }
    JPH::BroadPhaseLayer GetBroadPhaseLayer(JPH::ObjectLayer layer) const override {
        return layer == Layers::kMoving ? BroadPhase::kMoving : BroadPhase::kNonMoving;
    }
#if defined(JPH_EXTERNAL_PROFILE) || defined(JPH_PROFILE_ENABLED)
    const char *GetBroadPhaseLayerName(JPH::BroadPhaseLayer) const override { return "layer"; }
#endif
};

class PairFilter final : public JPH::ObjectLayerPairFilter {
public:
    bool ShouldCollide(JPH::ObjectLayer a, JPH::ObjectLayer b) const override {
        return a == Layers::kMoving || b == Layers::kMoving;
    }
};

class BroadFilter final : public JPH::ObjectVsBroadPhaseLayerFilter {
public:
    bool ShouldCollide(JPH::ObjectLayer layer, JPH::BroadPhaseLayer broad) const override {
        return layer == Layers::kMoving || broad == BroadPhase::kMoving;
    }
};

namespace {

constexpr unsigned kN = 32;           // 32 x 32 points, as a chunk is
constexpr double kDx = 0.25;          // the terrain's own cell
constexpr float kHole = JPH::HeightFieldShapeConstants::cNoCollisionValue;

constexpr double kSurfaceY = 5.0;     // the hill
constexpr double kCeilingY = 2.0;     // the void's top
constexpr double kFloorY = 1.0;       // the void's bottom
constexpr double kRoofRef = 8.0;      // where the turned body hangs from

// The void: a chamber, and a shaft up through the hill inside it.
bool inChamber(unsigned i, unsigned j) { return i >= 8 && i <= 23 && j >= 8 && j <= 23; }
bool inShaft(unsigned i, unsigned j) { return i >= 14 && i <= 17 && j >= 14 && j <= 17; }

// JoltWorld::groundShape, copied so the spike measures the real thing.
JPH::RefConst<JPH::Shape> groundShape(const std::vector<float> &heights, double origin_x,
                                     double origin_z, double max_error = 0.002) {
    std::vector<float> samples(heights);
    for (float &h : samples)
        if (!std::isfinite(h)) h = kHole;
    JPH::HeightFieldShapeSettings settings(
        samples.data(), JPH::Vec3(float(origin_x), 0.0F, float(origin_z)),
        JPH::Vec3(float(kDx), 1.0F, float(kDx)), kN);
    settings.mBlockSize = (kN % 4 == 0 && kN / 4 >= 2) ? 4 : 2;
    settings.mBitsPerSample =
        std::max<JPH::uint32>(1, settings.CalculateBitsPerSampleForError(float(max_error)));
    const JPH::ShapeSettings::ShapeResult made = settings.Create();
    if (made.HasError()) {
        const JPH::String &why = made.GetError();
        std::printf("REFUSED building a patch: %s\n", std::string(why.begin(), why.end()).c_str());
        return {};
    }
    return made.Get();
}

std::vector<float> surfaceSamples() {
    std::vector<float> h(std::size_t(kN) * kN, float(kSurfaceY));
    for (unsigned j = 0; j < kN; ++j)
        for (unsigned i = 0; i < kN; ++i)
            if (inShaft(i, j)) h[std::size_t(j) * kN + i] = kHole;   // open to the sky
    return h;
}

std::vector<float> floorSamples() {
    std::vector<float> h(std::size_t(kN) * kN, kHole);
    for (unsigned j = 0; j < kN; ++j)
        for (unsigned i = 0; i < kN; ++i)
            if (inChamber(i, j)) h[std::size_t(j) * kN + i] = float(kFloorY);
    return h;
}

// The ceiling, for a body at (x0, kRoofRef, z0 + (n-1) dx) turned half a turn
// about X. That maps local (x, y, z) to world (x, -y, -z), so a sample's height
// is kRoofRef - the world height it should sit at, and the rows run backwards.
std::vector<float> ceilingSamples(double ceiling_y) {
    std::vector<float> h(std::size_t(kN) * kN, kHole);
    for (unsigned j = 0; j < kN; ++j)
        for (unsigned i = 0; i < kN; ++i) {
            const unsigned world_j = kN - 1 - j;
            if (inChamber(i, world_j) && !inShaft(i, world_j))
                h[std::size_t(j) * kN + i] = float(kRoofRef - ceiling_y);
        }
    return h;
}

struct World {
    JPH::PhysicsSystem system;
    Layout layout;
    PairFilter pairs;
    BroadFilter broad;
    JPH::BodyID ceiling;
};

JPH::BodyID addPatch(JPH::PhysicsSystem &system, const JPH::RefConst<JPH::Shape> &shape,
                     JPH::RVec3 at, JPH::Quat facing) {
    JPH::BodyCreationSettings settings(shape.GetPtr(), at, facing, JPH::EMotionType::Static,
                                       Layers::kNonMoving);
    settings.mFriction = 0.6F;
    settings.mRestitution = 0.0F;
    return system.GetBodyInterface().CreateAndAddBody(settings, JPH::EActivation::DontActivate);
}

JPH::BodyID addBall(JPH::PhysicsSystem &system, JPH::RVec3 at, JPH::Vec3 velocity, double r) {
    JPH::BodyCreationSettings settings(new JPH::SphereShape(float(r)), at, JPH::Quat::sIdentity(),
                                       JPH::EMotionType::Dynamic, Layers::kMoving);
    settings.mRestitution = 0.0F;
    settings.mLinearDamping = 0.0F;
    const JPH::BodyID id = system.GetBodyInterface().CreateAndAddBody(settings, JPH::EActivation::Activate);
    system.GetBodyInterface().SetLinearVelocity(id, velocity);
    return id;
}

struct Track {
    double highest{-1e9};
    double lowest{1e9};
    double last{};
};

} // namespace

int main() {
    MARK("start");
    JPH::RegisterDefaultAllocator();
    JPH::Factory::sInstance = new JPH::Factory();
    JPH::RegisterTypes();

    MARK("types registered");
    JPH::TempAllocatorImpl temp(16 * 1024 * 1024);
    JPH::JobSystemThreadPool jobs(JPH::cMaxPhysicsJobs, JPH::cMaxPhysicsBarriers, 2);

    MARK("allocators");
    World w;
    w.system.Init(64, 0, 1024, 1024, w.layout, w.broad, w.pairs);
    w.system.SetGravity(JPH::Vec3(0.0F, -9.81F, 0.0F));

    MARK("system init");
    const JPH::RefConst<JPH::Shape> surface = groundShape(surfaceSamples(), 0.0, 0.0);
    const JPH::RefConst<JPH::Shape> floor = groundShape(floorSamples(), 0.0, 0.0);
    const JPH::RefConst<JPH::Shape> ceiling = groundShape(ceilingSamples(kCeilingY), 0.0, 0.0);
    if (surface == nullptr || floor == nullptr || ceiling == nullptr) {
        std::printf("FAILED: a patch would not build at all\n");
        return 1;
    }

    MARK("shapes built");
    addPatch(w.system, surface, JPH::RVec3::sZero(), JPH::Quat::sIdentity());
    addPatch(w.system, floor, JPH::RVec3::sZero(), JPH::Quat::sIdentity());
    // Half a turn about X: the surface faces down.
    const JPH::Quat turned = JPH::Quat::sRotation(JPH::Vec3::sAxisX(), 3.14159265358979323846F);
    w.ceiling = addPatch(w.system, ceiling,
                         JPH::RVec3(0.0, kRoofRef, (kN - 1) * kDx), turned);

    MARK("patches added");
    w.system.OptimizeBroadPhase();

    const double r = 0.1;
    // 1. Down the shaft: through the hole in the hill, into the chamber, onto its floor.
    const JPH::BodyID down_shaft = addBall(w.system, JPH::RVec3(3.875, 6.0, 3.875), JPH::Vec3::sZero(), r);
    // 2. Up at the ceiling from inside the chamber, 8 m/s: 4.26 m of rise if nothing stops it.
    const JPH::BodyID at_ceiling = addBall(w.system, JPH::RVec3(2.5, 1.2, 2.5), JPH::Vec3(0, 8.0F, 0), r);
    // 3. Onto the hill, away from all of it.
    const JPH::BodyID on_hill = addBall(w.system, JPH::RVec3(6.5, 6.0, 6.5), JPH::Vec3::sZero(), r);
    // 4. Up from the hill where there is no ceiling: nothing invisible overhead.
    // Its own column, well clear of 3: the first run put both in one and they
    // met in mid-air, which is the spike's bug and not the model's.
    const JPH::BodyID above_hill = addBall(w.system, JPH::RVec3(1.0, 5.2, 6.5), JPH::Vec3(0, 8.0F, 0), r);

    MARK("balls added");
    Track shaft, under_roof, hill, over_hill;
    const auto watch = [&](JPH::BodyID id, Track &t) {
        const double y = w.system.GetBodyInterface().GetPosition(id).GetY();
        t.highest = std::max(t.highest, y);
        t.lowest = std::min(t.lowest, y);
        t.last = y;
    };

    MARK("stepping");
    const float dt = 1.0F / 240.0F;
    for (int step = 0; step < 240 * 4; ++step) {
        w.system.Update(dt, 1, &temp, &jobs);
        watch(down_shaft, shaft);
        watch(at_ceiling, under_roof);
        watch(on_hill, hill);
        watch(above_hill, over_hill);
    }

    MARK("stepped");
    std::printf("1 down the shaft   rest y = %.4f   (the chamber floor is %.2f, so %.4f)\n",
                shaft.last, kFloorY, kFloorY + r);
    std::printf("2 up at the roof   highest y = %.4f  (the ceiling is %.2f, so %.4f; free flight would be 4.46)\n",
                under_roof.highest, kCeilingY, kCeilingY - r);
    std::printf("3 onto the hill    rest y = %.4f   (the hill is %.2f, so %.4f)\n",
                hill.last, kSurfaceY, kSurfaceY + r);
    std::printf("4 up off the hill  highest y = %.4f  (nothing overhead: 8.46 expected)\n",
                over_hill.highest);

    const bool one = std::abs(shaft.last - (kFloorY + r)) < 0.05;
    const bool two = under_roof.highest < kCeilingY - r + 0.05 && under_roof.highest > 1.5;
    const bool three = std::abs(hill.last - (kSurfaceY + r)) < 0.05;
    const bool four = over_hill.highest > 8.0;

    // 5. Swap the ceiling for a lower one, between steps, on the turned body.
    const JPH::RefConst<JPH::Shape> lower = groundShape(ceilingSamples(1.6), 0.0, 0.0);
    bool five = false;
    if (lower != nullptr) {
        w.system.GetBodyInterface().SetShape(w.ceiling, lower.GetPtr(), false, JPH::EActivation::DontActivate);
        const JPH::BodyID again = addBall(w.system, JPH::RVec3(2.5, 1.2, 2.5), JPH::Vec3(0, 8.0F, 0), r);
        Track swapped;
        for (int step = 0; step < 240 * 2; ++step) {
            w.system.Update(dt, 1, &temp, &jobs);
            watch(again, swapped);
        }
        std::printf("5 after the swap   highest y = %.4f  (the ceiling is now 1.60, so 1.50)\n",
                    swapped.highest);
        five = swapped.highest < 1.55 && swapped.highest > 1.2;
    }

    std::printf("\n%s  1:%s 2:%s 3:%s 4:%s 5:%s\n",
                (one && two && three && four && five) ? "ALL FIVE HELD" : "SOMETHING FAILED",
                one ? "ok" : "NO", two ? "ok" : "NO", three ? "ok" : "NO", four ? "ok" : "NO",
                five ? "ok" : "NO");
    return (one && two && three && four && five) ? 0 : 1;
}
