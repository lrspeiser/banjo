#pragma once
#include "rigid/JoltWorld.hpp"
#include <nlohmann/json.hpp>

namespace banjo::machines {
// Discrete elastic rods. Jolt owns every body, contact and connector response.
// Construction path is a stress-free manufactured shape, never a runtime pose.
class MechanicalCable {
public:
    MechanicalCable(JoltWorld &,const nlohmann::json &,MatterBodyId a,MatterBodyId b,
                    MatterBodyId first);
    void settle(double dt); // accepted steps only; may detach terminal constraints
    [[nodiscard]] bool connected() const { return attached_[0]&&attached_[1]; }
    [[nodiscard]] unsigned circuit() const { return declaration_.at("circuit").get<unsigned>(); }
    [[nodiscard]] std::string branch() const { return declaration_.at("name").get<std::string>(); }
    [[nodiscard]] std::size_t bodyCount() const { return rods_.size(); }
    [[nodiscard]] nlohmann::json report() const;
    [[nodiscard]] nlohmann::json saved() const;
private:
    JoltWorld *world_;
    nlohmann::json declaration_;
    MatterBodyId ends_[2]{},first_{};
    std::vector<MatterBodyId> rods_;
    std::vector<double> spans_;
    std::vector<unsigned> joints_;
    std::vector<JoltWorld::FaceSpringDescription> laws_;
    bool attached_[2]{true,true};
    double radius_{},line_mass_{},retention_{},peak_[2]{},released_j_{};
    [[nodiscard]] double elasticEnergy(std::size_t) const;
};
}
