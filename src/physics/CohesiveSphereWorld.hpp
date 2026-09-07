#pragma once
#include "physics/CohesiveDynamicPatch.hpp"
#include "physics/SpherePatchWorld.hpp"
#include "physics/FractureOverlap.hpp"
namespace banjo {
struct CohesiveSphereReport {
    bool accepted{};
    std::string error;
    CohesiveDynamicPatchReport material;
    // Contact counters and combined ledgers only; legacy contact.material is unused.
    SpherePatchReport contact;
    FractureOverlapResult fragment_overlap;
};
// Sphere and cohesive material share Verlet force/contact/drift stages and one
// atomic commit. Accepted damage exposes actual faces before final constraints.
// Explicit small-displacement or corotated elastic bulk. The corotated path
// rejects unsupported fragment overlap; neither path supplies fragment/fragment
// or support contacts, continuum calibration, or a realtime guarantee.
class CohesiveSphereWorld {
  public:
    CohesiveSphereWorld(PatchDefinition definition, PatchSphere sphere,
                        std::vector<CohesiveFacetLaw> laws,
                        CohesiveDynamicPatchOptions dynamics = {},
                        PatchContactOptions contact = {});
    const CohesiveDynamicPatch &material() const {
        return patch_;
    }
    const PatchSphere &sphere() const {
        return sphere_;
    }
    CohesiveSphereReport step(double dt_s, const std::vector<Vec3> &nodal_forces_n,
                              Vec3 material_gravity_m_s2 = {}, Vec3 sphere_force_n = {},
                              Vec3 sphere_gravity_m_s2 = {});

  private:
    CohesiveDynamicPatch patch_;
    PatchSphere sphere_;
    PatchContactOptions contact_;
    double energy_limit_{};
};
} // namespace banjo
