#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
namespace {
void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
void near(double a,double b,double tolerance,const char* message){check(std::isfinite(a)&&std::abs(a-b)<=tolerance,message);}
double coupon(double dt){
    JoltWorld world(0);world.setGravity({});world.setContactSolverIterations(24,4);
    auto material=makeReferenceMaterial(MaterialPreset::Iron);material.restitution=0;
    RigidBallDescription ball;ball.radius_m=.01;ball.material=material;ball.mass_override_kg=1;
    ball.body_id=1;ball.position_world_m={0,0,0};world.addBall(ball);
    ball.body_id=2;ball.position_world_m={.1,0,0};world.addBall(ball);
    const double rest=.08,k=100,c=2;
    const auto spring=world.addDistanceSpring(1,2,rest,k,c);
    world.step(dt);
    const auto a=world.snapshot(1),b=world.snapshot(2);
    const double rate=b.linear_velocity_m_s.x-a.linear_velocity_m_s.x;
    const double expected=-2*k*dt*.02/(1+2*c*dt+2*k*dt*dt);
    near(rate,expected,2e-7,"coupled spring matches backward-Euler two-mass oracle");
    const double impulse=world.distanceSpringImpulse(spring);
    near(impulse,expected/2,2e-7,"spring reports signed actual tensile impulse");
    const double reconstructed=(-impulse/dt-c*rate)/k;
    near(reconstructed,b.center_of_mass_world_m.x-a.center_of_mass_world_m.x-rest,2e-7,
        "applied reaction reconstructs elastic opening, with damping separated");
    const unsigned count=unsigned(std::round(.1/dt));
    const double omega=std::sqrt(2*k-c*c);
    double error=0;
    for(unsigned i=1;i<count;++i){
        world.step(dt);
        const double t=(i+1)*dt;
        const auto sa=world.snapshot(1),sb=world.snapshot(2);
        const double exact=.02*std::exp(-c*t)*(std::cos(omega*t)+c/omega*std::sin(omega*t));
        const double exactRate=-.02*std::exp(-c*t)*2*k/omega*std::sin(omega*t);
        const double positionError=sb.center_of_mass_world_m.x-sa.center_of_mass_world_m.x-rest-exact;
        const double velocityError=(sb.linear_velocity_m_s.x-sa.linear_velocity_m_s.x-exactRate)/omega;
        error=std::max(error,std::sqrt(positionError*positionError+velocityError*velocityError));
    }
    const auto endA=world.snapshot(1),endB=world.snapshot(2);
    check(length(endA.linear_velocity_m_s+endB.linear_velocity_m_s)<1e-7,"internal springs preserve linear momentum");
    std::cout<<"dt_s="<<dt<<" maximum_oscillator_state_error_m="<<error<<'\n';
    world.removeAndDestroy(1);
    bool removed=false;try{(void)world.distanceSpringImpulse(spring);}catch(const std::out_of_range&){removed=true;}
    check(removed,"removing a body also removes its attached physical springs");
    world.step(dt);
    return error;
}
}
int main(){try{
    const auto coarse=coupon(1./240),fine=coupon(1./960);
    check(fine<coarse*.4,"temporal refinement improves physical oscillator accuracy");
    std::cout<<"[PASS] physical spring reaction, damping, convergence and lifetime\n";
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
