#include "physics/SpherePatchSnapshotCodec.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {

constexpr std::array<std::uint8_t, 8> magic{{'B', 'J', 'S', 'P', 'S', 'N', 'P', '1'}};
constexpr std::uint32_t codec_version = 1;
constexpr std::size_t header_bytes = 24;

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

void validate(const SpherePatchSnapshotCodecLimits &limits) {
    require(limits.maximum_bytes >= header_bytes && limits.maximum_bytes <= 1024ULL * 1024 * 1024 &&
                limits.maximum_nodes >= 4 && limits.maximum_nodes <= 65536 &&
                limits.maximum_tetrahedra > 0 && limits.maximum_tetrahedra <= 16384 &&
                limits.maximum_materials > 0 && limits.maximum_materials <= 64,
            "Invalid sphere-patch snapshot codec limits");
}

class Writer {
  public:
    explicit Writer(std::size_t limit) : limit_(limit) {
        bytes_.reserve(std::min<std::size_t>(limit, 4096));
    }
    void u8(std::uint8_t value) { append(&value, 1); }
    void u32(std::uint32_t value) { for (unsigned i=0;i<4;++i) u8(value>>(8*i)); }
    void u64(std::uint64_t value) { for (unsigned i=0;i<8;++i) u8(value>>(8*i)); }
    void real(double value) { u64(std::bit_cast<std::uint64_t>(value)); }
    void vec(Vec3 value) { real(value.x); real(value.y); real(value.z); }
    void tensor(const SymmetricTensor3 &v) {
        real(v.xx); real(v.yy); real(v.zz); real(v.xy); real(v.yz); real(v.zx);
    }
    void raw(const std::uint8_t *data, std::size_t count) { append(data, count); }
    std::vector<std::uint8_t> take() { return std::move(bytes_); }
  private:
    void append(const std::uint8_t *data, std::size_t count) {
        require(count <= limit_ - bytes_.size(), "Sphere-patch snapshot byte cap exceeded");
        bytes_.insert(bytes_.end(), data, data + count);
    }
    std::size_t limit_;
    std::vector<std::uint8_t> bytes_;
};

class Reader {
  public:
    Reader(const std::uint8_t *data, std::size_t size) : data_(data), size_(size) {}
    std::uint8_t u8() { require(at_ < size_, "Truncated sphere-patch snapshot"); return data_[at_++]; }
    std::uint32_t u32() { std::uint32_t v=0; for(unsigned i=0;i<4;++i)v|=std::uint32_t(u8())<<(8*i); return v; }
    std::uint64_t u64() { std::uint64_t v=0; for(unsigned i=0;i<8;++i)v|=std::uint64_t(u8())<<(8*i); return v; }
    double real() { return std::bit_cast<double>(u64()); }
    Vec3 vec() { return {real(), real(), real()}; }
    SymmetricTensor3 tensor() { return {real(),real(),real(),real(),real(),real()}; }
    std::size_t remaining() const { return size_ - at_; }
  private:
    const std::uint8_t *data_; std::size_t size_; std::size_t at_{};
};

std::uint32_t crc32(const std::uint8_t *data, std::size_t size) {
    std::uint32_t crc = 0xffffffffU;
    for (std::size_t i=0;i<size;++i) {
        crc ^= data[i];
        for (unsigned bit=0;bit<8;++bit) crc=(crc>>1)^((0U-(crc&1U))&0xedb88320U);
    }
    return ~crc;
}

void state(Writer &w, const J2State &s) {
    w.tensor(s.total_strain); w.tensor(s.plastic_strain);
    w.real(s.equivalent_plastic_strain); w.real(s.plastic_dissipation_j_m3);
}
J2State state(Reader &r) { return {r.tensor(),r.tensor(),r.real(),r.real()}; }
void response(Writer &w, const SmallStrainResponse &v) {
    state(w,v.state); w.tensor(v.stress_pa);
    for(const auto &column:v.tangent_columns) w.tensor(column);
    w.real(v.stored_free_energy_j_m3); w.real(v.plastic_dissipation_j_m3);
    w.real(v.backward_euler_work_excess_j_m3); w.u8(v.yielded?1:0);
}
SmallStrainResponse response(Reader &r) {
    SmallStrainResponse v; v.state=state(r); v.stress_pa=r.tensor();
    for(auto &column:v.tangent_columns) column=r.tensor();
    v.stored_free_energy_j_m3=r.real(); v.plastic_dissipation_j_m3=r.real();
    v.backward_euler_work_excess_j_m3=r.real();
    const auto yielded=r.u8(); require(yielded<=1,"Malformed snapshot boolean"); v.yielded=yielded!=0; return v;
}
std::size_t count(Reader &r, std::size_t cap, std::size_t wire_bytes,
                  const char *message) {
    const auto n = r.u64();
    require(n <= cap && wire_bytes > 0 && n <= r.remaining() / wire_bytes, message);
    return static_cast<std::size_t>(n);
}
void law(Writer&w,const SmallStrainLaw&v) {
    w.u8(static_cast<std::uint8_t>(v.kind)); w.u8(static_cast<std::uint8_t>(v.j2.family));
    w.real(v.j2.young_modulus_pa);w.real(v.j2.poisson_ratio);w.real(v.j2.initial_yield_stress_pa);
    w.real(v.j2.isotropic_hardening_modulus_pa);w.real(v.j2.maximum_total_strain_norm);
    for(double x:v.young_modulus_pa)w.real(x);for(double x:v.poisson_xy_yz_zx)w.real(x);
    for(double x:v.shear_xy_yz_zx_pa)w.real(x);w.real(v.maximum_total_strain_norm);
}
SmallStrainLaw law(Reader&r) {
    SmallStrainLaw v; v.kind=static_cast<SmallStrainLawKind>(r.u8());v.j2.family=static_cast<ContinuumConstitutiveFamily>(r.u8());
    v.j2.young_modulus_pa=r.real();v.j2.poisson_ratio=r.real();v.j2.initial_yield_stress_pa=r.real();
    v.j2.isotropic_hardening_modulus_pa=r.real();v.j2.maximum_total_strain_norm=r.real();
    for(double&x:v.young_modulus_pa)x=r.real();for(double&x:v.poisson_xy_yz_zx)x=r.real();
    for(double&x:v.shear_xy_yz_zx_pa)x=r.real();v.maximum_total_strain_norm=r.real();return v;
}

void payload(Writer&w,const SpherePatchSnapshot&s,const SpherePatchSnapshotCodecLimits&l) {
    const auto nodes=s.definition.reference_positions_m.size(), tets=s.definition.elements.size(), mats=s.definition.materials.size();
    require(nodes<=l.maximum_nodes&&tets<=l.maximum_tetrahedra&&mats<=l.maximum_materials,"Snapshot count cap exceeded");
    require(s.definition.fixed_components.size()<=l.maximum_nodes&&
                s.patch.displacements_m.size()<=l.maximum_nodes&&
                s.patch.last_nodal_forces_n.size()<=l.maximum_nodes&&
                s.dynamic.velocities_m_s.size()<=l.maximum_nodes&&
                s.accepted_evaluation.internal_forces_n.size()<=l.maximum_nodes&&
                s.patch.material_points.size()<=l.maximum_tetrahedra&&
                s.accepted_evaluation.responses.size()<=l.maximum_tetrahedra,
            "Snapshot state or cache count cap exceeded");
    w.u32(s.version);w.u64(nodes);for(auto p:s.definition.reference_positions_m)w.vec(p);
    w.u64(tets);for(const auto&t:s.definition.elements){for(auto n:t.nodes)w.u32(n);w.u32(t.material);}
    w.u64(mats);for(const auto&m:s.definition.materials){law(w,m.law);w.real(m.density_kg_m3);}
    w.u64(s.definition.fixed_components.size());for(const auto&f:s.definition.fixed_components)for(bool b:f)w.u8(b?1:0);
    w.real(s.dynamics.stability_safety_factor);w.real(s.dynamics.maximum_displacement_gradient_norm);w.real(s.dynamics.maximum_time_step_s);w.u8(static_cast<std::uint8_t>(s.dynamics.integrator));
    w.real(s.contact.friction_coefficient);w.real(s.contact.contact_margin_m);w.real(s.contact.maximum_penetration_m);w.u32(s.contact.maximum_contact_events);w.u32(s.contact.maximum_geometry_queries);w.u32(s.contact.maximum_geometry_iterations);
    w.u64(s.patch.displacements_m.size());for(auto v:s.patch.displacements_m)w.vec(v);
    w.u64(s.patch.material_points.size());for(const auto&v:s.patch.material_points)state(w,v);
    w.u64(s.patch.last_nodal_forces_n.size());for(auto v:s.patch.last_nodal_forces_n)w.vec(v);
    w.real(s.patch.accumulated_trapezoidal_external_work_j);w.real(s.patch.accumulated_backward_euler_external_work_j);w.u64(s.patch.revision);
    w.u64(s.dynamic.velocities_m_s.size());for(auto v:s.dynamic.velocities_m_s)w.vec(v);
    w.real(s.dynamic.time_s);w.real(s.dynamic.accumulated_external_force_work_j);w.vec(s.dynamic.accumulated_support_impulse_n_s);w.u64(s.dynamic.revision);
    w.u64(s.accepted_evaluation.internal_forces_n.size());for(auto v:s.accepted_evaluation.internal_forces_n)w.vec(v);
    w.u64(s.accepted_evaluation.responses.size());for(const auto&v:s.accepted_evaluation.responses)response(w,v);
    w.real(s.accepted_evaluation.stored_free_energy_j);w.real(s.accepted_evaluation.plastic_dissipation_j);w.real(s.accepted_evaluation.backward_euler_work_excess_j);w.real(s.accepted_evaluation.maximum_displacement_gradient_norm);
    w.vec(s.sphere.center_m);w.vec(s.sphere.velocity_m_s);w.vec(s.sphere.spin_rad_s);w.real(s.sphere.radius_m);w.real(s.sphere.mass_kg);
}

SpherePatchSnapshot payload(Reader&r,const SpherePatchSnapshotCodecLimits&l) {
    SpherePatchSnapshot s;s.version=r.u32();
    auto n=count(r,l.maximum_nodes,24,"Snapshot node cap exceeded");s.definition.reference_positions_m.resize(n);for(auto&v:s.definition.reference_positions_m)v=r.vec();
    n=count(r,l.maximum_tetrahedra,20,"Snapshot tetrahedron cap exceeded");s.definition.elements.resize(n);for(auto&t:s.definition.elements){for(auto&x:t.nodes)x=r.u32();t.material=r.u32();}
    n=count(r,l.maximum_materials,130,"Snapshot material cap exceeded");s.definition.materials.resize(n);for(auto&m:s.definition.materials){m.law=law(r);m.density_kg_m3=r.real();}
    n=count(r,l.maximum_nodes,3,"Snapshot constraint cap exceeded");s.definition.fixed_components.resize(n);for(auto&f:s.definition.fixed_components)for(auto&&b:f){const auto x=r.u8();require(x<=1,"Malformed snapshot boolean");b=x!=0;}
    s.dynamics.stability_safety_factor=r.real();s.dynamics.maximum_displacement_gradient_norm=r.real();s.dynamics.maximum_time_step_s=r.real();s.dynamics.integrator=static_cast<DynamicPatchIntegrator>(r.u8());
    s.contact.friction_coefficient=r.real();s.contact.contact_margin_m=r.real();s.contact.maximum_penetration_m=r.real();s.contact.maximum_contact_events=r.u32();s.contact.maximum_geometry_queries=r.u32();s.contact.maximum_geometry_iterations=r.u32();
    n=count(r,l.maximum_nodes,24,"Snapshot displacement cap exceeded");s.patch.displacements_m.resize(n);for(auto&v:s.patch.displacements_m)v=r.vec();
    n=count(r,l.maximum_tetrahedra,112,"Snapshot material-point cap exceeded");s.patch.material_points.resize(n);for(auto&v:s.patch.material_points)v=state(r);
    n=count(r,l.maximum_nodes,24,"Snapshot force cap exceeded");s.patch.last_nodal_forces_n.resize(n);for(auto&v:s.patch.last_nodal_forces_n)v=r.vec();
    s.patch.accumulated_trapezoidal_external_work_j=r.real();s.patch.accumulated_backward_euler_external_work_j=r.real();s.patch.revision=r.u64();
    n=count(r,l.maximum_nodes,24,"Snapshot velocity cap exceeded");s.dynamic.velocities_m_s.resize(n);for(auto&v:s.dynamic.velocities_m_s)v=r.vec();
    s.dynamic.time_s=r.real();s.dynamic.accumulated_external_force_work_j=r.real();s.dynamic.accumulated_support_impulse_n_s=r.vec();s.dynamic.revision=r.u64();
    n=count(r,l.maximum_nodes,24,"Snapshot cache-force cap exceeded");s.accepted_evaluation.internal_forces_n.resize(n);for(auto&v:s.accepted_evaluation.internal_forces_n)v=r.vec();
    n=count(r,l.maximum_tetrahedra,473,"Snapshot response cap exceeded");s.accepted_evaluation.responses.resize(n);for(auto&v:s.accepted_evaluation.responses)v=response(r);
    s.accepted_evaluation.stored_free_energy_j=r.real();s.accepted_evaluation.plastic_dissipation_j=r.real();s.accepted_evaluation.backward_euler_work_excess_j=r.real();s.accepted_evaluation.maximum_displacement_gradient_norm=r.real();
    s.sphere.center_m=r.vec();s.sphere.velocity_m_s=r.vec();s.sphere.spin_rad_s=r.vec();s.sphere.radius_m=r.real();s.sphere.mass_kg=r.real();return s;
}

} // namespace

std::vector<std::uint8_t> encodeSpherePatchSnapshot(const SpherePatchSnapshot&s,const SpherePatchSnapshotCodecLimits&l) {
    validate(l);Writer body(l.maximum_bytes-header_bytes);payload(body,s,l);auto p=body.take();
    Writer out(l.maximum_bytes);out.raw(magic.data(),magic.size());out.u32(codec_version);out.u64(p.size());out.u32(crc32(p.data(),p.size()));out.raw(p.data(),p.size());return out.take();
}

SpherePatchSnapshot decodeSpherePatchSnapshot(const std::vector<std::uint8_t>&bytes,const SpherePatchSnapshotCodecLimits&l) {
    validate(l);require(bytes.size()>=header_bytes&&bytes.size()<=l.maximum_bytes,"Invalid snapshot byte length");Reader h(bytes.data(),header_bytes);
    for(auto expected:magic)require(h.u8()==expected,"Invalid sphere-patch snapshot magic");require(h.u32()==codec_version,"Unsupported snapshot codec version");
    const auto size=h.u64();const auto checksum=h.u32();require(size==bytes.size()-header_bytes,"Truncated or trailing sphere-patch snapshot");
    require(crc32(bytes.data()+header_bytes,size)==checksum,"Sphere-patch snapshot checksum mismatch");Reader r(bytes.data()+header_bytes,size);auto result=payload(r,l);require(r.remaining()==0,"Trailing sphere-patch snapshot payload");return result;
}

} // namespace banjo
