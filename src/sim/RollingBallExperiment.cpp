#include "sim/RollingBallExperiment.hpp"

#include "fracture/ConnectedComponents.hpp"
#include "material/MaterialCompiler.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <utility>

namespace banjo {
namespace {

void validateSettings(const ExperimentSettings &settings) {
    if (settings.radius_m <= 0.0 || settings.voxel_size_m <= 0.0 ||
        settings.neighbor_horizon_cells == 0U ||
        settings.occupancy_samples_per_axis == 0U ||
        settings.rigid_step_s <= 0.0 || settings.material_step_s <= 0.0 ||
        settings.maximum_material_steps == 0U ||
        settings.maximum_rigid_fragments == 0U ||
        settings.maximum_collision_points < 8U ||
        settings.iron_speed_m_s <= 0.0 ||
        settings.target_initial_speed_m_s < 0.0 ||
        settings.sphere_inertia_factor <= 0.0 ||
        !std::isfinite(settings.striker_spin_ratio) ||
        settings.impact_internal_energy_fraction != 0.0 ||
        !std::isfinite(settings.surface_slope_degrees) ||
        std::abs(settings.surface_slope_degrees) >= 89.0) {
        throw std::invalid_argument("rolling-ball experiment settings are invalid");
    }
    if (settings.minimum_material_steps > settings.maximum_material_steps) {
        throw std::invalid_argument(
            "minimum material steps exceed maximum material steps");
    }
}

[[nodiscard]] bool impactLess(
    const ImpactEvent &left,
    const ImpactEvent &right) {
    if (left.fixed_tick != right.fixed_tick) {
        return left.fixed_tick < right.fixed_tick;
    }
    if (left.body_a != right.body_a) {
        return left.body_a < right.body_a;
    }
    if (left.body_b != right.body_b) {
        return left.body_b < right.body_b;
    }
    if (left.contact_point_world_m.x != right.contact_point_world_m.x) {
        return left.contact_point_world_m.x < right.contact_point_world_m.x;
    }
    if (left.contact_point_world_m.y != right.contact_point_world_m.y) {
        return left.contact_point_world_m.y < right.contact_point_world_m.y;
    }
    return left.contact_point_world_m.z < right.contact_point_world_m.z;
}

[[nodiscard]] double sphereMass(
    double radius_m,
    const MaterialDefinition &material) {
    return (4.0 / 3.0) * std::numbers::pi * radius_m * radius_m * radius_m *
           material.density_kg_m3;
}

} // namespace

std::string_view experimentPhaseName(ExperimentPhase phase) {
    switch (phase) {
    case ExperimentPhase::Rigid:
        return "rigid bodies";
    case ExperimentPhase::Fracturing:
        return "active voxel fracture";
    case ExperimentPhase::RigidFragments:
        return "rigid fragments";
    }
    return "unknown";
}

RollingBallExperiment::RollingBallExperiment(ExperimentSettings settings) {
    reset(std::move(settings));
}

RollingBallExperiment::~RollingBallExperiment() = default;
RollingBallExperiment::RollingBallExperiment(
    RollingBallExperiment &&) noexcept = default;
RollingBallExperiment &RollingBallExperiment::operator=(
    RollingBallExperiment &&) noexcept = default;

void RollingBallExperiment::reset(ExperimentSettings settings) {
    validateSettings(settings);

    // Jolt uses process-global type registration in this bootstrap integration,
    // so the previous world must be destroyed before constructing its replacement.
    rigid_world_.reset();
    active_target_.reset();
    latest_components_.clear();
    fragment_build_ = {};
    debris_particles_.clear();
    activating_impact_.reset();
    compiled_target_.reset();
    target_lattice_.reset();

    settings_ = std::move(settings);
    support_plane_ = makeSupportPlaneFromSlopeDegrees(
        settings_.surface_slope_degrees);
    striker_material_ = makeReferenceMaterial(
        settings_.striker_material, settings_.material_seed);
    target_material_ = makeReferenceMaterial(
        settings_.target_material, settings_.material_seed);
    surface_material_ = makeReferenceMaterial(
        settings_.surface_material, settings_.material_seed);

    if (target_material_.model == MaterialModel::BrittleBond) {
        compiled_target_ = compileBrittleMaterial(
            target_material_,
            settings_.voxel_size_m,
            settings_.neighbor_horizon_cells);
        target_lattice_ = generateSphereLattice(
            {
                settings_.radius_m,
                settings_.voxel_size_m,
                settings_.neighbor_horizon_cells,
                settings_.occupancy_samples_per_axis,
            },
            *compiled_target_);
    }

    target_surface_contact_ = combineContactMaterials(
        compileContactMaterial(target_material_),
        compileContactMaterial(surface_material_));

    solver_ = BrittleBondSolver({
        .substeps = 1,
        .constraint_iterations = 8,
        .use_support_plane = true,
        .support_plane = support_plane_,
        .surface_dynamic_friction = target_surface_contact_.dynamic_friction,
        .surface_restitution = target_surface_contact_.restitution,
        .surface_static_friction = target_surface_contact_.static_friction,
        .support_half_tangent_m = 12.0,
        .support_half_bitangent_m = 6.0,
        .impact_internal_energy_fraction = 0.0,
        .maximum_internal_energy_j = settings_.maximum_internal_energy_j,
    });

    stats_ = {};
    stats_.phase = ExperimentPhase::Rigid;
    stats_.represented_target_mass_kg = target_lattice_
                                            ? target_lattice_->total_mass_kg
                                            : sphereMass(
                                                  settings_.radius_m,
                                                  target_material_);
    // Kept as a compatibility alias for the original glass-only headless test.
    stats_.represented_glass_mass_kg = stats_.represented_target_mass_kg;
    stats_.active_nodes = target_lattice_ ? target_lattice_->nodes.size() : 0U;
    stats_.total_bonds = target_lattice_ ? target_lattice_->bonds.size() : 0U;
    stats_.connected_components = 1U;
    updateScenarioProjection();

    last_broken_bonds_ = 0U;
    stable_material_steps_ = 0U;
    material_time_accumulator_s_ = 0.0;
    stable_material_time_s_ = 0.0;
    initializeWorld();
    updateMotionDiagnostics();
}

void RollingBallExperiment::updateScenarioProjection() {
    BallScenarioInput input;
    input.striker_material = striker_material_;
    input.target_material = target_material_;
    input.surface_material = surface_material_;
    input.striker_radius_m = settings_.radius_m;
    input.target_radius_m = settings_.radius_m;
    input.striker_speed_m_s = settings_.iron_speed_m_s;
    input.target_speed_m_s = settings_.target_initial_speed_m_s;
    input.slope_angle_degrees = settings_.surface_slope_degrees;
    input.gravity_world_m_s2 = settings_.gravity_m_s2;
    input.sphere_inertia_factor = settings_.sphere_inertia_factor;
    input.voxel_size_m = settings_.voxel_size_m;
    input.estimated_active_nodes =
        target_lattice_ ? target_lattice_->nodes.size() : 0U;
    input.estimated_bonds =
        target_lattice_ ? target_lattice_->bonds.size() : 0U;
    input.estimated_material_steps = settings_.maximum_material_steps;
    input.realtime_constraint_budget = settings_.realtime_constraint_budget;

    const ScenarioKey key = makeScenarioKey(
        settings_.striker_material,
        settings_.target_material,
        settings_.surface_material,
        settings_.radius_m,
        settings_.iron_speed_m_s,
        settings_.surface_slope_degrees,
        settings_.gravity_m_s2,
        settings_.voxel_size_m,
        settings_.material_seed);
    // Spin/sliding isn't an input to the current analytical rolling projection.
    // Never present a cache hit as a prediction of a different initial spin state.
    const ProjectionLookup lookup = settings_.striker_spin_ratio == 1.0
        ? projection_cache_.lookupOrProject(key, input)
        : ProjectionLookup{projectBallScenario(input), false};
    scenario_projection_ = lookup.projection;

    stats_.projection_cache_hit = lookup.cache_hit;
    stats_.predicted_peak_force_n = scenario_projection_.impact.peak_force_n;
    stats_.predicted_peak_pressure_pa =
        scenario_projection_.impact.peak_contact_pressure_pa;
    stats_.predicted_striker_mass_kg =
        scenario_projection_.impact.striker_mass_kg;
    stats_.predicted_target_mass_kg =
        scenario_projection_.impact.target_mass_kg;
    stats_.predicted_slope_acceleration_m_s2 =
        scenario_projection_.incline.acceleration_along_slope_m_s2;
    stats_.predicted_failure =
        scenario_projection_.impact.predicted_failure;
    stats_.predicted_incline_regime = scenario_projection_.incline.regime;
    stats_.runtime_strategy = scenario_projection_.runtime_strategy;
}

std::size_t RollingBallExperiment::loadProjectionCache(
    const std::filesystem::path &path) {
    const std::size_t loaded = projection_cache_.loadCsv(path);
    updateScenarioProjection();
    return loaded;
}

void RollingBallExperiment::saveProjectionCache(
    const std::filesystem::path &path) const {
    projection_cache_.saveCsv(path);
}

void RollingBallExperiment::initializeWorld() {
    rigid_world_ = std::make_unique<JoltWorld>();
    rigid_world_->setGravity(settings_.gravity_m_s2);
    rigid_world_->addSupportSurface({
        .frame = support_plane_,
        .material = surface_material_,
        .half_length_tangent_m = 12.0,
        .half_length_bitangent_m = 6.0,
        .thickness_m = 0.5,
    });

    const Vec3 striker_velocity =
        settings_.iron_speed_m_s * support_plane_.tangent_world;
    const Vec3 target_velocity =
        settings_.target_initial_speed_m_s * support_plane_.tangent_world;
    rigid_world_->addBall({
        .body_id = kStrikerBallId,
        .radius_m = settings_.radius_m,
        .material = striker_material_,
        .position_world_m = pointInPlaneFrame(
            support_plane_,
            -1.50,
            0.0,
            settings_.radius_m + 0.001),
        .linear_velocity_m_s = striker_velocity,
        .angular_velocity_rad_s =
            settings_.striker_spin_ratio *
            cross(support_plane_.normal_world, striker_velocity) /
            settings_.radius_m,
        .sphere_inertia_factor = settings_.sphere_inertia_factor,
    });
    rigid_world_->addBall({
        .body_id = kTargetBallId,
        .radius_m = settings_.radius_m,
        .material = target_material_,
        .position_world_m = pointInPlaneFrame(
            support_plane_,
            0.0,
            0.0,
            settings_.radius_m + 0.001),
        .linear_velocity_m_s = target_velocity,
        .angular_velocity_rad_s =
            cross(support_plane_.normal_world, target_velocity) /
            settings_.radius_m,
        .mass_override_kg = target_lattice_
                                ? target_lattice_->total_mass_kg
                                : 0.0,
        .sphere_inertia_factor = settings_.sphere_inertia_factor,
        .defer_brittle_contacts_to_material = target_lattice_.has_value(),
    });
}

void RollingBallExperiment::stepFixed() {
    if (!rigid_world_) throw std::logic_error("rolling-ball experiment has no rigid world");
    double remaining = settings_.rigid_step_s;
    unsigned microsteps = 0;
    while (remaining > 1.0e-12) {
        double dt = remaining;
        if (target_lattice_ && stats_.phase != ExperimentPhase::RigidFragments) {
            const auto striker = rigid_world_->snapshot(kStrikerBallId);
            const double speed = std::max({length(striker.linear_velocity_m_s),
                stats_.maximum_node_speed_m_s, 1.0});
            dt = std::min({remaining, 0.5 * settings_.material_step_s,
                0.4 * settings_.voxel_size_m / speed});
        }
        // Fail explicitly on an unsupported step/speed budget; never drop time.
        if (++microsteps > 256U) throw std::runtime_error("material contact substep budget exceeded");
        switch (stats_.phase) {
        case ExperimentPhase::Rigid: stepRigidPhase(dt); break;
        case ExperimentPhase::Fracturing: stepFracturingPhase(dt); break;
        case ExperimentPhase::RigidFragments: stepRigidFragmentsPhase(dt); break;
        }
        remaining -= dt;
    }
    updateMotionDiagnostics();
}

void RollingBallExperiment::updateMotionDiagnostics() {
    const auto measure = [&](MatterBodyId id) {
        const auto body = rigidSnapshot(id);
        if (!body) return RollingKinematics{};
        return measureRollingKinematics(*body, settings_.radius_m, support_plane_,
            insideSupportFootprint(support_plane_, body->center_of_mass_world_m, 12.0, 6.0));
    };
    stats_.striker_motion = measure(kStrikerBallId);
    stats_.target_motion = measure(kTargetBallId);
}

void RollingBallExperiment::stepRigidPhase(double dt_s) {
    rigid_world_->step(dt_s);
    ++stats_.rigid_steps;

    std::vector<ImpactEvent> impacts = rigid_world_->drainImpacts();
    std::sort(impacts.begin(), impacts.end(), impactLess);
    for (const ImpactEvent &impact : impacts) {
        if (!impact.involves(kTargetBallId)) {
            continue;
        }

        const ActivationDecision decision = activation_policy_.evaluate(
            impact,
            {
                .body_id = kTargetBallId,
                .radius_m = settings_.radius_m,
                .material = target_material_,
                .accumulated_damage = 0.0,
                .reduced_radius_m = impact.involves(kStrikerBallId)
                    ? 0.5 * settings_.radius_m : settings_.radius_m,
            });
        stats_.impact_speed_m_s = impact.closing_speed_m_s;
        stats_.impact_tangential_speed_m_s =
            impact.tangential_speed_m_s;
        stats_.impact_energy_j = impact.available_normal_energy_j;
        stats_.activation_threshold_j = decision.threshold_energy_j;
        stats_.normalized_impact_energy = decision.normalized_energy;
        stats_.actual_contact_friction = impact.applied_friction;
        stats_.actual_contact_restitution = impact.combined_restitution;
        if (!impact.response_deferred_to_material) {
            continue;
        }
        if (!target_lattice_ || !compiled_target_) {
            throw std::logic_error(
                "activatable target does not have a compiled material lattice");
        }

        stats_.activation_response_deferred = true;
        activating_impact_ = impact;
        const RigidSnapshot post_contact_target =
            rigid_world_->snapshot(kTargetBallId);
        rigid_world_->removeAndDestroy(kTargetBallId);
        active_target_ = solver_.activate(
            kTargetBallId,
            *target_lattice_,
            *compiled_target_,
            post_contact_target,
            impact);
        stats_.phase = ExperimentPhase::Fracturing;
        stats_.broken_bonds = 0U;
        stats_.connected_components = 1U;
        return;
    }
}

void RollingBallExperiment::stepFracturingPhase(double dt_s) {
    if (!active_target_) throw std::logic_error("fracturing phase has no active target material");
    // Jolt and the material solver advance the same microstep. Reactions are
    // written back before the next Jolt step, not delayed until fracture ends.
    rigid_world_->step(dt_s);
    ++stats_.rigid_steps;
    (void)rigid_world_->drainImpacts();
    CoupledSphereState striker = rigid_world_->sphereContactState(kStrikerBallId);
    const auto pair = combineContactMaterials(compileContactMaterial(striker_material_),
                                             compileContactMaterial(target_material_));
    const MaterialStepStats material_stats = solver_.step(*active_target_, dt_s,
        settings_.gravity_m_s2, &striker, {
            .static_friction = pair.static_friction,
            .dynamic_friction = pair.dynamic_friction,
            .restitution = pair.restitution,
            .node_contact_radius_m = 0.0, // material nodes are point quadrature samples
        });
    rigid_world_->applySphereContactState(kStrikerBallId, striker);
    ++stats_.material_steps;
    material_time_accumulator_s_ += dt_s;
    stats_.broken_bonds = material_stats.total_broken_bonds;
    stats_.maximum_tensile_stretch = material_stats.maximum_tensile_stretch;
    stats_.active_kinetic_energy_j = material_stats.kinetic_energy_j;
    stats_.active_elastic_energy_j = material_stats.estimated_elastic_energy_j;
    stats_.maximum_node_speed_m_s = material_stats.maximum_speed_m_s;
    stats_.coupled_contact_points += material_stats.rigid_contact.impulse_contacts;
    stats_.coupled_impulse_n_s += length(material_stats.rigid_contact.impulse_to_material_n_s);
    stats_.coupled_contact_dissipation_j += material_stats.rigid_contact.dissipated_kinetic_energy_j;
    stats_.internal_damping_loss_j += material_stats.internal_damping_loss_j;
    stats_.maximum_contact_penetration_m = std::max(stats_.maximum_contact_penetration_m,
        material_stats.rigid_contact.maximum_penetration_m);

    if (material_stats.total_broken_bonds == last_broken_bonds_) {
        stable_material_time_s_ += dt_s;
    } else {
        stable_material_time_s_ = 0.0;
        last_broken_bonds_ = material_stats.total_broken_bonds;
    }
    if (material_stats.broken_bonds_this_step > 0U || stats_.material_steps % 12U == 0U)
        updateComponentCount();
    const bool minimum_elapsed = material_time_accumulator_s_ >=
        settings_.minimum_material_steps * settings_.material_step_s;
    const bool stable = stable_material_time_s_ >=
        settings_.stable_material_steps_before_handoff * settings_.material_step_s;
    const bool timeout = material_time_accumulator_s_ >=
        settings_.maximum_material_steps * settings_.material_step_s;
    if ((minimum_elapsed && stable && stats_.broken_bonds > 0U) || timeout)
        finalizeFragments();
}

void RollingBallExperiment::stepRigidFragmentsPhase(double dt_s) {
    rigid_world_->step(dt_s);
    ++stats_.rigid_steps;
    (void)rigid_world_->drainImpacts();
    integrateDebris(dt_s);
}

void RollingBallExperiment::updateComponentCount() {
    if (!active_target_) {
        return;
    }
    latest_components_ = findConnectedComponents(*active_target_);
    stats_.connected_components = latest_components_.size();
}

void RollingBallExperiment::finalizeFragments() {
    if (!active_target_) {
        throw std::logic_error(
            "cannot finalize fragments without active material");
    }
    updateComponentCount();
    if (latest_components_.empty()) {
        throw std::runtime_error(
            "fractured material produced no connected components");
    }

    const CompiledContactMaterial target_contact =
        compileContactMaterial(target_material_);
    fragment_build_ = buildFragmentRepresentations(
        *active_target_,
        latest_components_,
        {
            .first_body_id = 1000,
            .maximum_rigid_fragments = settings_.maximum_rigid_fragments,
            .minimum_nodes_per_rigid_fragment =
                settings_.minimum_nodes_per_rigid_fragment,
            .maximum_collision_points = settings_.maximum_collision_points,
            .friction = target_contact.dynamic_friction,
            .restitution = target_contact.restitution,
        });
    rigid_world_->addFragments(fragment_build_.rigid_fragments);

    debris_particles_.reserve(fragment_build_.debris_particles.size());
    for (const DebrisParticleDescription &particle :
         fragment_build_.debris_particles) {
        debris_particles_.push_back({
            particle.position_world_m,
            particle.velocity_m_s,
            particle.angular_velocity_rad_s,
            particle.mass_kg,
            particle.radius_m,
        });
    }

    stats_.rigid_fragments = fragment_build_.rigid_fragments.size();
    stats_.debris_particles = debris_particles_.size();
    stats_.fragment_mass_kg = fragment_build_.total_mass_kg;
    stats_.mass_error_kg =
        fragment_build_.total_mass_kg - stats_.represented_target_mass_kg;
    stats_.phase = ExperimentPhase::RigidFragments;
    active_target_.reset();
}

void RollingBallExperiment::integrateDebris(double dt_s) {
    const Vec3 &normal = support_plane_.normal_world;
    const double normal_gravity =
        std::max(0.0, -dot(settings_.gravity_m_s2, normal));

    for (DebrisParticleState &particle : debris_particles_) {
        particle.velocity_m_s += dt_s * settings_.gravity_m_s2;
        particle.position_world_m += dt_s * particle.velocity_m_s;

        const double distance =
            signedDistanceToPlane(support_plane_, particle.position_world_m);
        if (distance < particle.radius_m && insideSupportFootprint(support_plane_,
                particle.position_world_m, 12.0, 6.0)) {
            particle.position_world_m +=
                (particle.radius_m - distance) * normal;

            const double incoming_normal_speed =
                dot(particle.velocity_m_s, normal);
            Vec3 tangent_velocity =
                particle.velocity_m_s - incoming_normal_speed * normal;
            if (incoming_normal_speed < 0.0) {
                const double tangent_speed = length(tangent_velocity);
                if (tangent_speed > 1.0e-12) {
                    const double friction_delta =
                        target_surface_contact_.dynamic_friction *
                        (1.0 + target_surface_contact_.restitution) *
                        (-incoming_normal_speed);
                    tangent_velocity *=
                        std::max(0.0, tangent_speed - friction_delta) /
                        tangent_speed;
                }
                particle.velocity_m_s = tangent_velocity -
                    target_surface_contact_.restitution *
                        incoming_normal_speed * normal;
            }

            const double tangent_speed = length(tangent_velocity);
            if (tangent_speed > 1.0e-12 && normal_gravity > 0.0) {
                const double rolling_deceleration =
                    target_surface_contact_.rolling_resistance *
                    normal_gravity / 1.4;
                const double retained_speed = std::max(
                    0.0,
                    tangent_speed - rolling_deceleration * dt_s);
                const Vec3 normal_velocity =
                    dot(particle.velocity_m_s, normal) * normal;
                particle.velocity_m_s = normal_velocity +
                    (retained_speed / tangent_speed) * tangent_velocity;
            }

            if (length(particle.velocity_m_s) < 0.02) {
                particle.velocity_m_s = {};
            }
        }
    }
}

std::optional<RigidSnapshot> RollingBallExperiment::rigidSnapshot(
    MatterBodyId body_id) const {
    if (!rigid_world_ || !rigid_world_->contains(body_id)) {
        return std::nullopt;
    }
    return rigid_world_->snapshot(body_id);
}

const ActiveMatter *RollingBallExperiment::activeMatter() const {
    return active_target_ ? &*active_target_ : nullptr;
}

const LatticeAsset &RollingBallExperiment::glassLattice() const {
    if (!target_lattice_) {
        throw std::logic_error(
            "selected target material does not use the brittle lattice solver");
    }
    return *target_lattice_;
}

} // namespace banjo
