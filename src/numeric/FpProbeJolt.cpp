// The probe compiled inside Jolt's own target (CMakeLists.txt adds this file to
// it), under Jolt's own flags -- its /fp:fast overridden by the profile, no
// exceptions, no RTTI, C++17 -- so what it reports is what Jolt's objects do.
#include <Jolt/Jolt.h>

#include "FpProbe.inl"

namespace banjo::fp {

Observations observeJolt(const Inputs &inputs) { return observeHere(inputs); }

float joltFusedMultiplyAdd(float a, float b, float c) {
    return JPH::Vec4::sFusedMultiplyAdd(JPH::Vec4::sReplicate(a), JPH::Vec4::sReplicate(b),
                                        JPH::Vec4::sReplicate(c)).GetX();
}

bool joltUsesFusedMultiplyAdd() {
#ifdef JPH_USE_FMADD
    return true;
#else
    return false;
#endif
}

} // namespace banjo::fp
