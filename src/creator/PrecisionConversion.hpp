#pragma once
#include <string>
#include <string_view>

namespace banjo {
// Explicit offline operations. Neither changes a live world or writes files.
// Normalization uses this build's existing compatibility/migration checks.
[[nodiscard]] std::string normalizeSavedWorldJson(std::string_view document);
// Only v5 with matching profiles/compiler and recorded 32-bit positions is
// accepted, and only in a 64-bit-position build. Returns a review package with
// the exact source text, converted world and conversion receipt. No time steps.
[[nodiscard]] std::string upgradePositionPrecisionJson(std::string_view document);
}
