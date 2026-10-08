#pragma once
#include <memory>
#include <string>
namespace banjo {
// Finite occupied boxes and passive six-axis face springs. Experimental reduced
// solid model, independent of browser presentation and the older axial lanes.
class VoxelImpactWorld {
public:
    explicit VoxelImpactWorld(const std::string &declaration);
    ~VoxelImpactWorld();
    void step(unsigned count);
    std::string snapshotJson() const;
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
