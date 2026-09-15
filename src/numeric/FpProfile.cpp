#include "numeric/FpProfile.hpp"

#include "numeric/FpProbe.inl"

#ifndef BANJO_FP_PROFILE
#error "cmake/FloatingPointModel.cmake defines BANJO_FP_PROFILE on banjo_core"
#endif

namespace banjo::fp {

const char *profile() { return BANJO_FP_PROFILE; }

std::uint64_t profileHash() {
    std::uint64_t hash = 14695981039346656037ULL;
    for (const char *c = BANJO_FP_PROFILE; *c != '\0'; ++c) {
        hash ^= static_cast<unsigned char>(*c);
        hash *= 1099511628211ULL;
    }
    return hash;
}

Observations observeCore(const Inputs &inputs) { return observeHere(inputs); }

} // namespace banjo::fp
