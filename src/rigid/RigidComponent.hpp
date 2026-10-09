#pragma once
#include "rigid/JoltWorld.hpp"
namespace banjo {
struct RigidComponentCell {
    MatterBodyId id{};
    Vec3 size_m{};
    MaterialDefinition material{};
};
struct ComponentTransferBudget {
    double mass_kg{1e-6}, linear_momentum_n_s{1e-5};
    double angular_momentum_n_m_s{1e-5}, energy_j{1e-5};
    double nonrigid_energy_j{1e-9};
};
struct ComponentTransferReceipt {
    bool admitted{};
    std::string reason;
    RepresentationTransferAudit audit;
    double nonrigid_energy_j{};
};
// Representation transfer only, not an activation/constitutive law. The host
// must expand before loading/contact can change material state. Original body
// IDs, exact occupied-box union and face constraints/rest are retained.
// No hidden velocity reservoir or disposal of appreciable deformation energy.
class RigidComponent {
public:
    RigidComponent(MatterBodyId proxy,std::vector<RigidComponentCell> cells);
    ComponentTransferReceipt collapse(JoltWorld &,double stored_elastic_j,
                                      ComponentTransferBudget = {},Vec3 gravity = {});
    ComponentTransferReceipt expand(JoltWorld &,Vec3 gravity = {});
    [[nodiscard]] bool collapsed() const { return collapsed_; }
    [[nodiscard]] MatterBodyId proxy() const { return proxy_; }
    [[nodiscard]] const std::vector<RigidComponentCell> &cells() const { return cells_; }
    [[nodiscard]] std::vector<RigidSnapshot> snapshots(const JoltWorld &) const;
private:
    MatterBodyId proxy_;
    std::vector<RigidComponentCell> cells_;
    std::vector<Vec3> centers_;
    std::vector<Quat> rotations_;
    bool collapsed_{};
    ComponentTransferBudget budget_;
};
}
