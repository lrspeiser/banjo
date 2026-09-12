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

#include <algorithm>
#include <deque>
#include <exception>
#include <string>
#include <vector>

using banjo::Vec3;
using banjo::fastlattice::BackendKind;
using banjo::fastlattice::LiveBodyPose;
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

} // extern "C"
