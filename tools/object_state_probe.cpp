#include "material/Plasticity.hpp"
#include "persistence/NumericStateDelta.hpp"

#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <iostream>
#include <span>
#include <stdexcept>
#include <vector>

using namespace banjo;
using Json = nlohmann::json;
namespace {
std::array<double, 14> pack(const J2State &state) {
    const auto &a = state.total_strain; const auto &b = state.plastic_strain;
    return {a.xx,a.yy,a.zz,a.xy,a.yz,a.zx,b.xx,b.yy,b.zz,b.xy,b.yz,b.zx,
        state.equivalent_plastic_strain,state.plastic_dissipation_j_m3};
}
J2State unpack(std::span<const double> values) {
    if (values.size() != 14) throw std::invalid_argument("J2 layout requires fourteen values");
    return {{values[0],values[1],values[2],values[3],values[4],values[5]},
        {values[6],values[7],values[8],values[9],values[10],values[11]},values[12],values[13]};
}
bool exact(const J2State &a, const J2State &b) {
    const auto x = pack(a), y = pack(b);
    for (unsigned i=0;i<14;++i) if (std::bit_cast<std::uint64_t>(x[i]) != std::bit_cast<std::uint64_t>(y[i])) return false;
    return true;
}
double percentile(std::vector<double> values, double p) {
    std::sort(values.begin(),values.end());
    return values[static_cast<std::size_t>(std::ceil(p*static_cast<double>(values.size())))-1];
}
Json coupon(const J2Material &material) {
    J2State state;
    Json path=Json::array();
    auto sample=[&](const char *phase) {
        const auto stress=reconstructJ2StressPa(material,state);
        const auto energy=j2EnergyDensity(material,state);
        path.push_back({{"phase",phase},{"tensor_shear_strain",state.total_strain.xy},
            {"engineering_shear_strain",2*state.total_strain.xy},{"shear_stress_pa",stress.xy},
            {"plastic_tensor_shear_strain",state.plastic_strain.xy},
            {"elastic_energy_density_j_m3",energy.elastic_free_energy_j_m3},
            {"hardening_energy_density_j_m3",energy.isotropic_hardening_free_energy_j_m3},
            {"plastic_dissipation_density_j_m3",energy.plastic_dissipation_j_m3}});
    };
    sample("virgin");
    for (unsigned i=0;i<100;++i) {
        state=integrateJ2StrainIncrement(material,state,{0,0,0,0.0001,0,0}).state;
        sample("loading");
    }
    const double elastic=state.total_strain.xy-state.plastic_strain.xy;
    for (unsigned i=0;i<100;++i) {
        state=integrateJ2StrainIncrement(material,state,{0,0,0,-elastic/100,0,0}).state;
        sample("unloading");
    }
    return {{"type","prescribed homogeneous pure-shear material-point coupon"},
        {"calibrated_iron",false},{"spatial_dent_simulation",false},{"samples",path},
        {"unloaded_state",pack(state)}};
}
Json benchmark(const J2Material &material, const J2State &unloaded, std::size_t points) {
    // Caller fixture identity for this standalone reference; no world/content
    // registry is implied. The codec independently checks actual base contents.
    NumericStateIdentity identity; identity.base_digest[0]=1;
    identity.layout_id=0x4a325f3134643031ULL; identity.object_id=42;
    std::vector<double> virgin(points*14,0.0);
    const auto base_start=std::chrono::steady_clock::now();
    NumericStateBase base(identity,virgin);
    const double base_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-base_start).count();
    const auto state=pack(unloaded);
    std::vector<NumericStateEdit> edits;
    for (unsigned point=0;point<16;++point) for (unsigned field=0;field<14;++field)
        if (std::bit_cast<std::uint64_t>(state[field])!=0)
            edits.push_back({point*14+field,state[field]});
    const auto bytes=encodeSparseNumericStateDelta(base,edits,1,0);
    auto full=decodeNumericStateDelta(base,bytes);
    if (full.values.size()!=virgin.size()) throw std::runtime_error("full decode size mismatch");
    for (unsigned point=0;point<16;++point) {
        const auto restored=unpack(std::span(full.values).subspan(point*14,14));
        validateJ2State(material,restored);
        if (!exact(unloaded,restored)) throw std::runtime_error("lossless state mismatch");
    }
    for (std::size_t field=16*14;field<full.values.size();++field)
        if (std::bit_cast<std::uint64_t>(full.values[field])!=0) throw std::runtime_error("untouched point changed");
    const SymmetricTensor3 next{0,0,0,.00005,0,0};
    const auto uninterrupted=integrateJ2StrainIncrement(material,unloaded,next);
    std::vector<double> encode_us, partial_us, continuation_us;
    // Warmup is excluded. Measured operations use the same accepted physical
    // state. Full reconstruction and base validation are reported separately.
    for (unsigned run=0;run<120;++run) {
        auto t0=std::chrono::steady_clock::now();
        const auto encoded=encodeSparseNumericStateDelta(base,edits,1,0);
        auto t1=std::chrono::steady_clock::now();
        const auto partial=decodeNumericStateRange(base,encoded,0,16*14);
        auto t2=std::chrono::steady_clock::now();
        for (unsigned point=0;point<16;++point) {
            const auto restored=unpack(std::span(partial.values).subspan(point*14,14));
            validateJ2State(material,restored);
            if (!exact(integrateJ2StrainIncrement(material,restored,next).state,uninterrupted.state))
                throw std::runtime_error("restored material-point continuation differs");
        }
        auto t3=std::chrono::steady_clock::now();
        if (encoded!=bytes) throw std::runtime_error("noncanonical encoding");
        if (run>=20) {
            encode_us.push_back(std::chrono::duration<double,std::micro>(t1-t0).count());
            partial_us.push_back(std::chrono::duration<double,std::micro>(t2-t1).count());
            continuation_us.push_back(std::chrono::duration<double,std::micro>(t3-t2).count());
        }
    }
    NumericStateHistory history(base,4,1024*1024);
    history.appendSparse(edits,0);
    const auto before=history.restorationCandidate(1);
    const auto original=history.restorationCandidate(0);
    // A reference history operation only. Gameplay repair admission, costs,
    // topology, geometry, contacts and collision-safe placement are NOT here.
    history.appendSparse({},1);
    if (history.restorationCandidate(1)!=before || history.restorationCandidate(2)!=original)
        throw std::runtime_error("history restoration lost source or original");
    const auto restored_values=history.restorationCandidate(2);
    const auto reloaded_original=unpack(std::span(restored_values).first(14));
    if (!exact(integrateJ2StrainIncrement(material,reloaded_original,next).state,
        integrateJ2StrainIncrement(material,{},next).state)) throw std::runtime_error("reference restore continuation differs");
    const auto full_start=std::chrono::steady_clock::now();
    const auto redecoded=decodeNumericStateDelta(base,bytes);
    const double full_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-full_start).count();
    return {{"material_points",points},{"changed_material_points",16},{"changed_scalar_values",edits.size()},
        {"base_numeric_bytes",virgin.size()*sizeof(double)},{"delta_bytes",bytes.size()},
        {"restore_original_revision_bytes",history.encodedRevision(2).size()},
        {"history_encoded_bytes",history.encodedBytes()},
        {"base_validation_once_ms",base_ms},{"full_decode_once_ms",full_ms},
        {"sparse_encode_p50_us",percentile(encode_us,.5)},{"sparse_encode_p95_us",percentile(encode_us,.95)},
        {"decode_16_points_p50_us",percentile(partial_us,.5)},{"decode_16_points_p95_us",percentile(partial_us,.95)},
        {"validate_and_resume_16_points_p95_us",percentile(continuation_us,.95)},
        {"measured_repetitions",100},{"lossless_roundtrip",true},{"next_strain_increment_exact",true},
        {"reference_restore_original_exact",true},{"gameplay_repair_implemented",false},
        {"world_reactivation_measured",false},{"render_rebuild_measured",false}};
}
}
int main() {
    try {
        const J2Material material{ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,
            211e9,.3,250e6,1e9,.05};
        Json report={{"schema","banjo.object-state-reference.v1"},
            {"scope","small-strain J2 coupon and sparse lossless numeric-state codec"},
            {"material",{{"young_modulus_pa",material.young_modulus_pa},{"poisson_ratio",material.poisson_ratio},
                {"initial_yield_stress_pa",material.initial_yield_stress_pa},
                {"hardening_modulus_pa",material.isotropic_hardening_modulus_pa},
                {"calibration","illustrative metal-like parameters; not measured iron calibration"}}},
            {"coupon",coupon(material)},{"storage_cases",Json::array()}};
        const auto values=report["coupon"]["unloaded_state"].get<std::array<double,14>>();
        const auto state=unpack(values);
        for (auto points : {64U,4096U,65536U}) report["storage_cases"].push_back(benchmark(material,state,points));
        std::cout<<report.dump(2)<<'\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr<<error.what()<<'\n'; return 1;
    }
}
