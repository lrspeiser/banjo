/* Drop an iron ball on a glass pane, in C.
 *
 * This is what building on Banjo looks like from outside the tree: one header,
 * one shared library, no C++. Build it the way any consumer would:
 *
 *     cmake --install build --prefix /somewhere
 *     cc drop.c -I/somewhere/include -L/somewhere/lib -lbanjo -o drop
 *
 * Run with --test and it checks itself, which is how it earns a place in the
 * suite: an example that is never run rots, and this one is also the only
 * proof that the header really is C and really is complete.
 */
#include "banjo/banjo.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *kScene =
    "{\"bodies\":["
    " {\"name\":\"pane\",\"shape\":\"box\",\"material\":\"glass\","
    "  \"dimensions_m\":[0.3,0.04,0.3],\"center_m\":[0,0.02,0]},"
    " {\"name\":\"ball\",\"shape\":\"sphere\",\"material\":\"iron\","
    "  \"dimensions_m\":[0.1,0.1,0.1],\"center_m\":[0,10.09,0]}"
    "]}";

static int failures = 0;

static void check(int ok, const char *what) {
    if (ok) return;
    fprintf(stderr, "FAIL: %s\n", what);
    if (banjo_last_error()[0]) fprintf(stderr, "      engine said: %s\n", banjo_last_error());
    ++failures;
}

/* Where a named body is, or 0 if it is gone -- which is what happens to
 * anything that breaks: it is replaced by pieces with new names. */
static int findY(banjo_world *world, const char *name, double *y) {
    int count = banjo_body_count(world), i, found = 0;
    banjo_body *bodies;
    if (count <= 0) return 0;
    bodies = malloc((size_t)count * sizeof *bodies);
    if (!bodies) return 0;
    count = banjo_bodies(world, bodies, count);
    for (i = 0; i < count; ++i)
        if (strcmp(bodies[i].name, name) == 0) { *y = bodies[i].position_m[1]; found = 1; break; }
    free(bodies);
    return found;
}

static int piecesOf(banjo_world *world, const char *prefix) {
    int count = banjo_body_count(world), i, n = 0;
    banjo_body *bodies;
    size_t len = strlen(prefix);
    if (count <= 0) return 0;
    bodies = malloc((size_t)count * sizeof *bodies);
    if (!bodies) return 0;
    count = banjo_bodies(world, bodies, count);
    for (i = 0; i < count; ++i)
        if (strncmp(bodies[i].name, prefix, len) == 0) ++n;
    free(bodies);
    return n;
}

int main(int argc, char **argv) {
    const int testing = argc > 1 && strcmp(argv[1], "--test") == 0;
    banjo_world *world;
    double y = 0.0, settled = 0.0;
    int i, panes;
    banjo_pick under;

    check(banjo_abi_version() == BANJO_ABI_VERSION,
          "the library was built against a different header than this program");

    world = banjo_open(kScene, 0.02);
    if (!world) {
        fprintf(stderr, "could not open the world: %s\n", banjo_last_error());
        return 1;
    }
    printf("opened %d bodies\n", banjo_body_count(world));

    /* A ray is how you ask where anything is. Straight down the middle from
     * above, the first thing met is the ball. */
    check(banjo_pick_ray(world, (double[3]){0, 12, 0}, (double[3]){0, -1, 0}, 0, &under) == BANJO_OK,
          "a ray could not be cast");
    check(under.hit && strcmp(under.name, "ball") == 0, "the ray down the middle did not meet the ball");
    printf("a ray from 12 m up meets %s at %.2f m\n", under.name, under.distance_m);
    /* Beside everything, it reaches the ground: a hit with no name. That is a
     * different answer from meeting nothing, and a pointer has to tell them
     * apart or empty space and the floor look the same. */
    check(banjo_pick_ray(world, (double[3]){3, 12, 0}, (double[3]){0, -1, 0}, 0, &under) == BANJO_OK
              && under.hit && under.name[0] == '\0',
          "a ray beside the scene should reach the unnamed ground");
    check(banjo_pick_ray(world, (double[3]){0, 12, 0}, (double[3]){0, 1, 0}, 0, &under) == BANJO_OK
              && !under.hit,
          "a ray fired at the sky hit something");

    /* Three seconds of world. banjo_advance settles whatever wants to break as
     * it goes, so this loop cannot wedge. */
    for (i = 0; i < 600; ++i) {
        int rc = banjo_advance(world, 1.0 / 120.0, 0.003);
        if (rc != BANJO_OK) { fprintf(stderr, "step %d: %s\n", i, banjo_last_error()); break; }
    }
    panes = piecesOf(world, "pane");
    printf("after %.2f s of world: %d bodies, %d of them pane\n",
           banjo_time(world), banjo_body_count(world), panes);
    /* 10 m of fall arrives at about 13.9 m/s against a 4.5 m/s threshold. The
     * height matters: 1.5 m arrives at 5.4 m/s, which also CLEARS the
     * threshold and still does not break the pane. The threshold is the speed
     * below which nothing can break -- necessary, never sufficient -- so a
     * program that treats clearing it as a promise is reading it backwards.
     * This example picked 3 m first and failed its own check for exactly that
     * reason. */
    check(panes > 1, "a 13.9 m/s iron ball did not break a glass pane");

    /* The hand. Pick a piece up, carry it, let go, and gravity has it back. */
    {
        int count = banjo_body_count(world);
        banjo_body *bodies = malloc((size_t)count * sizeof *bodies);
        char name[256];
        name[0] = '\0';
        count = banjo_bodies(world, bodies, count);
        for (i = 0; i < count; ++i)
            if (!bodies[i].anchored && strncmp(bodies[i].name, "pane", 4) == 0) {
                strncpy(name, bodies[i].name, sizeof name - 1);
                name[sizeof name - 1] = '\0';
                break;
            }
        free(bodies);
        check(name[0] != '\0', "nothing in the world could be picked up");
        if (name[0]) {
            check(findY(world, name, &settled), "the piece to lift is not there");
            check(banjo_grab(world, name) == BANJO_OK, "the piece could not be picked up");
            check(strcmp(banjo_held(world), name) == 0, "something else ended up in the hand");
            for (i = 1; i <= 60; ++i) {
                banjo_move_held(world, (double[3]){0.0, settled + i * (1.0 / 60.0), 0.0});
                banjo_advance(world, 1.0 / 120.0, 0.003);
            }
            check(findY(world, name, &y) && y > settled + 0.8, "the piece did not go where it was carried");
            printf("lifted %s from %.3f m to %.3f m\n", name, settled, y);
            banjo_release(world);
            for (i = 0; i < 360; ++i) banjo_advance(world, 1.0 / 120.0, 0.003);
            check(findY(world, name, &y), "the piece vanished after being let go");
            printf("let go: it fell to %.3f m\n", y);
            check(y < settled + 0.2, "it was let go a metre up and did not fall");
        }
    }

    /* Working one out without the world waiting for it.
     *
     * banjo_advance above settles a break by blocking for the whole run -- a
     * third of a second to a second -- and because this loop is what drives
     * time, everything stops with it. That is fine for a program printing
     * numbers and wrong for anything anybody watches, so here is the other way:
     * start it, keep stepping, collect it when it is in. */
    {
        int started = 0, stepsWhileWorking = 0, pieces = 0;
        for (i = 0; i < 2000; ++i) {
            if (banjo_fracture_pending(world)) {
                ++stepsWhileWorking;
                if (banjo_fracture_ready(world)) { pieces = banjo_finish_fracture(world); break; }
                banjo_step(world, 1.0 / 120.0);      /* the world carries on */
                continue;
            }
            if (banjo_step(world, 1.0 / 120.0) != BANJO_BREAK_PENDING) continue;
            if (banjo_breakable_count(world) < 1) continue;
            {
                const char *next = banjo_breakable_name(world, 0);
                if (next && banjo_begin_fracture(world, next, 0.0) == BANJO_OK) {
                    started = 1;
                    printf("working out %s without waiting for it\n",
                           banjo_fracture_subject(world));
                } else if (next) {
                    banjo_decline_break(world, next);   /* nothing to run; answer it */
                }
            }
        }
        if (started) {
            printf("the world took %d steps while that was worked out, "
                   "and it came to %d pieces\n", stepsWhileWorking, pieces);
            check(stepsWhileWorking > 0,
                  "the world took no steps while a fracture ran, so it waited after all");
        }
    }

    /* Sweeping the floor.
     *
     * A world that shatters fills with debris, and the reversible step a
     * fracture needs cannot run past a couple of thousand bodies -- so this is
     * not tidying, it is how the world stays able to break things. What comes
     * back is what the pieces were MADE of, which is the useful form. */
    {
        int count = banjo_body_count(world);
        banjo_body *bodies = malloc((size_t)count * sizeof *bodies);
        double where[3] = {0.0, 0.0, 0.0};
        int found = 0;
        count = banjo_bodies(world, bodies, count);
        for (i = 0; i < count; ++i)
            if (bodies[i].shape == BANJO_SHAPE_HULL && !bodies[i].anchored) {
                where[0] = bodies[i].position_m[0];
                where[1] = bodies[i].position_m[1];
                where[2] = bodies[i].position_m[2];
                found = 1;
                break;
            }
        free(bodies);
        if (found) {
            const int before = banjo_body_count(world);
            const int lots = banjo_collect(world, where, 5.0, 0);
            check(lots >= 0, "sweeping the floor failed");
            if (lots > 0) {
                banjo_lot *haul = malloc((size_t)lots * sizeof *haul);
                const int written = banjo_collected(world, haul, lots);
                for (i = 0; i < written; ++i)
                    printf("picked up %.0f g of %s (%d pieces)\n",
                           haul[i].kilograms * 1000.0, haul[i].material, haul[i].pieces);
                check(written > 0 && haul[0].kilograms > 0.0,
                      "it was collected but weighs nothing");
                free(haul);
                check(banjo_body_count(world) < before,
                      "a haul was reported but no bodies left the world");
            }
        }
    }

    /* Anchored scenery is the world, not a prop, and says so rather than
     * failing silently. */
    check(banjo_grab(world, "no such thing") == BANJO_BAD_ARGUMENT,
          "grabbing a name that is not there should be refused");

    banjo_close(world);

    if (testing) {
        printf(failures ? "\n%d checks failed\n" : "\nall checks passed\n", failures);
        return failures ? 1 : 0;
    }
    return 0;
}
