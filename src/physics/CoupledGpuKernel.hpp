#pragma once
// Reference-sized, shared CPU/CUDA, fully finite 3D trial evaluator. A trial
// never mutates accepted state. Newton/global admission live outside this file.
// Isotropic rigid-cell inertia only. One compliant response per shape pair.
#if defined(__CUDACC__) || defined(__CUDACC_RTC__)
#define BANJO_DG_HD __host__ __device__
#else
#define BANJO_DG_HD
#endif
namespace banjo {
BANJO_DG_HD inline bool dgFinite(double x){return x<=1.7976931348623157e308&&x>=-1.7976931348623157e308;}
constexpr unsigned dgMaxBodies=32,dgMaxEdges=128,dgBodyWidth=30,dgEdgeWidth=70,dgLedgerWidth=12;
BANJO_DG_HD inline FrameVector dgSub(FrameVector a,FrameVector b){return frameAdd(a,frameScale(b,-1));}
BANJO_DG_HD inline double dgLength(FrameVector a){return sqrt(frameDot(a,a));}
BANJO_DG_HD inline FrameQuaternion dgUnit(FrameQuaternion a){const double n=sqrt(a.w*a.w+a.x*a.x+a.y*a.y+a.z*a.z);return {a.w/n,a.x/n,a.y/n,a.z/n};}
BANJO_DG_HD inline FrameVector dgRead3(const double *p){return {p[0],p[1],p[2]};}
BANJO_DG_HD inline FrameQuaternion dgRead4(const double *p){return {p[0],p[1],p[2],p[3]};}
BANJO_DG_HD inline void dgWrite3(double *p,FrameVector v){p[0]=v.x;p[1]=v.y;p[2]=v.z;}
BANJO_DG_HD inline void dgWrite4(double *p,FrameQuaternion q){p[0]=q.w;p[1]=q.x;p[2]=q.y;p[3]=q.z;}
struct DGPose { FrameVector p;FrameQuaternion q; };
BANJO_DG_HD inline DGPose dgPose(const double *b){return {dgRead3(b+7),dgRead4(b+10)};}
BANJO_DG_HD inline FrameVector dgRotationChange(FrameQuaternion q,FrameQuaternion reference,FrameVector anchor){
    const auto relative=frameMultiply(q,{reference.w,-reference.x,-reference.y,-reference.z});
    const auto original=frameRotate(reference,anchor),t=frameScale(frameCross({relative.x,relative.y,relative.z},original),2);
    return frameAdd(frameScale(t,relative.w),frameCross({relative.x,relative.y,relative.z},t));
}
BANJO_DG_HD inline void dgStableCoordinates(FiniteFrameCoordinates &c,const double *a,const double *b,
    FrameVector u_a,FrameVector u_b,FrameQuaternion q_a,FrameQuaternion q_b,const double *edge){
    const auto gap=frameAdd(dgRead3(edge+67),frameAdd(dgSub(u_b,u_a),dgSub(dgRotationChange(q_b,dgRead4(b+26),dgRead3(edge+7)),dgRotationChange(q_a,dgRead4(a+26),dgRead3(edge+4)))));
    for(unsigned j=0;j<3;++j)c.q[j]=frameDot(c.axes[j],gap);
}
BANJO_DG_HD inline double dgSign(double x){return x<0?-1:x>0?1:0;}
BANJO_DG_HD inline FrameVector dgAxis(unsigned i){return i==0?FrameVector{1,0,0}:i==1?FrameVector{0,1,0}:FrameVector{0,0,1};}
// Orthogonal projection of a finite increment onto the internal pair space.
// Removing rigid translations/rotations preserves exact pair P/L at midpoint.
// The correction is a discrete gradient of the same integrated material work,
// not a changed potential, post-step velocity projection or dissipative sink.
BANJO_DG_HD inline bool dgWorkCorrect(FiniteFrameWrenches &w,FrameVector midpoint_a,FrameVector midpoint_b,
    FrameVector da,FrameVector db,FrameVector theta_a,FrameVector theta_b,double length,double target_work,double &correction_norm){
    const auto s=dgSub(midpoint_b,midpoint_a),translation=frameScale(frameAdd(da,db),.5);
    const double l2=length*length,alpha=.5*frameDot(s,s)+2*l2;
    const auto rhs=frameAdd(frameScale(frameCross(s,dgSub(db,da)),.5),frameScale(frameAdd(theta_a,theta_b),l2));
    const auto rotation=frameAdd(frameScale(rhs,1/alpha),frameScale(s,.5*frameDot(s,rhs)/(alpha*2*l2)));
    const auto za=frameAdd(dgSub(da,translation),frameScale(frameCross(rotation,s),.5));
    const auto zb=dgSub(dgSub(db,translation),frameScale(frameCross(rotation,s),.5));
    const auto ra=dgSub(theta_a,rotation),rb=dgSub(theta_b,rotation);
    const double denominator=frameDot(za,za)+frameDot(zb,zb)+l2*(frameDot(ra,ra)+frameDot(rb,rb));
    const double applied=frameDot(w.force_a,da)+frameDot(w.force_b,db)+frameDot(w.torque_a,theta_a)+frameDot(w.torque_b,theta_b);
    const double discrepancy=target_work-applied;
    if(denominator==0)return fabs(discrepancy)<=1e-14;
    const double multiplier=discrepancy/denominator;
    const auto ca=frameScale(za,multiplier),cb=frameScale(zb,multiplier),ta=frameScale(ra,multiplier*l2),tb=frameScale(rb,multiplier*l2);
    w.force_a=frameAdd(w.force_a,ca);w.force_b=frameAdd(w.force_b,cb);
    w.torque_a=frameAdd(w.torque_a,ta);w.torque_b=frameAdd(w.torque_b,tb);
    correction_norm+=frameDot(ca,ca)+frameDot(cb,cb)+(frameDot(ta,ta)+frameDot(tb,tb))/l2;
    return dgFinite(multiplier);
}
struct DGContact { double gap{};FiniteFrameWrenches gradient; };
// gradient is d(gap)/d(body pose), NOT the force. Material normal compliance
// determines traction. Branch changes remain visible and require refinement.
BANJO_DG_HD inline DGContact dgContact(const double *a,const double *b,DGPose pa,DGPose pb){
    DGContact out;const int sa=static_cast<int>(a[0]),sb=static_cast<int>(b[0]);
    if(sa==0){out=dgContact(b,a,pb,pa);auto old=out.gradient;out.gradient={old.force_b,old.torque_b,old.force_a,old.torque_a};return out;}
    if(sb==0){
        const auto n=frameRotate(pb.q,{0,1,0});FrameVector point=pa.p;double radius=0;
        if(sa==2)radius=a[4];
        else for(unsigned j=0;j<3;++j){const auto axis=frameRotate(pa.q,dgAxis(j));const double amount=a[4+j]*dgSign(frameDot(axis,n));point=dgSub(point,frameScale(axis,amount));radius+=a[4+j]*fabs(frameDot(axis,n));}
        out.gap=frameDot(dgSub(pa.p,pb.p),n)-radius;
        const auto negative=frameScale(n,-1);out.gradient={n,frameCross(dgSub(point,pa.p),n),negative,frameCross(dgSub(point,pb.p),negative)};return out;
    }
    if(sa==2&&sb==2){const auto d=dgSub(pa.p,pb.p);const double r=dgLength(d);const auto n=frameScale(d,1/r);out.gap=r-a[4]-b[4];out.gradient={n,{},frameScale(n,-1),{}};return out;}
    if(sa==1&&sb==2){out=dgContact(b,a,pb,pa);auto old=out.gradient;out.gradient={old.force_b,old.torque_b,old.force_a,old.torque_a};return out;}
    if(sa==2){
        const auto d=dgSub(pa.p,pb.p);FrameVector point=pb.p,normal{};double inside=1e300;unsigned face=0;double values[3];FrameVector axes[3];bool exterior=false;
        for(unsigned j=0;j<3;++j){axes[j]=frameRotate(pb.q,dgAxis(j));const double value=frameDot(d,axes[j]);values[j]=value;
            const double clamped=value<-b[4+j]?-b[4+j]:value>b[4+j]?b[4+j]:value;point=frameAdd(point,frameScale(axes[j],clamped));
            if(fabs(value)>b[4+j])exterior=true;const double depth=b[4+j]-fabs(value);if(depth<inside){inside=depth;face=j;}}
        const auto difference=dgSub(pa.p,point);double distance=dgLength(difference);
        if(exterior)normal=frameScale(difference,1/distance);
        else {normal=frameScale(axes[face],values[face]<0?-1:1);distance=-inside;point=frameAdd(pa.p,frameScale(normal,inside));}
        out.gap=distance-a[4];const auto negative=frameScale(normal,-1);out.gradient={normal,{},negative,frameCross(dgSub(point,pb.p),negative)};return out;
    }
    FrameVector axes_a[3],axes_b[3];for(unsigned j=0;j<3;++j){axes_a[j]=frameRotate(pa.q,dgAxis(j));axes_b[j]=frameRotate(pb.q,dgAxis(j));}
    const auto d=dgSub(pb.p,pa.p);out.gap=-1e300;
    for(unsigned index=0;index<15;++index){
        FrameVector n;double norm=1;unsigned ia=0,ib=0;
        if(index<3)n=axes_a[index];else if(index<6)n=axes_b[index-3];
        else {ia=(index-6)/3;ib=(index-6)%3;n=frameCross(axes_a[ia],axes_b[ib]);norm=dgLength(n);if(norm<1e-10)continue;n=frameScale(n,1/norm);}
        const double sign=frameDot(d,n)<0?-1:1;n=frameScale(n,sign);
        FrameVector support_a{},support_b{};double radius=0;
        for(unsigned j=0;j<3;++j){support_a=frameAdd(support_a,frameScale(axes_a[j],a[4+j]*dgSign(frameDot(axes_a[j],n))));support_b=frameAdd(support_b,frameScale(axes_b[j],b[4+j]*dgSign(frameDot(axes_b[j],n))));radius+=a[4+j]*fabs(frameDot(axes_a[j],n))+b[4+j]*fabs(frameDot(axes_b[j],n));}
        const double gap=frameDot(d,n)-radius;if(gap<=out.gap)continue;
        FrameVector ga=frameScale(frameCross(support_a,n),-1),gb=frameScale(frameCross(support_b,n),-1);
        const auto t=dgSub(d,frameAdd(support_a,support_b));
        if(index<3)ga=frameAdd(ga,frameCross(n,t));
        else if(index<6)gb=frameAdd(gb,frameCross(n,t));
        else {const auto perpendicular=dgSub(t,frameScale(n,frameDot(n,t)));const double c=frameDot(axes_a[ia],axes_b[ib]);
            ga=frameAdd(ga,frameScale(dgSub(frameScale(axes_b[ib],frameDot(perpendicular,axes_a[ia])),frameScale(perpendicular,c)),sign/norm));
            gb=frameAdd(gb,frameScale(dgSub(frameScale(perpendicular,c),frameScale(axes_a[ia],frameDot(perpendicular,axes_b[ib]))),sign/norm));}
        out.gap=gap;out.gradient={frameScale(n,-1),ga,n,gb};
    }
    return out;
}
BANJO_DG_HD inline double dgScale(const double *b){return static_cast<int>(b[0])==0?.01:static_cast<int>(b[0])==2?2*b[4]:2*(b[4]<b[5]?(b[4]<b[6]?b[4]:b[6]):(b[5]<b[6]?b[5]:b[6]));}
// Box surface quadrature: four interior Gauss points on each of six faces.
// Each sample has the signed distance to the other shape. This avoids the
// nonsmooth extreme-corner torque of a single SAT penetration spring at a
// flat support. It is a declared reduced compliant contact model, not exact
// volume integration or a general edge-edge collision certification.
BANJO_DG_HD inline DGContact dgSurfaceContact(const double *a,const double *b,DGPose pa,DGPose pb,unsigned site){
    const unsigned face=site/4,normal=face/2,u=(normal+1)%3,v=(normal+2)%3;
    FrameVector local{};double components[3]{};components[normal]=(face%2?1:-1)*a[4+normal];
    components[u]=(site%2?1:-1)*a[4+u]/sqrt(3.);
    components[v]=((site/2)%2?1:-1)*a[4+v]/sqrt(3.);
    local=dgRead3(components);const auto lever=frameRotate(pa.q,local);
    double point[30]{};point[0]=2; // zero-radius sphere is the sample point
    auto out=dgContact(point,b,{frameAdd(pa.p,lever),pa.q},pb);
    out.gradient.torque_a=frameCross(lever,out.gradient.force_a);return out;
}
BANJO_DG_HD inline void dgAdd(double *forces,unsigned a,unsigned b,FiniteFrameWrenches w){
    const FrameVector vectors[]{w.force_a,w.torque_a,w.force_b,w.torque_b};
    for(unsigned j=0;j<4;++j){double *p=forces+6*(j<2?a:b)+3*(j%2);p[0]+=vectors[j].x;p[1]+=vectors[j].y;p[2]+=vectors[j].z;}
}
// rows: shape(0 plane/1 box/2 sphere), mass, isotropic I, E, half extents,
// COM, wxyz, v, omega. Edge: a,b,kind,length,anchors,local frames,law,k/y,s32.
// ledger: U0,U1,D increment,return excess,contact U0/U1,correction norm^2,
// contacts,maximum compression,material work,work mismatch,reserved.
BANJO_DG_HD inline int coupledTrialUnchecked(const double *bodies,unsigned n,const double *edges,unsigned m,
    const double *velocity,double h,FrameVector gravity,double *poses,double *residual,double *histories,double *forces,double *ledger){
    DGPose initial[dgMaxBodies],ending[dgMaxBodies],midpoint[dgMaxBodies];FrameVector displacements[dgMaxBodies],turns[dgMaxBodies];
    for(unsigned j=0;j<dgLedgerWidth;++j)ledger[j]=0;
    for(unsigned i=0;i<n;++i){
        const auto b=bodies+dgBodyWidth*i,v=velocity+6*i;initial[i]=dgPose(b);
        const auto vm=frameScale(frameAdd(dgRead3(b+14),dgRead3(v)),.5),wm=frameScale(frameAdd(dgRead3(b+17),dgRead3(v+3)),.5);
        displacements[i]=b[1]>0?frameScale(vm,h):FrameVector{};turns[i]=b[1]>0?frameScale(wm,h):FrameVector{};
        ending[i].p=frameAdd(dgRead3(b+20),frameAdd(dgRead3(b+23),displacements[i]));
        const auto theta=turns[i];ending[i].q=dgUnit(frameMultiply(dgUnit({1,.5*theta.x,.5*theta.y,.5*theta.z}),initial[i].q));
        midpoint[i]={frameScale(frameAdd(initial[i].p,ending[i].p),.5),dgUnit({initial[i].q.w+ending[i].q.w,initial[i].q.x+ending[i].q.x,initial[i].q.y+ending[i].q.y,initial[i].q.z+ending[i].q.z})};
        dgWrite3(poses+7*i,ending[i].p);dgWrite4(poses+7*i+3,ending[i].q);
        dgWrite3(forces+6*i,frameScale(gravity,b[1]));dgWrite3(forces+6*i+3,{});
    }
    for(unsigned e=0;e<m;++e){
        const auto edge=edges+dgEdgeWidth*e;const unsigned a=static_cast<unsigned>(edge[0]),b=static_cast<unsigned>(edge[1]);const int kind=static_cast<int>(edge[2]);
        auto c=finiteFrameCoordinatesUnchecked(ending[a].p,ending[b].p,ending[a].q,ending[b].q,dgRead3(edge+4),dgRead3(edge+7),dgRead4(edge+10),dgRead4(edge+14));
        auto cm=finiteFrameCoordinatesUnchecked(midpoint[a].p,midpoint[b].p,midpoint[a].q,midpoint[b].q,dgRead3(edge+4),dgRead3(edge+7),dgRead4(edge+10),dgRead4(edge+14));
        const double *body_a=bodies+dgBodyWidth*a,*body_b=bodies+dgBodyWidth*b;
        dgStableCoordinates(c,body_a,body_b,frameAdd(dgRead3(body_a+23),displacements[a]),frameAdd(dgRead3(body_b+23),displacements[b]),ending[a].q,ending[b].q,edge);
        dgStableCoordinates(cm,body_a,body_b,frameAdd(dgRead3(body_a+23),frameScale(displacements[a],.5)),frameAdd(dgRead3(body_b+23),frameScale(displacements[b],.5)),midpoint[a].q,midpoint[b].q,edge);
        if(c.rotation.branch_angle>=3.141592653589793-1e-7)return 1;
        const double *old=edge+35;double *state=histories+32*e,loads[6];
        if(kind==2){
            // Same effective-opening potential as CohesiveFacet: kn<gn>+^2
            // + kt|gt|^2. This finite attachment's authored A frame rotates.
            // Rectangle quadrature is declared by the scene, not a new bulk law.
            const double ratio=edge[23],n1=c.q[0]>0?c.q[0]:0,n0=old[22]>0?old[22]:0;
            const double effective=sqrt(n1*n1+ratio*(c.q[1]*c.q[1]+c.q[2]*c.q[2]));
            double q[6]{effective};materialHistoryUnchecked(0,edge+18,edge+23,old,q,state,loads);
            const double scalar=loads[0],sum=effective+old[0],change=c.q[0]-old[22];
            for(unsigned j=0;j<6;++j){loads[j]=0;state[22+j]=c.q[j];}
            if(sum>0){loads[0]=scalar*(n1+n0)/sum*(change==0?(c.q[0]>0?1:0):(n1-n0)/change);
                loads[1]=scalar*ratio*(c.q[1]+old[23])/sum;loads[2]=scalar*ratio*(c.q[2]+old[24])/sum;}
        }else materialHistoryUnchecked(kind,edge+18,edge+23,old,c.q,state,loads);
        auto wrench=finiteFrameWrenchesUnchecked(cm,midpoint[a].p,midpoint[b].p,loads);
        const double work=kind!=1?state[8]:state[17];
        if(!dgWorkCorrect(wrench,midpoint[a].p,midpoint[b].p,displacements[a],displacements[b],turns[a],turns[b],edge[3],-work,ledger[6]))return 2;
        dgAdd(forces,a,b,wrench);
        ledger[0]+=kind!=1?old[3]:old[15];ledger[1]+=kind!=1?state[3]:state[15];
        ledger[2]+=kind!=1?state[9]:state[20];ledger[3]+=kind!=1?0:state[21];ledger[9]+=work;
        ledger[10]+=kind!=1?state[10]:state[18];
    }
    for(unsigned a=0;a<n;++a)for(unsigned b=a+1;b<n;++b){
        const double *ba=bodies+dgBodyWidth*a,*bb=bodies+dgBodyWidth*b;if(ba[1]==0&&bb[1]==0)continue;
        // SAT/distance supplies an exact endpoint separation rejection for
        // these shapes. A disjoint pair has no penetrating surface samples.
        // The independent interval travel gate still bounds missed crossings.
        const auto broad_before=dgContact(ba,bb,initial[a],initial[b]);
        const auto broad_after=dgContact(ba,bb,ending[a],ending[b]);
        if(broad_before.gap>0&&broad_after.gap>0)continue;
        const bool surface_a=static_cast<int>(ba[0])==1&&static_cast<int>(bb[0])!=2;
        const bool surface_b=static_cast<int>(bb[0])==1&&static_cast<int>(ba[0])!=2;
        const unsigned sites=surface_a&&surface_b?48:surface_a||surface_b?24:1;
        for(unsigned site=0;site<sites;++site){
        const bool swapped=surface_b&&(!surface_a||site>=24);
        const auto contact=[&](DGPose pa,DGPose pb){
            if(sites==1)return dgContact(ba,bb,pa,pb);
            if(!swapped)return dgSurfaceContact(ba,bb,pa,pb,site);
            auto out=dgSurfaceContact(bb,ba,pb,pa,site%24);const auto g=out.gradient;
            out.gradient={g.force_b,g.torque_b,g.force_a,g.torque_a};return out;
        };
        const auto before=contact(initial[a],initial[b]),after=contact(ending[a],ending[b]);
        if(!dgFinite(before.gap)||!dgFinite(after.gap))return 3;
        const double scale=dgScale(ba)<dgScale(bb)?dgScale(ba):dgScale(bb);
        const double stiffness=(2/(1/ba[3]+1/bb[3]))*scale/(sites==48?8:sites==24?4:1);
        const auto normal=normalComplianceUnchecked(before.gap,after.gap-before.gap,h,{stiffness,0});
        if(before.gap>0&&after.gap>0)continue;
        const auto middle=contact(midpoint[a],midpoint[b]);
        const double load=normal.impulse_kg_m_s/h;const auto g=middle.gradient;
        FiniteFrameWrenches w{frameScale(g.force_a,load),frameScale(g.torque_a,load),frameScale(g.force_b,load),frameScale(g.torque_b,load)};
        const double work=normal.energy_before_j-normal.energy_after_j;
        if(!dgWorkCorrect(w,midpoint[a].p,midpoint[b].p,displacements[a],displacements[b],turns[a],turns[b],scale,work,ledger[6]))return 4;
        dgAdd(forces,a,b,w);ledger[4]+=normal.energy_before_j;ledger[5]+=normal.energy_after_j;ledger[7]+=1;
        const double compression=before.gap<after.gap?-before.gap:-after.gap;if(compression>ledger[8])ledger[8]=compression;
        }
    }
    for(unsigned i=0;i<n;++i){const double *b=bodies+dgBodyWidth*i,*v=velocity+6*i;
        for(unsigned j=0;j<6;++j){const double mass=j<3?b[1]:b[2],root=sqrt(mass);residual[6*i+j]=mass>0?(v[j]-b[14+j])*root-h*forces[6*i+j]/root:0;if(!dgFinite(residual[6*i+j])||!dgFinite(forces[6*i+j]))return 5;}
    }
    for(unsigned i=0;i<32*m;++i)if(!dgFinite(histories[i]))return 6;
    for(unsigned i=0;i<7*n;++i)if(!dgFinite(poses[i]))return 7;
    for(unsigned i=0;i<dgLedgerWidth;++i)if(!dgFinite(ledger[i]))return 8;
    return 0;
}
}
#undef BANJO_DG_HD
