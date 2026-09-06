#include "material/SmallStrainLaw.hpp"
#include <nlohmann/json.hpp>
#include <array>
#include <cmath>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
using namespace banjo;
using Json=nlohmann::json;
namespace {
void require(bool b,const char *s){if(!b)throw std::invalid_argument(s);}
void keys(const Json &j,std::initializer_list<const char*> names){
    require(j.is_object()&&j.size()==names.size(),"Unexpected object fields");
    for(auto n:names)require(j.contains(n),"Missing required field");
}
double number(const Json &v){require(v.is_number(),"Expected numeric SI value");double x=v.get<double>();require(std::isfinite(x),"Nonfinite SI value");return x;}
std::array<double,3> triple(const Json &j){require(j.is_array()&&j.size()==3,"Expected three coefficients");return {number(j[0]),number(j[1]),number(j[2])};}
Json tensor(const SymmetricTensor3 &s){return {s.xx,s.yy,s.zz,s.xy,s.yz,s.zx};}
SmallStrainLaw law(const Json &m){
    keys(m,{"material_id","name","units","density_kg_m3","mechanical_law","parameters","required_capabilities","physical_hash"});
    require(m["material_id"].is_string()&&m["name"].is_string()&&m["physical_hash"].is_string(),"Invalid material labels");
    require(m["units"]=="SI","Only SI supported");
    const double density=number(m["density_kg_m3"]);require(density>0&&density<=1e9,"Invalid density");
    require(m["required_capabilities"]==Json::array({"small_strain_reference"}),"Unsupported requested capability");
    const auto &p=m["parameters"];SmallStrainLaw out;
    if(m["mechanical_law"]=="isotropic_elastic"){
        keys(p,{"young_modulus_pa","poisson_ratio","maximum_total_strain_norm"});
        out.kind=SmallStrainLawKind::IsotropicElastic;out.young_modulus_pa[0]=number(p["young_modulus_pa"]);out.poisson_xy_yz_zx[0]=number(p["poisson_ratio"]);out.maximum_total_strain_norm=number(p["maximum_total_strain_norm"]);
    }else if(m["mechanical_law"]=="orthotropic_elastic"){
        keys(p,{"young_modulus_pa","poisson_xy_yz_zx","shear_xy_yz_zx_pa","maximum_total_strain_norm"});
        out.kind=SmallStrainLawKind::OrthotropicElastic;out.young_modulus_pa=triple(p["young_modulus_pa"]);out.poisson_xy_yz_zx=triple(p["poisson_xy_yz_zx"]);out.shear_xy_yz_zx_pa=triple(p["shear_xy_yz_zx_pa"]);out.maximum_total_strain_norm=number(p["maximum_total_strain_norm"]);
    }else if(m["mechanical_law"]=="j2_plastic"){
        keys(p,{"young_modulus_pa","poisson_ratio","initial_yield_stress_pa","isotropic_hardening_modulus_pa","maximum_total_strain_norm"});
        out.kind=SmallStrainLawKind::J2Plastic;out.j2.young_modulus_pa=number(p["young_modulus_pa"]);out.j2.poisson_ratio=number(p["poisson_ratio"]);out.j2.initial_yield_stress_pa=number(p["initial_yield_stress_pa"]);out.j2.isotropic_hardening_modulus_pa=number(p["isotropic_hardening_modulus_pa"]);out.j2.maximum_total_strain_norm=number(p["maximum_total_strain_norm"]);
    }else throw std::invalid_argument("Unsupported mechanical law");
    validateSmallStrainLaw(out);return out;
}
}
int main(){
    try{
        std::string input;char c;while(std::cin.get(c)){require(input.size()<262144,"Input exceeds 256 KiB");input.push_back(c);}
        std::vector<std::set<std::string>> seen;
        auto callback=[&](int,Json::parse_event_t event,Json &value){
            if(event==Json::parse_event_t::object_start)seen.emplace_back();
            if(event==Json::parse_event_t::key)require(seen.back().insert(value.get<std::string>()).second,"Duplicate JSON field");
            if(event==Json::parse_event_t::object_end)seen.pop_back();return true;
        };
        const auto request=Json::parse(input,callback);keys(request,{"material","strains"});const auto material=law(request["material"]);
        const auto &strains=request["strains"];require(strains.is_array()&&!strains.empty()&&strains.size()<=256,"Strain path must contain 1..256 points");
        J2State state;Json samples=Json::array();
        for(const auto &a:strains){require(a.is_array()&&a.size()==6,"Strain requires six tensor components");
            const SymmetricTensor3 strain{number(a[0]),number(a[1]),number(a[2]),number(a[3]),number(a[4]),number(a[5])};
            const auto r=evaluateSmallStrain(material,state,strain);state=r.state;
            samples.push_back({{"stress_pa",tensor(r.stress_pa)},{"strain",tensor(state.total_strain)},{"plastic_strain",tensor(state.plastic_strain)},
                {"equivalent_plastic_strain",state.equivalent_plastic_strain},{"stored_free_energy_j_m3",r.stored_free_energy_j_m3},
                {"plastic_dissipation_j_m3",r.plastic_dissipation_j_m3},{"backward_euler_work_excess_j_m3",r.backward_euler_work_excess_j_m3},{"yielded",r.yielded}});
        }
        std::cout<<Json({{"schema","banjo.material-response.v1"},{"status","complete"},{"scope","small-strain material-point path; no geometry, collision, fracture or rubber model"},{"samples",samples}}).dump()<<'\n';return 0;
    }catch(const std::exception &){std::cout<<Json({{"status","rejected"},{"error","Invalid material, unsupported capability, strain path or input budget"}}).dump()<<'\n';return 1;}
}
