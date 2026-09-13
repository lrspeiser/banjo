// The C face of the engine.
//
// Everything here is a thin translation: C types in, C++ objects reached, C
// types out, and no exception allowed past the boundary. The only real thinking
// in this file is banjo_advance, which turns the break handshake -- the one
// part of this engine that surprises people -- into a call that cannot leave a
// world wedged.
#include "banjo/banjo.h"

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "thermo/ThermoJson.hpp"
#include "thermo/ThermoWorld.hpp"

#include <algorithm>
#include <cmath>
#include <deque>
#include <exception>
#include <string>
#include <vector>

using banjo::Vec3;
using banjo::fastlattice::BackendKind;
using banjo::fastlattice::LiveBlade;
using banjo::fastlattice::LiveBodyPose;
using banjo::fastlattice::LiveCut;
using banjo::fastlattice::LiveCollected;
using banjo::fastlattice::LiveDelay;
using banjo::fastlattice::LiveImpact;
using banjo::fastlattice::LiveJoint;
using banjo::fastlattice::LiveOverload;
using banjo::fastlattice::LivePick;
using banjo::fastlattice::LiveWorld;
using banjo::fastlattice::TileImpactRequest;

namespace {

// Why the last call on this thread failed. Thread-local because two threads
// driving two worlds must not overwrite each other's answer.
thread_local std::string g_error;

void clearError() { g_error.clear(); }
void setError(const std::string &what) { g_error = what; }

Vec3 readVec(const double v[3]) { return Vec3{v[0], v[1], v[2]}; }
void writeVec(const Vec3 &from, double to[3]) { to[0] = from.x; to[1] = from.y; to[2] = from.z; }

int shapeCode(const std::string &name) {
    if (name == "box") return BANJO_SHAPE_BOX;
    if (name == "sphere") return BANJO_SHAPE_SPHERE;
    return BANJO_SHAPE_HULL;
}

} // namespace

// The handle. It owns the world and the strings the caller is handed: a
// `const char *` has to point at something that outlives the call, and a
// std::string inside a vector that the next query rebuilds does not.
struct banjo_world {
    std::unique_ptr<LiveWorld> world;
    // Rebuilt by each query, so a name handed out stays good until the next
    // call on this world -- which is exactly what the header promises.
    std::vector<LiveBodyPose> poses;
    std::vector<LiveImpact> impacts;
    std::vector<std::string> breakable;
    std::string held;
    std::string picked;
    std::vector<LiveDelay> delays;
    std::string subject;
    // The last sweep, kept so the caller can read it without the sweep having
    // to fit in whatever buffer they brought. Sweeping REMOVES bodies, so a
    // result that did not fit would be matter that had simply vanished.
    std::vector<LiveCollected> collected;
    // The pins, last time anyone asked. Held for the same reason as the poses:
    // the names handed out point into here and have to stay good until the next
    // call on this world.
    std::vector<LiveJoint> joints;
    std::vector<LiveOverload> overloaded;
    // Heat, chemistry and gas, last time anyone asked. Kept for the same
    // reason as the poses: the names handed out point into here.
    std::vector<banjo::thermo::BodyHeat> heats;
    std::vector<banjo::thermo::RegionState> gases;
    std::string report;
    // Blades and their cuts, for the same reason: names handed out point in here.
    std::vector<LiveBlade> blades;
    std::vector<LiveCut> cut_list;
    // Terrain and water, last time anyone asked.
    std::string environment_report;
    std::string environment_state;
    std::string survey;
};

namespace {

// Every entry point is wrapped in this. An exception reaching a C caller is
// undefined behaviour, and the engine throws for ordinary things like a name
// that is not in the scene.
template <typename Work>
int guarded(Work &&work) {
    try {
        clearError();
        return work();
    } catch (const std::invalid_argument &error) {
        setError(error.what());
        return BANJO_BAD_ARGUMENT;
    } catch (const std::out_of_range &error) {
        setError(error.what());
        return BANJO_BAD_ARGUMENT;
    } catch (const std::exception &error) {
        setError(error.what());
        return BANJO_ERROR;
    } catch (...) {
        setError("the engine failed in a way it could not describe");
        return BANJO_ERROR;
    }
}

} // namespace

extern "C" {

int banjo_abi_version(void) { return BANJO_ABI_VERSION; }

const char *banjo_version_string(void) { return "banjo " __DATE__; }

const char *banjo_last_error(void) { return g_error.c_str(); }

banjo_world *banjo_open(const char *scene_json, double cell_size_m) {
    try {
        clearError();
        if (!scene_json) { setError("a scene is needed"); return nullptr; }
        if (!(cell_size_m > 0.0)) { setError("cell_size_m must be positive"); return nullptr; }
        TileImpactRequest request;
        request.cell_size_m = cell_size_m;
        // The lane that runs on any machine. CUDA is chosen by the batch tools
        // when they have it; a library handed to someone else cannot assume it.
        request.backend = BackendKind::CpuParallel;
        request.bodies = banjo::fastlattice::readSceneJson(scene_json);
        banjo::fastlattice::readSceneSettings(scene_json, request);
        if (request.bodies.empty()) { setError("a world needs at least one body"); return nullptr; }
        auto handle = std::make_unique<banjo_world>();
        handle->world = LiveWorld::open(request);
        return handle.release();
    } catch (const std::exception &error) {
        setError(error.what());
        return nullptr;
    } catch (...) {
        setError("the scene could not be opened");
        return nullptr;
    }
}

void banjo_close(banjo_world *world) { delete world; }

int banjo_step(banjo_world *world, double dt_s) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        world->world->forgetImpacts();
        world->world->step(dt_s);
        // A step that was taken back did not happen. Saying so in the return
        // value rather than in a flag the caller has to remember to read is the
        // whole reason this is a status and not void.
        return world->world->steppedBack() ? BANJO_BREAK_PENDING : BANJO_OK;
    });
}

int banjo_advance(banjo_world *world, double dt_s, double window_s) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        // Settle every break the step turns up, then take the step. A fracture
        // replaces a body with its pieces, and a piece can itself be in a
        // contact that wants answering, so this repeats -- but only while
        // something is actually being resolved, and each answered name is
        // recorded by the engine so the same one cannot come back for ever.
        world->world->forgetImpacts();
        for (int rounds = 0; rounds < 64; ++rounds) {
            world->world->step(dt_s);
            if (!world->world->steppedBack()) return BANJO_OK;
            const std::vector<std::string> waiting = world->world->breakable();
            if (waiting.empty()) {
                // Taken back with nothing named: nothing to answer and nothing
                // to do about it. Stop rather than spin.
                setError("the step was taken back but nothing was named as breakable");
                return BANJO_ERROR;
            }
            for (const std::string &name : waiting)
                world->world->fracture(name, window_s);
        }
        setError("breaks kept arriving for 64 rounds without the step going through");
        return BANJO_ERROR;
    });
}

double banjo_time(const banjo_world *world) {
    return world ? world->world->time_s() : 0.0;
}

int banjo_breakable_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->breakable = world->world->breakable();
        return static_cast<int>(mutable_world->breakable.size());
    });
}

const char *banjo_breakable_name(const banjo_world *world, int i) {
    if (!world || i < 0 || static_cast<std::size_t>(i) >= world->breakable.size()) return nullptr;
    return world->breakable[static_cast<std::size_t>(i)].c_str();
}

int banjo_fracture(banjo_world *world, const char *name, double window_s) {
    if (!world || !name) { setError("no world or no name"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { return static_cast<int>(world->world->fracture(name, window_s)); });
}

int banjo_begin_fracture(banjo_world *world, const char *name, double window_s) {
    if (!world || !name) { setError("no world or no name"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        // A window of 0 means the default, so a caller who does not want to
        // think about it does not have to.
        const bool started = window_s > 0.0 ? world->world->beginFracture(name, window_s)
                                            : world->world->beginFracture(name);
        // False means there was nothing to run -- anchored scenery, a name that
        // is not there, something in a hand. It was answered, so the world is
        // not wedged; there is simply nothing to collect.
        if (!started) { setError("there was nothing to work out for that name"); return BANJO_BAD_ARGUMENT; }
        return BANJO_OK;
    });
}

int banjo_fracture_pending(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { return world->world->fracturePending() ? 1 : 0; });
}

int banjo_fracture_ready(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { return world->world->fractureReady() ? 1 : 0; });
}

const char *banjo_fracture_subject(const banjo_world *world) {
    if (!world) return "";
    auto *mutable_world = const_cast<banjo_world *>(world);
    try {
        mutable_world->subject = world->world->fractureSubject();
    } catch (...) {
        mutable_world->subject.clear();
    }
    return mutable_world->subject.c_str();
}

int banjo_finish_fracture(banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { return static_cast<int>(world->world->finishFracture()); });
}

int banjo_last_outcome(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return static_cast<int>(world->world->lastOutcome());
}

int banjo_decline_break(banjo_world *world, const char *name) {
    if (!world || !name) { setError("no world or no name"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->declineBreak(name); return BANJO_OK; });
}

int banjo_body_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { return static_cast<int>(world->world->bodies()); });
}

int banjo_bodies(const banjo_world *world, banjo_body *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        // Cell geometry is deliberately not fetched: it does not change between
        // steps and a bowl carries two thousand points.
        mutable_world->poses = world->world->poses(false);
        const int count = std::min<int>(max, static_cast<int>(mutable_world->poses.size()));
        for (int i = 0; i < count; ++i) {
            const LiveBodyPose &pose = mutable_world->poses[static_cast<std::size_t>(i)];
            banjo_body &body = out[i];
            body.name = pose.name.c_str();
            body.material = pose.material.c_str();
            writeVec(pose.position_m, body.position_m);
            for (int k = 0; k < 4; ++k) body.orientation_wxyz[k] = pose.orientation_wxyz[k];
            writeVec(pose.velocity_m_s, body.velocity_m_s);
            writeVec(pose.dimensions_m, body.dimensions_m);
            body.shape = shapeCode(pose.shape);
            body.anchored = pose.anchored ? 1 : 0;
            body.held = pose.held ? 1 : 0;
            body.rgba = pose.color_rgba;
        }
        return count;
    });
}

int banjo_impact_count(const banjo_world *world, double quiet_speed_m_s) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->impacts = world->world->impacts(quiet_speed_m_s);
        return static_cast<int>(mutable_world->impacts.size());
    });
}

int banjo_impacts(const banjo_world *world, double quiet_speed_m_s,
                  banjo_impact *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->impacts = world->world->impacts(quiet_speed_m_s);
        const int count = std::min<int>(max, static_cast<int>(mutable_world->impacts.size()));
        for (int i = 0; i < count; ++i) {
            const LiveImpact &hit = mutable_world->impacts[static_cast<std::size_t>(i)];
            out[i].struck = hit.struck.c_str();
            out[i].by = hit.by.c_str();
            out[i].closing_speed_m_s = hit.closing_speed_m_s;
            out[i].threshold_speed_m_s = hit.threshold_speed_m_s;
            out[i].dent_speed_m_s = hit.dent_speed_m_s;
            out[i].energy_j = hit.energy_j;
            out[i].would_break = hit.would_break ? 1 : 0;
            out[i].would_dent = hit.would_dent ? 1 : 0;
        }
        return count;
    });
}

int banjo_delay_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->delays = world->world->delays();
        return static_cast<int>(mutable_world->delays.size());
    });
}

int banjo_delays(const banjo_world *world, banjo_delay *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->delays = world->world->delays();
        const int count = std::min<int>(max, static_cast<int>(mutable_world->delays.size()));
        for (int i = 0; i < count; ++i) {
            const LiveDelay &delay = mutable_world->delays[static_cast<std::size_t>(i)];
            out[i].at_s = delay.at_s;
            out[i].object = delay.object.c_str();
            out[i].kind = delay.kind;
            out[i].lead_ms = delay.lead_ms;
            out[i].cost_ms = delay.cost_ms;
        }
        return count;
    });
}

int banjo_forget_delays(banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->forgetDelays(); return BANJO_OK; });
}

int banjo_foresee(banjo_world *world, double horizon_s) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->foreseeCollisions(horizon_s); return BANJO_OK; });
}

int banjo_collect(banjo_world *world, const double at_m[3], double radius_m,
                  int largest_cells) {
    if (!world || !at_m) { setError("no world or no place to sweep"); return BANJO_BAD_ARGUMENT; }
    if (!(radius_m > 0.0)) { setError("a sweep needs a positive radius"); return BANJO_BAD_ARGUMENT; }
    if (largest_cells < 0) { setError("largest_cells cannot be negative"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        const std::size_t biggest = largest_cells > 0
                                        ? static_cast<std::size_t>(largest_cells) : 64;
        world->collected = world->world->collect(
            Vec3{at_m[0], at_m[1], at_m[2]}, radius_m, biggest);
        return static_cast<int>(world->collected.size());
    });
}

int banjo_collected(const banjo_world *world, banjo_lot *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    const int count = std::min<int>(max, static_cast<int>(world->collected.size()));
    for (int i = 0; i < count; ++i) {
        const LiveCollected &lot = world->collected[static_cast<std::size_t>(i)];
        out[i].material = lot.material.c_str();
        out[i].kilograms = lot.kilograms;
        out[i].pieces = static_cast<int>(lot.pieces);
        out[i].cells = static_cast<int>(lot.cells);
    }
    return count;
}

int banjo_overload_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->overloaded = world->world->overloaded();
        return static_cast<int>(mutable_world->overloaded.size());
    });
}

int banjo_overloaded(const banjo_world *world, banjo_overload *out, int max) {
    if (!world || (!out && max > 0) || max < 0) {
        setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->overloaded = world->world->overloaded();
        const int count = std::min<int>(max,
                                        static_cast<int>(mutable_world->overloaded.size()));
        for (int i = 0; i < count; ++i) {
            const LiveOverload &load = mutable_world->overloaded[static_cast<std::size_t>(i)];
            out[i].name = load.name.c_str();
            out[i].carrying_n = load.carrying_n;
            out[i].span_m = load.span_m;
            out[i].stress_pa = load.stress_pa;
            out[i].strength_pa = load.strength_pa;
        }
        return count;
    });
}

int banjo_grab(banjo_world *world, const char *name) {
    if (!world || !name) { setError("no world or no name"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        if (world->world->grab(name)) return BANJO_OK;
        setError(std::string("\"") + name + "\" cannot be picked up: it is not in the scene, "
                 "or it is anchored scenery");
        return BANJO_BAD_ARGUMENT;
    });
}

int banjo_move_held(banjo_world *world, const double to_m[3]) {
    if (!world || !to_m) { setError("no world or nowhere to move to"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->moveHeld(readVec(to_m)); return BANJO_OK; });
}

int banjo_release(banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->release(); return BANJO_OK; });
}

const char *banjo_held(const banjo_world *world) {
    if (!world) return "";
    auto *mutable_world = const_cast<banjo_world *>(world);
    mutable_world->held = world->world->held();
    return mutable_world->held.c_str();
}

int banjo_hinge(banjo_world *world, const char *a, const char *b,
                const double at_m[3], const double axis[3],
                double lower_deg, double upper_deg, double friction_n_m) {
    if (!world || !a || !b || !at_m || !axis) {
        setError("no world, no names, or no pin"); return BANJO_BAD_ARGUMENT;
    }
    if (!(lower_deg >= -180.0 && lower_deg <= 0.0 && upper_deg >= 0.0 && upper_deg <= 180.0)) {
        setError("hinge limits are degrees either side of where it is hung: a lower "
                 "from -180 to 0 and an upper from 0 to 180");
        return BANJO_BAD_ARGUMENT;
    }
    if (!(friction_n_m >= 0.0)) {
        setError("hinge friction is newton metres, zero or more"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const unsigned pin = world->world->hinge(a, b, readVec(at_m), readVec(axis),
                                                 lower_deg, upper_deg, friction_n_m);
        if (pin == 0) {
            setError(std::string("\"") + b + "\" cannot be hung on \"" + a +
                     "\": one of them is not in the scene, they are the same thing, "
                     "or the axis has no direction");
            // Both arms of this lambda have to be the same type, and one of
            // them is a joint id rather than a status.
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(pin);
    });
}

int banjo_slide(banjo_world *world, const char *a, const char *b,
                const double at_m[3], const double axis[3],
                double lower_m, double upper_m, double friction_n) {
    if (!world || !a || !b || !at_m || !axis) {
        setError("no world, no names, or no groove"); return BANJO_BAD_ARGUMENT;
    }
    if (!(lower_m <= 0.0) || !(upper_m >= 0.0) || !(lower_m <= upper_m)) {
        setError("slide travel is metres either side of where it is built: a lower "
                 "of zero or less and an upper of zero or more");
        return BANJO_BAD_ARGUMENT;
    }
    if (!(friction_n >= 0.0)) {
        setError("slide friction is newtons, zero or more"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const unsigned groove = world->world->slide(a, b, readVec(at_m), readVec(axis),
                                                    lower_m, upper_m, friction_n);
        if (groove == 0) {
            setError(std::string("\"") + b + "\" cannot slide along \"" + a +
                     "\": one of them is not in the scene, they are the same thing, "
                     "or the axis has no direction");
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(groove);
    });
}

int banjo_tie(banjo_world *world, const char *a, const char *b,
              const double at_a_m[3], const double at_b_m[3],
              double length_m, double breaking_tension_n) {
    if (!world || !a || !b || !at_a_m || !at_b_m) {
        setError("no world, no names, or nowhere to tie"); return BANJO_BAD_ARGUMENT;
    }
    if (!(length_m >= 0.0)) {
        setError("a tie's length is zero (as they stand) or more"); return BANJO_BAD_ARGUMENT;
    }
    if (!(breaking_tension_n >= 0.0)) {
        setError("breaking tension is newtons, zero (never parts) or more");
        return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const unsigned rope = world->world->tie(a, b, readVec(at_a_m), readVec(at_b_m),
                                                length_m, breaking_tension_n);
        if (rope == 0) {
            setError(std::string("\"") + b + "\" cannot be tied to \"" + a +
                     "\": one of them is not in the scene, or they are the same thing");
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(rope);
    });
}

int banjo_reeve(banjo_world *world, const char *a, const char *b,
                const double at_a_m[3], const double at_b_m[3],
                const double over_a_m[3], const double over_b_m[3],
                double ratio, double length_m) {
    if (!world || !a || !b || !at_a_m || !at_b_m || !over_a_m || !over_b_m) {
        setError("no world, no names, or nowhere to reeve"); return BANJO_BAD_ARGUMENT;
    }
    if (!(ratio > 0.0)) {
        setError("a pulley's ratio must be more than zero"); return BANJO_BAD_ARGUMENT;
    }
    if (!(length_m >= 0.0)) {
        setError("a pulley's length is zero (as rove) or more"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const unsigned rove = world->world->reeve(a, b, readVec(at_a_m), readVec(at_b_m),
                                                  readVec(over_a_m), readVec(over_b_m),
                                                  ratio, length_m);
        if (rove == 0) {
            setError(std::string("\"") + a + "\" and \"" + b +
                     "\" cannot be rove together: one of them is not in the scene, "
                     "or they are the same thing");
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(rove);
    });
}

int banjo_fix(banjo_world *world, const char *a, const char *b,
              const double at_m[3], const double axis[3],
              double holds_tension_n, double holds_shear_n) {
    if (!world || !a || !b || !at_m || !axis) {
        setError("no world, no names, or nowhere to fix"); return BANJO_BAD_ARGUMENT;
    }
    if (!(holds_tension_n >= 0.0) || !(holds_shear_n >= 0.0)) {
        setError("a fixing's strengths are newtons, zero (never lets go) or more");
        return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const unsigned peg = world->world->fix(a, b, readVec(at_m), readVec(axis),
                                               holds_tension_n, holds_shear_n);
        if (peg == 0) {
            setError(std::string("\"") + b + "\" cannot be fixed to \"" + a +
                     "\": one of them is not in the scene, they are the same thing, "
                     "or the axis has no direction");
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(peg);
    });
}

int banjo_spring(banjo_world *world, const char *a, const char *b,
                 const double at_a_m[3], const double at_b_m[3],
                 double rest_m, double stiffness_n_m, double damping_n_s_m) {
    if (!world || !a || !b || !at_a_m || !at_b_m) {
        setError("no world, no names, or nowhere to spring"); return BANJO_BAD_ARGUMENT;
    }
    if (!(stiffness_n_m > 0.0)) {
        setError("a spring needs a positive stiffness in newtons per metre");
        return BANJO_BAD_ARGUMENT;
    }
    if (!(damping_n_s_m >= 0.0)) {
        setError("spring damping is newton seconds per metre, zero or more");
        return BANJO_BAD_ARGUMENT;
    }
    if (!(rest_m >= 0.0)) {
        setError("a spring's rest length is zero (as it stands) or more");
        return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const unsigned limb = world->world->spring(a, b, readVec(at_a_m), readVec(at_b_m),
                                                   rest_m, stiffness_n_m, damping_n_s_m);
        if (limb == 0) {
            setError(std::string("a spring cannot go between \"") + a + "\" and \"" +
                     b + "\": one of them is not in the scene, or they are the same thing");
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(limb);
    });
}

int banjo_joint_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->joints = world->world->joints();
        return static_cast<int>(mutable_world->joints.size());
    });
}

int banjo_joints(const banjo_world *world, banjo_joint *out, int max) {
    if (!world || (!out && max > 0) || max < 0) {
        setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        constexpr double kDegrees = 180.0 / 3.14159265358979323846;
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->joints = world->world->joints();
        const int count = std::min<int>(max, static_cast<int>(mutable_world->joints.size()));
        for (int i = 0; i < count; ++i) {
            const LiveJoint &joint = mutable_world->joints[static_cast<std::size_t>(i)];
            const bool turning = joint.kind == "hinge";
            // Radians on the wire, degrees at the boundary -- but only for a
            // pin. A slide and a link are in metres and converting those would
            // be a very quiet way to make a portcullis 57 times too tall.
            const double scale = turning ? kDegrees : 1.0;
            out[i].id = joint.id;
            out[i].kind = joint.kind == "slider"   ? BANJO_JOINT_SLIDER
                          : joint.kind == "link"   ? BANJO_JOINT_LINK
                          : joint.kind == "pulley" ? BANJO_JOINT_PULLEY
                          : joint.kind == "fixing" ? BANJO_JOINT_FIXING
                          : joint.kind == "elastic" ? BANJO_JOINT_ELASTIC
                                                    : BANJO_JOINT_HINGE;
            out[i].a = joint.a.c_str();
            out[i].b = joint.b.c_str();
            out[i].at = joint.at * scale;
            out[i].lower = joint.lower * scale;
            out[i].upper = joint.upper * scale;
            out[i].friction = joint.friction;
            writeVec(joint.point_world_m, out[i].at_m);
            writeVec(joint.axis_world, out[i].axis);
            out[i].attached = joint.attached ? 1 : 0;
            out[i].tension_n = joint.tension_n;
            out[i].breaks_at_n = joint.breaks_at_n;
            out[i].ratio = joint.ratio;
            writeVec(joint.over_a_m, out[i].over_a_m);
            writeVec(joint.over_b_m, out[i].over_b_m);
            out[i].tension_now_n = joint.tension_n_now;
            out[i].shear_now_n = joint.shear_n_now;
            out[i].holds_tension_n = joint.holds_tension_n;
            out[i].holds_shear_n = joint.holds_shear_n;
            out[i].rest_m = joint.rest_m;
            out[i].stiffness_n_m = joint.stiffness_n_m;
            out[i].damping_n_s_m = joint.damping_n_s_m;
            out[i].force_n = joint.force_n;
            out[i].stored_j = joint.stored_j;
        }
        return count;
    });
}

int banjo_joint_friction(banjo_world *world, unsigned joint, double friction) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    if (!(friction >= 0.0)) {
        setError("joint friction is zero or more: newton metres for a pin, newtons "
                 "for a slide");
        return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        world->world->setJointFriction(joint, friction);
        return BANJO_OK;
    });
}

int banjo_unhinge(banjo_world *world, unsigned joint) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->unhinge(joint); return BANJO_OK; });
}

int banjo_make_blade(banjo_world *world, const char *body, const double heel_m[3],
                     const double tip_m[3], const double facing[3], double thickness_m,
                     double edge_radius_m, double bevel_deg, const double grip_m[3]) {
    if (!world || !body || !heel_m || !tip_m || !facing || !grip_m) {
        setError("no world, no body, or no edge"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const unsigned id = world->world->blade(body, readVec(heel_m), readVec(tip_m),
                                                readVec(facing), thickness_m, edge_radius_m,
                                                bevel_deg, readVec(grip_m));
        if (id == 0) {
            setError(std::string("\"") + body + "\" cannot take that edge: " +
                     world->world->bladeRefusal());
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(id);
    });
}

int banjo_blade_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->blades = world->world->blades();
        return static_cast<int>(mutable_world->blades.size());
    });
}

int banjo_blades(const banjo_world *world, banjo_blade *out, int max) {
    if (!world || (!out && max > 0) || max < 0) {
        setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->blades = world->world->blades();
        const int count = std::min<int>(max, static_cast<int>(mutable_world->blades.size()));
        for (int i = 0; i < count; ++i) {
            const LiveBlade &blade = mutable_world->blades[static_cast<std::size_t>(i)];
            banjo_blade &said = out[i];
            said.id = blade.id;
            said.body = blade.body.c_str();
            said.material = blade.material.c_str();
            writeVec(blade.heel_m, said.heel_m);
            writeVec(blade.tip_m, said.tip_m);
            writeVec(blade.facing, said.facing);
            writeVec(blade.flat, said.flat);
            writeVec(blade.grip_m, said.grip_m);
            said.thickness_m = blade.thickness_m;
            said.edge_radius_m = blade.edge_radius_m;
            said.bevel_deg = blade.bevel_deg;
            said.cut_area_m2 = blade.cut_area_m2;
            said.cut_work_j = blade.cut_work_j;
            said.cutting = blade.cutting.c_str();
            said.attached = blade.attached ? 1 : 0;
        }
        return count;
    });
}

int banjo_cut_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->cut_list = world->world->cuts();
        return static_cast<int>(mutable_world->cut_list.size());
    });
}

int banjo_cuts(const banjo_world *world, banjo_cut *out, int max) {
    if (!world || (!out && max > 0) || max < 0) {
        setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->cut_list = world->world->cuts();
        const int count = std::min<int>(max, static_cast<int>(mutable_world->cut_list.size()));
        for (int i = 0; i < count; ++i) {
            const LiveCut &cut = mutable_world->cut_list[static_cast<std::size_t>(i)];
            banjo_cut &said = out[i];
            said.blade = cut.blade.c_str();
            said.target = cut.target.c_str();
            said.kind = cut.kind.c_str();
            said.at_s = cut.at_s;
            said.speed_m_s = cut.speed_m_s;
            said.into_m_s = cut.into_m_s;
            said.along_m_s = cut.along_m_s;
            said.across_m_s = cut.across_m_s;
            said.resistance_j_m2 = cut.resistance_j_m2;
            said.area_m2 = cut.area_m2;
            said.work_j = cut.work_j;
            said.bonds = static_cast<int>(cut.bonds);
            said.links = static_cast<int>(cut.links);
            said.separated = cut.separated ? 1 : 0;
            said.pieces = static_cast<int>(cut.pieces);
            said.open = cut.open ? 1 : 0;
        }
        return count;
    });
}

int banjo_forget_cuts(banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->forgetCuts(); return BANJO_OK; });
}

int banjo_wield(banjo_world *world, const char *name, const double grip_m[3]) {
    if (!world || !name || !grip_m) { setError("no world, no name, or no grip"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        if (world->world->wield(name, readVec(grip_m))) return BANJO_OK;
        setError(std::string("\"") + name + "\" cannot be taken hold of: it is not in the "
                 "scene, or it is anchored scenery");
        return BANJO_BAD_ARGUMENT;
    });
}

int banjo_aim_held(banjo_world *world, const double orientation_wxyz[4]) {
    if (!world || !orientation_wxyz) { setError("no world or no orientation"); return BANJO_BAD_ARGUMENT; }
    const double size = orientation_wxyz[0] * orientation_wxyz[0] +
                        orientation_wxyz[1] * orientation_wxyz[1] +
                        orientation_wxyz[2] * orientation_wxyz[2] +
                        orientation_wxyz[3] * orientation_wxyz[3];
    if (!(size > 1e-12) || !std::isfinite(size)) {
        setError("an orientation is a quaternion with some length to it"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        world->world->aimHeld(banjo::Quat{orientation_wxyz[0], orientation_wxyz[1],
                                          orientation_wxyz[2], orientation_wxyz[3]});
        return BANJO_OK;
    });
}

int banjo_hand_strength(banjo_world *world, double newtons) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    if (!(newtons >= 0.0) || !std::isfinite(newtons)) {
        setError("hand strength is newtons, zero or more"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] { world->world->setHandStrength(newtons); return BANJO_OK; });
}

int banjo_hand_torque(banjo_world *world, double newton_metres) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    if (!(newton_metres >= 0.0) || !std::isfinite(newton_metres)) {
        setError("hand torque is newton metres, zero or more"); return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] { world->world->setHandTorque(newton_metres); return BANJO_OK; });
}

int banjo_pick_ray(const banjo_world *world, const double from_m[3],
                   const double direction[3], double max_m, banjo_pick *out) {
    if (!world || !from_m || !direction || !out) { setError("no world, no ray, or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        const LivePick found = world->world->pick(readVec(from_m), readVec(direction),
                                                  max_m > 0.0 ? max_m : 1000.0);
        auto *mutable_world = const_cast<banjo_world *>(world);
        mutable_world->picked = found.name;
        out->hit = found.hit ? 1 : 0;
        out->name = mutable_world->picked.c_str();
        out->distance_m = found.distance_m;
        writeVec(found.point_world_m, out->point_m);
        return BANJO_OK;
    });
}

int banjo_declare(banjo_world *world, const char *json) {
    if (!world || !json) { setError("no world or no declaration"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->declareThermo(json); return static_cast<int>(BANJO_OK); });
}

int banjo_heat(banjo_world *world, const char *target, double power_w, double seconds) {
    if (!world || !target) { setError("no world or nothing to heat"); return BANJO_BAD_ARGUMENT; }
    if (!(power_w >= 0.0) || !(seconds > 0.0)) {
        setError("a heater's power is zero or more watts, for a positive number of seconds");
        return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] { return static_cast<int>(world->world->heat(target, power_w, seconds)); });
}

int banjo_vent(banjo_world *world, const char *region, int open) {
    if (!world || !region) { setError("no world or no region"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { world->world->setVent(region, open != 0); return static_cast<int>(BANJO_OK); });
}

int banjo_body_heat_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        const banjo::thermo::ThermoWorld *network = world->world->thermo();
        mutable_world->heats = network ? network->bodies() : std::vector<banjo::thermo::BodyHeat>{};
        return static_cast<int>(mutable_world->heats.size());
    });
}

int banjo_bodies_heat(const banjo_world *world, banjo_body_heat *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        const banjo::thermo::ThermoWorld *network = world->world->thermo();
        mutable_world->heats = network ? network->bodies() : std::vector<banjo::thermo::BodyHeat>{};
        const int count = std::min<int>(max, static_cast<int>(mutable_world->heats.size()));
        for (int i = 0; i < count; ++i) {
            const banjo::thermo::BodyHeat &b = mutable_world->heats[static_cast<std::size_t>(i)];
            banjo_body_heat &o = out[i];
            o.name = b.body.c_str();
            o.material = b.material.c_str();
            o.temperature_k = b.temperature_k;
            o.core_temperature_k = b.core_temperature_k;
            o.mass_kg = b.mass_kg;
            o.fuel_kg = b.fuel_kg;
            o.heat_release_w = b.heat_release_w;
            o.fuel_use_kg_s = b.fuel_use_kg_s;
            o.remaining_s = b.remaining_s;
            o.heater_w = b.heater_w;
            o.gained_w = b.gained_w;
            o.lost_w = b.lost_w;
            o.reacting = b.reacting ? 1 : 0;
            o.declared = b.declared ? 1 : 0;
        }
        return count;
    });
}

int banjo_gas_region_count(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        const banjo::thermo::ThermoWorld *network = world->world->thermo();
        mutable_world->gases = network ? network->regions() : std::vector<banjo::thermo::RegionState>{};
        return static_cast<int>(mutable_world->gases.size());
    });
}

int banjo_gas_regions(const banjo_world *world, banjo_gas_region *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        auto *mutable_world = const_cast<banjo_world *>(world);
        const banjo::thermo::ThermoWorld *network = world->world->thermo();
        mutable_world->gases = network ? network->regions() : std::vector<banjo::thermo::RegionState>{};
        const int count = std::min<int>(max, static_cast<int>(mutable_world->gases.size()));
        for (int i = 0; i < count; ++i) {
            const banjo::thermo::RegionState &r = mutable_world->gases[static_cast<std::size_t>(i)];
            banjo_gas_region &o = out[i];
            o.name = r.name.c_str();
            o.piston = r.piston.c_str();
            o.temperature_k = r.temperature_k;
            o.pressure_pa = r.pressure_pa;
            o.volume_m3 = r.volume_m3;
            o.mass_kg = r.mass_kg;
            o.moles = r.moles;
            writeVec(r.base_m, o.base_m);
            writeVec(r.axis, o.axis);
            o.area_m2 = r.area_m2;
            o.height_m = r.height_m;
            o.stroke_m = r.stroke_m;
            o.force_n = r.force_n;
            o.work_to_bodies_j = r.work_to_bodies_j;
            o.work_to_atmosphere_j = r.work_to_atmosphere_j;
            o.heater_w = r.heater_w;
            o.wall_loss_w = r.wall_loss_w;
            o.vent_open = r.vent_open ? 1 : 0;
        }
        return count;
    });
}

int banjo_energy_ledger(const banjo_world *world, banjo_energy *out) {
    if (!world || !out) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        const banjo::thermo::ThermoWorld *network = world->world->thermo();
        const banjo::thermo::Ledger l = network ? network->ledger() : banjo::thermo::Ledger{};
        *out = banjo_energy{};
        out->chemical_j = l.reference_j;
        out->thermal_j = l.sensible_j;
        out->stored_j = l.storedJ();
        out->mass_kg = l.mass_kg;
        out->initial_j = l.initial_j;
        out->heater_in_j = l.heater_in_j;
        out->heat_to_surroundings_j = l.heat_to_surroundings_j;
        out->matter_in_j = l.matter_in_j;
        out->matter_in_kg = l.matter_in_kg;
        out->matter_out_j = l.matter_out_j;
        out->matter_out_kg = l.matter_out_kg;
        out->joined_j = l.joined_j;
        out->left_j = l.left_j;
        out->work_to_bodies_j = l.work_to_bodies_j;
        out->work_to_atmosphere_j = l.work_to_atmosphere_j;
        out->numerical_j = l.numerical_j;
        out->residual_j = l.residualJ();
        out->mass_residual_kg = l.massResidualKg();
        out->mechanical_j = world->world->mechanicalEnergyJ();
        return static_cast<int>(BANJO_OK);
    });
}

const char *banjo_thermo_report(const banjo_world *world, int with_model) {
    if (!world) return "";
    auto *mutable_world = const_cast<banjo_world *>(world);
    try {
        mutable_world->report = world->world->thermoReport(with_model != 0);
    } catch (...) {
        mutable_world->report.clear();
    }
    return mutable_world->report.c_str();
}

const char *banjo_thermo_model(void) {
    thread_local std::string model;
    try {
        const banjo::thermo::ThermoWorld nothing;
        model = banjo::thermo::reportJson(nothing, true);
    } catch (...) {
        model.clear();
    }
    return model.c_str();
}

// ---- terrain and water ---------------------------------------------------------

namespace {
constexpr const char *kNoTerrain = "this world has no terrain: its scene declares none";

// Null for a world without ground. It does not throw: everything in this
// block has C linkage, which the compiler takes as a promise not to, so the
// refusal is thrown by the caller's lambda inside guarded(), where it can be.
const banjo::terrain::Environment *environmentOf(const banjo_world *world) {
    return world->world->environment();
}

void writeDug(const banjo::terrain::EditEffect &effect, banjo_dug *out) {
    if (out == nullptr) return;
    *out = banjo_dug{};
    out->sand_m3 = effect.edit.moved.sand_m3;
    out->soil_m3 = effect.edit.moved.soil_m3;
    out->mass_kg = effect.edit.mass_kg;
    out->columns = static_cast<int>(effect.edit.cells.size());
    out->chunks_rebuilt = static_cast<int>(effect.chunks_rebuilt);
    out->rebuild_ms = effect.rebuild_ms;
    out->bodies_woken = static_cast<int>(effect.bodies_woken);
}
} // namespace

int banjo_terrain_info(const banjo_world *world, banjo_terrain *out) {
    if (!world || !out) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        const banjo::terrain::Environment *environment = environmentOf(world);
        if (environment == nullptr) throw std::invalid_argument(kNoTerrain);
        const banjo::terrain::TerrainField &ground = environment->terrain();
        const banjo::terrain::Grid &g = ground.grid();
        const banjo::terrain::Volumes v = ground.volumes();
        const banjo::terrain::Ledger &l = ground.ledger();
        const banjo::terrain::Volumes r = ground.residual();
        *out = banjo_terrain{};
        out->nx = g.nx;
        out->nz = g.nz;
        out->cell_m = g.dx;
        out->origin_m[0] = g.x0;
        out->origin_m[1] = g.z0;
        out->chunks_x = ground.chunksX();
        out->chunks_z = ground.chunksZ();
        out->lowest_m = ground.lowest();
        out->highest_m = ground.highest();
        out->floor_m = ground.floor();
        out->rock_m3 = v.rock_m3;
        out->soil_m3 = v.soil_m3;
        out->sand_m3 = v.sand_m3;
        out->dug_m3 = l.dug.total();
        out->cut_m3 = l.cut.total();
        out->deposited_m3 = l.deposited.total();
        out->slumped_m3 = l.slumped_m3;
        out->residual_m3 = r.total();
        out->unsettled_columns = static_cast<int>(ground.unsettled());
        out->chunks_rebuilt = static_cast<int>(environment->stats().chunks_rebuilt);
        out->rebuild_ms_worst = environment->stats().rebuild_ms_worst;
        return static_cast<int>(BANJO_OK);
    });
}

int banjo_water_info(const banjo_world *world, banjo_water *out) {
    if (!world || !out) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        const banjo::terrain::Environment *environment = environmentOf(world);
        if (environment == nullptr) throw std::invalid_argument(kNoTerrain);
        const banjo::water::ShallowWater &w = *environment->water();
        const banjo::water::Stats &s = w.stats();
        const banjo::water::Ledger &l = w.ledger();
        const banjo::terrain::EnvironmentStats &e = environment->stats();
        *out = banjo_water{};
        out->time_s = s.time_s;
        out->volume_m3 = w.volume();
        out->wet_area_m2 = w.wetArea();
        out->cells = static_cast<int>(w.grid().cells());
        out->wet_cells = static_cast<int>(w.wetCells());
        out->active_cells = static_cast<int>(s.active_cells);
        out->inflow_m3_s = w.inflowRate();
        out->outflow_m3_s = w.outflowRate();
        out->initial_m3 = l.initial_m3;
        out->inflow_m3 = l.inflow_m3;
        out->outflow_m3 = l.outflow_m3;
        out->numerical_m3 = l.numerical_m3;
        out->residual_m3 = w.residual();
        out->substeps = static_cast<double>(s.substeps);
        out->last_substep_s = s.last_substep_s;
        out->wave_speed_m_s = s.max_speed_m_s;
        out->bodies_in_water = static_cast<int>(e.bodies_in_water);
        out->water_ms_worst = e.water_ms_worst;
        out->coupling_ms_worst = e.coupling_ms_worst;
        out->step_ms_worst = e.step_ms_worst;
        return static_cast<int>(BANJO_OK);
    });
}

int banjo_dig(banjo_world *world, const double from_m[2], const double to_m[2], double width_m,
              double depth_m, banjo_dug *out) {
    if (!world || !from_m) { setError("no world or nowhere to dig"); return BANJO_BAD_ARGUMENT; }
    if (!(width_m > 0.0) || !(depth_m > 0.0)) {
        setError("a dig needs a positive width and a positive depth, in metres");
        return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        const double *to = to_m ? to_m : from_m;
        writeDug(world->world->dig(from_m[0], from_m[1], to[0], to[1], width_m, depth_m), out);
        return static_cast<int>(BANJO_OK);
    });
}

int banjo_deposit(banjo_world *world, const double at_m[2], double radius_m, double sand_m3,
                  double soil_m3, banjo_dug *out) {
    if (!world || !at_m) { setError("no world or nowhere to heap"); return BANJO_BAD_ARGUMENT; }
    if (!(radius_m > 0.0) || !(sand_m3 >= 0.0) || !(soil_m3 >= 0.0) || !(sand_m3 + soil_m3 > 0.0)) {
        setError("a heap needs a positive radius and some sand or soil, in cubic metres");
        return BANJO_BAD_ARGUMENT;
    }
    return guarded([&] {
        writeDug(world->world->deposit(at_m[0], at_m[1], radius_m, sand_m3, soil_m3), out);
        return static_cast<int>(BANJO_OK);
    });
}

int banjo_cut_block(banjo_world *world, const double at_m[2], int cells_x, int cells_z, double height_m,
                    banjo_block *out) {
    if (!world || !at_m || !out) { setError("no world, no place, or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        std::string why;
        const auto block = world->world->cutBlock(at_m[0], at_m[1], cells_x, cells_z, height_m, &why);
        if (!block) {
            setError(why.empty() ? std::string("that block cannot be cut") : why);
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        writeVec(block->center_m, out->center_m);
        writeVec(block->size_m, out->size_m);
        out->volume_m3 = block->volume_m3;
        out->mass_kg = block->mass_kg;
        return static_cast<int>(BANJO_OK);
    });
}

int banjo_set_discharge(banjo_world *world, const char *river, double discharge_m3_s) {
    if (!world || !river) { setError("no world or no river"); return BANJO_BAD_ARGUMENT; }
    if (!(discharge_m3_s >= 0.0)) { setError("a discharge is zero or more cubic metres a second"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        if (!world->world->setDischarge(river, discharge_m3_s)) {
            setError(std::string("there is no river called \"") + river + "\"");
            return static_cast<int>(BANJO_BAD_ARGUMENT);
        }
        return static_cast<int>(BANJO_OK);
    });
}

int banjo_terrain_heights(const banjo_world *world, float *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        const banjo::terrain::Environment *environment = environmentOf(world);
        if (environment == nullptr) throw std::invalid_argument(kNoTerrain);
        const std::vector<float> heights = environment->heights();
        const int count = std::min<int>(max, static_cast<int>(heights.size()));
        std::copy_n(heights.begin(), count, out);
        return count;
    });
}

int banjo_water_surface(const banjo_world *world, double *out, int max) {
    if (!world || (!out && max > 0) || max < 0) { setError("no world or nowhere to write"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] {
        const banjo::terrain::Environment *environment = environmentOf(world);
        if (environment == nullptr) throw std::invalid_argument(kNoTerrain);
        const banjo::water::ShallowWater &w = *environment->water();
        const int count = std::min<int>(max, static_cast<int>(w.grid().cells()));
        for (int c = 0; c < count; ++c)
            out[c] = w.depth(static_cast<std::size_t>(c)) > 0.003 ? w.surface(static_cast<std::size_t>(c))
                                                                 : std::nan("");
        return count;
    });
}

const char *banjo_environment_report(const banjo_world *world, int full) {
    if (!world) return "";
    auto *mutable_world = const_cast<banjo_world *>(world);
    try {
        mutable_world->environment_report = world->world->environmentReport(full != 0);
    } catch (...) {
        mutable_world->environment_report.clear();
    }
    return mutable_world->environment_report.c_str();
}

const char *banjo_environment_state(const banjo_world *world) {
    if (!world) return "";
    auto *mutable_world = const_cast<banjo_world *>(world);
    try {
        mutable_world->environment_state = world->world->environmentState();
    } catch (...) {
        mutable_world->environment_state.clear();
    }
    return mutable_world->environment_state.c_str();
}

const char *banjo_survey(const banjo_world *world, double x_m, double z_m) {
    if (!world) return "";
    auto *mutable_world = const_cast<banjo_world *>(world);
    try {
        mutable_world->survey = world->world->survey(x_m, z_m);
    } catch (...) {
        mutable_world->survey.clear();
    }
    return mutable_world->survey.c_str();
}

int banjo_awake_bodies(const banjo_world *world) {
    if (!world) { setError("no world"); return BANJO_BAD_ARGUMENT; }
    return guarded([&] { return static_cast<int>(world->world->awakeBodies()); });
}

} // extern "C"
