#include "physics/SpherePatchSnapshotCodec.hpp"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

using namespace banjo;
namespace {

void check(bool condition, const char *message) { if(!condition) throw std::runtime_error(message); }
template<class F> void rejects(F&&f,const char*message){try{f();}catch(const std::invalid_argument&){return;}throw std::runtime_error(message);}

std::uint32_t crc32(const std::uint8_t *data, std::size_t size) {
    std::uint32_t crc = 0xffffffffU;
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((0U - (crc & 1U)) & 0xedb88320U);
    }
    return ~crc;
}

void setU64(std::vector<std::uint8_t> &bytes, std::size_t offset, std::uint64_t value) {
    for (unsigned i = 0; i < 8; ++i)
        bytes[offset + i] = static_cast<std::uint8_t>(value >> (8 * i));
}

void setU32(std::vector<std::uint8_t> &bytes, std::size_t offset, std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i)
        bytes[offset + i] = static_cast<std::uint8_t>(value >> (8 * i));
}

SmallStrainLaw law(){SmallStrainLaw v;v.kind=SmallStrainLawKind::J2Plastic;v.j2={.young_modulus_pa=1.e6,.poisson_ratio=.25,.initial_yield_stress_pa=1200,.isotropic_hardening_modulus_pa=2.e4,.maximum_total_strain_norm=.08};v.maximum_total_strain_norm=.08;return v;}
PatchDefinition definition(){auto d=makeTetrahedralBrick({.08,.02,.08},{2,1,2},{law(),1000});for(std::size_t i=0;i<d.reference_positions_m.size();++i)if(d.reference_positions_m[i].y==0)d.fixed_components[i]={true,true,true};return d;}
SpherePatchWorld world(const PatchDefinition&d){constexpr double r=.012;return SpherePatchWorld(d,{{.007,.0325,.009},{},{},r,(4./3.)*std::acos(-1.)*r*r*r*7870},{},{.friction_coefficient=.15,.contact_margin_m=1.e-6,.maximum_penetration_m=1.e-5});}
DynamicPatchLoad load(std::size_t n){DynamicPatchLoad v;v.nodal_forces_n.resize(n);v.gravity_m_s2={0,-9.81,0};return v;}

SpherePatchSnapshot yieldedSnapshot(SpherePatchWorld&source,const DynamicPatchLoad&gravity,double dt){
    for(unsigned step=0;step<12000;++step){const auto report=source.step(dt,gravity,{}, {0,-9.81,0});check(report.accepted,"fixture step rejected");for(const auto&p:source.material().patch().state().material_points)if(p.equivalent_plastic_strain>0)return source.snapshot();}
    throw std::runtime_error("fixture did not yield");
}

void codecRoundTripAndContinuation(){
    const auto d=definition();auto source=world(d);const auto gravity=load(d.reference_positions_m.size());const double dt=source.material().stableTimeStepLimitS()*.025;
    const auto snapshot=yieldedSnapshot(source,gravity,dt);const auto bytes=encodeSpherePatchSnapshot(snapshot);const auto decoded=decodeSpherePatchSnapshot(bytes);
    check(encodeSpherePatchSnapshot(decoded)==bytes,"decode/encode must preserve every wire bit");
    auto restored=world(d);restored.restoreSnapshot(decoded);
    for(unsigned i=0;i<200;++i){check(source.step(dt,gravity,{}, {0,-9.81,0}).accepted,"source continuation rejected");check(restored.step(dt,gravity,{}, {0,-9.81,0}).accepted,"restored continuation rejected");}
    check(encodeSpherePatchSnapshot(source.snapshot())==encodeSpherePatchSnapshot(restored.snapshot()),"binary-restored continuation must remain bitwise identical");
    std::cout<<"[INFO] encoded_bytes="<<bytes.size()<<" nodes="<<snapshot.patch.displacements_m.size()<<" tetrahedra="<<snapshot.patch.material_points.size()<<'\n';
}

void corruptionAndBoundsReject(){
    const auto d=definition();auto source=world(d);const auto snapshot=source.snapshot();const auto bytes=encodeSpherePatchSnapshot(snapshot);
    auto corrupt=bytes;corrupt.back()^=0x40;rejects([&]{(void)decodeSpherePatchSnapshot(corrupt);},"payload corruption must fail checksum");
    corrupt=bytes;corrupt[8]=2;rejects([&]{(void)decodeSpherePatchSnapshot(corrupt);},"unsupported codec version rejected");
    corrupt=bytes;corrupt.pop_back();rejects([&]{(void)decodeSpherePatchSnapshot(corrupt);},"truncation rejected");
    corrupt=bytes;corrupt.push_back(0);rejects([&]{(void)decodeSpherePatchSnapshot(corrupt);},"trailing byte rejected");
    corrupt=bytes;
    // Payload starts at byte 24: snapshot version occupies four bytes and the
    // first collection count follows. This count is within the declared cap but
    // cannot fit its minimum 24-byte Vec3 wire footprint in the payload.
    setU64(corrupt,28,65536);
    setU32(corrupt,20,crc32(corrupt.data()+24,corrupt.size()-24));
    rejects([&]{(void)decodeSpherePatchSnapshot(corrupt);},
            "checksum-valid impossible collection footprint rejected before allocation");
    auto limits=SpherePatchSnapshotCodecLimits{};limits.maximum_nodes=snapshot.patch.displacements_m.size()-1;
    rejects([&]{(void)decodeSpherePatchSnapshot(bytes,limits);},"node cap rejects before vector allocation");
    limits={};limits.maximum_bytes=bytes.size()-1;rejects([&]{(void)decodeSpherePatchSnapshot(bytes,limits);},"byte cap rejected");
    auto over_cap=snapshot;
    over_cap.patch.displacements_m.resize(65537);
    rejects([&]{(void)encodeSpherePatchSnapshot(over_cap);},
            "encoder preflight rejects over-cap state vector");
    auto unsupported=snapshot;++unsupported.version;const auto decoded=decodeSpherePatchSnapshot(encodeSpherePatchSnapshot(unsupported));auto target=world(d);
    rejects([&]{target.restoreSnapshot(decoded);},"semantic snapshot version rejected by restore");
    auto malformed=snapshot;malformed.dynamic.time_s=std::numeric_limits<double>::quiet_NaN();
    const auto structurally_valid=decodeSpherePatchSnapshot(encodeSpherePatchSnapshot(malformed));
    const auto before=encodeSpherePatchSnapshot(target.snapshot());
    rejects([&]{target.restoreSnapshot(structurally_valid);},"semantic state corruption rejected by restore");
    check(encodeSpherePatchSnapshot(target.snapshot())==before,
          "semantic rejection must leave destination world bitwise unchanged");
}

} // namespace
int main(){try{codecRoundTripAndContinuation();corruptionAndBoundsReject();return EXIT_SUCCESS;}catch(const std::exception&e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return EXIT_FAILURE;}}
