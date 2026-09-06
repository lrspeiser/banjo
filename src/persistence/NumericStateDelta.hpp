#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <vector>

namespace banjo {

// A lossless codec for an explicitly ordered, finite-double state layout.
// This is not a complete physics-world checkpoint. The caller's layout must
// include every authoritative field and validate its constitutive invariants.
// Content-address resolution/authentication of base_digest belongs to the host.
struct NumericStateIdentity {
    std::array<std::uint8_t, 32> base_digest{};
    std::uint64_t layout_id{};
    std::uint64_t object_id{};
    bool operator==(const NumericStateIdentity &) const = default;
};

class NumericStateBase {
public:
    static constexpr std::size_t maximum_values = 1U << 20;
    NumericStateBase(NumericStateIdentity identity, std::span<const double> values);
    const NumericStateIdentity &identity() const { return identity_; }
    std::span<const double> values() const { return values_; }
    std::uint32_t checksum() const { return checksum_; }
private:
    NumericStateIdentity identity_;
    std::vector<double> values_;
    std::uint32_t checksum_{};
};

struct NumericStateRevision {
    std::uint64_t revision{}, parent_revision{};
    std::uint32_t changed_values{};
};
struct DecodedNumericState {
    NumericStateRevision metadata;
    // decodeRange returns only the requested contiguous values.
    std::vector<double> values;
};
struct NumericStateEdit {
    std::uint32_t index{};
    double value{};
};

// Canonical little-endian binary64 XOR deltas, sparse indices and byte masks.
// CRC32 detects accidental corruption; it is not cryptographic authentication.
// Revision zero is the immutable base. Every stored revision has parent < revision.
[[nodiscard]] std::vector<std::uint8_t> encodeNumericStateDelta(
    const NumericStateBase &base, std::span<const double> values,
    std::uint64_t revision, std::uint64_t parent_revision);
// Complete current overlay relative to base, not changes since the last tick.
// Strictly increasing indices. Work is O(edits), with no base-size scan.
[[nodiscard]] std::vector<std::uint8_t> encodeSparseNumericStateDelta(
    const NumericStateBase &base, std::span<const NumericStateEdit> edits,
    std::uint64_t revision, std::uint64_t parent_revision);
[[nodiscard]] DecodedNumericState decodeNumericStateRange(
    const NumericStateBase &base, std::span<const std::uint8_t> bytes,
    std::size_t first, std::size_t count);
[[nodiscard]] DecodedNumericState decodeNumericStateDelta(
    const NumericStateBase &base, std::span<const std::uint8_t> bytes);

// Host-thread bounded linear history. Each revision references the same base,
// so lookup never replays earlier deltas or impacts. Full capacity rejects;
// no automatic eviction of provenance. Export/retention policy belongs to host.
// Restoring a past revision only proposes values; it does not authorize a game
// repair, create matter, transfer energy, or mutate any physics world.
class NumericStateHistory {
public:
    NumericStateHistory(const NumericStateBase &base,
        std::size_t maximum_revisions, std::size_t maximum_encoded_bytes);
    std::uint64_t append(std::span<const double> values, std::uint64_t expected_revision);
    std::uint64_t appendSparse(std::span<const NumericStateEdit> edits, std::uint64_t expected_revision);
    [[nodiscard]] std::vector<double> restorationCandidate(std::uint64_t revision) const;
    [[nodiscard]] std::span<const std::uint8_t> encodedRevision(std::uint64_t revision) const;
    std::uint64_t currentRevision() const { return static_cast<std::uint64_t>(revisions_.size()); }
    std::size_t encodedBytes() const { return encoded_bytes_; }
private:
    const NumericStateBase &base_; // caller keeps immutable base alive
    std::size_t maximum_revisions_, maximum_encoded_bytes_, encoded_bytes_{};
    std::vector<std::vector<std::uint8_t>> revisions_;
    std::uint64_t commit(std::vector<std::uint8_t> bytes);
};
} // namespace banjo
