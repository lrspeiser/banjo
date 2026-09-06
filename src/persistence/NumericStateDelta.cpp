#include "persistence/NumericStateDelta.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {
using Bytes = std::vector<std::uint8_t>;
constexpr std::array<std::uint8_t, 8> magic{'B','J','D','N','U','M','0','1'};
constexpr std::size_t header_size = 88, minimum_size = header_size + 4;
constexpr std::size_t maximum_bytes = minimum_size + NumericStateBase::maximum_values * 14;
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

std::uint32_t crcByte(std::uint32_t crc, std::uint8_t byte) {
    crc ^= byte;
    for (unsigned bit = 0; bit < 8; ++bit)
        crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320U : 0U);
    return crc;
}
std::uint32_t crc(std::span<const std::uint8_t> bytes) {
    std::uint32_t value = ~0U;
    for (auto byte : bytes) value = crcByte(value, byte);
    return ~value;
}
void put(Bytes &bytes, std::uint64_t value, unsigned count) {
    for (unsigned i = 0; i < count; ++i) bytes.push_back(static_cast<std::uint8_t>(value >> (8*i)));
}
void variable(Bytes &bytes, std::uint32_t value) {
    while (value >= 128) { bytes.push_back(static_cast<std::uint8_t>((value & 127) | 128)); value >>= 7; }
    bytes.push_back(static_cast<std::uint8_t>(value));
}
struct Reader {
    std::span<const std::uint8_t> bytes;
    std::size_t position{};
    std::uint64_t get(unsigned count) {
        require(count <= 8 && count <= bytes.size() - position, "truncated numeric state");
        std::uint64_t result = 0;
        for (unsigned i = 0; i < count; ++i) result |= std::uint64_t(bytes[position++]) << (8*i);
        return result;
    }
    std::uint32_t variable() {
        std::uint32_t value = 0;
        for (unsigned i = 0; i < 5; ++i) {
            const auto byte = static_cast<std::uint32_t>(get(1));
            require(i < 4 || byte <= 15, "numeric state index overflow");
            value |= (byte & 127) << (7*i);
            if ((byte & 128) == 0) {
                require(i == 0 || byte != 0, "noncanonical numeric state index");
                return value;
            }
        }
        throw std::invalid_argument("invalid numeric state index");
    }
};
}

NumericStateBase::NumericStateBase(NumericStateIdentity identity, std::span<const double> values)
    : identity_(identity) {
    require(!values.empty() && values.size() <= maximum_values, "numeric base size is outside bounds");
    require(identity.layout_id != 0 && identity.object_id != 0, "numeric base identity must be explicit");
    require(std::any_of(identity.base_digest.begin(), identity.base_digest.end(),
        [](auto value) { return value != 0; }), "numeric base digest must be explicit");
    std::uint32_t checksum = ~0U;
    for (const double value : values) {
        require(std::isfinite(value), "numeric base must be finite");
        const auto bits = std::bit_cast<std::uint64_t>(value);
        for (unsigned i = 0; i < 8; ++i) checksum = crcByte(checksum, static_cast<std::uint8_t>(bits >> (8*i)));
    }
    values_.assign(values.begin(), values.end());
    checksum_ = ~checksum;
}

Bytes encodeNumericStateDelta(const NumericStateBase &base, std::span<const double> values,
    std::uint64_t revision, std::uint64_t parent_revision) {
    require(values.size() == base.values().size(), "numeric state layout size mismatch");
    std::vector<NumericStateEdit> edits;
    for (std::size_t index = 0; index < values.size(); ++index) {
        require(std::isfinite(values[index]), "numeric state must be finite");
        if (std::bit_cast<std::uint64_t>(values[index]) != std::bit_cast<std::uint64_t>(base.values()[index]))
            edits.push_back({static_cast<std::uint32_t>(index), values[index]});
    }
    return encodeSparseNumericStateDelta(base, edits, revision, parent_revision);
}

Bytes encodeSparseNumericStateDelta(const NumericStateBase &base, std::span<const NumericStateEdit> edits,
    std::uint64_t revision, std::uint64_t parent_revision) {
    require(revision > 0 && parent_revision < revision, "invalid numeric state revision");
    require(edits.size() <= base.values().size(), "too many numeric state edits");
    Bytes payload;
    std::uint32_t changes = 0, previous_plus_one = 0;
    std::uint64_t input_next = 0;
    for (const auto &edit : edits) {
        require(edit.index >= input_next && edit.index < base.values().size(), "numeric state edits must be ordered unique valid indices");
        input_next = std::uint64_t(edit.index) + 1;
        require(std::isfinite(edit.value), "numeric state must be finite");
        const auto difference = std::bit_cast<std::uint64_t>(edit.value) ^
            std::bit_cast<std::uint64_t>(base.values()[edit.index]);
        if (difference == 0) continue;
        const auto id = edit.index;
        variable(payload, id - previous_plus_one);
        previous_plus_one = id + 1;
        std::uint8_t mask = 0;
        for (unsigned i = 0; i < 8; ++i) if (((difference >> (8*i)) & 255) != 0) mask |= std::uint8_t(1U << i);
        payload.push_back(mask);
        for (unsigned i = 0; i < 8; ++i) if (mask & (1U << i)) payload.push_back(static_cast<std::uint8_t>(difference >> (8*i)));
        ++changes;
    }
    Bytes bytes;
    bytes.reserve(minimum_size + payload.size());
    bytes.insert(bytes.end(), magic.begin(), magic.end());
    bytes.insert(bytes.end(), base.identity().base_digest.begin(), base.identity().base_digest.end());
    put(bytes, base.identity().layout_id, 8); put(bytes, base.identity().object_id, 8);
    put(bytes, base.values().size(), 4); put(bytes, base.checksum(), 4);
    put(bytes, revision, 8); put(bytes, parent_revision, 8);
    put(bytes, changes, 4); put(bytes, payload.size(), 4);
    bytes.insert(bytes.end(), payload.begin(), payload.end());
    put(bytes, crc(bytes), 4);
    return bytes;
}

DecodedNumericState decodeNumericStateRange(const NumericStateBase &base,
    std::span<const std::uint8_t> bytes, std::size_t first, std::size_t count) {
    require(first <= base.values().size() && count <= base.values().size() - first,
        "numeric state range is outside layout");
    require(bytes.size() >= minimum_size && bytes.size() <= maximum_bytes, "numeric delta size is outside bounds");
    Reader tail{bytes.last(4)};
    require(crc(bytes.first(bytes.size()-4)) == tail.get(4), "numeric state checksum mismatch");
    Reader reader{bytes.first(bytes.size()-4)};
    for (auto byte : magic) require(reader.get(1) == byte, "unsupported numeric state format");
    for (auto byte : base.identity().base_digest) require(reader.get(1) == byte, "numeric state base digest mismatch");
    require(reader.get(8) == base.identity().layout_id, "numeric state layout mismatch");
    require(reader.get(8) == base.identity().object_id, "numeric state object mismatch");
    require(reader.get(4) == base.values().size(), "numeric state value count mismatch");
    require(reader.get(4) == base.checksum(), "numeric state base contents mismatch");
    DecodedNumericState result;
    result.metadata.revision = reader.get(8);
    result.metadata.parent_revision = reader.get(8);
    require(result.metadata.revision > 0 && result.metadata.parent_revision < result.metadata.revision,
        "invalid numeric state revision");
    result.metadata.changed_values = static_cast<std::uint32_t>(reader.get(4));
    require(result.metadata.changed_values <= base.values().size(), "too many numeric state changes");
    const auto payload_size = reader.get(4);
    require(payload_size == bytes.size() - minimum_size, "numeric state payload size mismatch");
    result.values.assign(base.values().begin() + first, base.values().begin() + first + count);
    std::uint64_t next_index = 0;
    for (std::uint32_t change = 0; change < result.metadata.changed_values; ++change) {
        const auto index = next_index + reader.variable();
        require(index < base.values().size(), "numeric state change index outside layout");
        next_index = index + 1;
        const auto mask = reader.get(1);
        require(mask != 0, "empty numeric state change");
        std::uint64_t difference = 0;
        for (unsigned i = 0; i < 8; ++i) if (mask & (std::uint64_t{1} << i)) {
            const auto byte = reader.get(1);
            require(byte != 0, "noncanonical numeric state byte");
            difference |= byte << (8*i);
        }
        const auto value = std::bit_cast<double>(std::bit_cast<std::uint64_t>(base.values()[index]) ^ difference);
        require(std::isfinite(value), "decoded numeric state must be finite");
        if (index >= first && index - first < count) result.values[index-first] = value;
    }
    require(reader.position == reader.bytes.size(), "trailing numeric state bytes");
    return result;
}

DecodedNumericState decodeNumericStateDelta(const NumericStateBase &base, std::span<const std::uint8_t> bytes) {
    return decodeNumericStateRange(base, bytes, 0, base.values().size());
}

NumericStateHistory::NumericStateHistory(const NumericStateBase &base,
    std::size_t maximum_revisions, std::size_t maximum_encoded_bytes)
    : base_(base), maximum_revisions_(maximum_revisions), maximum_encoded_bytes_(maximum_encoded_bytes) {
    require(maximum_revisions > 0 && maximum_revisions <= 4096, "history revision budget outside bounds");
    require(maximum_encoded_bytes >= minimum_size && maximum_encoded_bytes <= (512U << 20),
        "history byte budget outside bounds");
}

std::uint64_t NumericStateHistory::append(std::span<const double> values, std::uint64_t expected_revision) {
    require(expected_revision == currentRevision(), "stale numeric history revision");
    require(revisions_.size() < maximum_revisions_, "numeric history revision budget exhausted");
    return commit(encodeNumericStateDelta(base_, values, expected_revision + 1, expected_revision));
}

std::uint64_t NumericStateHistory::appendSparse(std::span<const NumericStateEdit> edits, std::uint64_t expected_revision) {
    require(expected_revision == currentRevision(), "stale numeric history revision");
    require(revisions_.size() < maximum_revisions_, "numeric history revision budget exhausted");
    return commit(encodeSparseNumericStateDelta(base_, edits, expected_revision + 1, expected_revision));
}

std::uint64_t NumericStateHistory::commit(Bytes bytes) {
    require(bytes.size() <= maximum_encoded_bytes_ - encoded_bytes_, "numeric history byte budget exhausted");
    const auto size = bytes.size();
    revisions_.push_back(std::move(bytes));
    encoded_bytes_ += size;
    return currentRevision();
}

std::span<const std::uint8_t> NumericStateHistory::encodedRevision(std::uint64_t revision) const {
    require(revision > 0 && revision <= currentRevision(), "numeric history revision is unavailable");
    return revisions_[static_cast<std::size_t>(revision - 1)];
}

std::vector<double> NumericStateHistory::restorationCandidate(std::uint64_t revision) const {
    if (revision == 0) return {base_.values().begin(), base_.values().end()};
    return decodeNumericStateDelta(base_, encodedRevision(revision)).values;
}
} // namespace banjo
