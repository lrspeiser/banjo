#pragma once
#include "platform/PlatformWorld.hpp"
#include <memory>

namespace banjo {
// Experimental continuously deformable cell network. All nodes/contact and
// springs evolve on the same clock. No detached shadow impact predictor.
class NetworkWorld {
public:
    static std::unique_ptr<NetworkWorld> load(const std::string &source);
    ~NetworkWorld();
    void step(double dt);
    std::vector<PlatformInstance> renderInstances() const;
    std::vector<PlatformBondLine> renderBonds() const;
    std::string reportJson() const;
    const std::vector<std::array<Vec3,3>> &supportMesh() const;
    unsigned fractureCount() const;
    double energy() const;
private:
    NetworkWorld();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
