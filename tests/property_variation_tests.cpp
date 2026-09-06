#include "material/PropertyVariation.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;

void require(bool condition,std::string_view message){
    if(!condition)throw std::runtime_error(std::string(message));
}
void near(double actual,double expected,double tolerance,std::string_view message){
    if(!std::isfinite(actual)||std::abs(actual-expected)>tolerance){
        throw std::runtime_error(std::string(message)+": actual="+std::to_string(actual)+" expected="+std::to_string(expected));}
}
PropertyVariationKey key(){
    return {.algorithm_version=kPropertyVariationAlgorithmVersion,.property_law_version=3,.material_seed=42,.object_id=7,.element_id=11,.property_id=13};
}

void algorithmVersionHasGoldenUniformSample(){
    const double sample=sampleBoundedProperty(key(),{.minimum=0.,.maximum=1.,.domain=PropertyRangeDomain::Nonnegative});
    require(std::bit_cast<std::uint64_t>(sample)==0x3fd3042115cb9fb8ULL,
        "algorithm v1 key must retain its exact portable top-53-bit sample");
}

void replayAndMaterialRenamingAreExact(){
    const auto stable_key=key();const BoundedPropertyRange bounds{40.e6,50.e6};
    const double first=sampleBoundedProperty(stable_key,bounds);
    for(unsigned tick=0;tick<100;++tick){
        (void)tick;
        require(sampleBoundedProperty(stable_key,bounds)==first,
            "same persisted key and bounds reconstruct exactly on every visit");
    }
    const std::string original_display_name="iron",renamed_display_name="renamed metal";
    require(original_display_name!=renamed_display_name&&
        sampleBoundedProperty(stable_key,bounds)==first,
        "display names are absent from the physical property key");
}

void visitOrderAndPopulationPrefixDoNotChangeSamples(){
    auto stable_key=key();const BoundedPropertyRange bounds{1.,2.};
    std::map<std::uint64_t,double> forward;
    for(std::uint64_t element=0;element<64;++element){
        stable_key.element_id=element;forward.emplace(element,sampleBoundedProperty(stable_key,bounds));
    }
    for(std::uint64_t offset=0;offset<64;++offset){
        const std::uint64_t element=63-offset;stable_key.element_id=element;
        require(sampleBoundedProperty(stable_key,bounds)==forward.at(element),
            "reordered visits must reproduce each stable element sample");
    }
    std::vector<double> prefix;
    for(std::uint64_t element=0;element<8;++element){
        stable_key.element_id=element;prefix.push_back(sampleBoundedProperty(stable_key,bounds));
    }
    for(std::uint64_t element=0;element<128;++element){
        stable_key.element_id=element;(void)sampleBoundedProperty(stable_key,bounds);
    }
    for(std::uint64_t element=0;element<prefix.size();++element){
        stable_key.element_id=element;
        require(sampleBoundedProperty(stable_key,bounds)==prefix[element],
            "adding later elements cannot perturb an existing sample prefix");
    }
}

void everyPhysicalKeyDimensionAffectsTheSample(){
    const BoundedPropertyRange bounds{1.,2.};const auto baseline_key=key();
    const double baseline=sampleBoundedProperty(baseline_key,bounds);
    auto changed=baseline_key;changed.material_seed+=1;
    require(sampleBoundedProperty(changed,bounds)!=baseline,"material seed is part of variation identity");
    changed=baseline_key;changed.object_id+=1;
    require(sampleBoundedProperty(changed,bounds)!=baseline,"stable object ID is part of variation identity");
    changed=baseline_key;changed.element_id+=1;
    require(sampleBoundedProperty(changed,bounds)!=baseline,"stable element ID is part of variation identity");
    changed=baseline_key;changed.property_id+=1;
    require(sampleBoundedProperty(changed,bounds)!=baseline,"stable property ID is part of variation identity");
    changed=baseline_key;changed.property_law_version+=1;
    require(sampleBoundedProperty(changed,bounds)!=baseline,"property law version is part of variation identity");
    changed=baseline_key;changed.object_id=std::numeric_limits<std::uint64_t>::max();
    changed.element_id=std::numeric_limits<std::uint64_t>::max();changed.property_id=std::numeric_limits<std::uint64_t>::max();
    const double maximum_ids=sampleBoundedProperty(changed,bounds);
    require(std::isfinite(maximum_ids)&&maximum_ids>=1.&&maximum_ids<=2.,
        "unsigned hash arithmetic stays bounded at maximum stable IDs");
}

void boundsAndVersionsRejectInvalidDeclarations(){
    const auto stable_key=key();
    require(sampleBoundedProperty(stable_key,{5.,5.})==5.,
        "equal positive endpoints represent a deterministic fixed property");
    const double friction=sampleBoundedProperty(
        stable_key,{.minimum=0.,.maximum=1.,.domain=PropertyRangeDomain::Nonnegative});
    require(friction>=0.&&friction<=1.,"nonnegative domain permits a zero friction lower bound");
    auto rejects=[&](BoundedPropertyRange bounds){
        bool rejected=false;try{(void)sampleBoundedProperty(stable_key,bounds);}catch(const std::invalid_argument &){rejected=true;}
        require(rejected,"invalid property bounds must reject");
    };
    rejects({.minimum=0.,.maximum=1.,.domain=PropertyRangeDomain::StrictlyPositive});
    rejects({.minimum=-1.,.maximum=1.,.domain=PropertyRangeDomain::Nonnegative});
    rejects({.minimum=2.,.maximum=1.,.domain=PropertyRangeDomain::StrictlyPositive});
    rejects({.minimum=std::numeric_limits<double>::quiet_NaN(),.maximum=1.,.domain=PropertyRangeDomain::StrictlyPositive});
    rejects({.minimum=1.,.maximum=std::numeric_limits<double>::infinity(),.domain=PropertyRangeDomain::StrictlyPositive});
    auto invalid_key=stable_key;invalid_key.algorithm_version=2;
    bool rejected=false;try{(void)sampleBoundedProperty(invalid_key,{1.,2.});}catch(const std::invalid_argument &){rejected=true;}
    require(rejected,"unknown variation algorithm version must reject rather than silently change a saved field");
    invalid_key=stable_key;invalid_key.property_law_version=0;rejected=false;
    try{(void)sampleBoundedProperty(invalid_key,{1.,2.});}catch(const std::invalid_argument &){rejected=true;}
    require(rejected,"unversioned property law must reject");
}

void manySeedsStayBoundedWithUniformMomentSanity(){
    auto varied_key=key();constexpr unsigned count=100000;double sum=0,sum_squared=0;
    for(unsigned seed=0;seed<count;++seed){
        varied_key.material_seed=seed;
        const double sample=sampleBoundedProperty(
            varied_key,{.minimum=0.,.maximum=1.,.domain=PropertyRangeDomain::Nonnegative});
        require(sample>=0.&&sample<=1.,"every deterministic variate remains inside declared bounds");
        sum+=sample;sum_squared+=sample*sample;
    }
    const double mean=sum/count,variance=sum_squared/count-mean*mean;
    near(mean,.5,.004,"normalized deterministic samples have the expected uniform mean");
    near(variance,1./12.,.002,"normalized deterministic samples have the expected uniform variance");
    // This is an algorithm sanity check, not a calibrated material flaw model.
}

void glassOakIronStrengthIntervalsArePropertyNotNameDriven(){
    struct Case{std::string_view display_name;std::uint64_t object_id,property_id;BoundedPropertyRange strength;};
    const std::vector<Case> cases{
        {"soda lime glass",101,1,{35.e6,55.e6}},
        {"oak",102,2,{35.e6,55.e6}},
        {"iron",103,3,{180.e6,240.e6}},
    };
    for(const auto &material:cases){
        auto physical_key=key();physical_key.material_seed=987654321;physical_key.object_id=material.object_id;
        physical_key.element_id=44;physical_key.property_id=material.property_id;physical_key.property_law_version=7;
        const double first=sampleBoundedProperty(physical_key,material.strength);
        const double replay=sampleBoundedProperty(physical_key,material.strength);
        require(first==replay&&first>=material.strength.minimum&&first<=material.strength.maximum,
            "glass/oak/iron property samples replay exactly inside their positive declared intervals");
        const std::string renamed=std::string(material.display_name)+" display alias";
        require(!renamed.empty()&&sampleBoundedProperty(physical_key,material.strength)==first,
            "material display rename does not enter the property law");
    }
}
}

int main(){
    const std::vector<std::pair<std::string_view,std::function<void()>>> tests{
        {"versioned golden sample",algorithmVersionHasGoldenUniformSample},
        {"exact replay and name independence",replayAndMaterialRenamingAreExact},
        {"visit order and prefix stability",visitOrderAndPopulationPrefixDoNotChangeSamples},
        {"stable key dimensions",everyPhysicalKeyDimensionAffectsTheSample},
        {"range and version validation",boundsAndVersionsRejectInvalidDeclarations},
        {"bounded uniform moment sanity",manySeedsStayBoundedWithUniformMomentSanity},
        {"glass oak iron property intervals",glassOakIronStrengthIntervalsArePropertyNotNameDriven},
    };
    unsigned failures=0;for(const auto &[name,test]:tests){try{test();std::cout<<"[PASS] "<<name<<'\n';}
        catch(const std::exception &error){++failures;std::cerr<<"[FAIL] "<<name<<": "<<error.what()<<'\n';}}
    std::cout<<tests.size()-failures<<'/'<<tests.size()<<" tests passed\n";return failures==0?EXIT_SUCCESS:EXIT_FAILURE;
}
