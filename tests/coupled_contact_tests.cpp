#include "physics/MaterialWrench.hpp"
#include "physics/CohesiveInterfaceKernel.hpp"
#include "material/ConnectorModeKernel.hpp"
#include "physics/MaterialHistoryKernel.hpp"
#include "physics/NormalComplianceKernel.hpp"
#include "physics/CoupledGpuKernel.hpp"
#include <array>
#include <cmath>
#include <iostream>
#include <random>
#include <stdexcept>
using namespace banjo;
namespace {
void require(bool v,const char *m){if(!v)throw std::runtime_error(m);}
FrameQuaternion turn(FrameQuaternion q,unsigned axis,double amount){auto v=dgAxis(axis);return dgUnit(frameMultiply({cos(amount/2),v.x*sin(amount/2),v.y*sin(amount/2),v.z*sin(amount/2)},q));}
void gradient(const std::array<double,30>&a,const std::array<double,30>&b,DGPose pa,DGPose pb,int site){
    auto evaluate=[&](DGPose x,DGPose y){return site<0?dgContact(a.data(),b.data(),x,y):dgSurfaceContact(a.data(),b.data(),x,y,static_cast<unsigned>(site));};
    auto base=evaluate(pa,pb);const auto g=base.gradient;
    const FrameVector rows[]{g.force_a,g.torque_a,g.force_b,g.torque_b};
    require(dgLength(frameAdd(g.force_a,g.force_b))<1e-12,"contact force reaction");
    require(dgLength(frameAdd(frameAdd(frameCross(pa.p,g.force_a),g.torque_a),frameAdd(frameCross(pb.p,g.force_b),g.torque_b)))<1e-12,"contact torque reaction");
    for(unsigned j=0;j<12;++j){auto ap=pa,am=pa,bp=pb,bm=pb;const unsigned row=j/3,axis=j%3;const double epsilon=row%2?1e-6:1e-7;
        auto &positive=row<2?ap:bp;auto &negative=row<2?am:bm;
        if(row%2){positive.q=turn(positive.q,axis,epsilon);negative.q=turn(negative.q,axis,-epsilon);}
        else {positive.p=frameAdd(positive.p,frameScale(dgAxis(axis),epsilon));negative.p=frameAdd(negative.p,frameScale(dgAxis(axis),-epsilon));}
        const double finite=(evaluate(ap,bp).gap-evaluate(am,bm).gap)/(2*epsilon);
        const double exact=frameDot(rows[row],dgAxis(axis));require(fabs(finite-exact)<2e-7,"independent contact gap derivative");
    }
}
}
int main(){try{
    // A zero-radius surface sample can be one ULP outside a translated box,
    // while adding its closest local point to the world center rounds back
    // onto the sample. The exterior normal must not divide that lost gap by
    // zero. This is a real Jacobian witness from the compiled ball probe.
    {
        std::array<double,30> sample{},box{};sample[0]=box[0]=1;
        sample[4]=sample[5]=sample[6]=box[4]=box[5]=box[6]=.0125;
        const DGPose a{{.012500000000000015,.06379968846241157,-.012500000000000164},
                      {1,5.225713013386706e-15,-5.027304629602819e-15,9.12335065991894e-15}};
        const DGPose b{{.012500000000000035,.0887996884624115,-.012499999999999954},
                      {1,3.3444898121104495e-15,-1.612270849281483e-15,1.935251965707791e-15}};
        const auto result=dgSurfaceContact(sample.data(),box.data(),a,b,12);
        require(std::isfinite(result.gradient.force_a.y),"finite exterior sample normal at a rounded world boundary");
        // 80-digit Decimal evaluation of the implemented (FP64) rotated lever
        // and box axes puts the unrounded sample slightly INSIDE the box.
        // The old positive gap belonged to the prematurely rounded point.
        require(fabs(result.gap-(-4.760854624018894e-19))<1e-31,"unrounded surface gap agrees with independent high-precision geometry");
        require(fabs(dgLength(result.gradient.force_a)-1)<1e-14,"exterior sample has a unit normal");
    }
    // A displacement smaller than the ULP of the published center must still
    // change physical compression. Test plane/box and point/box paths, positive
    // and negative increments, common translations and density-derived laws.
    for(double shift:{0.,1.,100.})for(double movement:{-1e-18,1e-18}){
        std::array<double,30> moving{},fixed{};
        moving[0]=1;moving[1]=.0025;moving[2]=moving[1]*.01*.01/6;moving[3]=70e9;
        moving[4]=moving[5]=moving[6]=.005;
        moving[8]=moving[21]=shift+.005;moving[10]=moving[26]=1;
        fixed[0]=0;fixed[3]=211e9;fixed[8]=fixed[21]=shift;fixed[10]=fixed[26]=1;
        double v[6]{};v[1]=2*movement;
        const auto p=dgPrepareTrial(moving.data(),v,1),q=dgPrepareTrial(fixed.data(),v,1);
        const auto before=dgContact(moving.data(),fixed.data(),p.initial,q.initial);
        const auto after=dgContact(moving.data(),fixed.data(),p.ending,q.ending);
        require(fabs((after.gap-before.gap)-movement)<1e-30,"sub-ULP plane compression follows authoritative displacement");
        // Direct surface sample toward an adjacent touching cube, without
        // relying on a quantized world-space closest point.
        fixed[0]=1;fixed[4]=fixed[5]=fixed[6]=.005;
        fixed[8]=fixed[21]=shift;
        moving[8]=moving[21]=shift+.01;
        const auto a=dgPrepareTrial(moving.data(),v,1),b=dgPrepareTrial(fixed.data(),v,1);
        const auto c0=dgSurfaceContact(moving.data(),fixed.data(),a.initial,b.initial,8);
        const auto c1=dgSurfaceContact(moving.data(),fixed.data(),a.ending,b.ending,8);
        require(fabs((c1.gap-c0.gap)-movement)<1e-30,"sub-ULP sampled cube compression follows authoritative displacement");
    }
    std::mt19937_64 rng(91843);std::uniform_real_distribution<double> random(-1,1);
    for(unsigned i=0;i<300;++i){std::array<double,30>a{},b{};a[0]=2;b[0]=i%3;a[4]=.008;b[4]=.012;b[5]=.017;b[6]=.023;
        DGPose pa{{random(rng)*.04,random(rng)*.04+.03,random(rng)*.04},dgUnit({1,random(rng)*.4,random(rng)*.4,random(rng)*.4})};
        DGPose pb{{-.005,-.007,.001},dgUnit({1,random(rng)*.4,random(rng)*.4,random(rng)*.4})};
        gradient(a,b,pa,pb,-1);
        if(i%3==1){a[0]=1;a[4]=a[5]=a[6]=.01;gradient(a,b,pa,pb,static_cast<int>(i%24));}
    }
    // A flat box plane contact has four continuous face loads, rather than a
    // selected corner whose torque jumps on an infinitesimal rotation.
    std::array<double,30>a{},b{};a[0]=1;a[4]=a[5]=a[6]=.01;b[0]=0;
    for(int j=0;j<24;++j)gradient(a,b,{{.003,.009,.002},{1,0,0,0}},{{0,0,0},{1,0,0,0}},j);
    for(unsigned i=0;i<1000;++i){const FrameVector p{.1,.2,-.03},q{-.04,.1,.03},point{.02,.02,.01};
        const FrameVector f{random(rng),random(rng),random(rng)},t{random(rng),random(rng),random(rng)};
        FiniteFrameWrenches w{f,frameAdd(frameCross(dgSub(point,p),f),t),frameScale(f,-1),frameAdd(frameCross(dgSub(point,q),frameScale(f,-1)),frameScale(t,-1))};
        const FrameVector da{random(rng)*.001,random(rng)*.001,random(rng)*.001},db{random(rng)*.001,random(rng)*.001,random(rng)*.001};
        const FrameVector ta{random(rng)*.01,random(rng)*.01,random(rng)*.01},tb{random(rng)*.01,random(rng)*.01,random(rng)*.01};
        const double target=random(rng)*.001;double correction=0;
        require(dgWorkCorrect(w,p,q,da,db,ta,tb,.01,target,correction),"finite work gradient");
        const double applied=frameDot(w.force_a,da)+frameDot(w.force_b,db)+frameDot(w.torque_a,ta)+frameDot(w.torque_b,tb);
        require(fabs(target-applied)<1e-14,"pair discrete work");require(dgLength(frameAdd(w.force_a,w.force_b))<1e-11,"work correction force reaction");
        require(dgLength(frameAdd(frameAdd(frameCross(p,w.force_a),w.torque_a),frameAdd(frameCross(q,w.force_b),w.torque_b)))<1e-11,"work correction torque reaction");
    }
    // Independent normal oscillator frequency; no display name dispatch.
    for(double modulus:{70e9,12e9,211e9,9e9}){
        std::array<double,30> plane{},ball{};plane[3]=211e9;ball[0]=2;ball[1]=.1;ball[2]=.4*.1*.02*.02;ball[3]=modulus;ball[4]=ball[5]=ball[6]=.02;ball[15]=-.3;
        const double k=2/(1/modulus+1/211e9)*.01,omega=sqrt(k/.1),h=.001;
        DGPose p{{0,0,0},{1,0,0,0}},q{{0,.02,0},{1,0,0,0}},future{{0,.02-.3*h,0},{1,0,0,0}};
        const auto plan=dgContactSchedule(plane.data(),ball.data(),p,q,p,future,h,.25,1e-4);
        require(fabs(plan.frequency_rad_s/omega-1)<1e-14,"normal frequency uses material stiffness and effective mass");
        require(fabs(plan.step_s*omega-.25)<1e-14,"bounded normal contact phase");
        ball[15]=0;const auto rest=dgContactSchedule(plane.data(),ball.data(),p,q,p,q,h,.25,1e-4);
        require(rest.step_s==h,"unexcited touching contact does not force tiny steps");
        q.p.y=.02003;future.p.y=q.p.y-.3*h;ball[15]=-.3;
        const auto approach=dgContactSchedule(plane.data(),ball.data(),p,q,p,future,h,.25,1e-4);
        require(fabs(approach.step_s-.00008)<1e-15,"free approach timestep is explicit prediction");
        ball[15]=0;q.p.y=.020000000000001;future.p.y=q.p.y-.5*9.81*h*h;
        const auto quiet=dgContactSchedule(plane.data(),ball.data(),p,q,p,future,h,.25,1e-4);
        require(quiet.step_s==h,"sub-tolerance predicted contact must not bypass excitation cutoff");
    }
    std::cout<<"424 contact derivative checks; rounded boundary witness; 1000 work/P/L projections; four stiffness/phase/approach controls passed\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
