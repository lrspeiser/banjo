#pragma once

#include "core/Math.hpp"
#include "core/Types.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/ImpactEvent.hpp"
#include "material/Material.hpp"

#include <memory>
#include <vector>

namespace banjo {

struct RigidBallDescription {
    MatterBodyId body_id{kInvalidMatterBodyId};
    double radius_m{};
    MaterialDefinition material{};
    Vec3 position_world_m{};
    Vec3 linear_velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
};

class JoltWorld {
public:
    JoltWorld();
    ~JoltWorld();

    JoltWorld(const JoltWorld &) = delete;
    JoltWorld &operator=(const JoltWorld &) = delete;
    JoltWorld(JoltWorld &&) noexcept;
    JoltWorld &operator=(JoltWorld &&) noexcept;

    void addFloor();
    void addBall(const RigidBallDescription &description);
    void step(double fixed_dt_s);

    [[nodiscard]] std::vector<ImpactEvent> drainImpacts();
    [[nodiscard]] RigidSnapshot snapshot(MatterBodyId body_id) const;
    [[nodiscard]] bool contains(MatterBodyId body_id) const;
    void removeAndDestroy(MatterBodyId body_id);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo
