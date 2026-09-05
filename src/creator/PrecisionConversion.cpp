#include "creator/PrecisionConversion.hpp"
#include "creator/StarterWorld.hpp"
#include <nlohmann/json.hpp>
#include <set>
#include <stdexcept>
namespace banjo {
namespace {
using Json=nlohmann::json;
void require(bool condition,const char *message){if(!condition)throw std::invalid_argument(message);}
Json parse(std::string_view text) {
    require(text.size()<=1024*1024,"conversion input exceeds 1 MiB");
    std::vector<std::set<std::string>> keys;
    auto value=Json::parse(text,[&](int depth,Json::parse_event_t event,Json &v){
        require(depth<=24,"conversion input nesting exceeds 24");
        if(event==Json::parse_event_t::object_start)keys.emplace_back();
        if(event==Json::parse_event_t::key)require(keys.back().insert(v.get<std::string>()).second,"duplicate conversion input field");
        if(event==Json::parse_event_t::object_end)keys.pop_back();return true;
    });
    require(value.is_object()&&(value.contains("world_version")!=value.contains("starter_version")),"conversion requires one creator or starter world");
    return value;
}
std::string normalize(const Json &value) {
    return value.contains("world_version")?CreatorWorld::deserialize(value.dump()).serialize():StarterWorld::deserialize(value.dump()).serialize();
}
}
std::string normalizeSavedWorldJson(std::string_view document) {return normalize(parse(document));}
std::string upgradePositionPrecisionJson(std::string_view document) {
    require(JoltWorld::positionPrecisionBits()==64,"position upgrade requires a 64-bit-position build");
    const auto source=parse(document);const bool creator=source.contains("world_version");
    const auto &version=source.at(creator?"world_version":"starter_version");
    require(version.is_number_unsigned()&&version==5,"normalize legacy saves to v5 in their compatible build before conversion");
    const auto target_signature=Json::parse(CreatorWorld::physicsSignatureJson());
    auto expected_source_signature=target_signature;expected_source_signature["position_bits"]=32;
    require(source.contains("physics_signature")&&source.at("physics_signature")==expected_source_signature,
        "conversion requires matching v5 compiler/materials with recorded 32-bit positions");
    auto candidate=source;candidate["physics_signature"]=target_signature;
    // Full destination validation reconstructs matter, allocations, gameplay
    // ledgers and histories. A tag rewrite alone is not an accepted conversion.
    const auto converted=Json::parse(normalize(candidate));
    require(converted==candidate,"conversion would change state beyond physics identity");
    Json package{{"conversion_version",1},{"operation","upgrade-position-precision-32-to-64"},
        {"source_document",std::string(document)},{"converted_world",converted},
        {"receipt",{{"world_kind",creator?"creator":"starter"},{"source_signature",expected_source_signature},
            {"target_signature",target_signature},{"state_preserved_except_signature",true},{"simulation_steps",0},
            {"limitation","Future trajectories may differ. This preserves declared state, not bit-identical solver caches, contacts or prior numerical errors. The source text is retained for review and recovery."}}}};
    auto output=package.dump(2);require(output.size()<=4*1024*1024,"conversion package exceeds 4 MiB");return output;
}
}
