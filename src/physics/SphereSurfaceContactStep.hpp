#pragma once
#include "physics/SpherePatchWorld.hpp"
namespace banjo {
// Internal contact stages shared by material integrators. The caller owns a
// complete trial and must discard sphere/nodes/diagnostics together on failure.
// candidate_sphere and candidate material velocity have received their first
// force kick; initial states are pre-kick. exchange performs the entire drift.
// finalVelocity performs the sphere's second Verlet kick and constraints after
// the material's second kick. This class never commits material or fracture state.
class SphereSurfaceContactStep {
  public:
    SphereSurfaceContactStep(const PatchDefinition &definition, const std::vector<double> &masses,
                             const std::vector<std::array<unsigned, 3>> &triangles,
                             const std::vector<Vec3> &positions,
                             const std::vector<Vec3> &pre_kick_velocity,
                             const PatchSphere &pre_kick_sphere, PatchSphere &candidate_sphere,
                             double time_step, Vec3 external_force, bool velocity_verlet,
                             const PatchContactOptions &options, SpherePatchReport &report);
    void exchange(std::vector<Vec3> &velocity, std::vector<Vec3> &drift);
    void finalVelocity(std::vector<Vec3> &velocity, const std::vector<Vec3> &u);

  private:
    void charge();
    void impulse(unsigned selected, const std::array<double, 3> &weights, Vec3 normal,
                 const std::vector<Vec3> &positions, std::vector<Vec3> &velocity, double event_time,
                 bool final_stage);
    const PatchDefinition &d;
    const std::vector<double> &mass;
    const std::vector<std::array<unsigned, 3>> &faces;
    const std::vector<Vec3> &x, &initial_velocity;
    const PatchSphere &initial_sphere;
    PatchSphere &sphere;
    double dt;
    Vec3 external;
    bool verlet;
    const PatchContactOptions &contact_;
    SpherePatchReport &out;
    std::vector<Vec3> before_final_velocity;
    PatchSphere before_final_sphere;
};
} // namespace banjo
