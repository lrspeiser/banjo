#pragma once
#include <memory>
#include <string>
#include <array>
namespace banjo {
enum class VoxelExecution { Inline, Reference };
// Finite occupied boxes and passive six-axis face springs. Experimental reduced
// solid model, independent of browser presentation and the older axial lanes.
class VoxelImpactWorld {
public:
    explicit VoxelImpactWorld(const std::string &declaration,
                              VoxelExecution storage=VoxelExecution::Inline);
    ~VoxelImpactWorld();
    void step(unsigned count);
    // Bounded external actuator. Adds mass * acceleration as a real native
    // force to each dynamic cell; never assigns motion or removes matter.
    void setObjectAcceleration(unsigned object,const std::array<double,3> &acceleration_m_s2);
    std::string snapshotJson() const;
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
