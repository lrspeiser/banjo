#pragma once
#include "fastlattice/DoubleFixedContact.hpp"
#include "material/MaterialCatalog.hpp"
#include <memory>
namespace banjo::fastlattice {
// Explicit bounded specimen experiment. A rigid reference pick assembly impacts
// a deformable axial-bond sheet. It is not a calibrated continuum or a soft-tool
// law. All target constituents and histories persist through accepted steps.
class SheetImpact {
public:
    SheetImpact(MaterialPreset sheet,MaterialPreset pick,double cell_m=.002,double timestep_scale=1,Vec3 strike_point_m={},double speed_m_s=6);
    ~SheetImpact();
    SheetImpact(const SheetImpact&)=delete;
    SheetImpact& operator=(const SheetImpact&)=delete;
    void advance(unsigned steps);
    const LatticeState &state() const;
    const RunStatus &status() const;
    const DoubleFixedSource &source() const;
    const LatticeAsset &asset() const;
    double timestep() const;
    double energyResidual() const;
    Vec3 momentumResidual() const;
    Vec3 angularResidual() const;
    double contactLoss() const;
    double initialEnergy() const;
    double numericalEnergy() const;
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
