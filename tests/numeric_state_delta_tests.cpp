#include "material/Plasticity.hpp"
#include "persistence/NumericStateDelta.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using banjo::J2Material;
using banjo::J2State;
using banjo::J2Update;
using banjo::NumericStateBase;
using banjo::NumericStateEdit;
using banjo::NumericStateHistory;
using banjo::NumericStateIdentity;
using banjo::SymmetricTensor3;
using Bytes = std::vector<std::uint8_t>;

constexpr std::size_t headerSize = 88;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void rejects(const std::function<void()> &operation, std::string_view message) {
    bool rejected = false;
    try {
        operation();
    } catch (const std::exception &) {
        rejected = true;
    }
    require(rejected, message);
}

bool sameBits(double first, double second) {
    return std::bit_cast<std::uint64_t>(first) ==
        std::bit_cast<std::uint64_t>(second);
}

void requireSameBits(std::span<const double> actual,
    std::span<const double> expected, std::string_view message) {
    require(actual.size() == expected.size(), message);
    for (std::size_t i = 0; i < actual.size(); ++i)
        require(sameBits(actual[i], expected[i]), message);
}

NumericStateIdentity identity(std::uint64_t layout = 17,
    std::uint64_t object = 23, std::uint8_t digestByte = 0xa5) {
    NumericStateIdentity result;
    result.base_digest.fill(digestByte);
    result.layout_id = layout;
    result.object_id = object;
    return result;
}

std::uint32_t crcByte(std::uint32_t crc, std::uint8_t byte) {
    crc ^= byte;
    for (unsigned bit = 0; bit < 8; ++bit)
        crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320U : 0U);
    return crc;
}

std::uint32_t crc(std::span<const std::uint8_t> bytes) {
    std::uint32_t result = ~0U;
    for (const auto byte : bytes) result = crcByte(result, byte);
    return ~result;
}

std::uint32_t read32(const Bytes &bytes, std::size_t offset) {
    std::uint32_t result = 0;
    for (unsigned i = 0; i < 4; ++i)
        result |= std::uint32_t(bytes[offset + i]) << (8 * i);
    return result;
}

void write32(Bytes &bytes, std::size_t offset, std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i)
        bytes[offset + i] = static_cast<std::uint8_t>(value >> (8 * i));
}

void refreshCrc(Bytes &bytes) {
    require(bytes.size() >= 4, "test fixture must contain a checksum");
    write32(bytes, bytes.size() - 4, crc(std::span<const std::uint8_t>(
        bytes.data(), bytes.size() - 4)));
}

void requireSameBytes(std::span<const std::uint8_t> actual,
    std::span<const std::uint8_t> expected, std::string_view message) {
    require(actual.size() == expected.size(), message);
    for (std::size_t i = 0; i < actual.size(); ++i)
        require(actual[i] == expected[i], message);
}

std::array<double, 14> packJ2(const J2State &state) {
    return {
        state.total_strain.xx, state.total_strain.yy, state.total_strain.zz,
        state.total_strain.xy, state.total_strain.yz, state.total_strain.zx,
        state.plastic_strain.xx, state.plastic_strain.yy,
        state.plastic_strain.zz, state.plastic_strain.xy,
        state.plastic_strain.yz, state.plastic_strain.zx,
        state.equivalent_plastic_strain, state.plastic_dissipation_j_m3,
    };
}

J2State unpackJ2(std::span<const double> values) {
    require(values.size() == banjo::kJ2StateScalarCount,
        "J2 persistent layout must contain 14 scalars");
    return {
        {values[0], values[1], values[2], values[3], values[4], values[5]},
        {values[6], values[7], values[8], values[9], values[10], values[11]},
        values[12], values[13],
    };
}

bool sameTensor(const SymmetricTensor3 &first, const SymmetricTensor3 &second) {
    return sameBits(first.xx, second.xx) && sameBits(first.yy, second.yy) &&
        sameBits(first.zz, second.zz) && sameBits(first.xy, second.xy) &&
        sameBits(first.yz, second.yz) && sameBits(first.zx, second.zx);
}

bool sameJ2State(const J2State &first, const J2State &second) {
    return sameTensor(first.total_strain, second.total_strain) &&
        sameTensor(first.plastic_strain, second.plastic_strain) &&
        sameBits(first.equivalent_plastic_strain,
            second.equivalent_plastic_strain) &&
        sameBits(first.plastic_dissipation_j_m3,
            second.plastic_dissipation_j_m3);
}

bool sameUpdateState(const J2Update &first, const J2Update &second) {
    return sameJ2State(first.state, second.state) &&
        sameTensor(first.stress_pa, second.stress_pa) &&
        sameTensor(first.trial_stress_pa, second.trial_stress_pa) &&
        sameTensor(first.plastic_strain_increment,
            second.plastic_strain_increment) &&
        first.yielded == second.yielded &&
        sameBits(first.trial_equivalent_stress_pa,
            second.trial_equivalent_stress_pa) &&
        sameBits(first.yield_stress_before_pa,
            second.yield_stress_before_pa) &&
        sameBits(first.yield_stress_after_pa,
            second.yield_stress_after_pa) &&
        sameBits(first.equivalent_plastic_strain_increment,
            second.equivalent_plastic_strain_increment) &&
        sameBits(first.constitutive_plastic_work_j_m3,
            second.constitutive_plastic_work_j_m3) &&
        sameBits(first.hardening_free_energy_increment_j_m3,
            second.hardening_free_energy_increment_j_m3) &&
        sameBits(first.plastic_dissipation_increment_j_m3,
            second.plastic_dissipation_increment_j_m3) &&
        sameBits(first.stored_free_energy_increment_j_m3,
            second.stored_free_energy_increment_j_m3) &&
        sameBits(first.backward_euler_stress_work_j_m3,
            second.backward_euler_stress_work_j_m3) &&
        sameBits(first.backward_euler_work_excess_j_m3,
            second.backward_euler_work_excess_j_m3);
}

void losslessOverlayAndPartialRanges() {
    const std::vector<double> baseValues{
        0.0, -0.0, std::numeric_limits<double>::denorm_min(),
        -std::numeric_limits<double>::max(), 1.0, -2.5, 7.0,
    };
    const NumericStateBase base(identity(), baseValues);
    auto target = baseValues;
    target[0] = -0.0;
    target[1] = 0.0;
    target[2] = -std::numeric_limits<double>::denorm_min();
    target[3] = std::numeric_limits<double>::max();
    target[4] = std::bit_cast<double>(std::uint64_t{0x3fedcba987654321});

    const auto dense = banjo::encodeNumericStateDelta(base, target, 4, 3);
    const auto sparse = banjo::encodeSparseNumericStateDelta(base,
        std::array<NumericStateEdit, 5>{
            NumericStateEdit{0, target[0]}, NumericStateEdit{1, target[1]},
            NumericStateEdit{2, target[2]}, NumericStateEdit{3, target[3]},
            NumericStateEdit{4, target[4]},
        }, 4, 3);
    requireSameBytes(dense, sparse,
        "dense and complete sparse overlays must have canonical identical bytes");

    const auto decoded = banjo::decodeNumericStateDelta(base, dense);
    require(decoded.metadata.revision == 4 && decoded.metadata.parent_revision == 3 &&
        decoded.metadata.changed_values == 5,
        "decoded revision metadata must retain the complete sparse count");
    requireSameBits(decoded.values, target,
        "signed zero, subnormal, and large finite values must round-trip bit-exactly");

    const auto partial = banjo::decodeNumericStateRange(base, dense, 1, 4);
    requireSameBits(partial.values,
        std::span<const double>(target.data() + 1, 4),
        "partial range decode must overlay only the requested range");
    require(partial.metadata.changed_values == decoded.metadata.changed_values,
        "partial range must preserve revision metadata");
}

void sparseCountsAndEditValidation() {
    constexpr std::size_t count = 4096;
    std::vector<double> baseValues(count, 0.0);
    const NumericStateBase base(identity(31, 41), baseValues);
    std::vector<NumericStateEdit> edits;
    for (unsigned i = 0; i < 16; ++i)
        edits.push_back({i * 257U, 0.125 * static_cast<double>(i + 1)});
    const auto sparse = banjo::encodeSparseNumericStateDelta(base, edits, 1, 0);
    auto target = baseValues;
    for (const auto edit : edits) target[edit.index] = edit.value;
    const auto dense = banjo::encodeNumericStateDelta(base, target, 1, 0);
    const auto decoded = banjo::decodeNumericStateDelta(base, sparse);
    require(decoded.metadata.changed_values == edits.size(),
        "sparse metadata must count changed fields rather than base fields");
    requireSameBytes(sparse, dense, "dense and sparse callers must produce the same canonical delta");
    require(sparse.size() < count * sizeof(double),
        "sparse encoding must be smaller than the uncompressed dense state payload");
    requireSameBits(decoded.values, target,
        "sparse decode must apply the complete overlay to the base");

    const std::vector<NumericStateEdit> equalToBase{{0, 0.0}};
    const auto unchanged = banjo::encodeSparseNumericStateDelta(base, equalToBase, 2, 1);
    require(banjo::decodeNumericStateDelta(base, unchanged).metadata.changed_values == 0,
        "an edit equal to the base must not create a changed field");

    const auto beforeValues = edits;
    rejects([&] {
        (void)banjo::encodeSparseNumericStateDelta(base,
            std::array<NumericStateEdit, 2>{{{4, 1.0}, {3, 2.0}}}, 1, 0);
    }, "unordered sparse edits must reject");
    rejects([&] {
        (void)banjo::encodeSparseNumericStateDelta(base,
            std::array<NumericStateEdit, 2>{{{4, 1.0}, {4, 2.0}}}, 1, 0);
    }, "duplicate sparse edits must reject");
    rejects([&] {
        (void)banjo::encodeSparseNumericStateDelta(base,
            std::array<NumericStateEdit, 1>{{{count, 1.0}}}, 1, 0);
    }, "out-of-range sparse edit must reject");
    rejects([&] {
        (void)banjo::encodeSparseNumericStateDelta(base,
            std::array<NumericStateEdit, 1>{{{4, std::numeric_limits<double>::quiet_NaN()}}},
            1, 0);
    }, "nonfinite sparse edit must reject");
    require(edits.size() == beforeValues.size(),
        "failed sparse encoding must preserve the caller edit list size");
    for (std::size_t i = 0; i < edits.size(); ++i)
        require(edits[i].index == beforeValues[i].index &&
            sameBits(edits[i].value, beforeValues[i].value),
            "failed sparse encoding must not mutate the caller edit list");
    requireSameBits(base.values(), baseValues,
        "failed sparse encoding must not mutate the immutable base values");
}

void identityAndMalformedInputRejectWithoutMutation() {
    const std::vector<double> baseValues{0.0, 1.0, -2.0};
    const NumericStateBase base(identity(), baseValues);
    const double finiteWithAllBytes = std::bit_cast<double>(
        std::uint64_t{0x7feeddccbbaa9988});
    const auto valid = banjo::encodeNumericStateDelta(
        base, std::array<double, 3>{finiteWithAllBytes, 1.0, -2.0}, 1, 0);
    const auto originalBase = std::vector<double>(base.values().begin(), base.values().end());

    auto badDigest = identity();
    badDigest.base_digest[0] ^= 1;
    const NumericStateBase digestBase(badDigest, baseValues);
    rejects([&] { (void)banjo::decodeNumericStateDelta(digestBase, valid); },
        "base digest mismatch must reject");
    const NumericStateBase layoutBase(identity(18, 23), baseValues);
    rejects([&] { (void)banjo::decodeNumericStateDelta(layoutBase, valid); },
        "layout identity mismatch must reject");
    const NumericStateBase objectBase(identity(17, 24), baseValues);
    rejects([&] { (void)banjo::decodeNumericStateDelta(objectBase, valid); },
        "object identity mismatch must reject");

    auto alteredValues = baseValues;
    alteredValues[1] = 1.5;
    const NumericStateBase alteredBase(identity(), alteredValues);
    rejects([&] { (void)banjo::decodeNumericStateDelta(alteredBase, valid); },
        "changed actual base contents must reject even with the same identity");

    auto corrupted = valid;
    corrupted[headerSize + 2] ^= 1;
    rejects([&] { (void)banjo::decodeNumericStateDelta(base, corrupted); },
        "checksum corruption must reject");
    auto truncated = valid;
    truncated.pop_back();
    rejects([&] { (void)banjo::decodeNumericStateDelta(base, truncated); },
        "truncated numeric state must reject");
    auto trailing = valid;
    trailing.insert(trailing.end() - 4, 0x00);
    write32(trailing, 84, read32(valid, 84) + 1);
    refreshCrc(trailing);
    rejects([&] { (void)banjo::decodeNumericStateDelta(base, trailing); },
        "trailing payload bytes must reject");
    auto nonfinite = valid;
    const auto nanBits = std::uint64_t{0x7ff1fedcba987654};
    for (unsigned i = 0; i < 8; ++i)
        nonfinite[headerSize + 2 + i] = static_cast<std::uint8_t>(nanBits >> (8 * i));
    refreshCrc(nonfinite);
    rejects([&] { (void)banjo::decodeNumericStateDelta(base, nonfinite); },
        "decoded nonfinite numeric value must reject");
    auto malformedIndex = valid;
    malformedIndex[headerSize] = 0x80;
    malformedIndex.insert(malformedIndex.begin() + headerSize + 1, 0x00);
    write32(malformedIndex, 84, read32(valid, 84) + 1);
    refreshCrc(malformedIndex);
    rejects([&] { (void)banjo::decodeNumericStateDelta(base, malformedIndex); },
        "noncanonical sparse index must reject");
    auto oversized = Bytes(NumericStateBase::maximum_values * 14 + headerSize + 5, 0);
    rejects([&] { (void)banjo::decodeNumericStateDelta(base, oversized); },
        "oversize numeric state must reject");
    rejects([&] { (void)banjo::decodeNumericStateRange(base, valid, 4, 0); },
        "out-of-range decode request must reject");
    requireSameBits(base.values(), originalBase,
        "all failed decode paths must preserve the actual base state");
}

void historyIsBoundedAndRestorationIsAProposal() {
    const std::vector<double> baseValues{0.0, 1.0, 2.0, 3.0};
    const NumericStateBase base(identity(52, 61), baseValues);
    NumericStateHistory history(base, 4, 4096);
    const std::array<double, 4> first{-0.0, 1.5, 2.0, 3.0};
    const std::array<double, 4> second{-0.0, 1.5, 2.25, 4.0};
    require(history.append(first, 0) == 1, "first history revision");
    const auto firstArchive = Bytes(history.encodedRevision(1).begin(),
        history.encodedRevision(1).end());
    require(history.appendSparse(
        std::array<NumericStateEdit, 3>{{{0, second[0]}, {1, second[1]}, {2, second[2]}}}, 1) == 2,
        "sparse history revision");
    const auto bytesBeforeQueries = history.encodedBytes();
    const auto currentBeforeQueries = history.currentRevision();
    const auto secondArchive = Bytes(history.encodedRevision(2).begin(),
        history.encodedRevision(2).end());
    requireSameBits(history.restorationCandidate(0), baseValues,
        "revision zero must restore the immutable original base");
    requireSameBits(history.restorationCandidate(1), first,
        "first history revision must restore exactly");
    requireSameBits(history.restorationCandidate(2),
        std::array<double, 4>{second[0], second[1], second[2], baseValues[3]},
        "sparse history is a complete base-relative overlay");
    require(history.currentRevision() == currentBeforeQueries &&
        history.encodedBytes() == bytesBeforeQueries,
        "restoration candidates must not mutate history");

    const auto restoredOriginal = history.restorationCandidate(0);
    require(history.append(restoredOriginal, 2) == 3,
        "restored original state must append as a new revision");
    requireSameBits(history.restorationCandidate(3), baseValues,
        "restoring the original must create an exact new revision");
    requireSameBytes(history.encodedRevision(1), firstArchive,
        "appending a restored state must preserve the old archive");
    requireSameBytes(history.encodedRevision(2), secondArchive,
        "appending a restored state must preserve the sparse archive");

    const auto revisionsBeforeStale = history.currentRevision();
    const auto bytesBeforeStale = history.encodedBytes();
    rejects([&] { (void)history.append(first, 1); },
        "stale expected history revision must reject");
    require(history.currentRevision() == revisionsBeforeStale &&
        history.encodedBytes() == bytesBeforeStale,
        "stale history rejection must be atomic");

    const auto oneChange = banjo::encodeNumericStateDelta(base, first, 1, 0);
    NumericStateHistory byteLimited(base, 4, oneChange.size());
    require(byteLimited.append(first, 0) == 1, "byte-limited first append");
    const auto byteLimitedRevision = byteLimited.currentRevision();
    const auto byteLimitedBytes = byteLimited.encodedBytes();
    rejects([&] { (void)byteLimited.append(second, 1); },
        "encoded byte budget must reject atomically");
    require(byteLimited.currentRevision() == byteLimitedRevision &&
        byteLimited.encodedBytes() == byteLimitedBytes,
        "byte budget rejection must preserve history");

    NumericStateHistory revisionLimited(base, 1, 4096);
    require(revisionLimited.append(first, 0) == 1, "revision-limited first append");
    rejects([&] { (void)revisionLimited.append(second, 1); },
        "revision budget must reject atomically");
    require(revisionLimited.currentRevision() == 1,
        "revision budget rejection must preserve current revision");
}

void j2StateRoundTripsAndContinuesExactly() {
    const J2Material material{
        banjo::ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,
        210.0e9, 0.3, 180.0e6, 2.0e9, 0.1,
    };
    const J2State initial{};
    banjo::validateJ2State(material, initial);
    const SymmetricTensor3 firstIncrement{
        1.0e-4, -5.0e-5, -5.0e-5, 2.0e-5, -1.0e-5, 3.0e-5};
    const SymmetricTensor3 nextIncrement{
        2.0e-4, -1.0e-4, -1.0e-4, -3.0e-5, 2.0e-5, -1.0e-5};
    const auto first = banjo::integrateJ2StrainIncrement(
        material, initial, firstIncrement);
    const auto initialPacked = packJ2(initial);
    const auto savedPacked = packJ2(first.state);
    const NumericStateBase base(identity(73, 89), initialPacked);
    const auto saved = banjo::encodeNumericStateDelta(base, savedPacked, 1, 0);
    const auto decoded = banjo::decodeNumericStateDelta(base, saved);
    require(decoded.values.size() == banjo::kJ2StateScalarCount,
        "J2 save must retain the explicit 14-double layout");
    const auto loaded = unpackJ2(decoded.values);
    banjo::validateJ2State(material, loaded);
    requireSameBits(decoded.values, savedPacked,
        "J2 state scalar packing must be lossless");
    require(sameJ2State(loaded, first.state),
        "decoded J2 state must equal the saved constitutive state");

    const auto originalContinuation = banjo::integrateJ2StrainIncrement(
        material, first.state, nextIncrement);
    const auto loadedContinuation = banjo::integrateJ2StrainIncrement(
        material, loaded, nextIncrement);
    require(sameUpdateState(originalContinuation, loadedContinuation),
        "a decoded J2 state must produce exact next-increment continuation");
}
}

int main() {
    try {
        losslessOverlayAndPartialRanges();
        sparseCountsAndEditValidation();
        identityAndMalformedInputRejectWithoutMutation();
        historyIsBoundedAndRestorationIsAProposal();
        j2StateRoundTripsAndContinuesExactly();
        std::cout << "[PASS] numeric state delta, bounded history, and J2 persistence contract\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
