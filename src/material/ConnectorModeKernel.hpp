#pragma once
// Shared CPU/CUDA single-mode perfect-plastic return. Validation, six-mode
// geometry compilation and history bounds stay in ConnectorPlasticity.cpp.
#if defined(__CUDACC__) || defined(__CUDACC_RTC__)
#define BANJO_CONNECTOR_HD __host__ __device__
#else
#define BANJO_CONNECTOR_HD
#endif
namespace banjo {
struct ConnectorModeReturn {
    double plastic_rest{},accumulated_flow{},stored_energy_j{};
    double plastic_increment_j{},return_excess_increment_j{};
    bool yielded{};
};
BANJO_CONNECTOR_HD inline ConnectorModeReturn connectorModeReturnUnchecked(
    double k,double y,double q,double old,double flow){
    ConnectorModeReturn out;out.plastic_rest=old;out.accumulated_flow=flow;
    double elastic=q-old;const double magnitude=elastic<0?-elastic:elastic;
    const double limit=y/k;
    if(magnitude>limit){
        const double magnitude_delta=magnitude-limit;
        const double delta=elastic<0?-magnitude_delta:magnitude_delta;
        out.plastic_rest+=delta;out.accumulated_flow+=magnitude_delta;
        out.plastic_increment_j=y*magnitude_delta;
        out.return_excess_increment_j=.5*k*delta*delta;
        elastic=q-out.plastic_rest;out.yielded=true;
    }
    out.stored_energy_j=.5*k*elastic*elastic;return out;
}
}
#undef BANJO_CONNECTOR_HD
