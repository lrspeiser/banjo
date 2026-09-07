#include "physics/CorotatedCohesiveFacet.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

constexpr std::array<std::array<double, 3>, 3> quadrature{{
    {{2. / 3., 1. / 6., 1. / 6.}},
    {{1. / 6., 2. / 3., 1. / 6.}},
    {{1. / 6., 1. / 6., 2. / 3.}},
}};

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

Vec3 interpolate(const std::array<Vec3, 3> &values,
                 const std::array<double, 3> &weights) {
    return weights[0] * values[0] + weights[1] * values[1] + weights[2] * values[2];
}

struct Frame {
    Vec3 tangent_1;
    Vec3 tangent_2;
    Vec3 normal;
};

Frame currentFrame(const std::array<Vec3, 3> &a,
                   const std::array<Vec3, 3> &b) {
    std::array<Vec3, 3> middle;
    for (unsigned i = 0; i < 3; ++i) middle[i] = .5 * (a[i] + b[i]);
    const Vec3 edge_1 = middle[1] - middle[0];
    const Vec3 edge_2 = middle[2] - middle[0];
    const double scale = length(edge_1) * length(edge_2);
    const Vec3 area_vector = cross(edge_1, edge_2);
    const double twice_area = length(area_vector);
    require(std::isfinite(scale) && std::isfinite(twice_area) &&
                twice_area > std::max(1.e-24, scale * 1.e-12),
            "Corotated cohesive midsurface is degenerate");
    const Vec3 normal = area_vector / twice_area;
    const Vec3 tangent_1 = edge_1 / length(edge_1);
    const Vec3 tangent_2 = cross(normal, tangent_1);
    const Vec3 area_a = cross(a[1] - a[0], a[2] - a[0]);
    const Vec3 area_b = cross(b[1] - b[0], b[2] - b[0]);
    require(dot(area_a, normal) > 1.e-12 * length(area_a) &&
                dot(area_b, normal) > 1.e-12 * length(area_b),
            "Corotated cohesive side frame is inverted or degenerate");
    return {tangent_1, tangent_2, normal};
}

double referenceArea(const std::array<Vec3, 3> &reference) {
    const Vec3 first = reference[1] - reference[0];
    const Vec3 second = reference[2] - reference[0];
    const double scale = length(first) * length(second);
    const double twice_area = length(cross(first, second));
    require(std::isfinite(scale) && std::isfinite(twice_area) &&
                twice_area > std::max(1.e-24, scale * 1.e-12),
            "Corotated cohesive reference triangle is degenerate");
    return .5 * twice_area;
}

struct PointData {
    double effective_opening{};
    double normal_gap{};
};

std::array<PointData, 3> pointData(const CohesiveFacetLaw &law,
                                   const std::array<Vec3, 3> &a,
                                   const std::array<Vec3, 3> &b) {
    const Frame frame = currentFrame(a, b);
    const double ratio = law.tangential_stiffness_pa_per_m / law.stiffness_pa_per_m;
    require(std::isfinite(ratio) && ratio >= 0.,
            "Corotated cohesive tangential stiffness is invalid");
    std::array<PointData, 3> result;
    for (unsigned point = 0; point < 3; ++point) {
        const Vec3 gap = interpolate(b, quadrature[point]) -
                         interpolate(a, quadrature[point]);
        const double normal_gap = dot(gap, frame.normal);
        const Vec3 tangent_gap = gap - normal_gap * frame.normal;
        result[point] = {std::sqrt(std::max(0., normal_gap) *
                                      std::max(0., normal_gap) +
                                  ratio * lengthSquared(tangent_gap)),
                         normal_gap};
        require(std::isfinite(result[point].effective_opening),
                "Corotated cohesive opening exceeds numeric range");
    }
    return result;
}


constexpr unsigned variables = 18;
struct Dual {
    double value{};
    std::array<double, variables> derivative{};
};
Dual operator+(Dual a, const Dual &b) { a.value += b.value; for(unsigned i=0;i<variables;++i)a.derivative[i]+=b.derivative[i];return a; }
Dual operator-(Dual a, const Dual &b) { a.value -= b.value; for(unsigned i=0;i<variables;++i)a.derivative[i]-=b.derivative[i];return a; }
Dual operator-(Dual a) { a.value=-a.value;for(double &v:a.derivative)v=-v;return a; }
Dual operator*(Dual a, const Dual &b) { const auto da=a.derivative;for(unsigned i=0;i<variables;++i)a.derivative[i]=da[i]*b.value+a.value*b.derivative[i];a.value*=b.value;return a; }
Dual operator*(double a,Dual b){b.value*=a;for(double &v:b.derivative)v*=a;return b;}
Dual operator/(Dual a,const Dual &b){const double inverse=1./b.value;const auto da=a.derivative;for(unsigned i=0;i<variables;++i)a.derivative[i]=(da[i]*b.value-a.value*b.derivative[i])*inverse*inverse;a.value*=inverse;return a;}
Dual root(Dual a){const double value=std::sqrt(a.value);const double scale=.5/value;for(double &v:a.derivative)v*=scale;a.value=value;return a;}
struct DualVec { Dual x,y,z; };
DualVec operator+(DualVec a,const DualVec &b){a.x=a.x+b.x;a.y=a.y+b.y;a.z=a.z+b.z;return a;}
DualVec operator-(DualVec a,const DualVec &b){a.x=a.x-b.x;a.y=a.y-b.y;a.z=a.z-b.z;return a;}
DualVec operator*(Dual a,const DualVec &b){return {a*b.x,a*b.y,a*b.z};}
DualVec operator*(double a,const DualVec &b){return Dual{a}*b;}
Dual dotD(const DualVec&a,const DualVec&b){return a.x*b.x+a.y*b.y+a.z*b.z;}
DualVec crossD(const DualVec&a,const DualVec&b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
Dual normD(const DualVec&a){return root(dotD(a,a));}

struct PotentialParts { Dual cohesion; Dual compression; };
PotentialParts differentiatedPotential(const CohesiveFacetLaw &law,double area,
    const CorotatedCohesiveFacetState &state,const std::array<Vec3,3>&a,
    const std::array<Vec3,3>&b) {
    std::array<DualVec,3> da,db;
    for(unsigned side=0;side<2;++side)for(unsigned node=0;node<3;++node)for(unsigned axis=0;axis<3;++axis){
        const unsigned index=(side*3+node)*3+axis;const Vec3 p=side?b[node]:a[node];
        Dual value;value.value=axis==0?p.x:axis==1?p.y:p.z;value.derivative[index]=1.;
        DualVec &target=side?db[node]:da[node];if(axis==0)target.x=value;else if(axis==1)target.y=value;else target.z=value;
    }
    std::array<DualVec,3> middle;for(unsigned i=0;i<3;++i)middle[i]=.5*(da[i]+db[i]);
    const DualVec e1=middle[1]-middle[0],e2=middle[2]-middle[0];
    const DualVec normal=crossD(e1,e2);const DualVec n=(Dual{1.}/normD(normal))*normal;
    const double ratio=law.tangential_stiffness_pa_per_m/law.stiffness_pa_per_m;
    PotentialParts energy;
    for(unsigned point=0;point<3;++point){
        DualVec gap;
        for(unsigned i=0;i<3;++i)gap=gap+Dual{quadrature[point][i]}*(db[i]-da[i]);
        const Dual gn=dotD(gap,n);const DualVec gt=gap-gn*n;
        const Dual positive=gn.value>0?gn:Dual{};
        const Dual q2=positive*positive+ratio*dotD(gt,gt);
        const CohesiveInterfaceLaw point_law{law.stiffness_pa_per_m,law.strength_pa,
            law.fracture_energy_j_m2,area/3.,0.};
        auto peak=state.integration_points[point];peak.opening_m=peak.maximum_opening_m;
        const auto response=evaluateCohesiveInterface(point_law,peak);
        const double secant=peak.maximum_opening_m>0?response.traction_pa/peak.maximum_opening_m:law.stiffness_pa_per_m;
        energy.cohesion=energy.cohesion+(.5*area/3.*secant)*q2;
        const Dual compression=gn.value<0?gn:Dual{};
        energy.compression=energy.compression+(.5*area/3.*law.compression_stiffness_pa_per_m)*compression*compression;
    }
    return energy;
}

} // namespace

CorotatedCohesiveFacetEvaluation advanceCorotatedCohesiveFacet(
    const CohesiveFacetLaw &law,
    const std::array<Vec3, 3> &reference,
    const std::array<Vec3, 3> &current_a,
    const std::array<Vec3, 3> &current_b,
    const CorotatedCohesiveFacetState &prior,
    const CorotatedCohesiveFacetOptions &options) {
    for (const Vec3 point : reference) require(finite(point), "Invalid cohesive reference point");
    for (const Vec3 point : current_a) require(finite(point), "Invalid cohesive side-A point");
    for (const Vec3 point : current_b) require(finite(point), "Invalid cohesive side-B point");
    require(options.maximum_derivative_evaluations <= 1,
            "Invalid corotated cohesive work options");
    require(std::isfinite(law.compression_stiffness_pa_per_m) &&
                law.compression_stiffness_pa_per_m >= 0.,
            "Invalid corotated cohesive compression stiffness");
    const double area = referenceArea(reference);
    const auto points = pointData(law, current_a, current_b);
    CorotatedCohesiveFacetEvaluation result;
    result.reference_area_m2 = area;
    for (unsigned point = 0; point < 3; ++point) {
        const CohesiveInterfaceLaw point_law{
            law.stiffness_pa_per_m, law.strength_pa,
            law.fracture_energy_j_m2, area / 3., 0.};
        const auto increment = advanceCohesiveInterface(
            point_law, prior.integration_points[point], points[point].effective_opening);
        result.state.integration_points[point] = increment.state;
        result.integration_points[point] = increment.response;
        result.fracture_dissipation_j += increment.response.dissipated_energy_j;
        result.fracture_dissipation_increment_j += increment.dissipated_increment_j;
        result.separated_integration_points += increment.response.separated ? 1U : 0U;
    }
    require(options.maximum_derivative_evaluations >= 1,
            "Corotated cohesive derivative-evaluation budget exhausted");
    const auto parts=differentiatedPotential(law,area,result.state,current_a,current_b);
    const Dual potential=parts.cohesion+parts.compression;
    result.cohesive_stored_energy_j=parts.cohesion.value;
    result.compression_stored_energy_j=parts.compression.value;
    require(std::isfinite(potential.value),
            "Corotated cohesive potential exceeds numeric range");
    for (const double derivative : potential.derivative)
        require(std::isfinite(derivative),
                "Corotated cohesive potential gradient exceeds numeric range");
    result.stored_energy_j=potential.value;++result.derivative_evaluations;
    for (unsigned node = 0; node < 3; ++node)
        for (unsigned axis = 0; axis < 3; ++axis) {
            const unsigned ai=node*3+axis,bi=(3+node)*3+axis;
            double *fa=axis==0?&result.forces_on_a_n[node].x:axis==1?&result.forces_on_a_n[node].y:&result.forces_on_a_n[node].z;
            double *fb=axis==0?&result.forces_on_b_n[node].x:axis==1?&result.forces_on_b_n[node].y:&result.forces_on_b_n[node].z;
            *fa=-potential.derivative[ai];*fb=-potential.derivative[bi];
        }
    for (unsigned node = 0; node < 3; ++node) {
        require(finite(result.forces_on_a_n[node]) && finite(result.forces_on_b_n[node]),
                "Corotated cohesive endpoint force exceeds numeric range");
        result.resultant_n += result.forces_on_a_n[node] + result.forces_on_b_n[node];
        result.current_moment_n_m += cross(current_a[node], result.forces_on_a_n[node]) +
                                     cross(current_b[node], result.forces_on_b_n[node]);
    }
    require(finite(result.resultant_n) && finite(result.current_moment_n_m) &&
                std::isfinite(result.stored_energy_j) &&
                std::isfinite(result.fracture_dissipation_j) &&
                std::isfinite(result.fracture_dissipation_increment_j),
            "Corotated cohesive force, moment, or energy exceeds numeric range");
    return result;
}

} // namespace banjo
