// Compiled only when BANJO_BUILD_CUDA is OFF: the GPU backend is absent and
// says so, instead of silently doing nothing.

#include "fastlattice/FastLattice.hpp"

#include <stdexcept>
#include <string>

namespace banjo::fastlattice {

bool cudaLatticeAvailable() { return false; }

std::string cudaLatticeDescription() {
    return "CUDA backend not compiled (configure with -DBANJO_BUILD_CUDA=ON)";
}

unsigned cudaLatticeMultiprocessorCount() { return 0; }

std::unique_ptr<LatticeBackend> makeCudaLatticeBackend(
    const LatticeSchedule &, Precision, unsigned) {
    throw std::runtime_error(
        "this build has no CUDA lattice backend: it was configured with "
        "BANJO_BUILD_CUDA=OFF. Use the CPU backend or reconfigure with "
        "-DBANJO_BUILD_CUDA=ON.");
}

} // namespace banjo::fastlattice
