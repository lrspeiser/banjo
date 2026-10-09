#pragma once
// Renderer-independent finite-frame geometry and conjugate wrenches. The
// checked CPU adapters validate frames/branches; CUDA callers must do so too.
#if defined(__CUDACC__) || defined(__CUDACC_RTC__)
#define BANJO_FRAME_HD __host__ __device__
#else
#define BANJO_FRAME_HD
#endif
namespace banjo {
struct FrameVector { double x{},y{},z{}; };
struct FrameQuaternion { double w{1},x{},y{},z{}; };
BANJO_FRAME_HD inline FrameVector frameAdd(FrameVector a,FrameVector b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
BANJO_FRAME_HD inline FrameVector frameScale(FrameVector a,double s){return {a.x*s,a.y*s,a.z*s};}
BANJO_FRAME_HD inline FrameVector frameCross(FrameVector a,FrameVector b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
BANJO_FRAME_HD inline double frameDot(FrameVector a,FrameVector b){return a.x*b.x+a.y*b.y+a.z*b.z;}
BANJO_FRAME_HD inline FrameVector frameRotate(FrameQuaternion q,FrameVector v){
    const FrameVector u{q.x,q.y,q.z};const auto t=frameScale(frameCross(u,v),2);
    return frameAdd(frameAdd(v,frameScale(t,q.w)),frameCross(u,t));
}
BANJO_FRAME_HD inline FrameQuaternion frameMultiply(FrameQuaternion a,FrameQuaternion b){return {
    a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
    a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
struct FrameRotationStrain { FrameVector angle;FrameVector gradient[3];double branch_angle{}; };
BANJO_FRAME_HD inline FrameRotationStrain frameRotationStrainUnchecked(FrameQuaternion a,FrameQuaternion b){
    auto q=frameMultiply({a.w,-a.x,-a.y,-a.z},b);if(q.w<0)q={-q.w,-q.x,-q.y,-q.z};
    const FrameVector v{q.x,q.y,q.z};const double sine=sqrt(frameDot(v,v)),angle=2*atan2(sine,q.w);
    const auto phi=frameScale(v,sine>1e-14?angle/sine:2);const double t2=frameDot(phi,phi);
    const double coefficient=t2<1e-8?1./12+t2/720+t2*t2/30240:(1-.5*angle/tan(.5*angle))/t2;
    FrameRotationStrain out;out.angle=phi;out.branch_angle=angle;
    const FrameVector axes[]{{1,0,0},{0,1,0},{0,0,1}};
    for(unsigned i=0;i<3;++i)out.gradient[i]=frameRotate(a,frameAdd(frameAdd(axes[i],frameScale(frameCross(phi,axes[i]),.5)),frameScale(frameCross(phi,frameCross(phi,axes[i])),coefficient)));
    return out;
}
struct FiniteFrameCoordinates {
    double q[6]{};FrameVector anchor_a,anchor_b,axes[3];FrameRotationStrain rotation;
};
BANJO_FRAME_HD inline FiniteFrameCoordinates finiteFrameCoordinatesUnchecked(
    FrameVector com_a,FrameVector com_b,FrameQuaternion orientation_a,FrameQuaternion orientation_b,
    FrameVector local_anchor_a,FrameVector local_anchor_b,FrameQuaternion local_frame_a,FrameQuaternion local_frame_b){
    FiniteFrameCoordinates out;
    out.anchor_a=frameAdd(com_a,frameRotate(orientation_a,local_anchor_a));
    out.anchor_b=frameAdd(com_b,frameRotate(orientation_b,local_anchor_b));
    const auto a=frameMultiply(orientation_a,local_frame_a),b=frameMultiply(orientation_b,local_frame_b);
    const auto gap=frameAdd(out.anchor_b,frameScale(out.anchor_a,-1));
    const FrameVector axes[]{{1,0,0},{0,1,0},{0,0,1}};
    for(unsigned i=0;i<3;++i){out.axes[i]=frameRotate(a,axes[i]);out.q[i]=frameDot(out.axes[i],gap);}
    out.rotation=frameRotationStrainUnchecked(a,b);
    out.q[3]=out.rotation.angle.x;out.q[4]=out.rotation.angle.y;out.q[5]=out.rotation.angle.z;
    return out;
}
struct FiniteFrameWrenches { FrameVector force_a,torque_a,force_b,torque_b; };
// loads[i] = dU/dq_i, including retained plastic rest / current damage.
// The common B anchor includes the rotating anisotropic A-frame derivative.
// Applying the same force at each separate anchor omits gap x force and
// creates angular momentum for shear. This is the native LogFaceSpring row.
BANJO_FRAME_HD inline FiniteFrameWrenches finiteFrameWrenchesUnchecked(
    const FiniteFrameCoordinates &coordinates,FrameVector com_a,FrameVector com_b,const double *loads){
    FrameVector force{},couple{};
    for(unsigned i=0;i<3;++i){force=frameAdd(force,frameScale(coordinates.axes[i],loads[i]));couple=frameAdd(couple,frameScale(coordinates.rotation.gradient[i],loads[i+3]));}
    const auto opposite=frameScale(force,-1);
    return {force,frameAdd(frameCross(frameAdd(coordinates.anchor_b,frameScale(com_a,-1)),force),couple),
        opposite,frameAdd(frameCross(frameAdd(coordinates.anchor_b,frameScale(com_b,-1)),opposite),frameScale(couple,-1))};
}
}
#undef BANJO_FRAME_HD
