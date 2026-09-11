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
using banjo::fastlattice::LiveDelay;
using banjo::fastlattice::LiveImpact;
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
