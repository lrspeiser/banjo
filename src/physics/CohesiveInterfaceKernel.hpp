#pragma once
// CPU and CUDA evaluate exactly this one physical law. The unchecked entry
// points require validated finite parameters/history. Host wrappers in
// CohesiveInterface.cpp retain public validation and overflow checks.
#if defined(__CUDACC__) || defined(__CUDACC_RTC__)
#define BANJO_COHESIVE_HD __host__ __device__
#else
#define BANJO_COHESIVE_HD
#endif
namespace banjo {
// Explicit normal-opening cohesive law with optional reversible compression.
// No shear, friction, bulk plasticity, thermal conversion or name-based rules.
struct CohesiveInterfaceLaw {
    double stiffness_pa_per_m{};
    double strength_pa{};
    double fracture_energy_j_m2{};
    double area_m2{};
    // Optional reversible compression stiffness. Zero retains tension-only law.
    double compression_stiffness_pa_per_m{};
};
struct CohesiveInterfaceState {
    double opening_m{};
    double maximum_opening_m{};
};
struct CohesiveInterfaceResponse {
    double traction_pa{},force_n{},stored_energy_j{},dissipated_energy_j{};
    double damage{};
    bool separated{};
};
struct CohesiveInterfaceIncrement {
    CohesiveInterfaceState state;
    CohesiveInterfaceResponse response;
    double opening_work_j{};
    double dissipated_increment_j{};
    double balance_residual_j{};
    // Integral of force over this monotone opening increment divided by its
    // signed displacement. It is not an instantaneous endpoint force.
    double work_conjugate_force_n{};
};
BANJO_COHESIVE_HD inline double cohesiveMax(double a,double b){return a<b?b:a;}
BANJO_COHESIVE_HD inline double cohesiveMin(double a,double b){return b<a?b:a;}
BANJO_COHESIVE_HD inline CohesiveInterfaceResponse evaluateCohesiveInterfaceUnchecked(const CohesiveInterfaceLaw &p,const CohesiveInterfaceState &s){
    const double d0=p.strength_pa/p.stiffness_pa_per_m,df=2*p.fracture_energy_j_m2/p.strength_pa;
    const double kappa=s.maximum_opening_m,opening=cohesiveMax(0.0,s.opening_m);
    CohesiveInterfaceResponse r;
    if(kappa>=df){r.damage=1;r.separated=true;r.dissipated_energy_j=p.area_m2*p.fracture_energy_j_m2;}
    double secant=p.stiffness_pa_per_m;
    if(kappa>=df)secant=0;
    else if(kappa>d0){
        secant=p.strength_pa*((df-kappa)/(df-d0))/kappa;
        r.damage=1-secant/p.stiffness_pa_per_m;
        r.dissipated_energy_j=(p.area_m2*p.fracture_energy_j_m2)*((kappa-d0)/(df-d0));
    }
    r.traction_pa=secant*opening;r.force_n=p.area_m2*r.traction_pa;
    r.stored_energy_j=.5*r.force_n*opening;
    if(s.opening_m<0){r.traction_pa=p.compression_stiffness_pa_per_m*s.opening_m;r.force_n=p.area_m2*r.traction_pa;r.stored_energy_j=.5*r.force_n*s.opening_m;}
    return r;
}
BANJO_COHESIVE_HD inline CohesiveInterfaceIncrement advanceCohesiveInterfaceUnchecked(const CohesiveInterfaceLaw &p,const CohesiveInterfaceState &s,double opening){
    const auto before=evaluateCohesiveInterfaceUnchecked(p,s);
    CohesiveInterfaceIncrement out;out.state={opening,cohesiveMax(s.maximum_opening_m,cohesiveMax(0.0,opening))};out.response=evaluateCohesiveInterfaceUnchecked(p,out.state);
    out.dissipated_increment_j=out.response.dissipated_energy_j-before.dissipated_energy_j;
    // Independently integrate the piecewise-linear force path, including
    // unloading/reloading before new damage. Do not define work by balancing
    // the ledger: expose the remaining roundoff residual below.
    const double a=cohesiveMax(0.0,s.opening_m),b=cohesiveMax(0.0,opening),kappa=s.maximum_opening_m;
    const double d0=p.strength_pa/p.stiffness_pa_per_m,df=2*p.fracture_energy_j_m2/p.strength_pa;
    const double secant=kappa>=df?0:kappa<=d0?p.stiffness_pa_per_m:p.strength_pa*((df-kappa)/(df-d0))/kappa;
    if(b<=kappa)out.opening_work_j=(.5*secant*p.area_m2)*(b+a)*(b-a);
    else {
        out.opening_work_j=(.5*secant*p.area_m2)*(kappa+a)*(kappa-a);
        double x=kappa;
        if(x<d0){const double end=cohesiveMin(b,d0);out.opening_work_j+=(.5*p.stiffness_pa_per_m*p.area_m2)*(end+x)*(end-x);x=end;}
        if(x<df&&b>x){const double end=cohesiveMin(b,df);const double t0=p.strength_pa*((df-x)/(df-d0)),t1=p.strength_pa*((df-end)/(df-d0));out.opening_work_j+=p.area_m2*(.5*t0+.5*t1)*(end-x);}
    }
    const double ca=cohesiveMin(0.0,s.opening_m),cb=cohesiveMin(0.0,opening);
    out.opening_work_j+=(.5*p.compression_stiffness_pa_per_m*p.area_m2)*(cb+ca)*(cb-ca);
    out.balance_residual_j=out.opening_work_j-(out.response.stored_energy_j-before.stored_energy_j)-out.dissipated_increment_j;
    const double displacement=opening-s.opening_m;
    out.work_conjugate_force_n=displacement==0?out.response.force_n:out.opening_work_j/displacement;
    return out;
}
}
#undef BANJO_COHESIVE_HD
