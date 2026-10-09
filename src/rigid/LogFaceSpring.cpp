#include "rigid/LogFaceSpring.hpp"
#include "physics/RotationStrain.hpp"
#include <Jolt/Physics/Constraints/DistanceConstraint.h>
#include <Jolt/Physics/Constraints/ConstraintPart/AxisConstraintPart.h>
#include <Jolt/Physics/Constraints/ConstraintPart/AngleConstraintPart.h>
#include <Jolt/Physics/StateRecorder.h>
#include <cfloat>
#include <stdexcept>
namespace banjo {
namespace {
JPH::Vec3 native(Vec3 v){return {float(v.x),float(v.y),float(v.z)};}
Vec3 vector(JPH::Vec3Arg v){return {v.GetX(),v.GetY(),v.GetZ()};}
Vec3 position(JPH::RVec3Arg v){return {v.GetX(),v.GetY(),v.GetZ()};}
Quat quaternion(JPH::QuatArg q){return {q.GetW(),q.GetX(),q.GetY(),q.GetZ()};}
double axis(Vec3 v,unsigned i){return i==0?v.x:i==1?v.y:v.z;}
class LogSettings final:public JPH::TwoBodyConstraintSettings {
public:
    explicit LogSettings(const JoltWorld::FaceSpringDescription &d):description(d){}
    JPH::TwoBodyConstraint *Create(JPH::Body &a,JPH::Body &b)const override;
    void SaveBinaryState(JPH::StreamOut &)const override{throw std::logic_error("log face spring generic settings serialization unsupported");}
    JoltWorld::FaceSpringDescription description;
};
class LogFaceSpring final:public JPH::TwoBodyConstraint {
public:
    LogFaceSpring(JPH::Body &a,JPH::Body &b,const JoltWorld::FaceSpringDescription &d):
        JPH::TwoBodyConstraint(a,b,LogSettings(d)),description(d){
        JPH::Mat44 frame=JPH::Mat44::sIdentity();frame.SetColumn3(0,native(d.normal_world));
        frame.SetColumn3(1,native(d.tangent_world));frame.SetColumn3(2,native(cross(d.normal_world,d.tangent_world)));
        const JPH::RVec3 anchor(d.anchor_world_m.x,d.anchor_world_m.y,d.anchor_world_m.z);
        for(unsigned i=0;i<2;++i){const auto &body=i?b:a;
            local_anchor[i]=JPH::Vec3(body.GetInverseCenterOfMassTransform()*anchor);
            local_frame[i]=body.GetRotation().Conjugated()*frame.GetQuaternion();
        }
    }
    JPH::EConstraintSubType GetSubType()const override{return JPH::EConstraintSubType::User1;}
    void NotifyShapeChanged(const JPH::BodyID &id,JPH::Vec3Arg delta)override{
        if(mBody1->GetID()==id)local_anchor[0]-=delta;else if(mBody2->GetID()==id)local_anchor[1]-=delta;
    }
    JPH::Mat44 GetConstraintToBody1Matrix()const override{return JPH::Mat44::sRotationTranslation(local_frame[0],local_anchor[0]);}
    JPH::Mat44 GetConstraintToBody2Matrix()const override{return JPH::Mat44::sRotationTranslation(local_frame[1],local_anchor[1]);}
    JoltWorld::FaceSpringObservation observe()const{
        const auto qa=mBody1->GetRotation()*local_frame[0],qb=mBody2->GetRotation()*local_frame[1];
        const auto pa=mBody1->GetCenterOfMassTransform()*local_anchor[0],pb=mBody2->GetCenterOfMassTransform()*local_anchor[1];
        const auto strain=rotationStrain(quaternion(qa),quaternion(qb));const auto gap=vector(JPH::Vec3(pb-pa));
        std::array<Vec3,3> axes{vector(qa.RotateAxisX()),vector(qa.RotateAxisY()),vector(qa.RotateAxisZ())};
        Vec3 translation_impulse{},rotation_impulse{};double *t[]{&translation_impulse.x,&translation_impulse.y,&translation_impulse.z};
        double *r[]{&rotation_impulse.x,&rotation_impulse.y,&rotation_impulse.z};
        for(unsigned i=0;i<3;++i){*t[i]=translation[i].GetTotalLambda();*r[i]=rotation[i].GetTotalLambda()/rotation_scale[i];}
        Vec3 displacement{dot(gap,axes[0]),dot(gap,axes[1]),dot(gap,axes[2])},angle=strain.angle_rad;
        if(plastic_rest_active){displacement-=plastic_translation;angle-=plastic_rotation;}
        return {displacement,angle,translation_impulse,rotation_impulse,position(pb),angle,axes,strain.gradient_axes_world};
    }
    void setPlasticRest(Vec3 translation_m,Vec3 rotation_rad){
        if(translation_m.x==plastic_translation.x&&translation_m.y==plastic_translation.y&&translation_m.z==plastic_translation.z&&
           rotation_rad.x==plastic_rotation.x&&rotation_rad.y==plastic_rotation.y&&rotation_rad.z==plastic_rotation.z)return;
        plastic_translation=translation_m;plastic_rotation=rotation_rad;
        plastic_rest_active=lengthSquared(translation_m)+lengthSquared(rotation_rad)>0;
        ResetWarmStart();
    }
    void prepare(Vec3 va,Vec3 wa,Vec3 vb,Vec3 wb){initial_va=va;initial_wa=wa;initial_vb=vb;initial_wb=wb;}
    void SetupVelocityConstraint(float h)override{
        const auto current=observe();translation_axes=current.translation_axes_world;
        rotation_axes=current.rotation_axes_world;
        const auto point=JPH::RVec3(current.anchor_b_world_m.x,current.anchor_b_world_m.y,current.anchor_b_world_m.z);
        const JPH::Vec3 ra(point-mBody1->GetCenterOfMassPosition()),rb(point-mBody2->GetCenterOfMassPosition());
        const auto relative=initial_vb+cross(initial_wb,vector(rb))-initial_va-cross(initial_wa,vector(ra));
        const auto spin=initial_wb-initial_wa;
        const bool centered=description.centered_integration;
        // Midpoint: J=-h[k*q0+(c/2+h*k/4)*(v0+v1)]. The
        // native soft row solves that equation using k/4, c/2, C=4*q0
        // and bias=v0. Physical coefficients remain in the declaration.
        for(unsigned i=0;i<3;++i){
            translation[i].CalculateConstraintPropertiesWithStiffnessAndDamping(h,*mBody1,ra,*mBody2,rb,native(translation_axes[i]),centered?float(dot(relative,translation_axes[i])):0,
                float(axis(current.displacement_cs_m,i)*(centered?4:1)),float(axis(description.translation_stiffness_n_m,i)*(centered?.25:1)),float(axis(description.translation_damping_n_s_m,i)*(centered?.5:1)));
            rotation_scale[i]=length(rotation_axes[i]);rotation_axes[i]=rotation_axes[i]/rotation_scale[i];
            const auto scale=rotation_scale[i];
            rotation[i].CalculateConstraintPropertiesWithStiffnessAndDamping(h,*mBody1,*mBody2,native(rotation_axes[i]),centered?float(dot(spin,rotation_axes[i])):0,
                float(axis(current.rotation_cs_rad,i)/scale*(centered?4:1)),float(axis(description.rotation_stiffness_n_m_rad,i)*scale*scale*(centered?.25:1)),
                float(axis(description.rotation_damping_n_m_s_rad,i)*scale*scale*(centered?.5:1)));
        }
    }
    void ResetWarmStart()override{for(auto &p:translation)p.Deactivate();for(auto &p:rotation)p.Deactivate();}
    void WarmStartVelocityConstraint(float ratio)override{
        for(unsigned i=0;i<3;++i){translation[i].WarmStart(*mBody1,*mBody2,native(translation_axes[i]),ratio);
            rotation[i].WarmStart(*mBody1,*mBody2,ratio);}
    }
    bool SolveVelocityConstraint(float)override{
        bool applied=false;for(unsigned i=0;i<3;++i)applied|=translation[i].SolveVelocityConstraint(*mBody1,*mBody2,native(translation_axes[i]),-FLT_MAX,FLT_MAX);
        for(unsigned i=0;i<3;++i)applied|=rotation[i].SolveVelocityConstraint(*mBody1,*mBody2,native(rotation_axes[i]),-FLT_MAX,FLT_MAX);
        return applied;
    }
    bool SolvePositionConstraint(float,float)override{return false;}
    void SaveState(JPH::StateRecorder &s)const override{
        TwoBodyConstraint::SaveState(s);for(const auto &p:translation)p.SaveState(s);for(const auto &p:rotation)p.SaveState(s);
        for(unsigned i=0;i<3;++i){s.Write(translation_axes[i]);s.Write(rotation_axes[i]);s.Write(rotation_scale[i]);}
        s.Write(plastic_translation);s.Write(plastic_rotation);s.Write(plastic_rest_active);
    }
    void RestoreState(JPH::StateRecorder &s)override{
        TwoBodyConstraint::RestoreState(s);for(auto &p:translation)p.RestoreState(s);for(auto &p:rotation)p.RestoreState(s);
        for(unsigned i=0;i<3;++i){s.Read(translation_axes[i]);s.Read(rotation_axes[i]);s.Read(rotation_scale[i]);}
        s.Read(plastic_translation);s.Read(plastic_rotation);s.Read(plastic_rest_active);
    }
    JPH::Ref<JPH::ConstraintSettings> GetConstraintSettings()const override{
        throw std::logic_error("log face spring generic settings serialization unsupported; recreate from validated declaration");
    }
#ifdef JPH_DEBUG_RENDERER
    void DrawConstraint(JPH::DebugRenderer *)const override{}
    void DrawConstraintLimits(JPH::DebugRenderer *)const override{}
#endif
private:
    JoltWorld::FaceSpringDescription description;
    Vec3 initial_va{},initial_wa{},initial_vb{},initial_wb{};
    JPH::Vec3 local_anchor[2];JPH::Quat local_frame[2];
    JPH::AxisConstraintPart translation[3];JPH::AngleConstraintPart rotation[3];
    std::array<Vec3,3> translation_axes{},rotation_axes{};double rotation_scale[3]{1,1,1};
    Vec3 plastic_translation{},plastic_rotation{};bool plastic_rest_active{};
};
JPH::TwoBodyConstraint *LogSettings::Create(JPH::Body &a,JPH::Body &b)const{return new LogFaceSpring(a,b,description);}
}
JPH::Ref<JPH::TwoBodyConstraintSettings> logFaceSpringSettings(const JoltWorld::FaceSpringDescription &d){return new LogSettings(d);}
void prepareCenteredFaceSpring(JPH::TwoBodyConstraint &c,Vec3 va,Vec3 wa,Vec3 vb,Vec3 wb){static_cast<LogFaceSpring&>(c).prepare(va,wa,vb,wb);}
JoltWorld::FaceSpringObservation observeLogFaceSpring(const JPH::TwoBodyConstraint &c){return static_cast<const LogFaceSpring&>(c).observe();}
void setLogFacePlasticRest(JPH::TwoBodyConstraint &c,Vec3 p,Vec3 r){static_cast<LogFaceSpring&>(c).setPlasticRest(p,r);}
}
