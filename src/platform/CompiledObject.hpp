#pragma once
#include "core/RigidPrimitive.hpp"
#include "material/Material.hpp"
#include <vector>
#include <cstdint>

namespace banjo {
struct CompiledSample {
    Vec3 center_m;
    RigidPrimitive collision;
    double mass_kg{};
    Mat3 intrinsic_inertia;
};
struct CompiledLink {
    unsigned a{}, b{};
    Vec3 direction;
    double length_m{}, area_m2{}, stiffness_n_m{}, strength_pa{}, work_j{};
};
// Intact quadrature and linear response operator, never a prescribed shard list.
// Sphere: 19 samples, exact total analytical mass/inertia, coarse collision skin.
// Box: 27 occupied cubical samples, exact homogeneous box mass/inertia.
struct CompiledObject {
    std::vector<CompiledSample> samples;
    std::vector<CompiledLink> links;
    std::vector<double> initial_factor;
    double response_duration_s{}; // Local predictor timestep; an activation advances 64 steps.
    MaterialDefinition material;
    std::uint64_t seed{};
};
CompiledObject compileObject(const RigidPrimitive &, const MaterialDefinition &, std::uint64_t seed);
struct LocalFailure {
    unsigned link{}, solve_index{};
    double predicted_stress_pa{}, predicted_elastic_energy_j{}, work_j{};
};
struct LocalImpactResult {
    std::vector<LocalFailure> failures;
    double work_j{};
    unsigned solves{}, factor_builds{};
    bool budget_limited{};
};
// Reduced impact model. The predictor does not apply another collision impulse.
// Its virtual elastic energy is a trigger only: work MUST be funded separately
// by the caller's measured contact-loss allowance. No virtual stored energy is
// released into the real rigid bodies. Linearized, uncalibrated, brittle only.
class CompiledDamage {
public:
    explicit CompiledDamage(CompiledObject object);
    const CompiledObject &object() const { return object_; }
    const std::vector<unsigned char> &liveLinks() const { return live_; }
    std::vector<unsigned> components() const;
    LocalImpactResult impact(unsigned sample, Vec3 impulse_local_n_s,
        double work_allowance_j, unsigned max_failures=8);
private:
    CompiledObject object_;
    std::vector<unsigned char> live_;
    std::vector<double> factor_;
    bool dirty_{};
};
}
