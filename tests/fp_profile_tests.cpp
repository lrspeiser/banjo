// What the build's objects do under its floating-point profile
// (docs/floating-point-model.md), asked of the objects themselves.
//
// - The same probe (src/numeric/FpProbe.inl), compiled in banjo_core, in
//   banjo_runtime beside Jolt, and inside Jolt's own target, is fed at run time
//   -- so no compiler can fold the answer in advance -- and must find a product
//   and sum left unfused, a sum taken in the order written, NaNs unequal to
//   themselves, infinities infinite (HUGE_VAL among them, which /fp:fast
//   compiles to 1e+300), signed zeros kept and denormals not flushed; while an
//   FMA asked for explicitly, by std::fma or by Jolt's own, is fused.
// - The engine's own checks, fed a NaN at run time, refuse it: an axis, a pin, a
//   motor's command; and an anchored post's inertia stays infinite.
// - The floating-point environment of the main thread, of a plain thread and of
//   one of Jolt's worker threads rounds to nearest and flushes nothing.

#include "fastlattice/LiveWorld.hpp"
#include "numeric/FpProfile.hpp"

#include <Jolt/Jolt.h>
#include <Jolt/Core/JobSystemThreadPool.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#include <xmmintrin.h>
#define BANJO_FP_TESTS_X86 1
#endif

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

int failures = 0;

void check(bool ok, const std::string &what) {
    std::cout << (ok ? "  ok: " : "  FAILED: ") << what << "\n";
    if (!ok) ++failures;
}

std::string hex(double value) {
    char text[64];
    std::snprintf(text, sizeof text, "%a", value);
    return text;
}

// From text, at run time.
double number(const char *text) { return std::strtod(text, nullptr); }

fp::Inputs runtimeInputs() {
    fp::Inputs in;
    const double step = std::ldexp(1.0, std::atoi("-27"));
    in.near_one_up = 1.0 + step;
    in.near_one_down = 1.0 - step;
    in.minus_one = number("-1");
    in.big = number("1e16");
    in.minus_big = number("-1e16");
    in.one = number("1");
    in.nan = number("nan");
    in.inf = number("inf");
    in.zero = number("0");
    in.negative_zero = number("-0");
    in.min_normal = number("2.2250738585072014e-308");
    in.half = number("0.5");
    const double step_f = std::ldexp(1.0, std::atoi("-13"));
    in.near_one_up_f = static_cast<float>(1.0 + step_f);
    in.near_one_down_f = static_cast<float>(1.0 - step_f);
    in.minus_one_f = static_cast<float>(in.minus_one);
    in.zero_f = static_cast<float>(in.zero);
    return in;
}

void objectsKeepTheProfile(const std::string &where, const fp::Observations &o, const fp::Inputs &in) {
    const double fused = std::fma(in.near_one_up, in.near_one_down, in.minus_one);
    const float fused_f = std::fma(in.near_one_up_f, in.near_one_down_f, in.minus_one_f);
    check(o.product_sum == 0.0,
          where + ": a product and a sum are not fused (" + hex(o.product_sum) + "; fused would be " + hex(fused) + ")");
    check(o.product_sum_f == 0.0f, where + ": nor in float (" + hex(o.product_sum_f) + ")");
    check(fused != 0.0 && o.explicit_fma == fused, where + ": std::fma is fused (" + hex(o.explicit_fma) + ")");
    check(fused_f != 0.0f && o.explicit_fma_f == fused_f, where + ": and in float (" + hex(o.explicit_fma_f) + ")");
    check(o.sum_in_order == 1.0, where + ": (1e16 - 1e16) + 1 is summed in the order written (" + hex(o.sum_in_order) + ")");
    check(o.nan_unequal, where + ": a NaN is unequal to itself");
    check(o.nan_not_positive, where + ": !(NaN > 0) holds");
    check(o.nan_not_finite, where + ": a NaN is not finite");
    check(o.inf_not_finite && o.inf_is_inf, where + ": an infinity is infinite and not finite");
    check(o.huge_val_is_inf, where + ": HUGE_VAL is infinite (/fp:fast makes it 1e+300)");
    check(o.infinity_is_inf, where + ": INFINITY is infinite");
    check(o.negative_zero_sum_is_positive, where + ": -0 + +0 is +0");
    check(o.negative_zero_product_is_negative, where + ": -1 * +0 is -0");
    check(o.denormal_kept, where + ": half of DBL_MIN is a denormal, not zero");
}

void theBuildsObjectsKeepTheProfile() {
    const fp::Inputs in = runtimeInputs();
    check(std::string(fp::profile()) == "banjo-cpu-precise-v1",
          std::string("the build says it is banjo-cpu-precise-v1 (") + fp::profile() + ")");
    objectsKeepTheProfile("banjo_core", fp::observeCore(in), in);
    objectsKeepTheProfile("banjo_runtime", fp::observeRuntime(in), in);
    objectsKeepTheProfile("Jolt", fp::observeJolt(in), in);
    const float fused = std::fma(in.near_one_up_f, in.near_one_down_f, in.minus_one_f);
    const float jolt = fp::joltFusedMultiplyAdd(in.near_one_up_f, in.near_one_down_f, in.minus_one_f);
    if (fp::joltUsesFusedMultiplyAdd()) {
        check(jolt == fused, "Jolt's explicit FMA (JPH_USE_FMADD) is fused, as asked (" + hex(jolt) + ")");
    } else {
        check(jolt == 0.0f, "Jolt, built without FMA, multiplies and adds (" + hex(jolt) + ")");
    }
}

// The flywheel room of motor_tests: an iron post fixed in place, and an iron
// flywheel above it.
TileImpactRequest flywheelRoom() {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Iron;
    post.dimensions_m = {0.1, 0.8, 0.1};
    post.center_m = {0.5, 0.4, 0.0};
    post.anchored = true;
    SceneBody wheel;
    wheel.name = "flywheel";
    wheel.shape = BodyShape::Box;
    wheel.material = MaterialPreset::Iron;
    wheel.dimensions_m = {0.4, 0.1, 0.4};
    wheel.center_m = {0.5, 1.0, 0.0};
    r.bodies = {post, wheel};
    return r;
}

void theEnginesOwnChecksRefuseNaNs() {
    const fp::Inputs in = runtimeInputs();
    const auto world = LiveWorld::open(flywheelRoom());
    const Vec3 up{0.0, 1.0, 0.0};
    const Vec3 axle{0.5, 1.0, 0.0};
    const Vec3 not_an_axis{in.nan, 1.0, 0.0};
    check(std::isinf(world->inertiaAbout("post", up)),
          "an anchored post's inertia is infinite: it is as hard to turn as anything can be");
    bool refused = false;
    try {
        (void)world->inertiaAbout("flywheel", not_an_axis);
    } catch (const std::invalid_argument &) {
        refused = true;
    }
    check(refused, "an axis with a NaN in it is refused (JoltWorld::inertiaAbout)");
    check(world->hinge("post", "flywheel", axle, not_an_axis) == 0,
          "a pin on an axis with a NaN in it is refused (LiveWorld::hinge)");
    const unsigned pin = world->hinge("post", "flywheel", axle, up);
    const unsigned battery = world->energyStore("battery", "post", 100.0, 100.0);
    const unsigned drive = world->motor(pin, battery, 10.0, 10.0);
    check(pin != 0 && battery != 0 && drive != 0, "the flywheel's pin, battery and motor go together");
    check(!world->driveMotor(drive, in.nan), "a NaN command to a motor is refused (LiveWorld::driveMotor)");
    check(world->driveMotor(drive, 0.5), "and a number is taken");
}

#ifdef BANJO_FP_TESTS_X86
struct Csr {
    unsigned value{};
    [[nodiscard]] unsigned rounding() const { return (value >> 13) & 3U; }   // 0: to nearest
    [[nodiscard]] bool flushToZero() const { return (value & 0x8000U) != 0; }
    [[nodiscard]] bool denormalsAreZero() const { return (value & 0x0040U) != 0; }
    [[nodiscard]] unsigned masks() const { return (value >> 7) & 0x3FU; }       // all six: 0x3f
};

void environmentKeepsTheProfile(const std::string &where, Csr csr) {
    char text[160];
    std::snprintf(text, sizeof text, "%s: MXCSR %#06x -- rounding %u, flush-to-zero %d, denormals-are-zero %d, exception masks %#04x",
                  where.c_str(), csr.value, csr.rounding(), static_cast<int>(csr.flushToZero()),
                  static_cast<int>(csr.denormalsAreZero()), csr.masks());
    check(csr.rounding() == 0 && !csr.flushToZero() && !csr.denormalsAreZero(), text);
}

void everyThreadRoundsToNearestAndFlushesNothing() {
    environmentKeepsTheProfile("the main thread", Csr{_mm_getcsr()});
    std::atomic<unsigned> plain{0};
    std::thread([&] { plain = _mm_getcsr(); }).join();
    environmentKeepsTheProfile("a plain thread", Csr{plain.load()});
    JPH::RegisterDefaultAllocator();
    std::atomic<unsigned> worker{0};
    std::atomic<bool> done{false};
    {
        JPH::JobSystemThreadPool pool(64, 8, 2);
        const JPH::JobHandle job = pool.CreateJob("fp-environment", JPH::Color::sGreen, [&] {
            worker = _mm_getcsr();
            done = true;
        });
        const auto give_up = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while (!done && std::chrono::steady_clock::now() < give_up)
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    check(done.load(), "one of Jolt's worker threads ran the job");
    // Jolt unmasks invalid, divide-by-zero and overflow on its workers where it
    // is built with JPH_FLOATING_POINT_EXCEPTIONS_ENABLED (MSVC, Debug and
    // Release): a trap instead of a NaN, not a different number. Said, not refused.
#ifdef JPH_FLOATING_POINT_EXCEPTIONS_ENABLED
    std::cout << "  note: Jolt's workers run with floating-point exceptions unmasked "
                 "(JPH_FLOATING_POINT_EXCEPTIONS_ENABLED)\n";
#endif
    environmentKeepsTheProfile("a Jolt worker thread", Csr{worker.load()});
}
#endif

} // namespace

int main() {
    try {
        std::cout << "profile " << fp::profile() << "\n";
        theBuildsObjectsKeepTheProfile();
        theEnginesOwnChecksRefuseNaNs();
#ifdef BANJO_FP_TESTS_X86
        everyThreadRoundsToNearestAndFlushesNothing();
#else
        std::cout << "  not checked here: the floating-point environment is read from x86's MXCSR\n";
#endif
    } catch (const std::exception &error) {
        std::cout << "  FAILED: " << error.what() << "\n";
        ++failures;
    }
    std::cout << (failures ? std::to_string(failures) + " floating-point profile checks failed\n"
                           : std::string("all floating-point profile checks passed\n"));
    return failures ? 1 : 0;
}
