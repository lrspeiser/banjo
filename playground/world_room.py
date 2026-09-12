"""The room, and a model that can reach into it.

Two things live here. The first is the room itself: a set of objects chosen so
that the three things matter can do -- shatter, dent, bounce -- are all reachable
by hand, from a standing start, without anyone having to know what speed to aim
for. The second is the model's side of the chat: real tools over the live world,
so "put a glass ball on the iron plate" is a query and a change rather than a
guess at a scene file.

The model never touches physics. It says which objects should exist and where;
the engine decides what happens to them.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Any

import fracture_lab

# Every material in the catalogue, by the name the engine uses for it.
MATERIALS = ["iron", "aluminum", "glass", "ceramic", "oak", "rubber", "ice", "concrete"]
SHAPES = ["box", "sphere"]

# What a person calls the thing, as opposed to what it is made of. A label that
# says "alumina ceramic" and nothing else tells you the substance and not the
# object; both together is how anyone actually describes a thing.
COMMON_NAMES = {
    "iron": "iron", "aluminum": "aluminium", "glass": "glass",
    "ceramic": "alumina ceramic", "oak": "oak", "rubber": "rubber",
    "ice": "ice", "concrete": "concrete",
}

# How big a thing may be, and how far out. The room is 60 m of drawn floor; the
# engine's ground is much larger, but nothing useful happens 100 m away and a
# body that size costs cells nobody asked for.
# The object cap is about what the engine can still fracture, not about tidiness.
# Past 250 bodies the reversible trial stops being used and fracture quietly
# stops working, and a single plate coming apart can add ninety. The room starts
# at 58, so this leaves room for a couple of shatters on top of whatever gets
# built.
LIMITS = {"size_mm": (10.0, 2000.0), "position_mm": (-12000.0, 12000.0),
          "speed_m_s": 60.0, "objects": 120}


def room() -> dict[str, Any]:
    """The room as authored.

    Laid out so that everything is within reach of someone standing at the
    origin and turning round: a bench of things to pick up, a pair of anvils to
    drop them onto, and a thin pane bridged between two piers, which is the one
    arrangement in the room that will shatter at hand-held speeds.

    Sizes are deliberately mixed. A 40 mm marble and a 600 mm slab behave
    nothing alike and the difference is most of what there is to notice.
    """
    bodies: list[dict[str, Any]] = []

    def add(name, shape, material, size_mm, center_mm, **rest):
        body = {"name": name, "shape": shape, "material": material,
                "size_mm": list(size_mm), "center_mm": list(center_mm)}
        body.update(rest)
        bodies.append(body)

    # Every side is a whole number of 20 mm cells, because matter here is built
    # out of cells and a 30 mm side is not a thing the engine can make. That is
    # also the floor on how thin a plate can be: one cell, 20 mm. Real window
    # glass is 4 to 6 mm and is not reachable without a finer grid, which costs
    # about h^-4 -- eight times the cells and twice the substeps for each
    # halving -- so 20 mm is the thin end here and it is structural glass.
    #
    # Every loose object rests ON the floor, so its centre sits at half its own
    # height; putting it at y = 0 buries half of it.

    # ---- the targets: something of everything, at two thicknesses -----------
    #
    # Laid out as a grid you can walk between. Each plate bridges two short
    # piers, unsupported in the middle, because that is the arrangement that
    # breaks: the same plate lying flat on the floor is held everywhere and
    # will not.
    #
    # Thickness matters, though not in the way it first looks. The admission
    # bound is a stress-wave argument and does not depend on geometry at all:
    # a 20 mm and an 80 mm glass plate are admitted at the same 4.5 m/s. What
    # thickness changes is what the lattice then DOES -- measured, a 120 mm iron
    # ball dropped 1.5 m breaks the 20 mm glass and is held by the 40 mm.
    #
    # Plates are kept small on purpose. A 600 x 200 mm concrete plate comes
    # apart into 291 pieces and an 80 mm one exceeded Jolt's contact budget
    # outright; past 250 bodies the reversible trial stops being used and
    # fracture quietly stops working. A 240 x 160 plate is at most 96 cells, so
    # at most 96 pieces.
    TARGETS = ["glass", "ceramic", "ice", "concrete", "oak", "aluminum", "iron", "rubber"]
    for column, material in enumerate(TARGETS):
        x = -2800 + column * 800
        for row, thick in enumerate((20, 40)):
            z = -1200 - row * 800
            rest = 120                      # how high the plate is carried
            add(f"{material} pier {column}{row}L", "box", "iron", [40, rest, 160],
                [x - 100, rest // 2, z], anchored=True)
            add(f"{material} pier {column}{row}R", "box", "iron", [40, rest, 160],
                [x + 100, rest // 2, z], anchored=True)
            add(f"{material} plate {thick}mm", "box", material,
                [240, thick, 160], [x, rest + thick // 2, z])

    # ---- an anvil, for the things that need something immovable ------------
    add("iron anvil", "box", "iron", [300, 160, 240], [0, 80, -3200], anchored=True)

    # ---- a bench of things to pick up and drop -----------------------------
    #
    # Eight materials, sizes from a marble to a slab, because a 40 mm marble and
    # a 400 mm slab behave nothing alike and that difference is most of what
    # there is to notice.
    add("iron ball", "sphere", "iron", [120, 120, 120], [-900, 60, 0])
    add("aluminium ball", "sphere", "aluminum", [140, 140, 140], [-600, 70, 0])
    add("glass marble", "sphere", "glass", [60, 60, 60], [-350, 30, 0])
    add("rubber ball", "sphere", "rubber", [180, 180, 180], [-100, 90, 0])
    add("oak block", "box", "oak", [200, 200, 200], [200, 100, 0])
    add("ice cube", "box", "ice", [160, 160, 160], [500, 80, 0])
    add("concrete brick", "box", "concrete", [240, 120, 120], [800, 60, 0])
    add("ceramic cup", "box", "ceramic", [120, 140, 120], [1060, 70, 0])
    add("iron marble", "sphere", "iron", [40, 40, 40], [-1250, 20, 0])

    return {
        "algorithm": "lattice",
        "cell_m": 0.02,
        # Pins. None in this room; see courtyard().
        "joints": [],
        # A dent needs a material that can hold a shape it was pushed into, and
        # that is off unless a scene asks for it. "on"/"off" is the panel's
        # spelling of it; scene_document turns it into the boolean the engine
        # reads.
        "plasticity": "on",
        "bodies": bodies,
    }


def courtyard() -> dict[str, Any]:
    """A gateway you can push open, and a few things to push it with.

    Built at 40 mm cells rather than 20. Cost goes as the cube of the cell, so a
    gate that is 12,000 cells at 20 mm is 1,500 at 40 -- and this room is about
    a thing that SWINGS, where what matters is the pin and the mass hanging off
    it, not whether the leaf can be split into 60 mm splinters. The bench room
    next door is where the fine grid earns its keep.

    Nothing in here is animated. The gate is a body, the pin is a constraint,
    and it opens because you put a force on something half a metre out from its
    hinge. Break the jamb the pin is in and the pin follows whichever piece of
    stone it ends up inside; break away all of it and the pin comes out and the
    gate falls over.
    """
    bodies: list[dict[str, Any]] = []

    def add(name, shape, material, size_mm, center_mm, **rest):
        body = {"name": name, "shape": shape, "material": material,
                "size_mm": list(size_mm), "center_mm": list(center_mm)}
        body.update(rest)
        bodies.append(body)

    # Every side is a whole number of 40 mm cells.
    #
    # The opening is 1.2 m wide and 2 m tall, which is a real doorway: wide
    # enough to walk through and small enough that the leaf is a mass you can
    # feel. The jambs stand at x = 0 and x = 1520.
    add("gate jamb left", "box", "concrete", [160, 2000, 160], [-80, 1000, 0],
        anchored=True)
    add("gate jamb right", "box", "concrete", [160, 2000, 160], [1600, 1000, 0],
        anchored=True)
    # 120 mm rather than 160: cost goes as the cube of the cell and this room
    # runs right up against the lane's 16,000. A lintel is scenery.
    add("gate lintel", "box", "concrete", [1840, 120, 120], [760, 2060, 0],
        anchored=True)

    # The leaf, in FRONT of the jambs rather than between them.
    #
    # A leaf sharing space with its own frame is jammed against it, and jammed
    # is exactly what a working hinge looks like from the outside -- two degrees
    # of swing and an afternoon spent on the constraint solver. It also hangs
    # 40 mm clear of the floor, because a gate resting on the ground is held by
    # friction with the ground and will not swing either.
    #
    # 1.44 m x 1.76 m of 80 mm oak is 111 kg, which is what a real gate weighs
    # and is most of why it takes a shove rather than a nudge.
    add("oak gate", "box", "oak", [1440, 1760, 80], [720, 1000, 120])

    # The locking bar. Fixed to the jamb at one end and to the gate at the
    # other, which makes the two into ONE PIECE: barred, the gate does not
    # swing however hard you shove it, and nothing about the gate itself has
    # changed. Lift the bar off and it is a gate again.
    #
    # That is what a latch is for, and it is the reason a latch is not just a
    # very stiff hinge: releasing it changes what the assembly can DO.
    #
    # IRON, and not for looks. The gate is 142 kg and a 5 kg oak bar restraining
    # it through two fixed constraints is a mass ratio of thirty to one, which
    # is where an iterative solver quietly gives up: measured, a shove that
    # moved the unbarred gate 15 degrees moved the OAK-barred one 15 degrees
    # too. A 60 kg iron bar is a ratio of two, which it holds.
    add("locking bar", "box", "iron", [1200, 80, 80], [600, 1400, 240])

    # ---- a portcullis, in its own gateway ----------------------------------
    #
    # Set well along from the gate so you can stand between them. It is an iron
    # grate in a pair of grooves: hauled up it has 1.6 m of lift, and let go it
    # FALLS, because nothing here knows what a portcullis is -- it is a body
    # free to move down one line with gravity still acting on it.
    #
    # Which also means it stops on whatever is under it. Push the barrel into
    # the gateway and the grate comes to rest on the barrel, at the barrel's
    # height, because that is where the contact is.
    #
    # 1.28 x 1.2 x 0.12 m of iron is 1,450 kg and 14.2 kN of weight; the grooves
    # grip at 3 kN, which is enough to slow it and nowhere near enough to hold
    # it. A winch is what would hold it, and a winch is a rope and a pulley.
    #
    # Sized down to what the cell budget allows: the room is 40 mm cells and the
    # lane caps at 16,000 of them, and the first version of this gateway put the
    # room at 16,952. A 3 m jamb is 1,500 cells and a 2.4 m one is 960.
    PORT_X, PORT_Z = -2600, 0
    add("portcullis jamb left", "box", "concrete", [160, 2400, 160],
        [PORT_X - 720, 1200, PORT_Z], anchored=True)
    add("portcullis jamb right", "box", "concrete", [160, 2400, 160],
        [PORT_X + 720, 1200, PORT_Z], anchored=True)
    add("portcullis lintel", "box", "concrete", [1600, 120, 120],
        [PORT_X, 2460, PORT_Z], anchored=True)
    # In front of the jambs in z, and resting on the ground. Its 1.2 m of lift
    # puts its top at 2.4 m, exactly under the lintel -- a grate that would go
    # through its own arch is a grate whose travel was never measured.
    add("iron portcullis", "box", "iron", [1280, 1040, 120],
        [PORT_X, 520, PORT_Z + 140])

    # The winch: a rope from the top of the grate, over the lintel, out to a
    # counterweight hanging beside the gateway.
    #
    # The sums, because a winch either works or it is scenery.
    #
    #   grate          1.28 x 1.04 x 0.12 m of iron   1,257 kg   12.33 kN
    #   counterweight  0.4 x 0.32 x 0.4 m of iron       403 kg    3.95 kN
    #   through a ratio of 0.35, at the grate                     11.30 kN
    #   grooves                                                    0.50 kN
    #
    # So the grate sits down by 1.03 kN and the grooves hold it with another
    # 0.5 -- it does NOT lift itself, which is the point of a winch somebody has
    # to work. A person heaving with their 800 N takes the counterweight side to
    # 4.75 kN, which arrives at the grate as 13.58, and that lifts it with
    # 0.75 kN to spare.
    #
    # RATIO BELOW ONE, and the direction is the thing to get right. The
    # constraint puts force `lambda` on end a and `ratio * lambda` on end b, so
    # a counterweight at b arrives at the grate DIVIDED by the ratio. Measured
    # with a ratio of 3: a 3.95 kN counterweight showed a rope tension of
    # 1.32 kN -- its own weight over three -- and an 800 N heave moved a 12.3 kN
    # grate not at all, which is correct arithmetic and the wrong way round.
    # Balance is at 0.32; anything above that and the grate stays down.
    #
    # IRON, not stone, and that is a cell-budget decision rather than a
    # metallurgical one. Concrete is a third the density, so the same mass in
    # stone is a 640 mm block -- 4,096 cells of the room's 16,000 -- against 800
    # for the iron. The first version of this put the room at 18,304 and it
    # would not open at all.
    # Hung HIGH, because the ratio that gives the lift takes it back in
    # distance: the grate rises 0.35 m for every metre the counterweight
    # descends, so the counterweight needs room to fall. From 1.6 m it had
    # 1.44 m of drop and could only ever raise the grate half a metre.
    add("winch counterweight", "box", "iron", [400, 320, 400],
        [PORT_X + 1600, 2000, PORT_Z + 140])

    # ---- a hanging sign ----------------------------------------------------
    #
    # A board on two ropes off a bracket. The goal names hanging signs, and they
    # are the cheapest honest test of a rope: the board hangs because two links
    # are pulling up on it, it swings when you push it because the links let it,
    # and it is not attached to the bracket by anything else.
    #
    # The ropes are not drawn as segments here -- they are two direct ties, one
    # to each corner -- because a two-link sign needs no catenary to be right. A
    # rope with a shape in it is a run of segments; see the chain below.
    SIGN_X, SIGN_Z = 1400, 900
    add("sign bracket", "box", "oak", [160, 120, 640],
        [SIGN_X, 2400, SIGN_Z - 200], anchored=True)
    add("tavern sign", "box", "oak", [720, 480, 80], [SIGN_X, 1600, SIGN_Z - 440])

    # ---- a chain, hanging from a beam --------------------------------------
    #
    # Eight links in a row, each an ordinary body tied to the next. This is what
    # makes it a rope rather than a rope-shaped thing: every link is a body, so
    # the chain hangs in a curve because its own links are heavy, swings where
    # you push it, and drapes over whatever it touches. Take hold of the bottom
    # one and the whole thing follows.
    CHAIN_X, CHAIN_Z = -1000, 1400
    add("chain beam", "box", "oak", [640, 160, 160], [CHAIN_X, 2600, CHAIN_Z],
        anchored=True)
    for i in range(8):
        add(f"chain {i + 1}", "box", "iron", [80, 80, 80],
            [CHAIN_X, 2360 - i * 160, CHAIN_Z])

    # ---- a stone shelf on two piers ----------------------------------------
    #
    # Somewhere to stack things, and the one thing in this room that can break
    # WITHOUT being hit. A shelf at rest under a pile reports no contacts at
    # all -- nothing strikes it -- so the load survey is the only thing that
    # ever notices, and it notices from statics: what is on it, how far apart
    # its piers are, and the bending that puts in it.
    #
    # A THIN slab, and the thinness is the point twice over.
    #
    # Bending stress goes as 1/depth squared, so 40 mm of stone over an 840 mm
    # clear span is 3,281 Pa per newton on it. Concrete takes 3 MPa in tension --
    # famously little, which is why real concrete is reinforced -- so about
    # 914 N breaks it. The stone block in this room is 772 N and the iron ball
    # is 324 N: either one alone is fine, and the two together are not. That is
    # a shelf somebody can overload by hand, which is the whole idea.
    #
    # A 120 mm slab would have wanted 3.7 kN, which is more than everything
    # loose in this courtyard put together, and it would have been a shelf that
    # demonstrates nothing.
    SHELF_X, SHELF_Z = 1400, -1600
    add("shelf pier left", "box", "concrete", [160, 800, 160],
        [SHELF_X - 500, 400, SHELF_Z], anchored=True)
    add("shelf pier right", "box", "concrete", [160, 800, 160],
        [SHELF_X + 500, 400, SHELF_Z], anchored=True)
    add("stone shelf", "box", "concrete", [1200, 40, 240],
        [SHELF_X, 820, SHELF_Z])

    # ---- a bow on a stand, and an arrow ------------------------------------
    #
    # There is no bow here. There is a grip, two limbs, a string and a nock, and
    # every one of them is a joint this room already had before anyone said the
    # word archery:
    #
    #   the grip     two anchored blocks with a gap between them for the arrow.
    #                The lower one is also the arrow REST -- its top face is
    #                exactly where the shaft lies.
    #   the limbs    a HINGE at each root so a limb can only swing in the bow's
    #                own plane, and an ELASTIC anchored forward of that root
    #                which lengthens as the tip swings back. That is where the
    #                energy goes.
    #   the string   two LINKS, tip to nocking point, because a string pulls and
    #                does not push and that is exactly what a link is
    #   the nock     a FIXING between the string and the arrow, because what a
    #                nock does is hold two things together until it is let go,
    #                which is what a latch is
    #
    # So the arrow's speed is not a number anywhere. It is whatever the limbs
    # are holding when the nock is let go, less what the string, the tips and
    # the rest keep for themselves. Draw further, stiffen the limbs or nock a
    # heavier arrow and the shot changes, because nothing else could happen.
    #
    # It faces the gate, 1.6 m away in +x, because an arrow that lands in an
    # empty courtyard tells you less than one that swings a 111 kg gate.
    # 1220 and not 1200, and the 20 mm is not taste. Matter here is built out of
    # 40 mm cells laid on the world grid, so a 40 mm shaft centred on 1200
    # straddles two rows of them and claims half of each -- which the placement
    # check reads, correctly, as the arrow and the grip it rests on occupying
    # the same cells. On 1220 the shaft is one clean row and the rest ends where
    # the shaft begins.
    BOW_X, BOW_Y, BOW_Z = -1600, 1220, 120
    BRACE_X = BOW_X - 160           # the string, a brace height behind the grip
    TIP_X, TIP_UP = BRACE_X, 400    # the tips, LEVEL with the string
    ROOT_UP, SPRING_X = 120, BOW_X + 360
    # The two grip blocks are NOT symmetric about the shaft, because the lower
    # one has a second job: its top face is the arrow REST, set exactly at the
    # underside of the shaft, while the upper one stands 40 mm clear above it.
    #
    # The rest is not decoration. The string hangs on two ropes and a rope end
    # is a ball joint, so what holds the string against tipping nose-down is a
    # second-order term and not much of one -- and an arrow whose weight sits
    # 360 mm in front of the nock tips it. Taken away, the ropes went slack
    # before anyone touched the bow and a 300 mm draw stored 3 J instead of 25.
    # What stops it is the same thing that stops it on a real bow: the shaft is
    # lying on something.
    GRIP_Y = {1: BOW_Y + 180, -1: BOW_Y - 100}

    # THE TIPS ARE LEVEL WITH THE STRING, and that is the whole of why this
    # stands up. Set them forward of it, as the first version did, and the
    # braced string is a V with the nocking point at its apex -- which is not an
    # equilibrium at all: the two rope tensions no longer cancel, their
    # resultant shoves the nock towards the bow, and the arrow's weight hanging
    # 300 mm in front of the nock turns the whole assembly over. Measured, with
    # nobody touching it: braced at x = -1.760, and one second later the string
    # was at -1.385 and the arrow was pointing at the floor.
    #
    # On the line, the two tensions are equal and opposite and cancel exactly,
    # which is what "braced" means on a real bow. Push the nock off that line in
    # any direction and BOTH segments lengthen, the limbs bend, and it comes
    # back. That is also, drawn far enough, the shot.
    for side in (1, -1):
        # An 80 mm window between them for the shaft to pass through. A single
        # block would have the arrow running through the middle of the grip, and
        # a narrow one has the shaft rubbing as it is drawn: measured with 40 mm
        # of gap the bow reached 50 mm of draw and 0.7 J before it jammed.
        #
        # The pin sits INSIDE a block rather than at its middle. Where the pin
        # is and where the block is are two questions.
        add(f"bow grip {'upper' if side > 0 else 'lower'}", "box", "oak",
            [40, 160, 120], [BOW_X, GRIP_Y[side], BOW_Z], anchored=True)
        # SMALL tips -- one cell, which is as small as matter gets here. A tip
        # is a mass the limb has to accelerate before any of the energy can
        # reach the arrow, so whatever it weighs is taken out of the shot twice
        # over: it keeps energy, and it LAGS. Measured at 80 mm, the two tips
        # were 717 g against 851 g of arrow and string, and the string ran home
        # to a brace the tips had not got back to yet -- the ropes went taut
        # 62 mm short, stopped the arrow dead at 4.75 m/s, and the whole
        # assembly sat there. At 40 mm they are 90 g and the string arrives at
        # brace. Real bows are built the same way round and for the reason.
        add(f"{'upper' if side > 0 else 'lower'} limb tip", "box", "oak",
            [40, 40, 40], [TIP_X, BOW_Y + side * TIP_UP, BOW_Z])
    # A LENGTH of string, not a point, and that is what makes the thing hold
    # its shape. A rope end is a ball joint: two ropes made off at the same
    # point leave the piece they hold free to spin there however it likes, and
    # an arrow whose weight sits 300 mm in front of the nock spins it. Made off
    # 160 mm apart, turning the string has to lengthen one of them, so it does
    # not turn. It weighs 179 g, which is a quarter of the arrow and is taken
    # out of every shot -- a real string is lighter, and a cell here is 40 mm.
    # Two ropes made off 160 mm apart hold the string against turning end over
    # end, which is what keeps the arrow level. What they do NOT hold is the
    # string ROLLING about its own length -- both attachments are on that line,
    # so the lever arm is exactly zero -- and rolling it swings the arrow
    # sideways. Nothing drives that and nothing stopped it: measured, a drawn
    # arrow had yawed and was pointing 240 mm out of the bow's plane.
    #
    # So the window has cheeks, 20 mm clear of the shaft on each side. That is
    # an arrow rest with a side plate, and it is why real ones have them.
    for side in (1, -1):
        add(f"bow grip {'near' if side > 0 else 'far'} cheek", "box", "oak",
            [40, 40, 40], [BOW_X, BOW_Y, BOW_Z + side * 60], anchored=True)
    add("bowstring", "box", "oak", [40, 160, 40], [BRACE_X, BOW_Y, BOW_Z])
    # Nocked, lying forward through the window in the grip and resting on the
    # lower block. A cell CLEAR of the string rather than buried in it: two
    # bodies sharing space fly apart the moment whatever held them together
    # stops, and a nock holds two things in whatever pose they are in, touching
    # or not.
    #
    # The REST is not decoration either. The nocking point is held by two ropes
    # and a rope end is a ball joint, so nothing at all resists the string
    # turning on the spot -- and an arrow whose weight sits 300 mm in front of
    # the nock turns it. What stops that is the same thing that stops it on a
    # real bow: the shaft is lying on something.
    add("arrow", "box", "oak", [600, 40, 40], [BRACE_X + 360, BOW_Y, BOW_Z])
    # And a spare on the ground, because retrieving what you shot is half of it.
    add("spare arrow", "box", "oak", [600, 40, 40], [BOW_X, 20, BOW_Z + 400])

    # Things to push with, and to wedge things open.
    add("iron ball", "sphere", "iron", [200, 200, 200], [-800, 100, 800])
    add("oak barrel", "box", "oak", [400, 480, 400], [400, 240, 1200])
    add("stone block", "box", "concrete", [320, 320, 320], [1200, 160, 1200])

    return {
        "algorithm": "lattice",
        "cell_m": 0.04,
        "plasticity": "on",
        "bodies": bodies,
        # The gate swings outward only, up to 100 degrees, and carries enough
        # friction to stay where it is pushed instead of swinging back and forth
        # for ever like a saloon door. The pin is at the left jamb's inner face,
        # at the leaf's own depth -- a hinge is where the two meet.
        "joints": [{
            "kind": "hinge",
            "a": "gate jamb left",
            "b": "oak gate",
            "at_mm": [0, 1000, 120],
            "axis": [0, 1, 0],
            "lower_deg": 0,
            "upper_deg": 100,
            "friction_n_m": 12,
        }, {
            # Straight up and down, 1.2 m of lift, and nothing holding it there.
            "kind": "slider",
            "a": "portcullis jamb left",
            "b": "iron portcullis",
            "at_mm": [PORT_X, 520, PORT_Z + 140],
            "axis": [0, 1, 0],
            "lower_mm": 0,
            "upper_mm": 1200,
            # 500 N, not 3,000. The grooves have to grip enough to be grooves
            # and not so much that they swallow the winch: the whole margin a
            # person works with here is about 1.4 kN at the grate, and 3 kN of
            # friction is twice that. A number chosen before the winch existed.
            "friction_n": 500,
        }, {
            # The bar to the jamb. A peg driven along x, so pulling the bar
            # straight off the jamb is tension and the gate shoving it sideways
            # is shear. Both zero: a bar you can lift off but not break.
            "kind": "fixing",
            "a": "gate jamb left",
            "b": "locking bar",
            "at_mm": [0, 1400, 240],
            "axis": [1, 0, 0],
            "holds_tension_n": 0,
            "holds_shear_n": 0,
        }, {
            # And the bar to the gate, across the other way.
            "kind": "fixing",
            "a": "locking bar",
            "b": "oak gate",
            "at_mm": [900, 1400, 200],
            "axis": [0, 0, 1],
            "holds_tension_n": 0,
            "holds_shear_n": 0,
        }, {
            # The winch. The rope runs from the top of the grate up over the
            # lintel, across, and down to the counterweight.
            #
            # Both sheaves sit at the lintel's underside: one above the grate,
            # one above the counterweight. They are points in the WORLD and stay
            # there however the room is rearranged -- that is what makes them
            # the fixed half of the length relationship.
            #
            # See the sums above the counterweight for why this is 0.35 and
            # not 3: force at b is ratio times force at a, so a counterweight
            # hung at b arrives at the grate DIVIDED by the ratio.
            "kind": "pulley",
            "a": "iron portcullis",
            "b": "winch counterweight",
            "at_mm": [PORT_X, 1040, PORT_Z + 140],
            "to_mm": [PORT_X + 1600, 2160, PORT_Z + 140],
            "over_a_mm": [PORT_X, 2400, PORT_Z + 140],
            "over_b_mm": [PORT_X + 1600, 2400, PORT_Z + 140],
            "ratio": 0.35,
            "length_mm": 0,             # as it is rove
        }] + [{
            # The sign, on two ropes. Tied where they actually meet each body,
            # which is what makes it hang level rather than pivot on one point.
            "kind": "link",
            "a": "sign bracket",
            "b": "tavern sign",
            "at_mm": [SIGN_X + side * 280, 2340, SIGN_Z - 440],
            "to_mm": [SIGN_X + side * 280, 1840, SIGN_Z - 440],
            "length_mm": 0,             # as they stand
            "breaks_at_n": 0,           # a sign is not a thing you overload
        } for side in (-1, 1)] + [{
            # The chain: beam to link 1, link 1 to link 2, and so on. Every one
            # is the same joint as the sign's ropes.
            "kind": "link",
            "a": "chain beam" if i == 0 else f"chain {i}",
            "b": f"chain {i + 1}",
            # The upper end of link i is on the body ABOVE it -- the beam for
            # the first, and link i itself for the rest. Written the long way
            # because the short way was off by one: every link was tied to the
            # beam's underside rather than to the link it hangs from, which is
            # not a chain, it is eight things all nailed to the same spot.
            "at_mm": [CHAIN_X, 2520 if i == 0 else 2360 - (i - 1) * 160, CHAIN_Z],
            "to_mm": [CHAIN_X, 2360 - i * 160, CHAIN_Z],
            "length_mm": 0,
            "breaks_at_n": 0,
        } for i in range(8)] + [{
            # The limb roots. A pin across the bow, so a limb can only swing in
            # the bow's own plane -- without it the tip is free on a sphere and
            # simply follows the string round, storing nothing.
            #
            # Sixty degrees each way and not a hundred and twenty: a limb that
            # can fold right over is a limb that will, and a bow whose limbs turn
            # inside out is not a bow.
            "kind": "hinge",
            "a": f"bow grip {'upper' if side > 0 else 'lower'}",
            "b": f"{'upper' if side > 0 else 'lower'} limb tip",
            "at_mm": [BOW_X, BOW_Y + side * ROOT_UP, BOW_Z],
            "axis": [0, 0, 1],
            "lower_deg": -60,
            "upper_deg": 60,
            "friction_n_m": 0,
        } for side in (1, -1)] + [{
            # The limbs themselves: elastic, anchored 360 mm FORWARD of the root
            # so that swinging the tip back lengthens them. A lever with a spring
            # on it -- a declared and ordinary way to model a limb, where the
            # restoring torque is the spring force times the moment arm rather
            # than a true bending stiffness.
            #
            # 6 kN/m against the 800 N a person has. A bow nobody can draw stores
            # nothing either, and the hand here pulls with what it has rather
            # than with whatever the bow demands. Stiffer is not simply better:
            # a limb tip is 45 g, so at 40 kN/m the tips ring at 150 Hz and the
            # world is stepped at 240 -- under two samples a cycle, which the
            # solver damps into nonsense. Measured, the arrow leaves at 1.6 m/s
            # at 3 kN/m, 3.1 at 6 and 4.9 at 10, and past that it stops meaning
            # anything.
            "kind": "elastic",
            "a": f"bow grip {'upper' if side > 0 else 'lower'}",
            "b": f"{'upper' if side > 0 else 'lower'} limb tip",
            "at_mm": [SPRING_X, BOW_Y + side * ROOT_UP, BOW_Z],
            "to_mm": [TIP_X, BOW_Y + side * TIP_UP, BOW_Z],
            "rest_mm": 0,               # as it stands, which is braced
            "stiffness_n_m": 6000,
            # A DECLARED loss, and the only thing that should take energy out of
            # the limbs. Zero gives 96% of it back and a bow that rings for ever
            # after the shot; 20 settles them in about a second.
            "damping_n_s_m": 20,
        } for side in (1, -1)] + [{
            # The string. Two links, because a string pulls and does not push,
            # made off at the two ENDS of it rather than both at the nocking
            # point -- see the body above for why that is the difference between
            # a bow and a thing that falls over.
            "kind": "link",
            "a": f"{'upper' if side > 0 else 'lower'} limb tip",
            "b": "bowstring",
            "at_mm": [TIP_X, BOW_Y + side * TIP_UP, BOW_Z],
            "to_mm": [BRACE_X, BOW_Y + side * 80, BOW_Z],
            "length_mm": 0,             # as it is strung
            "breaks_at_n": 0,           # a string somebody can snap is a later room
        } for side in (1, -1)] + [{
            # The nock: the arrow held to the string until it is let go. The
            # same joint as the locking bar on the gate, and for the same
            # reason -- releasing it is what changes what the assembly does.
            #
            # Let go by hand and not by being overloaded, and that is measured
            # rather than chosen: a fixing reports the MAGNITUDE of the force
            # along its axis, so a nock being shoved forward by the string reads
            # the same as one being pulled apart. Given a strength it let go
            # during the draw, at 2.5 kN, long before the string ever stopped.
            "kind": "fixing",
            "a": "bowstring",
            "b": "arrow",
            "at_mm": [BRACE_X, BOW_Y, BOW_Z],
            "axis": [1, 0, 0],
            "holds_tension_n": 0,
            "holds_shear_n": 0,
        }],
    }


def armoury() -> dict[str, Any]:
    """A sword, and things to cut with it: a rope with a weight on it, an oak
    panel hung from a lintel, and an oak batten across two piers carrying a load.

    Nothing here knows the word "sword". There is an iron bar, and a declared
    edge along one side of it (docs/cutting-model.md): where the edge runs, which
    way it faces, how thick and how sharp it is, and where it is held. What the
    edge does to anything is decided by the edge's geometry, the two materials,
    how they are moving and how hard they are pressed -- never by a name.

    Built at 10 mm cells, because a blade is thin and the thin end of matter here
    is one cell. The bar is one cell thick: a heavy blade, 1.9 kg, 820 mm long.

    Standing where the room opens you face all of it. Click the sword on its rest
    to take hold of it: it is held at its grip by a hand with 800 N and 60 N m,
    in front of you and pointing where you look. Drag to look, and the sword
    swings with your view -- as fast as the hand can make it, and no faster. The
    edge starts facing LEFT; right-click turns it a quarter turn (left, down,
    right, up), which is how a flat strike is made: the edge facing down, swung
    sideways, leads with the flat. Click again to let go.

      the rope    front left. Six rubber segments tied end to end, 1 kg of
                  iron on the bottom. To cut it: holding the sword, look level
                  at the middle of the rope from a little to its right, clear
                  of the panel, and wait a moment for the sword to come round.
                  Then drag the view LEFT about 60 degrees (some 480 px) in a
                  fifth of a second or less. The edge arrives at 10-13 m/s and
                  goes through: that segment comes apart, its upper piece
                  stays tied to the rope above and the lower piece falls with
                  the rest of the rope and the weight. A slower drag reaches
                  it slower and only notches it -- the slit is drawn, and it
                  stays. The same drag with the edge turned down (one right-
                  click) leads with the flat: the rope swings and holds.
      the panel   front right, hung from a lintel by its top edge. Holding the
                  sword, look up so the blade clears everything, walk to stand
                  square in front of the panel with your eye at its middle,
                  look a little right of it, and flick the view LEFT about 35
                  degrees (some 270 px) in an eighth of a second: the edge
                  goes through the 20 mm oak at 7-8 m/s for about 120 J, the
                  lower piece falls and the upper stays on its fixings. A slow
                  drag stops part way and the slit stays, drawn; drawn back
                  and flicked again along the same cut, it carries on.
      the batten  straight ahead, low. Oak 20 mm deep and 30 mm wide across
                  two piers with 32 kg on its middle: 41 MPa of bending against
                  oak's 90, so it holds. Turn the edge down (one right-click),
                  look up, stand over the batten a little right of the load,
                  look level, and pitch the view DOWN about 25 degrees (some
                  200 px) in a fifth of a second: the edge chops through and
                  the load comes down with the pieces. A chop that stops part
                  way leaves a notch, and a deep enough notch beside the load
                  overloads what is left of the batten: the room says so, and
                  the lattice decides what it does about that.
    """
    bodies: list[dict[str, Any]] = []

    def add(name, shape, material, size_mm, center_mm, **rest):
        body = {"name": name, "shape": shape, "material": material,
                "size_mm": list(size_mm), "center_mm": list(center_mm)}
        body.update(rest)
        bodies.append(body)

    # ---- the sword, on a rest in front of where you stand ---------------------
    #
    # One iron bar, 820 x 10 x 30 mm. The edge runs along its far long side for
    # the 700 mm nearest the point; the last 120 mm is the grip. A plain bar
    # rather than a join with a guard and a pommel: a join collides as the
    # convex hull of its cells, and a hull round a crossguard is a flat kite
    # wider than the blade -- an invisible wing that would strike things the
    # steel never touches. This bar collides exactly as it is drawn.
    SWORD_Y, SWORD_Z = 1005, 1900
    add("sword rest left", "box", "oak", [40, 40, 40], [-250, 980, SWORD_Z], anchored=True)
    add("sword rest right", "box", "oak", [40, 40, 40], [250, 980, SWORD_Z], anchored=True)
    add("sword", "box", "iron", [820, 10, 30], [0, SWORD_Y, SWORD_Z])

    # ---- a rope with a weight on it -------------------------------------------
    #
    # Six rubber segments, 20 x 120 x 20 mm, each tied to the next where they
    # meet. A rope struck from the side is knocked away about as fast as it is
    # cut, and how fast depends on how much rope the edge has to move: an edge
    # gets through a segment before it gets away above about
    # sqrt(2 R / (density x segment length)) -- 15 m/s for 60 mm of rubber,
    # 10.6 for 120. A real rope is one piece and is harder still to knock
    # aside; twelve short segments made it easier to push away than to cut.
    # A rope made of bodies because a link on its own is a constraint with no
    # matter in it, and nothing can cut what is not there. Rubber because the
    # catalogue has no fibre: it is a rubber cord, and says so.
    ROPE_X, ROPE_Z, BEAM_Y = -500, 1400, 2000
    add("rope beam", "box", "oak", [300, 40, 40], [ROPE_X, BEAM_Y + 20, ROPE_Z],
        anchored=True)
    for k in range(6):
        add(f"rope {k + 1}", "box", "rubber", [20, 120, 20],
            [ROPE_X, BEAM_Y - 60 - 120 * k, ROPE_Z])
    ROPE_END = BEAM_Y - 120 * 6
    # A kilogram of iron, not eight. A chain of light links under a load three
    # hundred times heavier does not hold its length in an iterative solver:
    # the first rope hung 0.6 m long, with gaps between its segments that a
    # blade went straight through without touching anything. Each segment here
    # is 53 g, and at 19 to one the rope hangs as it was tied.
    add("weight", "box", "iron", [50, 50, 50], [ROPE_X, ROPE_END - 25, ROPE_Z])

    # ---- an oak panel hung from a lintel --------------------------------------
    PANEL_X, PANEL_Z, LINTEL_Y = 700, 1300, 1720
    add("panel lintel", "box", "oak", [500, 40, 40], [PANEL_X, LINTEL_Y + 20, PANEL_Z],
        anchored=True)
    add("oak panel", "box", "oak", [400, 300, 20], [PANEL_X, LINTEL_Y - 150, PANEL_Z])

    # ---- an oak batten across two piers, carrying a load ----------------------
    #
    # The sums. 30 mm wide, 20 mm deep oak over a 1.04 m clear span carrying
    # 32.2 kg (316 N) at mid-span: 3 W L / (2 b d^2) = 41 MPa, against oak's 90.
    # It holds. A notch half its depth, 200 mm from the middle, leaves a 10 mm
    # ligament where the moment is 51 N m: 102 MPa, and the room offers it to
    # the lattice to break. 300 mm out the moment there is 35 N m: 70 MPa, and
    # it still holds -- where the notch is matters, as it does. That is the
    # survey's answer changing because of what a blade did, and nothing else.
    # (It was 20 mm square, and a 160 mm block on a 20 mm stick is a balancing
    # act that tips at 5.7 degrees of roll. On 30 mm it stands 8.5.)
    BATTEN_Z, PIER_TOP = 700, 1000
    for side in (-1, 1):
        add(f"batten pier {'left' if side < 0 else 'right'}", "box", "oak",
            [40, PIER_TOP, 40], [side * 540, PIER_TOP // 2, BATTEN_Z], anchored=True)
    add("oak batten", "box", "oak", [1200, 20, 30], [0, PIER_TOP + 10, BATTEN_Z])
    add("iron load", "box", "iron", [160, 160, 160], [0, PIER_TOP + 20 + 80, BATTEN_Z])

    joints: list[dict[str, Any]] = []
    # The rope: beam to the first segment, each segment to the next, the last to
    # the weight -- tied between the centres of the two cells either side of
    # each join, so the tie runs through matter and a blade that crosses it
    # there cuts it.
    joints.append({"kind": "link", "a": "rope beam", "b": "rope 1",
                   "at_mm": [ROPE_X, BEAM_Y + 5, ROPE_Z],
                   "to_mm": [ROPE_X, BEAM_Y - 5, ROPE_Z],
                   "length_mm": 0, "breaks_at_n": 0})
    for k in range(1, 6):
        join = BEAM_Y - 120 * k
        joints.append({"kind": "link", "a": f"rope {k}", "b": f"rope {k + 1}",
                       "at_mm": [ROPE_X, join + 5, ROPE_Z],
                       "to_mm": [ROPE_X, join - 5, ROPE_Z],
                       "length_mm": 0, "breaks_at_n": 0})
    joints.append({"kind": "link", "a": "rope 6", "b": "weight",
                   "at_mm": [ROPE_X, ROPE_END + 5, ROPE_Z],
                   "to_mm": [ROPE_X, ROPE_END - 5, ROPE_Z],
                   "length_mm": 0, "breaks_at_n": 0})
    # The panel on two welds to the lintel, one at each top corner. Cut across
    # it and the lower piece has nothing holding it; the fixings stay with the
    # piece whose matter they are in.
    for side in (-1, 1):
        joints.append({"kind": "fixing", "a": "panel lintel", "b": "oak panel",
                       "at_mm": [PANEL_X + side * 150, LINTEL_Y - 5, PANEL_Z],
                       "axis": [0, 1, 0], "holds_tension_n": 0, "holds_shear_n": 0})

    return {
        "algorithm": "lattice",
        "cell_m": 0.01,
        "plasticity": "on",
        "bodies": bodies,
        "joints": joints,
        # The edge: the far long side of the bar, from the grip to the point.
        # 0.2 mm radius is a working edge, not a razor; a 30 degree bevel.
        "blades": [{
            "body": "sword",
            "heel_mm": [290, SWORD_Y, SWORD_Z - 15],
            "tip_mm": [-405, SWORD_Y, SWORD_Z - 15],
            "facing": [0, 0, -1],
            "thickness_mm": 10,
            "edge_radius_mm": 0.2,
            "bevel_deg": 30,
            "grip_mm": [350, SWORD_Y, SWORD_Z],
        }],
    }


# Every room this playground can open, by the name a person would ask for.
SCENES = {
    "bench": room,
    "courtyard": courtyard,
    "armoury": armoury,
}


def describe(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Every object and where it is, in the words the model is asked to use."""
    out = []
    for body in state.get("bodies", []):
        position = body.get("position_m") or [0, 0, 0]
        size = body.get("dimensions_m") or [0, 0, 0]
        out.append({
            "name": body.get("name", ""),
            "material": body.get("material", ""),
            "shape": body.get("shape", ""),
            "position_mm": [round(v * 1000.0, 1) for v in position],
            "size_mm": [round(v * 1000.0, 1) for v in size],
            "anchored": bool(body.get("anchored")),
            "held": bool(body.get("held")),
            "moving_m_s": round(math.sqrt(sum(v * v for v in (body.get("velocity_m_s") or [0, 0, 0]))), 3),
        })
    return out


# ---------------------------------------------------------------------------
# The model's side
# ---------------------------------------------------------------------------

TOOLS = [
    {"type": "function", "name": "list_objects",
     "description": "Every object in the room right now: name, material, shape, "
                    "position in millimetres, size in millimetres, whether it is "
                    "anchored scenery, and how fast it is moving. Call this first "
                    "whenever the answer depends on where anything is.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False,
                    "required": []}},
    {"type": "function", "name": "add_object",
     "description": "Put a new object in the room. Use it for 'drop a ...', "
                    "'add a ...', 'put a ... above the ...'. Give it a downward "
                    "speed to make it arrive hard rather than be placed.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "required": ["name", "shape", "material", "size_mm", "position_mm",
                                 "velocity_m_s", "anchored"],
                    "properties": {
                        "name": {"type": "string",
                                 "description": "What a person would call it, like "
                                                "'glass ball' or 'oak plank'."},
                        "shape": {"type": "string", "enum": SHAPES},
                        "material": {"type": "string", "enum": MATERIALS},
                        "size_mm": {"type": "array", "items": {"type": "number"},
                                    "description": "Three numbers. A sphere uses the "
                                                   "first as its diameter."},
                        "position_mm": {"type": "array", "items": {"type": "number"},
                                        "description": "Its centre: x across, y up, "
                                                       "z toward the viewer."},
                        "velocity_m_s": {"type": "array", "items": {"type": "number"},
                                         "description": "How fast it is already going. "
                                                        "[0,0,0] to just place it."},
                        "anchored": {"type": "boolean",
                                     "description": "True makes it scenery: it does not "
                                                    "move and cannot be picked up."}}}},
    {"type": "function", "name": "move_object",
     "description": "Put an existing object somewhere else, at rest.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "required": ["name", "position_mm"],
                    "properties": {"name": {"type": "string"},
                                   "position_mm": {"type": "array",
                                                   "items": {"type": "number"}}}}},
    {"type": "function", "name": "remove_object",
     "description": "Take an object out of the room.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}}}},
    {"type": "function", "name": "clear_room",
     "description": "Empty the room of everything, for building a scene from nothing.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False,
                    "required": []}},
]

GUIDE = """You are the room. Someone is standing in a physics simulation and
talking to you about it. The engine is real: every object is matter with a
material, and it can shatter, dent or bounce depending on what it is and how
hard it is hit.

Axes, in millimetres: x runs left and right, y is up, z runs toward the person.
The floor is y = 0 and things rest ON it, so an object's centre sits at half its
height. Putting something at y = 0 buries half of it.

Call list_objects before answering anything that depends on where things are.
Then make the changes with add_object, move_object, remove_object or clear_room,
and say in one or two plain sentences what you did and what is likely to happen.

The room has a grid of plates to drop things on: every material in the
catalogue, at 20 mm and 40 mm, each bridged between two short iron piers. The
20 mm row is nearer the viewer. There is also a bench of loose objects to pick
up and an iron anvil.

What actually breaks things, measured on this engine and worth knowing:

- A thin brittle plate with a span under it is what shatters. The same plate
  lying flat on the floor is held everywhere and will not break however hard it
  is hit.
- Thickness matters, but not to whether a hit COUNTS -- the bar is the same for
  a 20 mm and an 80 mm plate. It matters to what happens next: measured, a
  120 mm iron ball dropped 1.5 m shatters the 20 mm glass plate and is held by
  the 40 mm one.
- What is doing the hitting matters as much as how fast. A glass plate needs
  4.5 m/s from an iron ball and 6.7 m/s from an aluminium one, because
  aluminium is springier and transmits less of the blow. Iron is the thing to
  reach for when you want something to break.
- Mass does not help. A 111 kg iron ball and a 0.9 kg one arriving at the same
  speed are judged identically, and a heavy thing resting on a plate will never
  break it -- the engine judges the blow, not the load.
- Metals dent rather than shatter, and only when they are hit hard -- tens of
  metres a second, not a hand-drop.
- Rubber bounces about a third of the height it fell. Concrete bounces least.
- Dropping something from higher is the reliable way to make more happen. A
  fall of h metres arrives at sqrt(2*9.81*h) metres a second; to drop something
  from four metres, put it at y = 4000 with no velocity.

Name a thing after what it is actually made of. If you make it out of aluminium
it is an aluminium tile, not a ceramic one, whatever you were asked for -- and
if you could not use the material that was asked for, say which one you used
instead. Every tool call is shown to the person underneath your answer, so an
answer that does not match what you did is one they can see is wrong.

Never claim something broke, dented or bounced. You are arranging the room; the
engine decides what happens, and the person is watching it happen."""


def _bounded(value: Any, low: float, high: float, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number")
    if not math.isfinite(number):
        raise ValueError(f"{what} is not a finite number")
    return max(low, min(high, number))


def _triple(values: Any, low: float, high: float, what: str) -> list[float]:
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError(f"{what} needs three numbers")
    return [_bounded(v, low, high, what) for v in values]


class Room:
    """The room's current bodies, and the tools that change them.

    Held as a plain list of authored bodies rather than as whatever the engine
    last reported, because those are different things: the engine reports pieces
    and dents, and rebuilding a room out of two hundred shards is not what
    anyone means by "add a ball to it".
    """

    def __init__(self, scene: str = "bench") -> None:
        self.scene = scene if scene in SCENES else "bench"
        self.spec = SCENES[self.scene]()

    def bodies(self) -> list[dict[str, Any]]:
        return self.spec["bodies"]

    def checked(self, change):
        """Make a change, and undo it if the engine would not accept the room.

        The same check the world is opened with, run here rather than when the
        room is rebuilt. What matters is WHO gets told. A complaint raised at
        rebuild time arrives after the model's turn has ended, so the person
        reads a validator message about overlapping cells and the model never
        learns it did anything wrong. Raised here, it comes back as the answer
        to the tool call and the model fixes it on the next round.

        That is not hypothetical: the first time this was tried, the model laid
        a tile across two piers overlapping them by 18 cells, the room refused
        to rebuild, and nobody could tell the one thing that could move it.
        """
        before = [dict(body) for body in self.bodies()]
        try:
            note = change()
            # An empty room has nothing to check, and checking it anyway asks
            # the validator about a scene with no bodies -- which it reads as
            # the single-tile lane and complains about a plate nobody mentioned.
            # Emptying is almost always the first half of "clear this and build
            # me ...", and the half that follows is what gets checked.
            if self.bodies():
                fracture_lab.validate({**self.spec,
                                       "bodies": [dict(body) for body in self.bodies()]})
            return note
        except ValueError:
            self.spec["bodies"] = before
            raise

    def find(self, name: str) -> dict[str, Any] | None:
        wanted = str(name or "").strip().lower()
        for body in self.bodies():
            if body["name"].lower() == wanted:
                return body
        # A piece of something is still that something as far as a request goes.
        for body in self.bodies():
            if wanted.startswith(body["name"].lower()):
                return body
        return None

    # -- the tools --------------------------------------------------------
    def add_object(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._add_object(args))

    def _add_object(self, args: dict[str, Any]) -> str:
        if len(self.bodies()) >= LIMITS["objects"]:
            raise ValueError(f"the room already holds {LIMITS['objects']} objects")
        name = str(args.get("name", "")).strip()[:60] or "thing"
        if self.find(name):
            name = f"{name} {sum(1 for b in self.bodies() if b['name'].startswith(name)) + 1}"
        shape = str(args.get("shape", "box"))
        if shape not in SHAPES:
            raise ValueError(f"{shape} is not a shape this room can build")
        material = str(args.get("material", "glass"))
        if material not in MATERIALS:
            raise ValueError(f"{material} is not a material this engine has")
        size = _triple(args.get("size_mm"), *LIMITS["size_mm"], "size_mm")
        if shape == "sphere":
            size = [size[0], size[0], size[0]]
        center = _triple(args.get("position_mm"), *LIMITS["position_mm"], "position_mm")
        speed = _triple(args.get("velocity_m_s") or [0, 0, 0],
                        -LIMITS["speed_m_s"], LIMITS["speed_m_s"], "velocity_m_s")
        self.bodies().append({"name": name, "shape": shape, "material": material,
                              "size_mm": size, "center_mm": center,
                              "velocity_m_s": speed,
                              "anchored": bool(args.get("anchored"))})
        return (f"added {name}, made of {material}, "
                f"{size[0]:.0f}x{size[1]:.0f}x{size[2]:.0f} mm "
                f"at {center[0]:.0f}, {center[1]:.0f}, {center[2]:.0f} mm")

    def move_object(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._move_object(args))

    def _move_object(self, args: dict[str, Any]) -> str:
        body = self.find(args.get("name", ""))
        if body is None:
            raise ValueError(f"there is nothing here called {args.get('name')!r}")
        body["center_mm"] = _triple(args.get("position_mm"), *LIMITS["position_mm"],
                                    "position_mm")
        body["velocity_m_s"] = [0.0, 0.0, 0.0]
        return f"moved {body['name']} to {body['center_mm'][0]:.0f}, " \
               f"{body['center_mm'][1]:.0f}, {body['center_mm'][2]:.0f} mm"

    def remove_object(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._remove_object(args))

    def _remove_object(self, args: dict[str, Any]) -> str:
        body = self.find(args.get("name", ""))
        if body is None:
            raise ValueError(f"there is nothing here called {args.get('name')!r}")
        self.bodies().remove(body)
        return f"removed {body['name']}"

    def clear_room(self, args: dict[str, Any]) -> str:
        return self.checked(lambda: self._clear_room(args))

    def _clear_room(self, _args: dict[str, Any]) -> str:
        count = len(self.bodies())
        self.spec["bodies"] = []
        return f"emptied the room of {count} objects"
