#include "physics/ContactFrictionBlock.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {
using Pair=std::array<double,2>;
Pair disk(double a,double b,double c,Pair q,double cap){
    if(cap==0)return {};
    auto at=[&](double eta){
        const double aa=a+eta,cc=c+eta,det=aa*cc-b*b;
        return Pair{(b*q[1]-cc*q[0])/det,(b*q[0]-aa*q[1])/det};
    };
    Pair p=at(0);
    if(std::hypot(p[0],p[1])<=cap)return p;
    // For SPD H, |(H+eta I)^-1 q| <= |q|/eta. The right endpoint
    // is feasible, so returned impulses never exceed the specified disk.
    double lo=0,hi=std::hypot(q[0],q[1])/cap;
    for(unsigned i=0;i<64;++i){
        const double mid=lo+(hi-lo)*.5;p=at(mid);
        if(std::hypot(p[0],p[1])>cap)lo=mid;else hi=mid;
    }
    return at(hi);
}
}
std::array<double,3> solveContactFrictionBlock(const std::array<double,9>& k,
    const std::array<double,3>& q,double cap,double twist){
    for(double v:k)if(!std::isfinite(v))throw std::invalid_argument("nonfinite friction mass");
    for(double v:q)if(!std::isfinite(v))throw std::invalid_argument("nonfinite friction gradient");
    if(!std::isfinite(cap)||!std::isfinite(twist)||cap<0||twist<0)
        throw std::invalid_argument("invalid friction cap");
    const double scale=std::max({std::abs(k[0]),std::abs(k[4]),std::abs(k[8])});
    if(std::abs(k[1]-k[3])>1e-12*scale||std::abs(k[2]-k[6])>1e-12*scale||std::abs(k[5]-k[7])>1e-12*scale)
        throw std::invalid_argument("nonsymmetric friction mass");
    const double a=k[0],b=k[1],c=k[4],d=k[2],e=k[5],f=k[8];
    const double sa=a-d*d/f,sb=b-d*e/f,sc=c-e*e/f;
    const double determinant=sa*sc-sb*sb;
    if(!(f>0&&sa>0&&sc>0&&determinant>0)||!std::isfinite(sa)||!std::isfinite(sb)||!std::isfinite(sc)||!std::isfinite(determinant))
        throw std::invalid_argument("friction mass is not positive definite");
    std::array<double,3> best{};double best_value=std::numeric_limits<double>::infinity();
    auto consider=[&](Pair p,double z){
        if(z < -twist || z > twist)return;
        const double value=.5*(a*p[0]*p[0]+2*b*p[0]*p[1]+c*p[1]*p[1]+2*z*(d*p[0]+e*p[1])+f*z*z)+q[0]*p[0]+q[1]*p[1]+q[2]*z;
        if(!std::isfinite(value))throw std::overflow_error("friction objective overflow");
        if(value<best_value){best_value=value;best={p[0],p[1],z};}
    };
    if(twist>0){
        const auto p=disk(sa,sb,sc,{q[0]-d*q[2]/f,q[1]-e*q[2]/f},cap);
        consider(p,-(q[2]+d*p[0]+e*p[1])/f);
        // Eliminating z minimizes over an unrestricted twist axis. If that
        // global minimizer also satisfies the twist interval, restricting
        // the feasible set cannot improve it. No endpoint solves are needed.
        // Keep the original disk root calculation and finite-objective guard.
        if(std::isfinite(best_value))return best;
    }else{
        // Both interval endpoints are the same when twisting is disabled.
        // Solve once, retaining the objective overflow/finite checks.
        consider(disk(a,b,c,{q[0],q[1]},cap),0);
        if(!std::isfinite(best_value))throw std::runtime_error("no finite friction minimizer");
        return best;
    }
    // A constrained minimizer is either interior in z or on one endpoint.
    for(double z:{-twist,twist})consider(disk(a,b,c,{q[0]+d*z,q[1]+e*z},cap),z);
    if(!std::isfinite(best_value))throw std::runtime_error("no finite friction minimizer");
    return best;
}
}
