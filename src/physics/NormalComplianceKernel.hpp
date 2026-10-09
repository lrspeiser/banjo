#pragma once
#if defined(__CUDACC__) || defined(__CUDACC_RTC__)
#define BANJO_NORMAL_HD __host__ __device__
#else
#define BANJO_NORMAL_HD
#endif
namespace banjo {
struct NormalComplianceLaw { double stiffness_n_m{},compression_damping_kg_s{}; };
struct NormalComplianceEvaluation {
    double impulse_kg_m_s{},impulse_gap_derivative_kg_s{};
    double energy_before_j{},energy_after_j{},damping_loss_j{};
};
BANJO_NORMAL_HD inline NormalComplianceEvaluation normalComplianceUnchecked(double g0,double change,double dt,const NormalComplianceLaw &law){
    const double g1=g0+change,s0=g0>0?0:g0,s1=g1>0?0:g1;
    NormalComplianceEvaluation r;r.energy_before_j=.5*law.stiffness_n_m*s0*s0;r.energy_after_j=.5*law.stiffness_n_m*s1*s1;
    double force=0,derivative=0;
    if(g0<=0&&g1<=0){force=-.5*law.stiffness_n_m*(2*g0+change);derivative=-.5*law.stiffness_n_m;}
    else if(g0>0&&g1<0){force=-.5*law.stiffness_n_m*g1*g1/change;derivative=-.5*law.stiffness_n_m*g1*(2*change-g1)/(change*change);}
    else if(g0<0&&g1>0){force=.5*law.stiffness_n_m*g0*g0/change;derivative=-.5*law.stiffness_n_m*g0*g0/(change*change);}
    const double compressed_change=g0<=0&&g1<=0?change:s1-s0;
    const double damping_impulse=-law.compression_damping_kg_s*(compressed_change>0?0:compressed_change);
    r.impulse_kg_m_s=dt*force+damping_impulse;r.impulse_gap_derivative_kg_s=dt*derivative;
    if(g1<=0&&compressed_change<=0)r.impulse_gap_derivative_kg_s-=law.compression_damping_kg_s;
    r.damping_loss_j=-damping_impulse*change/dt;return r;
}
}
#undef BANJO_NORMAL_HD
