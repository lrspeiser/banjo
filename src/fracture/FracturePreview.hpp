#pragma once
#include "fracture/RuptureCascade.hpp"
#include "material/MaterialCatalog.hpp"
#include <array>
namespace banjo {
struct FracturePreviewRun {MaterialPreset material;std::vector<RuptureCascadeFrame> frames;std::vector<RuptureCascadeEvent> events;};
using FracturePreview=std::array<FracturePreviewRun,3>;
// Fresh microscopic chain comparison; all results publish only on success.
// Fixed shared fixture, per-model capability, no saved outcome substitution.
FracturePreview buildFracturePreview(double impact_speed_m_s);
}
