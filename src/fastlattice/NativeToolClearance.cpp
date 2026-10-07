#include "fastlattice/NativeToolClearance.hpp"
#include "rigid/JoltWorld.hpp"
#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>

namespace banjo::fastlattice {
namespace {
Quat multiply(Quat a,Quat b) {
    return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,
        a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
        a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
        a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};
}
bool finite(Vec3 p) {return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z);}
}
NativeToolEntryClearance inspectToolEntry(const JoltWorld &world,
    std::span<const MatterBodyId> assembly,MatterBodyId held,Vec3 grip_local_m,
    Vec3 desired_grip_m,Quat desired_facing,double tolerance_m) {
    const std::set<MatterBodyId> members(assembly.begin(),assembly.end());
    const double q2=desired_facing.w*desired_facing.w+desired_facing.x*desired_facing.x+
        desired_facing.y*desired_facing.y+desired_facing.z*desired_facing.z;
    if(members.empty() || members.size()>64 || members.size()!=assembly.size() || !members.contains(held) ||
        !finite(grip_local_m)||!finite(desired_grip_m)||!std::isfinite(q2)||std::abs(q2-1)>1e-6||
        !std::isfinite(tolerance_m)||tolerance_m<0||tolerance_m>.01)
        throw std::invalid_argument("invalid native tool entry query");
    const auto root=world.snapshot(held);
    const Quat back{root.orientation_world.w,-root.orientation_world.x,-root.orientation_world.y,-root.orientation_world.z};
    const Quat turn=multiply(desired_facing,back);
    const Vec3 center=desired_grip_m-desired_facing.rotate(grip_local_m);
    NativeToolEntryClearance result;result.checked=result.clear=true;
    for(const auto id:assembly) {
        const auto actual=world.snapshot(id);
        const Vec3 at=center+turn.rotate(actual.center_of_mass_world_m-root.center_of_mass_world_m);
        const Quat facing=multiply(turn,actual.orientation_world);
        ++result.parts_checked;
        for(const auto &met:world.overlapsAt(id,at,facing,tolerance_m)) {
            if(met.named && members.contains(met.body_id))continue;
            if(met.depth_m>result.overlap_m) {
                result.clear=false;result.ground=!met.named;
                result.tool_part=id;result.blocking_body=met.body_id;
                result.overlap_m=met.depth_m;result.witness_m=met.point_world_m;
            }
        }
    }
    return result;
}
}
