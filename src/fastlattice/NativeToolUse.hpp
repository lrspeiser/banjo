#pragma once
#include "fastlattice/LiveWorld.hpp"

namespace banjo::fastlattice {

// Sensor facts supplied by the native adapter. No rendering or host deadlines.
struct NativeToolFeedback {
    Vec3 grip_m{}, grip_velocity_m_s{}, tip_m{}, pointing{};
    Quat facing{};
    bool grip_present{true}, connected{}, reachable{}, target_matches{true};
    double point_depth_m{}, ground_height_m{}, hand_work_j{};
};
struct NativeToolWish {
    Vec3 grip_m{}, grip_velocity_m_s{};
    Quat facing{};
    bool cuts{};
};

// Desired-frame controller only. The existing bounded hand/reaction and native
// contacts determine motion and work. Copying this state participates in rollback.
class NativeToolUseController {
public:
    NativeToolUseController() = default;
    NativeToolUseController(const LiveToolUseAdmission &admission, const LiveToolContactPlan &plan,
        const NativeToolFeedback &actual, double native_s);
    [[nodiscard]] const LiveToolUse &state() const { return state_; }
    [[nodiscard]] NativeToolWish wish(const NativeToolFeedback &actual, double native_s,
        double dt_s, double available_acceleration_m_s2);
    void accepted(const NativeToolFeedback &actual, double native_s,
        const std::vector<LiveGroundWork> &contacts, const std::string &actor);
    void cancel(double native_s, const std::string &reason = "cancelled");
    void interrupt(double native_s, const std::string &reason);
    [[nodiscard]] Vec3 liftGrip() const { return lift_grip_; }
private:
    LiveToolUse state_;
    LiveToolContactPlan plan_;
    Vec3 lift_grip_{}, recovery_tip_{}, working_tip_{};
    Quat initial_facing_{};
    bool lifting_{};
    bool recovery_from_current_{};
    bool pending_contact_close_{};
    Quat recovery_facing_{};
    std::size_t contact_waypoint_{1};
    double requested_speed_m_s_{}, initial_work_j_{};
    void recover(double native_s, const std::string &reason);
    void finish(double native_s, const std::string &reason);
};

} // namespace banjo::fastlattice
