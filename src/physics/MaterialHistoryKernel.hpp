#pragma once
// The existing resident 32-value material history, with endpoint and integrated
// loads. Requires the shared cohesive/connector kernels and finite inputs.
#if defined(__CUDACC__) || defined(__CUDACC_RTC__)
#define BANJO_HISTORY_HD __host__ __device__
#else
#define BANJO_HISTORY_HD
#endif
namespace banjo {
BANJO_HISTORY_HD inline void materialHistoryUnchecked(int kind,const double *law,const double *coefficients,
    const double *s,const double *q,double *o,double *integrated_loads){
    for(unsigned j=0;j<32;++j)o[j]=s[j];
    for(unsigned j=0;j<6;++j)integrated_loads[j]=0;
    if(kind==0){
        const CohesiveInterfaceLaw p{law[0],law[1],law[2],law[3],law[4]};
        const auto r=advanceCohesiveInterfaceUnchecked(p,{s[0],s[1]},q[0]);
        o[0]=r.state.opening_m;o[1]=r.state.maximum_opening_m;o[2]=r.response.force_n;
        o[3]=r.response.stored_energy_j;o[4]=r.response.dissipated_energy_j;o[5]=r.response.damage;
        o[6]=r.response.separated?1:0;o[7]+=r.opening_work_j;o[8]=r.opening_work_j;
        o[9]=r.dissipated_increment_j;o[10]=r.balance_residual_j;o[11]=r.work_conjugate_force_n;
        integrated_loads[0]=r.work_conjugate_force_n;
    }else{
        double work=0,stored=0,plastic=0,excess=0;bool yielded=false;
        for(unsigned j=0;j<6;++j){
            const double k=coefficients[j],y=coefficients[6+j];
            const double prior=s[22+j]-s[j],trial=q[j]-s[j];
            work+=(.5*k)*(trial+prior)*(trial-prior);
            integrated_loads[j]=(.5*k)*(trial+prior);
            const auto r=connectorModeReturnUnchecked(k,y,q[j],s[j],s[6+j]);
            o[j]=r.plastic_rest;o[6+j]=r.accumulated_flow;o[22+j]=q[j];
            plastic+=r.plastic_increment_j;excess+=r.return_excess_increment_j;
            stored+=r.stored_energy_j;yielded|=r.yielded;
        }
        o[12]+=plastic;o[13]+=excess;if(yielded)o[14]+=1;
        o[15]=stored;o[16]+=work;o[17]=work;o[18]=work-(stored-s[15])-plastic-excess;
        o[19]=coefficients[0]*(o[22]-o[0]);o[20]=plastic;o[21]=excess;
    }
}
}
#undef BANJO_HISTORY_HD
