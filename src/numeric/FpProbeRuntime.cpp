// The probe compiled in banjo_runtime, which takes Jolt's usage requirements
// (/arch:AVX2, or -mavx2 -mfma): the objects that sit beside Jolt's own.
#include "numeric/FpProbe.inl"

namespace banjo::fp {

Observations observeRuntime(const Inputs &inputs) { return observeHere(inputs); }

} // namespace banjo::fp
