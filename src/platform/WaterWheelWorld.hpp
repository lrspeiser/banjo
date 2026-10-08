#pragma once
#include "platform/PlatformWorld.hpp"
#include <memory>
namespace banjo {
// Bounded fluid/rigid laboratory backend; no renderer or outcome scripts.
class WaterWheelWorld {
public:
    static std::unique_ptr<WaterWheelWorld> load(const std::string &source);
    ~WaterWheelWorld();
    void step(double dt);
    std::vector<PlatformInstance> renderInstances() const;
    std::string reportJson() const;
private:
    WaterWheelWorld();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
