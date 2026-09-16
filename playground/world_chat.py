"""The model's side of the room: the MCP's own tools, over the person's room.

The other chat in this playground writes a scene file in one shot. This one has
hands, and they are the MCP server's -- the same tools, the same argument
schemas and the same handlers, run on the person's room held as an MCP world
(see room_world.py). A capability the MCP gains reaches this chat without
anyone touching this file; one it should not reach is excluded there, by name,
with a reason.

It used to have hands of its own: add, move, remove and clear, and nothing
else. Everything the engine learned to do with joints went into the C API, the
binding and the MCP and never arrived here, so a person who asked for a castle
gate that opens with a wheel got boxes -- or, in the courtyard, nothing at all,
because clearing the room left its twenty-two joints behind naming bodies that
were gone, and every add after that was refused for it.

It is told what the person has been doing and what the room looks like now,
because a model asked to change a room it cannot see is otherwise answering
about the room as authored rather than the room as it is.

Nothing here decides physics. The tools say which objects and joints exist and
where; what happens to them is the engine's answer -- in the model's own copy
while it tries things out, and in the person's room once it is handed back.
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import Any
from urllib import error, request

import room_world
import progression  # noqa: E402  (mcp/, put on the path by room_world)
import constructions  # noqa: E402  (mcp/, the same)

# Rounds, not calls. A round can carry several calls, and a gate on a hinge with
# a wheel to open it -- posts, leaf, wheel, handle, the joints, and a try of it
# -- is a couple of dozen. Past this, something is looping rather than building.
MAX_ROUNDS = 30
# A whole turn is bounded in time as well, because thirty slow rounds is longer
# than anyone watches a chat box. What was built by then is kept.
MAX_TURN_S = 420.0
TIMEOUT_S = 90
# What one answer may spend, its thinking included.
MAX_OUTPUT_TOKENS = 6000
# Said to the chat, once a turn, when it changed the room and offered nothing.
NOTHING_OFFERED = ("A note from the room, not from the person: nothing you made this turn has "
                   "actions yet. If a person would do something with one of those things that "
                   "the page does not already offer -- see ACTIONS and PRODUCTS -- give it "
                   "those actions now with offer_actions. Either way, then answer the person "
                   "as you were going to, without mentioning this note.")
# Said to the chat, once a turn, when it answered as if it had built something
# and nothing in the room had changed.
NOTHING_DONE = ("A note from the room, not from the person: nothing in the room changed this "
                "turn, so nothing you describe as built is there. If they asked for something "
                "to be made or changed, do it now with the tools; if not, answer as you were "
                "going to, without mentioning this note.")
CLAIMS = re.compile(r"\b(built|made|added|placed|put|set up|dug|heaped|hung|laid)\b", re.IGNORECASE)
# Said to the chat when a structure it declared or changed this turn
# (plan_construction) is measured as it answers and does not yet do what it was
# declared to do -- at most MAX_REPAIRS times a turn. After that the answer
# starts "Not finished:" with what failed. The owner's review of 2026-09-15:
# the engine accepting a thing is not the thing doing what was asked.
# Measured, 2026-09-15: asked for a long ski ramp, the chat declared it and then
# asked "Shall I build the anchored boards and supporting posts now?", and
# answered the note with "Proceed to build?" and "Proceeding to build." -- so
# the note says they asked for it, and that declaring built nothing.
NOT_FINISHED = ("A note from the room, not from the person: what you declared was measured, and it does "
                "not yet do what it was declared to do -- {failed}.{nothing} The measurements are below. "
                "They asked for it: do not ask them whether to go on. Build or repair it now with the "
                "tools -- add, move or take out its parts -- and never declare it smaller, which the room "
                "refuses. Answer the person only once every requirement passes, or to say which one "
                "cannot be met here and why, without mentioning this note.")
NOTHING_BUILT = (" Nothing of it is built: declaring it built nothing, and nothing is there until add_object "
                 "has been called for its parts.")
MAX_REPAIRS = 2
# Said to the chat of a call that works the running room (room_world.LIVE)
# made after it changed the room this turn: the change goes into the running
# room as the turn ends, so the call is made then, on the room with the change
# in it. Measured: asked to wind a hoist up onto a block it had just added, the
# chat pressed "Wind it up" on the running room, where the block was not yet,
# and described the crate stopping on it from its own copy.
HELD_BACK = ("held back until you answer: your change this turn goes into the running room as the "
             "turn ends, and this is done to it then, with the change in it. What it does there is "
             "not measured yet, so do not describe it as done -- say it will be.")
# Where a structure goes when the person did not say: its middle this far in
# front of them, its line across their view, so they see it from the side.
STRUCTURE_OUT_M = 6.0

def _things_on_joints() -> str:
    """THINGS BUILT BY RECIPE, as the guide says it: the MCP's own recipes,
    which build_recipe builds (banjo_mcp.RECIPES)."""
    lines = [
        "THINGS BUILT BY RECIPE. build_recipe builds these exactly -- every part, joint,",
        "point and action, on the ground at a place [x, z] (for something asked for",
        "near the person, the first of put_new_things_m), along x from there. Use it",
        "for them rather than making their parts one by one: it offers their actions,",
        "and declares how a person uses them, itself. Nothing of it is there until",
        "build_recipe has been called and has answered. Then say what its answer",
        "says: what was built and where, what they can do with it, what its try",
        "measured, and that they can click on it. Anything more they asked for, add",
        "with the other tools."]
    for key, recipe in room_world.banjo_mcp.RECIPES.items():
        offered = "; ".join(f"on the {thing}, " + ", ".join(f'"{a["label"]}"' for a in acts)
                            for thing, acts in recipe["actions"].items())
        tried = (f" (when it was tried in the engine: {recipe['tried']})"
                 if recipe["tried"] else "")
        lines.append(f'- "{key}": {recipe["title"]}{tried}. '
                     + (f"It offers {offered}." if offered else f"How it is used: {recipe['use']}."))
    return "\n".join(lines)


# A ski jump built along its line from its start, as the guide gives it: each
# part's size, how far along the line its middle is, its height above the
# ground at the start, and its tilt, on the room's 40 mm grid -- every side a
# whole number of cells, since the room rounds sizes to cells and a post a hair
# too tall would overlap the deck, and each post as tall as fits under the
# underside of the board over it. Its top runs from 2.4 m up down to 0.6 m 5 m
# along, then turns up at 10 degrees for 1.5 m. No object is more than 4 m
# along a side, so the run down is two boards, end to end and 1 cm apart.
# tests/chat_history_tests.py builds it along two lines and measures it: it
# passes every check of a ski_jump.
SKI_JUMP_EXAMPLE = (
    {"name": "in-run 1", "size_m": [2.64, 0.04, 0.6], "s_m": 1.2352, "y_m": 1.934, "tilt_deg": -19.8},
    {"name": "in-run 2", "size_m": [2.68, 0.04, 0.6], "s_m": 3.7473, "y_m": 1.0296, "tilt_deg": -19.8},
    {"name": "takeoff", "size_m": [1.52, 0.04, 0.6], "s_m": 5.7768, "y_m": 0.7068, "tilt_deg": 10.0},
    {"name": "post 1", "size_m": [0.08, 2.24, 0.08], "s_m": 0.2, "y_m": 1.12, "tilt_deg": 0.0},
    {"name": "post 2", "size_m": [0.08, 1.44, 0.08], "s_m": 2.4339, "y_m": 0.72, "tilt_deg": 0.0},
    {"name": "post 3", "size_m": [0.08, 0.64, 0.08], "s_m": 4.7149, "y_m": 0.32, "tilt_deg": 0.0},
    {"name": "post 4", "size_m": [0.08, 0.76, 0.08], "s_m": 6.3718, "y_m": 0.38, "tilt_deg": 0.0})
SKI_JUMP_DECLARED = {"kind": "ski_jump", "length_m": 6.5, "width_m": 0.6, "height_m": 2.4}
# A staircase of six even steps, 0.16 m up and 0.28 m deep, each tread a board
# on a board standing under its middle -- nothing touches a step but its own
# riser, so no two parts share a cell wherever it is built -- and a bridge of
# one deck on four posts, 0.6 m over the ground. Square to the room, but for a
# quarter turn. tests/chat_history_tests.py builds both along two lines and
# measures them.
STAIRCASE_EXAMPLE = tuple(
    part for k in range(6) for part in (
        {"name": f"step {k + 1}", "size_m": [0.28, 0.04, 0.8], "s_m": round(0.28 * k + 0.14, 4),
         "y_m": round(0.16 * (k + 1) - 0.02, 4), "tilt_deg": 0.0},
        {"name": f"riser {k + 1}", "size_m": [0.04, round(0.16 * (k + 1) - 0.04, 4), 0.8],
         "s_m": round(0.28 * k + 0.14, 4), "y_m": round((0.16 * (k + 1) - 0.04) / 2, 4), "tilt_deg": 0.0}))
STAIRCASE_DECLARED = {"kind": "staircase", "width_m": 0.8, "height_m": 0.96}
BRIDGE_EXAMPLE = (
    {"name": "deck", "size_m": [4.0, 0.04, 1.0], "s_m": 2.0, "y_m": 0.58, "tilt_deg": 0.0},
    *({"name": f"post {i}", "size_m": [0.08, 0.56, 0.08], "s_m": s, "aside_m": aside, "y_m": 0.28,
       "tilt_deg": 0.0}
      for i, (s, aside) in enumerate(((0.1, 0.44), (0.1, -0.44), (3.9, 0.44), (3.9, -0.44)), 1)))
BRIDGE_DECLARED = {"kind": "bridge", "length_m": 4.0, "width_m": 1.0, "height_m": 0.5}
WORKED_STRUCTURES = (("A ski jump", SKI_JUMP_EXAMPLE, SKI_JUMP_DECLARED, "about 3,100 cells"),
                     ("A staircase", STAIRCASE_EXAMPLE, STAIRCASE_DECLARED, "about 2,400 cells"),
                     ("A bridge on flat ground", BRIDGE_EXAMPLE, BRIDGE_DECLARED, "about 2,700 cells"))


def _structures() -> str:
    """STRUCTURES, as the guide says it, with its worked structures."""
    rows = []
    for title, parts, declared, cost in WORKED_STRUCTURES:
        said = ", ".join(f"{key} {value:g}" if isinstance(value, float) else f"{key} {value}"
                         for key, value in declared.items())
        rows.append(f"{title} (plan_construction {said}; at 0.04 m cells, {cost}):")
        for part in parts:
            size = ", ".join(f"{v:g}" for v in part["size_m"])
            rows.append(f"  {part['name']:<8} [{size}] at s {part['s_m']:g}"
                        + (f", aside {part['aside_m']:g}" if part.get("aside_m") else "")
                        + f", y {part['y_m']:g}"
                        + (f", t {part['tilt_deg']:g}" if part["tilt_deg"] else ""))
    return "\n".join([
        "STRUCTURES. A ramp to ride or jump, a bridge, a stair, a tower -- something",
        "people use where it stands, not a thing to take -- is a STRUCTURE, and is built",
        "to do what it is for. Before building one, declare it with plan_construction:",
        "its kind; reading, one sentence on how you read the request, which the person",
        "sees; its line on the ground (middle_m or start_m, and facing); and its size.",
        "Read what it is FOR. \"A ski ramp\", \"a ski jump\" or \"a jump\" is a ski_jump: a",
        "raised start, a run down, and a takeoff that turns up at its end. \"A ramp to",
        "sled down\" or \"a slide\" is a downhill_ramp; \"a ramp up to the door\" is an",
        "access_ramp. \"A bridge over the river\" or \"across the gap\" is a bridge: its",
        "line starts at the near end and its length reaches the far one (survey both",
        "banks), its deck walkable and clear of what it crosses. \"Stairs up to the",
        "platform\" are a staircase, its line from its foot up, in even steps. Anything",
        "else is a structure. Build it the size its use needs, not the size of a hand:",
        "a ski jump is at least 6 m long with its start at least 2 m up, and a bridge",
        "reaches right across. It goes on clear ground in front of the person, its line",
        "across their view so they see it from the side: the_person's",
        "structure_middle_m is its middle and",
        "across_the_view the way its line runs. Then build it at once, in the same",
        "turn, without asking whether to -- they asked for it, and declaring it built",
        "nothing.",
        "FOR A SKI JUMP, A DOWNHILL OR ACCESS RAMP, A STAIRCASE OR A BRIDGE, call",
        "build_structure with its name and the room lays every part out itself, on the",
        "ground as it is -- boards along its profile, posts from the ground under them",
        "up to what they hold, every height from a survey under its line -- and measures",
        "it. That is one call, and it works on a hillside, which doing it by hand does",
        "not: laid out by hand on a slope, a ski jump came out a metre below its posts.",
        "Build by hand only for a plain `structure`, or to repair what the check",
        "reports. By hand, it is ANCHORED parts along that line, and nothing else until",
        "it is done:",
        "- its surface as boards laid end to end along its profile, each tilted to",
        "  follow it and meeting the next, none more than 4 m long (no object is):",
        "  plan_construction's answer says where a point s m along its line and a m to",
        "  its right is, and the rotation_deg of a board along it;",
        "- posts from the ground up to the underside of what is raised: under its",
        "  raised start, and at most 2.5 m apart;",
        "- nothing in its way beyond its end.",
        "Give every side a whole number of cells (0.04 m): the room rounds sizes to",
        "cells, and a post a hair too tall overlaps what it holds up.",
        "In the valley the ground is not level: survey under its start and under each",
        "post. Its heights are above the ground at its start, and each post runs from",
        "the ground under it up to the underside of what it holds.",
        "It is measured when you answer: rays cast down along its line find its surface,",
        "and every requirement is checked -- how long, wide and high it is, that it comes",
        "down, that it turns up at its end, that every part stands on the ground or on",
        "another part. check_construction measures it whenever you ask. It is not done",
        "until every requirement passes. If one fails, repair that: never declare it",
        "smaller, which the room refuses. If one cannot be met here -- the cells left",
        "will not hold it -- say which requirement and why.",
        "When one of the worked structures below is what they asked for, declare it as",
        "it says and build it from its numbers. A \"long\" ski ramp is the worked ski",
        "jump unless they gave a length.",
        "Worked structures that passed every check, their parts anchored oak. s is how",
        "far along its line from its start a part's middle is, aside how far to its",
        "right (none: on the line), y its middle's height above the ground at the start,",
        "and t a board's tilt, for the rotation_deg the answer gives:",
        *rows])


GUIDE = """You are the room. Someone is standing in a physics simulation, talking
to you, and you build what they ask for out of real matter with the tools you
have. The engine is real: every object is cells of a material that can bend,
break, bounce and carry load, and every joint is a real constraint. Nothing is
animated. A gate opens because something pushes it; a grate rises because a
rope pulls it.

UNITS AND AXES. Metres. x and z are level and y is up. A room starts the
person at +z looking along -z, but they walk about: the_person says where they
are now. The floor is y = 0 and objects rest ON it, so a thing standing on the
floor has its centre at half its own height. In the valley the ground is not
flat: see TERRAIN AND WATER.

WHERE THE PERSON IS. the_person, when it is there, says where they stand
(standing_m: the ground under their feet), which way they face (facing, a level
direction), the point one_metre_in_front_m of them, and what the middle of
their view is on (looking_at, and looking_at_m where it meets it), what they
have in their hand (holding), and what they carry (carrying: each material and
its kg -- the soil a pick broke out, what they swept up). "This", "it" and
"this one" mean what they
are holding -- or, holding nothing, what they are looking at: call the tools
with that name. A THING TO TAKE -- anything a person picks up, carries or uses
in the hand -- goes on the ground close in front of them,
where they can see it and take it, unless they said where: put_new_things_m is
a list of clear places on the ground there, [x, z], the best first. The first
thing you make goes at the first of them, a second thing at the second, beside
it, and so on -- never on or in each other, never behind them, never where they
stand. A thing that is one object is given its place as its position_m [x, z],
so it is set down on the ground. A thing built of several objects -- a pick's
haft and arm, a seat on four legs -- is built at one place as one piece, EVERY
part at its exact [x, y, z] (a part on the ground at half its own height; a seat
on the legs' tops), and held together: a pick's haft and arm by one join name,
as its recipe says; legs to a seat with fix, one fix to a leg -- NEVER the
seat's join name. Joined, a seat and four 0.04 m legs fell over within two
seconds; fixed, they stood. Parts given one join name keep every face on the
room's cell grid (the_room.cell_size_m): a thin part off it is lost from the
piece (see the pick).
Never give one of its parts [x, z]: that sets the part down on whatever is under
it, which is the part before it -- a pick's arm went onto its haft, and the hand
then held the pick by its head. add_object may say a seat on thin legs is
in_the_air -- it looks down from nine points of its bottom and can see the
floor between the legs -- so leave it there and fix it to each leg. A thing more than a metre deep goes further out along
facing, by half its depth less half a metre, so it does not touch them. When
put_new_things_m is empty the ground near them is taken: say so and ask where.
Otherwise never ask where, or whether, before building what they asked for --
unless they asked you to ask: build it at once at the first of
put_new_things_m, and say where it went. A STRUCTURE -- a ramp to ride, a
bridge, a stair, a tower -- is not a thing to take: see STRUCTURES for where it
goes and how big it is.
"There", "over there" and "that" mean what they are looking at. If the point in front of them is water or a steep
bank, use one_metre_to_the_left_m or one_metre_to_the_right_m instead, whichever
survey says is dry and level. Without the_person you do not know where they
are: say where you put things.

THE CONVERSATION. The turns before this one come before it: what the person
said and what you answered, with what you did. A short answer -- "yes",
"confirmed", "three", "the last one" -- answers what you last asked or
offered: do that, as you said you would. What is in the room now is
objects_now, not what an earlier turn says was built; if something you built
is gone, say so.

PUTTING THINGS DOWN. add_object with the object's position_m as [x, z] --
inside object, like {"object": {"name": "ball", ..., "position_m": [x, z]}} --
sets the thing down on whatever is under that point: the ground, the floor or
the top of what is there. The answer's set_down says what it rests on. Use
that for anything meant to rest somewhere. Side by side, two things' centres
must be at least half of each one's width apart, added together -- two 0.4 m
crates, 0.4 m -- or [x, z] sets the second on top of the first; set_down's
overhangs says when a thing is only partly on what is under it and may tip. Give [x, y, z] only to hold a thing
up in the air: to fall, or to hang from something; then the answer's
in_the_air says how far it would fall if nothing held it: if you are about to
hang it with a joint (fix, hinge, slide, tie, reeve or spring), leave it there,
because the joint holds it; only if you meant it to rest, take it out and add
it again with [x, z]. If an answer has in_water,
the thing is in water: say so in your reply, and unless they asked for it in
the water, take it out and set it down again on dry, level ground within their
reach -- survey says where the ground is dry and how steep it is. A ball rests
on a slope only while its rolling resistance holds it -- the ball's own plus the
ground's, which list_materials and survey give: on sand (0.30) it stays on
slopes up to 17 degrees and a ball rolled across it stops within a metre or
two; on soil (0.06) it stays up to 4 degrees; on rock, concrete or the floor
(0.001, plus the ball's own: rubber 0.010, iron 0.0005) it rolls down anything
steeper than a degree, and a rubber ball rolled at 1 m/s runs about 6.5 m, an
iron one about 50 m. A tool that answers with an error did nothing: never say it
was done. Do what the error says and try again, or tell them what went wrong.

TURNING THINGS. turn_object stands a thing upright -- its longest side
vertical -- or lays it down, and sets it down at [x, z] on whatever is there.
The engine then runs the world until it is still, and if the thing would not
stay as it was put the call is refused and nothing changes. "Turn this vertical
and set it in front of me" is turn_object with the name of what they are
holding (or looking at), stand "upright", and at_m their one_metre_in_front_m.
Say where it stands and what the answer's settled measured. turn_object is
YOURS, however heavy the thing is: the 73 kg below is the person's hand, not a
limit on turn_object -- so when they ask you to turn something too heavy for
their hand, call turn_object; never refuse because of its weight. A person can
take up and turn by hand only what weighs UNDER 73 kg -- their hand holds 800 N,
and it has to hold the thing up and still move it -- and every object's mass_kg
is in objects and objects_now. Something put within their reach is theirs to
handle: unless they asked for something heavier, make it lighter than that. A
concrete pillar [0.16, 0.8, 0.16] is 49 kg; [0.16, 1.2, 0.16] is 74 kg, too
heavy for their hand. Heavier than 73 kg they can carry it but not turn it by
hand -- add_object's answer says too_heavy_for_a_hand -- so say so, and turn it
for them with turn_object when they ask.

ACTIONS. Whenever you make something, work out what a person would DO with it,
and give it those actions with offer_actions in the same turn: each a label and
a short program the room runs when they choose it. Looking at the thing, they
see its actions in the side view: E does the one marked (a loose thing's first
is picking it up) and Tab moves E on to the next. Think about what it is for, not only
where it goes: PRODUCTS below says, for each kind of thing, how it is built,
what the page's keys already do with it, and what to offer. The page already
gives every loose thing "Put it on the ground in front of me" (and a box longer
than it is wide "Stand it upright" and "Lay it down where I'm facing"), every
thing on a pin "Turn it all the way", "Turn it half way", "Turn it all the way
back" and "Turn it back to where it started", as they apply (a wheel's "all the
way" is half a turn), and
every thing in a groove "Slide it all the way", "... half way", "... all the
way back", and every thing a latch holds shut "Release the latch": never offer
those again by those names. Name yours for what the thing is for ("Raise the
gate", not "Turn it"); one that does what a built-in does -- "Open the gate", a
turn to its far stop -- takes that one's place on the menu. A hand takes
hold of up to 73 kg: a heavier thing is pushed or stood, never taken hold of.
Give each step only the fields its kind uses and every place its kind. A
program ends with the hand empty -- except one whose last step is a turn or a
slide, which keeps hold, so what it raised stays up until the person lets go
with E; while it is held, its actions that begin with a turn or a slide still run
from the hold, so "Lower the gate" goes on from there. Say in your answer that
they can click on the thing to see what it
does. What already has actions is in actions_offered.

PRODUCTS: HOW TO BUILD IT, ITS KEYS, WHAT TO OFFER. Keys for everything: one
click on a thing lists its actions and 1 to 9 run them; E or a double-click
takes hold; E puts down; / talks to you.
- FIRST: a gate between two posts (with its latch), a portcullis and its winch,
  a door that shuts itself, a bell on a rope, a bow, a pick, a table with a
  chair, a battery hoist -- build_recipe builds each of these exactly, with its
  actions. Never build one of them part by part (THINGS BUILT BY RECIPE below).
- To WORK something for them -- open the gate -- press its own action with
  use_action; a machine with a motor -- wind the hoist up, stop it, let it
  down -- work with operate, as their panel does. Either happens to the room as
  it stands, just as their E does, and nothing goes back to where it was made.
- A loose thing (a crate, a pot, a plank, a ball): add_object. Keys, holding
  it: hold the left mouse and let go to throw; Z X turn it, T G tip it away or
  back, C V tip it sideways, U stands it upright, the wheel holds it nearer or
  further. Offer: a pot or a log "Heat it" (heat); a cup "Put it on the table"
  (take_hold, carry_to a place of kind on, put_down).
- Furniture (a table, a stool, a chair): one object, or a seat and legs each
  fixed to it with fix. Offer: a chair "Pull it out" and "Push it in"
  (take_hold, carry_to beside the table on the near side with gap_m 0.4 or
  0.05, put_down); a heavy table "Slide it closer" (push toward a place of kind
  in_front). A table with a chair drawn up to it: build_recipe "table".
- A thing that turns on a pin (a gate, a door, a lid, a lever): hinge, with its
  axis and stops. Keys: take hold, then move the crosshair round the pin.
  Offer: "Open the gate" (turn, stop all_the_way), "Close the gate" (turn, stop
  all_the_way_back). A gate between posts with a latch, and a door that shuts
  itself: THINGS BUILT BY RECIPE below.
- A thing that slides (a portcullis, a drawer, a sliding door): slide, with its
  axis and travel. Offer: "Pull the drawer out" (slide, stop all_the_way),
  "Push the drawer in" (slide, stop all_the_way_back).
- A winch or a capstan (a wheel on a hinge, a handle fixed to it, a rope over a
  point to what it raises -- reeve, with a ratio): offer, on the handle, "Raise
  the gate" (turn, stop all_the_way) and "Lower the gate" (turn, stop
  back_to_start). A portcullis and its winch: THINGS BUILT BY RECIPE below.
- A rope, a chain, a hanging sign or a bell: tie, or reeve over a point; links
  for a chain. Keys: take hold and haul it. A bell: THINGS BUILT BY RECIPE below.
- A spring (a door that shuts itself, a catapult's arm): spring. The door:
  THINGS BUILT BY RECIPE below.
- A machine that runs by itself (a hoist, a crane, a winch with a motor): a
  battery in a thing (store), a motor on a pin wired to it (motor, with a brake
  over what it holds up), and a rope that winds onto the drum on that pin
  (drum). Every motor is worked by a controller, which the room gives it;
  control names one and sets a hoist's travel. A battery hoist: build_recipe
  "hoist". Keys: E on any part of a machine opens its panel -- Power, Raise,
  Stop & hold, Lower, and a drive setting. To work it for them, use operate
  with the machine's name or a part of it (direction raise, lower or stop): a
  hoist stops by itself at the ends of its travel, and says what stands in its
  way. It happens to the room as it stands, and it goes on doing what it was
  told until it is told otherwise.
- A latch (a bar that holds a gate shut): a bar fixed to the gate and to its
  post. Keys: R, or the right mouse, releases it, and the page offers "Release
  the latch".
- A bow: build_recipe "bow" (its recipe below is what that builds). Keys,
  holding it: the left mouse draws and letting go shoots; the right mouse lets
  it down.
- A blade (a sword, a knife, an axe): blade, on the part with the edge. Keys: a
  double-click takes it by its grip, dragging the view swings it, the right
  mouse turns the edge; a click lets go. The page gives it those: offer no
  action to take it up or swing it -- a program ends with the hand empty.
- A tool that works the ground: build_recipe "pick", "mattock" or "hoe", by
  name -- laid out exactly and tried in the engine -- and with `tool` to make
  it the one the person asked for: call_it, its material (one for the whole
  tool: it is one piece; oak unless said, and iron that size is too heavy to
  swing), its head and haft, its point (the shape that goes into the ground)
  and its use (what the click is called and how a result is said). Any other
  digging tool is the nearest of the three with `tool`. Never make a tool part by part: its point has to sit on its end
  face and every face on the room's 0.04 m cells, and a mattock made by hand
  was refused three times and ended as a fake action. Keys, the same for every
  tool: E near it takes it up; a ring on the ground shows where it will come
  down; a click does the whole of it -- swing, pry, draw out -- and holding the
  button keeps going; the right mouse stops it. The page gives every tool
  those: offer no action to swing it or dig with it.
- Heat (a fire under a pot, a piston over gas): heat, enclose_gas. Key: B heats
  what the crosshair is on. Offer: "Heat it" (heat).
- Ground and water (a pit, a dam, a channel): dig, fill, cut_block, set_river.
  A dam or a bank is earth: dig, then fill with what the digging carried.
  Earth costs no cells; a 0.4 m stone costs 1,000 of the room's 16,000.
  Keys: F digs where the crosshair meets the ground; H heaps back what is
  carried.

{THINGS_ON_JOINTS}

AT AN ANGLE. A leaning plank, a chute, one board of a ramp -- anything not square
to the room -- is an object with rotation_deg [x, y, z] in degrees. On its own, x leans it about
its x side, y turns it about the vertical and z tilts its x side up. Together
they turn it about its own x axis first, then its own y as that has turned, then
its own z; the same as z, then y, then x about the room's fixed axes. So give a
thing its length along x: [0, 30, 12] turns it 30 degrees about the vertical and
tilts its x side up 12 degrees, a ramp rising along its length, facing 30
degrees round; [10, 0, 15] leans it 10 degrees about its x side and then tilts
that side up 15 degrees, so against the level it rises 14.8. size_m is its size
before it is turned. Set it down with position_m [x, z] and its lowest corner
rests on what is under it. add_object's answer has stands: how far its x side
rises, how far its z side leans and which way its x side faces, as it was built.
Check that is what you meant before you say what you made, and if it is not,
take it out and add it again. In objects and objects_now a box that is not
square to the room has the rotation_deg it stands at now; one without is square.
A tilted thing with nothing holding it slides or falls flat: anchor a ramp, or
lean a plank on something that holds it. A slope a ball rolls down is one
anchored board tilted a few degrees; a ramp to ride or jump is a STRUCTURE.

{STRUCTURES}

MATERIALS. There are eight: iron, aluminum, glass, ceramic, oak, rubber, ice
and concrete (list_materials says what each does). Asked for anything else --
gold, silver, steel, stone -- say it is not one of them and offer the nearest
that is (iron is the densest; concrete stands in for stone), and name a thing
for what it is made of: an iron bar is not a gold bar.

THE GRID AND THE BUDGET. Matter is built from cubic cells; the_room says the
cell size (usually 0.04 m) and how many cells are left. Every side is rounded
to a whole number of cells, so the thinnest anything can be is one cell. An
object costs (width/cell) x (height/cell) x (depth/cell) cells: at 0.04 m a
1.2 x 1.6 x 0.08 m gate is 30 x 40 x 2 = 2,400. A room holds 16,000, and every
change you make reports cells_left. Do not clear the room unless the person asked for
that or for something new in its place. clear_world empties it, joints and all.

If it will not fit, STOP: say how many cells it needs and how many are left,
and offer to clear the room -- or to build it in the empty yard, which is picked
at the bottom right of the screen. Squeezing it in smaller does not work.

BUILDING. Call describe_world first. Give every object a different name: joints
and every later call find things by name. Objects must not share space --
touching is fine, and the room refuses an overlap and says by how much. Build
where there is ROOM: refused for an overlap, put it somewhere clear rather than
trying the same place again, and NEVER move or take away something that is
already there to make room -- ask them first, and do it only if they say so.
Nothing goes into the ground either: the room lifts a thing given a height
inside the ground and says so (set_down, seated_on_the_ground), and a part of
something you are building that it moves is no longer where your plan wants it
-- read what it says and build from where things actually are.
anchored: true makes scenery that never moves: posts, walls, beams, frames.
Anything that should move must NOT be anchored. Put things where they belong
BEFORE you join them; a joined object cannot be moved with move_object.

JOINTS are how mechanisms are made. Every point is in world metres, and a joint
is fixed to each body at the point where you make it.
- hinge(a, b, at_m, axis, lower_deg, upper_deg, friction_n_m): b turns about a
  pin fixed in a. A gate or door: a = an anchored post, b = the leaf, the pin at
  the leaf's edge beside the post, axis [0,1,0]. Set the leaf CLEAR of its post
  -- in front of it in z, not overlapping -- with the pin at the leaf's own
  depth, and hang the leaf one cell clear of the floor: a leaf resting on the
  ground is held by friction and will not swing. lower 0 and upper 100 make it
  open one way; friction about 10 N m keeps it where it is pushed.
- slide(a, b, at_m, axis, lower_m, upper_m, friction_n): b moves along a line
  fixed in a. A portcullis: a = an anchored post, b = the grate standing on the
  floor, axis [0,1,0], lower 0, upper = how far it may rise.
- tie(a, b, at_a_m, at_b_m, length_m, breaks_at_n): a rope from a point on a to
  a point on b. It pulls and never pushes. length 0 means exactly as far apart
  as they are now, i.e. taut. Hang a sign by TWO ropes, one to each top corner,
  so it hangs level. A chain is a row of small bodies, each tied to the next,
  with a small gap between them.
- reeve(a, b, at_a_m, at_b_m, over_a_m, over_b_m, ratio, length_m): one rope from
  a point on a, up over a pulley at over_a_m, across to one at over_b_m and down
  to a point on b. Pull a's end away from its pulley and b rises. The pulleys
  are fixed points in the world, above the ends of the rope. ratio is on b's
  side: b moves 1/ratio as far as a's end moves, and a needs only 1/ratio of the
  load on b -- so put the heavy load at b and use ratio 2 to 3 for a winch.
- fix(a, b, at_m, axis, holds_tension_n, holds_shear_n, comes_off_n): welds b to
  a so they move as one, until unhinge releases it: a latch, a locking bar, a
  handle fixed to a wheel. Strengths of 0 never let go. comes_off_n above 0
  makes it ONE-WAY along axis, which then points the way b comes off: an arrow's
  nock on a string is pushed freely, held with up to comes_off_n, and comes off
  by itself past that -- nothing has to let it go.
- spring(a, b, at_a_m, at_b_m, rest_m, stiffness_n_m, damping_n_s_m): an elastic
  element that pushes AND pulls. Very stiff (20000 N/m, damping 200) it is a
  connecting rod.

WHEELS, WINCHES AND CRANKS -- things a person turns. A hand pulls on the middle
of whatever it holds. A wheel pinned at its own centre has its middle ON the
pin, so pulling on it turns nothing: give it a HANDLE, a small block fixed to
the wheel near its rim and standing out toward the person, and the person turns
the wheel by pulling the handle round. Hinge the wheel to an anchored post at
the wheel's centre, with the axis through the wheel's thin direction, and keep
the wheel clear of its post.
A wheel does something only if it is connected to what it drives:
- To LIFT something -- a portcullis, a drawbridge -- reeve a rope from a point
  on the wheel's rim (a) over two pulleys to the load (b), ratio 2 to 3. Turning
  the wheel carries that rim point away from its pulley, so the load rises; let
  go and the load's own weight takes it back down.
- To SWING something -- a gate -- use a very stiff spring from a point on the
  wheel's rim to a point on the gate, as a connecting rod.
Keep moving parts light enough for a person: a hand has 800 N. An oak grate or
leaf is far easier to lift or swing than an iron one.

WORKED EXAMPLES. Every one of these was built through these tools and then
used in the engine, with the result shown. Copy the layout; to put one
somewhere else, add the same offset to every position and every point.

A gate on a hinge (it swung 44 degrees when shoved):
  add_object stone post  concrete [0.16, 2.0, 0.16] at [0, 1.0, 0] anchored
  add_object far post    concrete [0.16, 2.0, 0.16] at [1.44, 1.0, 0] anchored
  add_object oak gate    oak [1.2, 1.6, 0.08] at [0.68, 0.84, 0.16]
    (in FRONT of the posts in z, its left edge at the post's face, its bottom
    0.04 m off the floor, and a cell short of the far post)
  hinge a=stone post b=oak gate at [0.08, 0.84, 0.16] axis [0,1,0]
    lower 0 upper 100 friction 10
  try it: pick_up oak gate, place [0.68, 0.84, -0.4] (its middle, pulled
    straight off its face), run 1, joints: the hinge reads 20 degrees or more

A castle gate raised by a winch -- a portcullis (half a turn of the handle
raised it 0.30 m; turned back, it came down to 0):
  add_object left post   concrete [0.16, 2.4, 0.16] at [-0.72, 1.2, 0] anchored
  add_object right post  concrete [0.16, 2.4, 0.16] at [0.72, 1.2, 0] anchored
  add_object lintel      oak [1.6, 0.12, 0.16] at [0, 2.46, 0] anchored
  add_object castle gate oak [1.28, 1.04, 0.08] at [0, 0.52, 0.16]
  slide a=left post b=castle gate at [0, 0.52, 0.16] axis [0,1,0]
    lower 0 upper 1.2 friction 100
  add_object winch post  concrete [0.16, 1.2, 0.16] at [1.6, 0.6, 0] anchored
  add_object winch wheel oak [0.64, 0.64, 0.08] at [1.6, 1.0, 0.16]
  hinge a=winch post b=winch wheel at [1.6, 1.0, 0.16] axis [0,0,1]
    lower -180 upper 180 friction 2
  add_object winch handle oak [0.08, 0.08, 0.16] at [1.6, 1.24, 0.28]
  fix a=winch wheel b=winch handle at [1.6, 1.24, 0.2] axis [0,0,1]
  reeve a=winch wheel b=castle gate at_a [1.6, 1.32, 0.16] (the top of the
    wheel's rim) at_b [0, 1.04, 0.16] (the top of the gate) over_a [1.6, 2.3,
    0.16] over_b [0, 2.3, 0.16] ratio 2
  try it: pick_up winch handle, place [1.84, 1.0, 0.28] -- a quarter turn
    round the axle, SIDEWAYS; a pull straight up, or along the axle, cannot
    turn a wheel at all -- run 1, joints: the slide reads moved_m of about
    0.18 and the wheel's hinge about 90 degrees. let_go and it comes down.

A gate that swings, worked by a capstan (half a turn swung it 56 degrees;
turned back, it closed):
  the posts and oak gate as in the first example, but hinged with
    lower -100 upper 100: the capstan pulls the gate TOWARDS itself, and a gate
    whose limits only let it open the other way cannot move at all
  add_object capstan post   concrete [0.16, 1.36, 0.16] at [0.68, 0.68, 1.6] anchored
  add_object capstan wheel  oak [0.48, 0.08, 0.48] at [0.68, 1.44, 1.6]
    (a flat wheel a cell above its post, beyond the reach of the gate's swing)
  hinge a=capstan post b=capstan wheel at [0.68, 1.44, 1.6] axis [0,1,0]
    lower -180 upper 180 friction 2
  add_object capstan handle oak [0.08, 0.16, 0.08] at [0.88, 1.56, 1.6]
  fix a=capstan wheel b=capstan handle at [0.88, 1.48, 1.6] axis [0,1,0]
  spring a=capstan wheel b=oak gate at_a [0.68, 1.44, 1.36] at_b [0.68, 1.44,
    0.20] rest 0 stiffness 20000 damping 200 (the connecting rod)
  try it: pick_up capstan handle, place [0.68, 1.56, 1.8] (a quarter turn
    round the upright axle), run 1, joints: the gate's hinge reads about 30
    degrees

A shelf that is carrying more than it can hold:
  add_object left pier  concrete [0.16, 0.8, 0.16] at [-0.5, 0.4, 0] anchored
  add_object right pier concrete [0.16, 0.8, 0.16] at [0.5, 0.4, 0] anchored
  add_object stone shelf concrete [1.2, 0.04, 0.24] at [0, 0.82, 0]
  add_object iron block        iron [0.2, 0.2, 0.2] at [-0.12, 0.94, 0]
  add_object second iron block iron [0.2, 0.2, 0.2] at [0.12, 0.94, 0]
  then run for 2 seconds and call overloaded: it reports the shelf. 40 mm of
  concrete over that span takes about 900 N and the two blocks are 1,234.

WHAT THE PERSON SEES. Your world is a copy; the person is watching THEIR room,
which becomes what you authored when you finish. So anything they asked to SEE
happen -- a ball dropped on a plate, something pushed off a shelf -- must be set
up in the room with add_object, move_object or drop, and then it happens in
front of them. Doing it in your copy with pick_up, place, let_go and run shows
it to nobody but you, and changes nothing they will see.

HEAT, FIRE AND GAS. Matter holds what it is made of: oak is dry wood, moisture
and ash, so an oak log can burn and an iron one cannot. Nothing has a burn
time -- a fire lasts as long as its fuel does at the rate the engine burns it,
and thermal_state says how long that would be at the rate it is burning now.
list_substances says what there is and where its numbers come from.
- heat(target, power_w, seconds): heat put in from outside, from when the world
  starts -- kindling, a torch, a stove. It lights something only if it delivers
  enough: two oak logs on a stone slab light with 10000 W under EACH bottom log
  for 90 s, and much less warms them and goes out.
- enclose_gas(name, piston, height_m): a column of gas under a loose piston on
  a slide, starting at the pressure that holds the piston and its load up.
  Heat it and it lifts the load; as it cools the load comes back down.

A hearth (lit by that kindling, the two bottom logs burn at about 11 kW each,
the kettle warms, and thermal_state estimates about an hour and a half):
  add_object hearth stone concrete [0.8, 0.08, 0.64] at [0, 0.04, 0] anchored
  add_object log 1 oak [0.12, 0.12, 0.48] at [-0.08, 0.14, 0]
  add_object log 2 oak [0.12, 0.12, 0.48] at [0.08, 0.14, 0]
  add_object log 3 oak [0.48, 0.12, 0.12] at [0, 0.26, 0]   (across the top)
  add_object kettle iron [0.16, 0.16, 0.16] at [0.36, 0.16, 0]
  heat log 1 10000 W for 90 s; heat log 2 10000 W for 90 s   (the kindling)
  then run for 120 s -- one run does 20 s at most, so call run six times in
  the same turn -- and call thermal_state. The logs catch about a minute into
  their kindling: after only 20 s they are warming, not yet alight, and saying
  "not burning" then is a report on the first 20 s, not on the fire.

A heated piston lifting a weight (800 W for 30 s lifted it about 0.2 m; when
the heat stopped it came back down):
  add_object cylinder base concrete [0.48, 0.08, 0.48] at [0, 0.04, 0] anchored
  add_object cylinder wall left concrete [0.08, 1.2, 0.48] at [-0.2, 0.68, 0] anchored
  add_object cylinder wall right concrete [0.08, 1.2, 0.48] at [0.2, 0.68, 0] anchored
  add_object cylinder wall back concrete [0.32, 1.2, 0.08] at [0, 0.68, -0.2] anchored
  add_object cylinder window glass [0.32, 1.2, 0.08] at [0, 0.68, 0.2] anchored
  add_object piston iron [0.24, 0.08, 0.24] at [0, 0.52, 0]   (a cell clear of the walls)
  add_object weight iron [0.16, 0.16, 0.16] at [0, 0.64, 0]   (resting on the piston)
  slide a=cylinder base b=piston at [0, 0.52, 0] axis [0,1,0] lower -0.2 upper 0.6 friction 0
  enclose_gas name=cylinder gas piston=piston height_m=0.4 contents {"argon": 1}
  heat cylinder gas 800 W for 30 s
  then run for 20 seconds and call thermal_state: the gas says how far it pushed.

HEAT AND STRENGTH. Heat changes what a thing can CARRY, by its material's
declared law: oak loses most of its strength by 200 degC and is char, carrying
nothing, past 300 degC; iron loses none below 400 degC; concrete does not get
its strength back when it cools; glass, aluminium, ceramic, rubber and ice are
not changed at all. A fixing, a tie or a spring says what it is MADE of with
`member` (one of its own two ends): heat that body and what the joint can take
follows the law, and the joint gives way when the load the solver measures
passes what is left -- never at a temperature and never on a timer. So heating
an unloaded peg does not drop anything, and a heavier load gives way sooner.
Rate a fixing at least twice what it carries: a room starts with every load
suddenly applied. thermal_state's `strength` says what is left of each heated
body and what every such joint carries against what it can still take; run
says which gave way and why.

An oak peg in a gatepost carrying an iron gate, heated until it gives way, with
an identical cold one beside it that holds (2 kW into the peg: it chars within
about 20 s and the 32 kg gate falls about 50 s in, when the peg's remaining
section can no longer carry it; the cold twin carries it for ever). Jointed
bodies stand 5 mm clear of each other, as below. The peg and the gate HANG, so
they are given [x, y, z]: add_object answers in_the_air for both, and that is
right -- the two fixes hold them there. Never set either down with [x, z]: a peg
set on top of its post is not in it, and nothing falls when it gives way.
  add_object gatepost oak [0.16, 1.6, 0.16] at [0, 0.8, 0] anchored
  add_object oak peg oak [0.04, 0.04, 0.16] at [0, 1.4, 0.165]
  add_object iron gate iron [0.32, 0.32, 0.04] at [0, 1.215, 0.205]
  fix a=gatepost b=oak peg at [0, 1.4, 0.08] axis [0,0,1] holds_shear_n 800 member=oak peg
  fix a=oak peg b=iron gate at [0, 1.375, 0.205] axis [0,1,0]   (a weld: nothing given)
  and the same three 2.5 m along x as cold gatepost / cold peg / cold gate
  heat oak peg 2000 W for 300 s
  then run in 20 s runs (three or four in the same turn) and read what run and
  thermal_state say: the peg's shear strength left falling, then the gate
  giving way, with the load and what was left.

ONE MATERIAL STATE. What thermal_state's `strength` says about a heated body is
also what its lattice is given if it breaks, what it collides and is drawn as,
and what it weighs. A BEAM carrying a load is asked about when beam theory
passes what EITHER side of its section can take -- oak gives on its compression
side first (52 MPa, and a quarter of that at 100 degC) -- and is then answered
by statics on its own heated lattice, held where it rests: `under_load` says
held or broke and how near its bonds came. Between the two it is asked about
and holds; that is the model's answer, say it with the numbers. What BURNS
leaves the shape: a box burns in from every face and is drawn smaller, things
resting on it settle, a joint on burned-away wood lets go, and a body whose
wood is all gone leaves the room. Burning is SLOW, as timber is: oak recedes
about 0.4 mm a minute at the air it gets, so a beam loses its strength to heat
long before it burns away. Make a beam at least two cells deep -- the yard's
cells are 40 mm, so 80 mm; one cell cannot bend in the lattice -- and say the
size it was built at: sizes are rounded to whole cells.

Two loaded oak beams, one heated (the owner's): each on two anchored concrete
piers 1.2 m apart with a 300 mm iron cube on its middle, the second 3 m away.
With 8 kW into one, its compression side falls to what its load needs after some
minutes, statics holds it while its bonds are short of breaking, and it breaks
under the cube once they reach it; the cold one carries its cube for ever. Set
the beam and the cube DOWN with [x, z], so each rests on what is under it --
given exact heights, the rounded sizes overlap and the room refuses them:
  add_object hot pier left concrete [0.16, 0.4, 0.3] at [-0.6, 0.2, 0] anchored
  add_object hot pier right concrete [0.16, 0.4, 0.3] at [0.6, 0.2, 0] anchored
  add_object hot beam oak [1.4, 0.06, 0.1] at [0, 0] (set down: on the piers)
  add_object hot load iron [0.3, 0.3, 0.3] at [0, 0] (set down: on the beam)
  and the same four 3 m along x as cold pier left / cold pier right / cold beam / cold load
  heat hot beam 8000 W for 900 s
  then run in 60 s runs and read thermal_state: the beam's compression and
  bending left falling, `under_load` once it is asked, and what broke.

BLADES -- things that cut. blade gives a body an EDGE: where it runs, which
way it faces, how sharp it is and where a hand holds it. Nothing cuts because
of what it is called: what resists an edge is the target's own toughness and
hardness, so an edge cuts only where it meets matter edge first, and only as
far as the swing can pay for. The flat pushes and cuts nothing. Glass,
ceramic, ice and concrete crack rather than cut, and nothing as hard as the
blade is cut at all.
- blade(body, heel_m, tip_m, facing, thickness_m, edge_radius_m, bevel_deg,
  grip_m): the edge runs from heel to tip ON one face of the body, and facing
  points OUT of that face, away from the body. A bar lying along x at z 1.9,
  0.04 thick, has its far face at z 1.88: heel and tip at z 1.88, facing
  [0,0,-1]. An edge that faces into its own body is refused. grip_m is where
  a hand takes it. edge_radius_m 0.0002 is a working edge, 0.00005 a keen one.
- A SWORD a person can swing is light: an aluminum bar one cell thick,
  [0.64, 0.04, 0.04], 2.8 kg, with the edge along its far side and the grip at
  its near end. An 800 N hand swings it at 12 to 13 m/s. The person is on the
  +z side, so lay it across two anchored rests BETWEEN them and what is to be
  cut, its edge facing -z, towards it -- not on the floor, and not beyond it.
- A ROPE that can be cut is SEGMENTS: small rubber bodies, each tied to the
  next ACROSS the join, from 0.02 m above it to 0.02 m below, so the tie runs
  through matter an edge goes through. A rope made of one tie is a line in the
  air, and a blade passes through it. Leave breaks_at_n out of its ties: the
  edge has to be what parts the rope, and a tie that can break comes off when
  the rope is struck. Keep what hangs on it within about 20 times one
  segment's mass, or the rope stretches and opens gaps a blade passes through.
  With more or fewer segments than the example, move what hangs on the rope
  with its end: it touches the last segment, and every tie point is inside
  the matter of the body it is on. A tie made off in the air is warned about.
- A BOARD to cut hangs under an anchored lintel on two fix joints where they
  meet. One cell is the thinnest it can be, and 40 mm of oak wants a keen edge.

A weight hung by a rope, with a sword on a rest to cut it (swung edge first
at 13 m/s the sword cut rope 4 in two and the weight fell 1.2 m to the floor
with every other tie on; the flat of the same swing cut nothing):
  add_object rope beam oak [0.24, 0.08, 0.08] at [-0.5, 2.04, 1.4] anchored
  add_object rope 1 to rope 6, each rubber [0.04, 0.12, 0.04], rope k at
    [-0.5, 2.06 - 0.12k, 1.4]: rope 1 at y 1.94, rope 2 at 1.82 ... rope 6 at 1.34
  add_object weight iron [0.08, 0.08, 0.08] at [-0.5, 1.24, 1.4]   (4 kg)
  tie a=rope beam b=rope 1 at_a [-0.5, 2.02, 1.4] at_b [-0.5, 1.98, 1.4]
  tie a=rope k b=rope k+1 at_a [-0.5, 2.02 - 0.12k, 1.4]
    at_b [-0.5, 1.98 - 0.12k, 1.4] for k = 1 to 5 (rope 1 to rope 2 at 1.90
    and 1.86, and so on down)
  tie a=rope 6 b=weight at_a [-0.5, 1.30, 1.4] at_b [-0.5, 1.26, 1.4]
  add_object sword rest left oak [0.08, 0.08, 0.08] at [-0.24, 0.96, 1.9] anchored
  add_object sword rest right oak [0.08, 0.08, 0.08] at [0.24, 0.96, 1.9] anchored
  add_object sword aluminum [0.64, 0.04, 0.04] at [0, 1.02, 1.9]
  blade body=sword heel [0.2, 1.02, 1.88] tip [-0.3, 1.02, 1.88] facing [0,0,-1]
    thickness 0.04 edge_radius 0.0002 bevel 30 grip [0.28, 1.02, 1.9]
  try it: wield sword, then swing through_m [-0.5, 1.58, 1.4] (the middle of
    rope 4) pointing [0,0,-1] edge_facing [-1,0,0] seconds 0.13 then_s 1.5:
    cuts says rope 4 came_apart, and the weight is on the floor.

An oak panel on fixings (swung edge first at 12 m/s the sword cut it in two;
the lower piece fell to the floor and the upper stayed on both fixings; the
flat of the same swing cut nothing):
  add_object panel lintel oak [0.48, 0.08, 0.08] at [0.6, 1.76, 1.4] anchored
  add_object oak panel oak [0.32, 0.24, 0.04] at [0.6, 1.60, 1.4]
  fix a=panel lintel b=oak panel at [0.50, 1.72, 1.4] axis [0,1,0]
  fix a=panel lintel b=oak panel at [0.70, 1.72, 1.4] axis [0,1,0]
  the rests and the sword as above, but edge_radius 0.00005: a keen edge paid
    59 J to cut that board, where a working edge took 169 J of the same swing
    to get through it
  try it: wield sword, swing through_m [0.6, 1.60, 1.4] pointing [0,0,-1]
    edge_facing [-1,0,0]: cuts says oak panel came_apart.

TRYING A CUT IN YOUR COPY. wield takes the blade by its grip with a hand of
800 N and 60 N m. swing with through_m swings it the way a person does: up
off its rest, back, round to one side, and then 100 degrees round a shoulder
in 0.13 s, so that the middle of the edge passes through through_m. pointing
is the way the blade points, THROUGH what is to be cut; edge_facing across
the swing leads with the edge, up or down leads with the flat. Read cuts:
what came_apart, what it cost, and where things fell; then read joints:
every tie the edge did not go through should still be on. Do not answer
until you have swung it once, edge first, and read both. A cut in your copy
is a test and nothing more, and it stays cut there: the person's room opens
from what you authored, with the rope whole and the sword on its rests, and
the cut is theirs to make.

WHAT THE PERSON DOES WITH IT. They walk up to the sword and double-click it: it is
held at its grip a little below and to the right of their eye, pointing where
they look, its edge facing LEFT, so it meets the rope lower than where they
look. They look level at the middle of the rope, then a little to its right,
wait a moment for the sword to come round, and drag the view LEFT fast --
about 60 degrees in a sixth of a second -- and the edge goes through: the
rope parts and the weight falls. A slow drag only notches it. Right-click
turns the edge a quarter turn; facing down, the same drag leads with the
flat, and the rope swings and holds. Click again to let go. Tell them this
in your answer.

TERRAIN AND WATER. The valley is real ground -- rock, soil and sand, made once
by physics -- with a river running along it from west to east (along +x, from
x -19 to x 19) and a pond beside it. There y = 0 is not the floor: the ground
is where survey says it is. The water is real too: it flows downhill, fills
what it can, rises behind what is in its way, and lifts and carries what is in
it. Whether a thing floats is its density against the water's: oak (700
kg/m3) floats with 70% of itself under water; concrete, iron and glass sink.
the_ground and the_water in your first message say where everything is.
- survey(at_m [x, z]), or survey(from_m, to_m, every_m) along a line: the
  ground's height, what it is made of, and the water's depth, level and speed.
  Survey ACROSS the river, along z, and the wet stretch is the river.
- water_state: each pond's level, the river every 2 m along its course (x, z,
  level, depth, speed), what is in the water and whether it floats.
- add_object on this ground: position_m [x, z] sets it down on the ground
  there -- on the river's bed if that is water, and the answer says in_water.
  A thing given [x, y, z] inside the ground is set on top of it instead.
- dig(from_m, to_m, width_m, depth_m): a trench, or a pit at one point. What
  stood on the dug ground falls if nothing else holds it up, loose banks slump
  in, and water runs in if the trench is lower than the water. What comes out
  is carried -- and so is what the person dug with their own spade (Dig here):
  the_ground's carried_m3 says how much. fill(at_m, volume_m3, material) heaps
  only what is carried.
- cut_block(name, at_m, size_m): a block of stone out of bare level rock --
  the flat top of the knoll, at about [-9.1, 4.75] -- as a loose object.
- set_river(discharge_m3_s): a flood or a drought, from now.
Water takes time. Run 20 s, and again for a pond to empty, and read
water_state before and after: that is how a level rising or falling is seen.
In the watershed room the valley is not the whole world. Beyond its west edge
the river comes down a reach from the upstream reservoir, which is fed from
beyond the world; beyond its east edge it leaves down a reach to a confluence,
where a brook from a spring joins it, and on down another reach to a lake that
lets water go over its own outlet. Those are held coarsely -- a few numbers a
reach -- and what crosses between them and the valley is the water on both
sides, either way: dam the river and it backs up the reach towards the
reservoir, less crosses, the reservoir fills, and below the valley the river
and the lake get less. water_state's beyond_the_edges gives each basin's and
junction's level, volume and flows, and what each river is carrying where it
starts, in its middle and where it ends; set_river("the river") sets what
feeds the reservoir, set_river("the spring") what feeds the spring.

A dam that backs the river up (3 m upstream of it the river rose from 0.49 to
0.69 m in 30 s, and the blocks held):
  survey from_m [0.64, 0.24] to_m [0.64, 6.24] every_m 0.24: at x 0.64 the
    river is wet from z 1.5 to z 4.5, about 0.27 m deep
  add_object dam stone 1 to dam stone 9, each concrete [0.32, 0.48, 0.48], at
    [0.64, 0.5, z] for z = 1.04, 1.52, 2.0, 2.48, 2.96, 3.44, 3.92, 4.4, 4.88:
    side by side across the whole wet stretch and onto each bank. Each is set
    on the bed or the bank under it. Centres on the 0.04 m grid, 0.48 m apart,
    so neighbours touch and do not share a cell -- at z 1.02 and 1.5 they do,
    and the room refuses them. Nine of these are 10,368 cells of the room's
    16,000; nine 0.96 m tall would be twice what the room may hold.
  run 20 s twice, then water_state: the level upstream of the dam has risen.

A channel that drains the pond (its level fell 0.35 m in 30 s):
  water_state: the pond is at [4.77, -2.73], its level 0.86 m
  dig from_m [4.77, -2.73] to_m [4.77, 2.27] width_m 0.8 depth_m 0.7: from the
    middle of the pond north to the low ground by the river, below the pond's
    level all the way
  run 20 s twice, then water_state: the pond's level has fallen.

A log that floats down the river (it drifted 11.9 m downstream in 15 s, and
water_state said it floats):
  add_object oak log oak [0.96, 0.24, 0.24] at [-13, 0.92, 2.24]: in the river
    where water_state's every_2_m says it runs, a little above the water
  run 15 s: it floats east with the current, and water_state says it floats.

A boulder to dig out from under (dug under, it fell 0.32 m into the pit):
  add_object boulder concrete [0.48, 0.48, 0.48] at [0.64, 1.04, 6.0]: on the
    sand of the bank, 1.5 m from the water
  then tell the person: aim at the ground right beside it and press Dig here,
  and the pit takes the ground from under it. Do not dig it yourself unless
  they ask: a pit you dig is dug in their room too.

THINGS A PERSON USES. Whatever you build, a person can push, pull, carry and
throw. A BOW is more: they take it up, draw its string back and let go -- and
the room gives them those controls only for what you declare with interaction,
once it is built. interaction names its parts, the part the hand draws and
which way, the one-way nock that holds the arrow, the springs that store the
draw, and the arrow -- never a speed. It checks that against what is built and
then TRIES the bow: a person's 800 N hand draws it and lets go in a copy, and
trial says how far it drew, what the limbs held and how fast the arrow left.
Say those numbers. If trial says sound: false, the engine did not follow that
shot: say so, and not its speed. Built things the tools only warn about are
not a bow; what interaction refuses is not one either -- fix what it says.

A bow (6 kN/m limbs: drawn 0.44 m by 214 N it held 42 J, and the arrow left at
8.3 m/s). It shoots along +x, and the person draws it towards -x:
  add_object bow grip upper oak [0.04, 0.16, 0.12] at [0, 1.40, 0] anchored
  add_object bow grip lower oak [0.04, 0.16, 0.12] at [0, 1.12, 0] anchored
    (the arrow's REST: its top is exactly where the shaft lies)
  add_object bow grip near cheek oak [0.04, 0.04, 0.04] at [0, 1.22, 0.06] anchored
  add_object bow grip far cheek oak [0.04, 0.04, 0.04] at [0, 1.22, -0.06] anchored
  add_object upper limb tip oak [0.04, 0.04, 0.04] at [-0.16, 1.62, 0]
  add_object lower limb tip oak [0.04, 0.04, 0.04] at [-0.16, 0.82, 0]
  add_object bowstring oak [0.04, 0.16, 0.04] at [-0.16, 1.22, 0]
    (its CENTRE: the ties below are made off at its two ENDS, 1.30 and 1.14)
  add_object arrow oak [0.6, 0.04, 0.04] at [0.2, 1.22, 0]
    (all with [x, y, z]; the tips and the string answer in_the_air, which is
    right -- the joints below hold them)
  hinge a=bow grip upper b=upper limb tip at [0, 1.34, 0] axis [0,0,1]
    lower -60 upper 60 friction 0
  hinge a=bow grip lower b=lower limb tip at [0, 1.10, 0] axis [0,0,1]
    lower -60 upper 60 friction 0
  spring a=bow grip upper b=upper limb tip at_a [0.36, 1.34, 0]
    at_b [-0.16, 1.62, 0] rest 0 stiffness 6000 damping 20
  spring a=bow grip lower b=lower limb tip at_a [0.36, 1.10, 0]
    at_b [-0.16, 0.82, 0] rest 0 stiffness 6000 damping 20
    (the limbs, made off 0.36 m forward of the grip on purpose: that is the
    lever they work on)
  tie a=upper limb tip b=bowstring at_a [-0.16, 1.62, 0] at_b [-0.16, 1.30, 0]
    length 0
  tie a=lower limb tip b=bowstring at_a [-0.16, 0.82, 0] at_b [-0.16, 1.14, 0]
    length 0
  fix a=bowstring b=arrow at [-0.13, 1.22, 0] axis [1,0,0] comes_off_n 20
    (the nock: one-way along +x, the way the arrow leaves)
  interaction object="the bow" parts=[the eight above] draw={part: bowstring,
    axis: [-1,0,0], max_m: 0.45} nock={a: bowstring, b: arrow}
    limbs=[[bow grip upper, upper limb tip], [bow grip lower, lower limb tip]]
    projectile=arrow
A stiffer or softer bow is the same with another stiffness on both springs,
drawn by the same hand: 4.5 kN/m sent the arrow off at 7.1 m/s, 8 kN/m at 9.7,
12 kN/m at 11.9, and 20 kN/m -- 686 N of the hand's 800 -- at 15.5.
ANOTHER LIKE ONE ALREADY BUILT -- a bow beside the courtyard's, a stiffer one, a
second gate -- is duplicate, never the recipe again: the names of its parts
(things_a_person_uses lists a bow's), an offset, a prefix for the copies' names,
and changes for what should differ: {"spring": {"stiffness_n_m": 8000}} gives a
bow's limbs 8 kN/m. It copies the bodies, every joint between them and how a
person uses them, exactly, and tries a copied bow: say what its trial measured.
BESIDE a bow is across its line of fire, never along it: the courtyard's shoots
along +x, so move the copy in z, 0.8 m or more, clear of everything else. The
recipe above is for a bow where there is none; to build it somewhere else, add
the same offset to EVERY position and EVERY point, whole cells (0.04 m) each way.
WHAT THE PERSON DOES WITH IT: E on any part of it takes it up; they hold the
left mouse to draw and let go to shoot; the right mouse lets the string down.
Tell them that in your answer.

TOOLS THAT DIG. A pick is a body with a POINT, and tool_point gives a body
one: where its tip is, the way it goes in, how wide and thick it is and how much
of the tool is point. Nothing digs because of what it is called. How far a point
goes in is the soil's own resistance against what the swing brings, a pry breaks
out what it can and what comes loose is carried, and rock at least as hard as
the point stops it: ground-work-v1, a declared model from the ground's own
density, friction angle and cohesion. The clearing room is level soil at y = 0
with a slab of bare rock 1.6 m by 1.2 m at [1.6, -1.2], 0.12 m proud of it.
- A PICK a person can swing is ONE PIECE of oak: a haft and an arm given the
  same join name, the haft FIRST, so the world calls the pick by the haft's
  name. It weighs 1.2 kg and held level pulls 5.5 N m on the grip, well inside
  the hand's 60 N m wrist; iron of the same size is ten times the weight, and
  tool_point says when the wrist cannot hold a tool level.
- tool_point's tip is at the very end of the arm, ON its end face, pointing
  runs OUT of the arm there, and grip_m is a point ON the haft near its far
  end -- [x, y, z] like the tip, at the haft's own height and depth.
A found oak pick lying on the soil in front of the person (tried, it went
120 mm into the soil at 9.2 m/s, levered it broke out 5.6 L of soil, and the
rock stopped it), at a place [px, pz]: px is the x of the first of
put_new_things_m, and pz its z with 0.02 added, so every face of both parts
lies on the room's 0.04 m cell grid. Joined, a part off the grid is lost from
the piece: measured, a haft at z 1.2 left a piece of just its arm, 0.36 kg,
whose grip was refused; at z 1.22 the piece was 1.21 kg and took its grip.
Every number below is worked out from px and pz, so the parts, the tip and the
grip stay together:
  add_object pick haft oak [0.8, 0.04, 0.04] at [px, 0.02, pz] join "pick"
  add_object pick arm oak [0.04, 0.04, 0.28] at [px + 0.38, 0.02, pz - 0.16] join "pick"
    (the arm lies along -z from the haft's +x end, touching it; both with
    [x, y, z])
  tool_point body=pick haft tip [px + 0.38, 0.02, pz - 0.30] pointing [0, 0, -1]
    grip [px - 0.36, 0.02, pz] width 0.04 thickness 0.04 angle 30 length 0.2
  For the place [0.0, 1.2]: px 0.0 and pz 1.22, so the haft at [0.0, 0.02, 1.22],
  the arm at [0.38, 0.02, 1.06], the tip at [0.38, 0.02, 0.92] and the grip at
  [-0.36, 0.02, 1.22].
  interaction object="the pick" template=swing-and-lever
    parts=[pick haft, pick arm] tool=pick haft
A pick is not the person's to swing until interaction declares it: tool_point
gives it a point, not controls, and without the interaction they can only carry
it. Always finish a pick with interaction, in the same turn.
Its trial swings it into the nearest level soil, levers it out, and swings it at
the nearest bare rock: say how deep it went, what came loose and what stopped
it, in its numbers. Do not strike in your copy unless they ask: what a pick
breaks out of the ground is gone from their room's ground too.
WHAT THE PERSON DOES WITH IT: they walk up to the pick and press E, looking at it
or at the ground beside it: it is held ready by its grip, point down. A ring on
the ground shows where it will come down -- green where it can work, amber when
that is too far or too near, red on bare rock. One click does the whole of it:
the hand swings it over and down, the point goes in, the hand pries it and
draws it out, and what it breaks out is carried. Holding the button keeps
going; the right mouse stops it. Aimed at the rock, the rock stops it. E puts
it down. Tell them that in your answer.
SHAPING HOW IT IS USED. The page uses every tool the same way, and interaction
takes `use` to shape it for what you made -- only what you say is kept:
label, what the click is called ("Dig here" unless you say; "Break up the soil"
for a mattock, "Drive it in" for a stake); past, how a result is said ("dug");
swing {speed_m_s 1 to 5, raise_deg 30 to 170}, how fast the HAND swings it (4
m/s, raised 110 degrees -- the point arrives two to three times faster, so the
9 m/s a trial says is the point, not the hand; leave it out unless it should
swing slower); lever {speed_m_s 0.3 to 4, lever_deg 5 to 80}, how it is
pried (1.2 m/s, 40 degrees); pry false for a tool that is only swung and drawn
out, never pried; reach_m [nearest, furthest], within 0.3 to 2 m ([1.15, 2]);
repeat false when holding the button should not go on. Say only what differs
from those. How deep it goes and what comes loose are still the ground's, and
its trial swings it with the use you gave it. For a grub hoe: build_recipe
"hoe" at the place with tool {call_it "the grub hoe", use {label "Grub it
out", past "grubbed out"}} -- one call. Said again for a tool already built,
interaction replaces how it is used, whatever it was called. A hoe's draw through the soil
and an axe's chop are not modelled: a hoe made with a point is swung and pried
like a pick, and an axe is a blade.

WHAT THE PERSON KNOWS. their_notebook, in what you are given, is their notebook
as it stands (read_knowledge gives the same in full): what the engine measured
their own tools doing -- "went 120 mm into the soil at 9.2 m/s and broke out
5.6 L" -- each claim scoped to the design, the ground and the action tried; what
is blocked, and by what; and what the engine does not model yet. When they ask
what they know, what a thing of theirs can do, or what they could make, say what
it holds, in its own words -- a claim holds only for what was tried -- and when
it holds nothing yet, say that. Never say it records anything it does not: a
trial in your copy is not in it. You cannot add to it. No tool does; only their
own hand's results in their own room do. A tool you make for them is one they
found, not one they made.

TRY IT BEFORE YOU SAY IT WORKS. The world you build in is a real engine world.
Use the mechanism the way a person would: pick_up the handle (or the leaf, or
the grate), place it where a hand would pull it -- a quarter turn round the
axle, or 0.3 m up -- run for about a second, then read joints: a hinge reports
degrees, a slide moved_m, a rope tension_n. let_go when you have finished. If it
did not move, find out why and fix it -- a joint that reads 0 when it was pulled
on is almost always touching something: the floor, its own post, or another
part -- or it is HELD: a fix (a latch, a locking bar) keeps a gate shut until
unhinge takes it out, so read joints for anything else on the thing you are
moving. Every joint call says what it noticed under `warnings`, and each names
a mistake that will stop the thing working: fix it before you go on. A rope or rod that
pulls along a hinge's own axis, or is made off right at the hinge line, cannot
turn it at all. overloaded only knows about what has settled, so run for a
second or two before asking it. Adding, moving or removing anything opens the
world again from what you authored, so try it after your last change.

ANSWER in two or three plain sentences: what you built, from what, and what you
measured when you tried it. Name things by what they are made of. Never say
something works, broke, bent or bounced unless a tool told you it did."""
GUIDE = GUIDE.replace("{THINGS_ON_JOINTS}", _things_on_joints()).replace("{STRUCTURES}", _structures())


def ran_out(result: dict[str, Any]) -> bool:
    """Whether the model used up its whole answer before it finished."""
    details = result.get("incomplete_details")
    return (result.get("status") == "incomplete" and isinstance(details, dict)
            and details.get("reason") == "max_output_tokens")


def unfinished(result: dict[str, Any], asked_again: bool = False) -> str:
    """Why the model's answer came back unfinished, as the person should hear it.

    It used to say "try a shorter request" whatever the reason, and a one-line
    request once failed that way after 62 s with nothing to say why. The answer
    carries the reason (incomplete_details, or an error's code), so that is what
    is said. A turn that fails changes nothing in the room, whatever the reason.
    An answer that ran out is asked for once more first (ask), so the person
    hears that it ran out only when it did so twice."""
    status = str(result.get("status") or "no status")
    details = result.get("incomplete_details")
    reason = str(details.get("reason") or "") if isinstance(details, dict) else ""
    if reason == "max_output_tokens":
        if asked_again:
            return (f"the model used up its whole answer -- {MAX_OUTPUT_TOKENS} tokens, its "
                    f"thinking included -- before it finished, and again when it was asked once "
                    f"more, so nothing in the room was changed; asking for less at a time may work")
        return (f"the model used up its whole answer -- {MAX_OUTPUT_TOKENS} tokens, its thinking "
                f"included -- before it finished, so nothing in the room was changed; asking "
                f"again usually works")
    if reason == "content_filter":
        return "the model's answer was stopped by its content filter, so nothing in the room was changed"
    error = result.get("error")
    code = str(error.get("code") or "")[:60] if isinstance(error, dict) else ""
    why = reason or code
    return (f"the model's answer came back {status}" + (f" ({why})" if why else "")
            + ", so nothing in the room was changed; asking again usually works")


def payload(model: str, conversation: list[dict[str, Any]]) -> dict[str, Any]:
    """What is sent each round. The tools are the MCP's, via room_world."""
    return {"model": model, "store": False, "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reasoning": {"effort": "low"},
            # Handed back each round with the calls it led to, so that a model
            # that planned a gate in round one still has the plan in round five.
            "include": ["reasoning.encrypted_content"],
            "instructions": GUIDE,
            "tools": room_world.chat_tools(),
            "input": conversation}


def _call(api_key: str, model: str, conversation: list[dict[str, Any]]) -> dict[str, Any]:
    req = request.Request("https://api.openai.com/v1/responses",
                          data=json.dumps(payload(model, conversation),
                                          allow_nan=False).encode(), method="POST",
                          headers={"Authorization": "Bearer " + api_key,
                                   "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=TIMEOUT_S) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("the model's answer exceeded the size budget")
            return json.loads(raw)
    except error.HTTPError as exc:
        # The upstream body can echo the key or the input. Do not log it.
        raise ValueError(f"the model request failed (HTTP {exc.code}); check the local "
                         f"key, model access and account limits") from None
    except (error.URLError, TimeoutError):
        raise ValueError("the model could not be reached, and no paid retry was issued") from None


def _now(live_state: dict[str, Any]) -> list[dict[str, Any]]:
    """The room as the person sees it right now, in the MCP's units."""
    out = []
    for body in live_state.get("bodies", []):
        velocity = body.get("velocity_m_s") or [0, 0, 0]
        said = {"name": body.get("name", ""), "material": body.get("material", ""),
                "shape": body.get("shape", ""),
                "position_m": [round(v, 3) for v in (body.get("position_m") or [0, 0, 0])],
                "size_m": [round(v, 3) for v in (body.get("dimensions_m") or [0, 0, 0])],
                "mass_kg": round(float(body.get("mass_kg") or 0.0), 2),
                "anchored": bool(body.get("anchored")), "held": bool(body.get("held")),
                "moving_m_s": round(math.sqrt(sum(v * v for v in velocity)), 3)}
        # How a box stands, when it is not square to the room: a plank the chat
        # leaned, or a pillar that fell over.
        turned = room_world.banjo_mcp._turned(said["shape"],
                                              body.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0])
        if turned:
            said["rotation_deg"] = turned
        out.append(said)
    return out


# Where a structure's middle may go, in front of the person: (metres ahead,
# metres to their right), the first with room for it -- STRUCTURE_OUT_M out,
# then further, then beside the first. Room for it is a strip along its line,
# STRUCTURE_ROOM_M long and STRUCTURE_WIDE_M across, with nothing standing in
# it: a second structure asked for from where they stand went where the first
# already was.
STRUCTURE_SPOTS = ((STRUCTURE_OUT_M, 0.0), (10.0, 0.0), (STRUCTURE_OUT_M, 9.0), (STRUCTURE_OUT_M, -9.0),
                   (14.0, 0.0))
STRUCTURE_ROOM_M = 12.0
STRUCTURE_WIDE_M = 3.0


def _structure_place(person: dict[str, Any],
                     bodies: list[dict[str, Any]] = ()) -> tuple[list[float], list[float]]:
    """Where a structure goes when they did not say: its middle out in front
    of them where nothing stands (STRUCTURE_SPOTS), and its line across their
    view -- along whichever of the room's x and z is nearest to that, so its
    boards turn only by their tilt and a quarter turn. The first spot, if none
    has room: the chat is refused an overlap and says so."""
    sx, _, sz = person["standing_m"]
    fx, _, fz = person["facing"]
    rx, rz = -fz, fx       # their right, as one_metre_to_the_right_m has it
    if abs(rx) >= abs(rz):
        way = [1.0 if rx > 0 else -1.0, 0.0, 0.0]
    else:
        way = [0.0, 0.0, 1.0 if rz > 0 else -1.0]
    reach = (STRUCTURE_ROOM_M / 2.0, STRUCTURE_WIDE_M / 2.0) if way[0] else (STRUCTURE_WIDE_M / 2.0,
                                                                            STRUCTURE_ROOM_M / 2.0)
    footprints = _footprints(person, list(bodies))
    spots = [[round(sx + fx * ahead + rx * right, 2), round(sz + fz * ahead + rz * right, 2)]
             for ahead, right in STRUCTURE_SPOTS]
    for mx, mz in spots:
        if not any(abs(mx - bx) < reach[0] + hx and abs(mz - bz) < reach[1] + hz for bx, bz, hx, hz in footprints):
            return [mx, mz], way
    return spots[0], way


def _constructions_due(entry: dict[str, Any], declared_now: set[str], changed_names: set[str]) -> list[str]:
    """The structures to measure as a turn ends: those it declared, and those
    it added a part to, moved, turned or took one out of."""
    names_now = {b["name"] for b in entry["scene"]["bodies"]}
    return [name for name, record in (entry.get("constructions") or {}).items()
            if name in declared_now
            or (set(record.get("parts") or ()) | set(constructions.parts_now(record, names_now))) & changed_names]


def _measured(world_id: str, entry: dict[str, Any], declared_now: set[str],
              changed_names: set[str]) -> list[dict[str, Any]]:
    """Each structure this turn declared or changed, measured as it stands."""
    out = []
    for name in _constructions_due(entry, declared_now, changed_names):
        checked = room_world.call(world_id, "check_construction", {"name": name})
        if "error" not in checked:
            out.append(checked)
    return out


def _loose(entry: dict[str, Any], made_names: list[str]) -> list[str]:
    """Of what this turn made, what a person could take: not anchored, and not
    a part of a structure."""
    bodies = {b["name"]: b for b in entry["scene"]["bodies"]}
    parts = {p for record in (entry.get("constructions") or {}).values()
             for p in constructions.parts_now(record, set(bodies))}
    return [n for n in made_names if n in bodies and not bodies[n].get("anchored") and n not in parts]


def _did(name: str, args: dict[str, Any], answer: dict[str, Any]) -> str:
    """One line for the person, under the answer, per change that was made."""
    if name == "use_action":
        return f"pressed {answer.get('action') or args.get('action')} on {args.get('name')}"
    if name == "plan_construction":
        return f"declared {answer.get('construction')}: {answer.get('reading')}"
    if name == "build_structure":
        checked = answer.get("checked") or {}
        return (f"built {answer.get('construction')} of {answer.get('parts')} parts: "
                + ("it does what it was declared to do" if checked.get("passed")
                   else "not finished -- " + ", ".join(checked.get("failed") or ["nothing measured"])))
    if name == "add_object":
        return f"added {answer.get('added')}"
    if name == "remove_object":
        return f"removed {answer.get('removed')}"
    if name == "move_object":
        return f"moved {answer.get('moved')}"
    if name == "turn_object":
        at = answer.get("at_m") or []
        return (f"stood {answer.get('turned')} {answer.get('stands')}"
                + (f" at [{at[0]:.2f}, {at[2]:.2f}]" if len(at) == 3 else ""))
    if name == "build_recipe":
        at = answer.get("at_m") or [0.0, 0.0]
        return f"built {answer.get('built')} at [{at[0]:.2f}, {at[1]:.2f}]"
    if name == "offer_actions":
        return (f"gave {answer.get('offered')} {len(answer.get('actions') or [])} actions "
                f"in the side view")
    if name == "clear_world":
        return "cleared the room"
    if name == "drop":
        return f"dropped {(answer.get('dropped') or {}).get('object')}"
    if name in ("unhinge", "hinge_friction"):
        return f"{name} on joint {args.get('joint')}"
    if name == "enclose_gas":
        return f"filled {answer.get('gas_region')} with gas under {args.get('piston') or 'nothing'}"
    if name == "heat":
        return (f"heating {args.get('target')} at {float(args.get('power_w') or 0) / 1000:g} kW "
                f"for {args.get('seconds')} s")
    if name == "blade":
        return f"gave {args.get('body')} an edge"
    if name == "interaction":
        if args.get("template") == "swing-and-lever":
            return f"made {args.get('object')} something a person can swing into the ground and lever"
        return f"made {args.get('object')} something a person can draw and loose"
    if name == "tool_point":
        return f"gave {answer.get('body') or args.get('body')} a point that can go into the ground"
    if name == "strike":
        return (f"levered {answer.get('levered')}" if args.get("lever")
                else f"swung {answer.get('struck')} at {args.get('at_m')}")
    if name == "duplicate":
        return (f"copied {len(answer.get('copied') or [])} things as '{args.get('prefix')}'"
                + (f", with {answer['changed']}" if answer.get("changed") else ""))
    if name == "make_terrain":
        return f"made the ground: {args.get('kind') or 'valley'}"
    if name == "dig":
        return f"dug {answer.get('dug_m3')} m3 out at {args.get('from_m')}"
    if name == "fill":
        return f"heaped {answer.get('heaped_m3')} m3 of {answer.get('of')} at {args.get('at_m')}"
    if name == "cut_block":
        return f"cut {answer.get('cut')} out of the rock"
    if name == "set_river":
        return f"set {answer.get('river')} to {answer.get('discharge_m3_s')} m3/s"
    if name == "drum":
        return f"hung {args.get('b')} on a rope from the drum {args.get('a')}"
    if name == "store":
        return f"put a {float(answer.get('capacity_j') or 0.0) / 1000.0:g} kJ battery in {answer.get('in')}"
    if name == "motor":
        return f"put a motor on the pin between {' and '.join((answer.get('motor') or {}).get('on') or [])}"
    if name == "drive":
        return f"told the motor turning {args.get('part')} {answer.get('command')}"
    if name == "control":
        return f"gave {answer.get('control')} a controller, worked from its panel"
    if name == "operate":
        return f"worked {answer.get('machine')}: {answer.get('does')}"
    return f"{name} {args.get('a')} to {args.get('b')}"


# The conversation. The model is sent the turns before this one, so an answer
# to its own question -- "confirmed", "three", "the last one" -- means
# something. Sent only the newest message, a room asked "which pit, and how
# many bars?" was answered "confirmed", described the room and built nothing.
KEEP_TURNS = 40        # turns a room remembers
SEND_TURNS = 12        # of those, how many go to the model with each request
SAID_CHARS = 2000      # a turn's words are cut to this, each way


def remember_turn(history: list[dict[str, Any]], message: str,
                  answer: dict[str, Any] | None, failure: str | None = None) -> None:
    """Keep one turn with the room it was said in: what was asked, what the room
    answered -- or that the request failed -- and what it did."""
    replied = (str((answer or {}).get("reply") or "") if failure is None
               else f"(that request failed: {failure})")
    history.append({"asked": str(message)[:SAID_CHARS],
                    "replied": replied[:SAID_CHARS] or "(nothing said)",
                    "did": [str(d) for d in list((answer or {}).get("did") or [])[:20]]})
    del history[:-KEEP_TURNS]


def _earlier_turns(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The turns before this one, as the model's own conversation: what the
    person said, then what the room answered and did."""
    messages: list[dict[str, Any]] = []
    for turn in (history or [])[-SEND_TURNS:]:
        did = turn.get("did") or []
        messages.append({"role": "user", "content": str(turn.get("asked") or "")[:SAID_CHARS]
                                                    or "(nothing)"})
        messages.append({"role": "assistant",
                         "content": (str(turn.get("replied") or "(nothing said)")[:SAID_CHARS]
                                     + (f" [did: {', '.join(did)}]" if did else ""))})
    return messages


REACH_M = 1.2   # how far the room's hand reaches: playground/world.js, REACH_M


def where_the_person_is(raw: Any) -> dict[str, Any] | None:
    """Where the person is, as the page says it, in the words the chat is given:
    where they stand, which way they face, the point a metre in front of them,
    and what the middle of their view is on. None when the page did not say, or
    said something that is not a place -- it arrives over HTTP, so every number
    is checked rather than trusted, and nothing is guessed."""
    if not isinstance(raw, dict):
        return None

    def point(value: Any) -> list[float] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return None
        try:
            out = [float(v) for v in value]
        except (TypeError, ValueError):
            return None
        if not all(v == v and abs(v) < 1000.0 for v in out):   # finite, and in a room
            return None
        return [round(v, 3) for v in out]

    standing, facing = point(raw.get("standing_m")), point(raw.get("facing"))
    if standing is None or facing is None:
        return None
    level = (facing[0] ** 2 + facing[2] ** 2) ** 0.5
    if level < 1e-6:
        return None
    fx, fz = facing[0] / level, facing[2] / level
    said: dict[str, Any] = {
        "standing_m": standing,
        "facing": [round(fx, 3), 0.0, round(fz, 3)],
        "one_metre_in_front_m": [round(standing[0] + fx, 3), round(standing[2] + fz, 3)],
        # Their left and right, for when what is in front of them is water.
        "one_metre_to_the_left_m": [round(standing[0] + fz, 3), round(standing[2] - fx, 3)],
        "one_metre_to_the_right_m": [round(standing[0] - fz, 3), round(standing[2] + fx, 3)],
        "reach_m": REACH_M}
    eyes = point(raw.get("eyes_m"))
    if eyes is not None:
        said["eyes_m"] = eyes
    # What they have in their hand: "this" and "it", before anything they are
    # looking at. By name, as the room's objects are named.
    holding = raw.get("holding")
    if isinstance(holding, str) and holding.strip():
        said["holding"] = holding.strip()[:80]
        at = point(raw.get("holding_at_m"))
        if at is not None:
            said["holding_at_m"] = at
    looking = raw.get("looking_at")
    if isinstance(looking, str) and looking.strip():
        said["looking_at"] = looking.strip()[:80]
        at = point(raw.get("looking_at_m"))
        if at is not None:
            said["looking_at_m"] = at
    # What they carry, by material, as the page counts it -- the soil a pick
    # broke out, the glass swept up -- so "heap what I'm carrying here" means
    # something. Only names and weights that make sense are passed on.
    carrying = raw.get("carrying")
    if isinstance(carrying, list):
        kept = []
        for item in carrying[:12]:
            if not isinstance(item, dict) or not isinstance(item.get("what"), str):
                continue
            name = item["what"].strip()[:40]
            try:
                kg = float(item.get("kg"))
            except (TypeError, ValueError):
                continue
            if name and kg == kg and 0.0 < kg < 1e6:
                kept.append({"what": name, "kg": round(kg, 3)})
        if kept:
            said["carrying"] = kept
    return said


def notebook_said(journal: Any) -> Any:
    """The person's notebook as the chat is given it in the opening: each design
    they have met by its standing, each claim with what the engine measured and
    its scope, what is blocked and by what, and what the engine does not model.
    The same as read_knowledge, shorter (mcp/progression.py)."""
    try:
        book = progression.notebook(journal, room_world.banjo_mcp._registry())
    except room_world.banjo_mcp.Refused as failure:
        return f"the notebook cannot be read: {failure}"
    designs = [{"design": d["name"] + ("" if d["registered"] else " (a design of their own)"),
                "standing": d["standing"],
                "claims": [f"{e['said']}: {e['claim']} ({e['scope']})" for e in d["evidence"]]}
               for d in book["designs"]]
    return {"designs": designs or "nothing yet: no tool of theirs has been measured doing anything",
            "blocked": [f"making {b['name'].lower()} themselves: " + "; ".join(b["because"])
                        for b in book["blocked"]],
            "not_modelled": book["not_modelled"]}


# Where something made for the person goes when they do not say where (the
# owner: "put the item on the ground in front of them (close)"): places on the
# ground a metre in front of them with nothing there, the nearest first --
# straight ahead, then either side of that, then a little further out, so
# what is in the way is gone round before it is gone past. Each is (metres
# ahead, metres to their left; negative is to their right).
NEW_THING_SPOTS = ((1.0, 0.0), (1.0, 0.8), (1.0, -0.8), (1.5, 0.0), (1.5, 0.8), (1.5, -0.8),
                   (1.0, 1.6), (1.0, -1.6), (2.0, 0.0), (2.0, 0.9), (2.0, -0.9),
                   (2.5, 0.0), (3.0, 0.0))
NEW_THING_CLEAR_M = 0.4     # how far round the middle of a new thing is kept clear
NEW_THING_APART_M = 0.7     # how far apart two new things' middles are
ABOVE_THE_GROUND_M = 1.6    # a thing whose bottom is higher (a lamp) leaves the ground free


def _footprints(person: dict[str, Any], bodies: list[dict[str, Any]]) -> list[tuple[float, float, float, float]]:
    """Where each body stands on the ground, as a level box round it as it is
    turned: (x, z, half its extent in x, half in z), from the running room's
    state. What is held moves with the person and takes no ground; nor does
    what is over their head (a lamp) or no higher than the ground (a floor
    slab, a rug)."""
    sy = person["standing_m"][1]
    footprints = []
    for body in bodies:
        if body.get("held"):
            continue
        try:
            at = [float(v) for v in body.get("position_m") or []]
            dims = [float(v) for v in body.get("dimensions_m") or []]
            w, x, y, z = (float(v) for v in (body.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0]))
        except (TypeError, ValueError):
            continue
        if len(at) != 3 or len(dims) != 3:
            continue
        if body.get("shape") == "sphere":
            half = [dims[0] / 2.0] * 3
        else:
            turn = ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
                    (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
                    (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))
            half = [sum(abs(turn[r][i]) * dims[i] / 2.0 for i in range(3)) for r in range(3)]
        if at[1] - half[1] > sy + ABOVE_THE_GROUND_M or at[1] + half[1] <= sy + 0.02:
            continue
        footprints.append((at[0], at[2], half[0], half[2]))
    return footprints


def clear_spots(person: dict[str, Any], bodies: list[dict[str, Any]],
                wanted: int = 3, grid_m: float = 0.04) -> list[list[float]]:
    """Up to `wanted` places [x, z] on the ground close in front of the person
    with nothing standing there, the best first, and apart from each other --
    so a second thing goes beside the first, not on it. What the room has is
    each body's footprint as it is turned, from the running room's state; what
    is held moves with them and takes no ground."""
    sx, sy, sz = person["standing_m"]
    fx, _, fz = person["facing"]
    footprints = _footprints(person, bodies)
    chosen: list[list[float]] = []
    for ahead, left in NEW_THING_SPOTS:
        cx, cz = sx + fx * ahead + fz * left, sz + fz * ahead - fx * left
        # On the room's cell grid, so a recipe worked out from the place keeps
        # a joined piece's faces on it (the guide's pick): off it, a part is
        # lost from the piece.
        cx, cz = round(cx / grid_m) * grid_m, round(cz / grid_m) * grid_m
        if any(max(abs(cx - bx) - hx, 0.0) ** 2 + max(abs(cz - bz) - hz, 0.0) ** 2
               < NEW_THING_CLEAR_M ** 2 for bx, bz, hx, hz in footprints):
            continue
        if any(math.hypot(cx - px, cz - pz) < NEW_THING_APART_M for px, pz in chosen):
            continue
        chosen.append([round(cx, 3), round(cz, 3)])
        if len(chosen) == wanted:
            break
    return chosen


def ask(api_key: str, model: str, room: Any, live_state: dict[str, Any],
        message: str, story: list[str],
        trace: list[dict[str, Any]] | None = None,
        water_state: dict[str, Any] | None = None,
        person: Any = None,
        history: list[dict[str, Any]] | None = None,
        journal: Any = None,
        live: Any = None) -> dict[str, Any]:
    """One turn. Returns what to say, what was changed, and whether to reopen.

    `live`, when given, works the running room for the calls in
    room_world.LIVE -- live(name, args) returns what it did there, or
    {"error": why} -- so pressing a thing's action or telling its motor what to
    do happens to the room as it stands, and does not open it again.

    `live_state` is the world as the ENGINE has it -- pieces, dents and all --
    and is what the model is told the room looks like now. `room` is the
    authored room, which is what gets changed: it is held as an MCP world for
    the length of the turn and written back into room.spec if anything the
    person will be handed was changed.

    `trace`, when given a list, receives every round: what the model said, each
    tool it called with its arguments, and the answer it got back. The answers
    are the part worth having -- a refusal is the only record of WHY a request
    did not make it into the room.

    `water_state` is the running room's water, when it stands on ground: the
    model's copy of the room then holds the water as the person sees it.
    """
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set in the local .env, so the room has "
                         "nobody to talk to. Add it and restart the server. Everything "
                         "else on this page works without it.")

    world_id = room_world.open_room(room.spec, water_state=water_state)
    entry = room_world.entry_of(world_id)
    # The person's notebook, for read_knowledge -- read-only, since no tool
    # writes to one (mcp/progression.py).
    if journal is not None:
        entry["journal"] = journal
    started = time.perf_counter()
    try:
        opening = {"what_you_were_asked": message,
                   "what_the_person_has_been_doing": story[-24:] or ["nothing yet"],
                   "objects_now": _now(live_state),
                   "the_room": {"cell_size_m": entry["cell_m"],
                                "cells_used": entry["cells"],
                                "cells_left": max(0, entry["max_cells"] - entry["cells"]),
                                "joints": len(entry["joints"])}}
        # What in it a person can take up and use, and how -- so a bow already
        # in the room is known to be one, and a second one built beside it is
        # not given the first one's names.
        if entry.get("interactions"):
            opening["things_a_person_uses"] = [room_world.banjo_mcp._use_said(p)
                                               for p in entry["interactions"]]
        # And the actions already given to things in it (offer_actions), so a
        # thing is not given the same ones again.
        if entry.get("actions"):
            opening["actions_offered"] = {name: [action["label"] for action in actions]
                                          for name, actions in entry["actions"].items()}
        # And the structures declared in it, with what each must do, so a later
        # turn holds one to it rather than declaring it again.
        if entry.get("constructions"):
            opening["structures_declared"] = [
                {"name": name, "kind": record["kind"], "reading": record["reading"],
                 "must": constructions.said(record), "parts": record.get("parts") or []}
                for name, record in entry["constructions"].items()]
        # Where the person is: what "near me" and "over there" refer to. A
        # model that cannot see the room has no other way to know.
        person = where_the_person_is(person)
        if person is not None:
            # Where something made for them goes when they do not say where.
            person["put_new_things_m"] = clear_spots(person, live_state.get("bodies", []),
                                                     grid_m=float(entry["cell_m"]))
            # And where a structure goes: not in their hand's reach, but out in
            # front of them with its line across their view.
            person["structure_middle_m"], person["across_the_view"] = _structure_place(
                person, live_state.get("bodies", []))
            opening["the_person"] = person
        # What they know, as it stands, so that what the chat says of their
        # notebook is what it holds. Left to ask read_knowledge, the model once
        # answered from the conversation instead and said the notebook held a
        # trial it never did.
        if journal is not None:
            opening["their_notebook"] = notebook_said(journal)
        if entry["scene"].get("terrain") and entry.get("world") is not None:
            # The ground and the water as they are now, so a dam or a channel
            # can be placed from the first round rather than after a survey.
            try:
                opening["the_ground"] = room_world.banjo_mcp._ground_said(
                    entry["world"].environment_report())
                opening["the_water"] = room_world.banjo_mcp._water_said(entry["world"], full=True)
            except Exception:   # noqa: BLE001 - a summary; the tools say it all again
                pass
        # The turns before this one, then this one: "three" answers a question
        # only if the question is there to answer.
        conversation: list[dict[str, Any]] = _earlier_turns(history) + [
            {"role": "user", "content": json.dumps(opening, allow_nan=False)}]
        did: list[str] = []
        changed = offered = reminded = worked = recorded = False
        usage = {"input_tokens": 0, "output_tokens": 0}
        reply = ""
        rounds = 0
        # What this turn declared (plan_construction), made and changed, by
        # name: the structures it touched are measured before it is called
        # done. And the calls that work the running room held back until a
        # change this turn is in it (HELD_BACK).
        declared_now: set[str] = set()
        made_names: list[str] = []
        changed_names: set[str] = set()
        repairs = 0
        deferred: list[dict[str, Any]] = []

        asked_again = False
        for turn in range(MAX_ROUNDS):
            if time.perf_counter() - started > MAX_TURN_S:
                reply = (f"I ran out of time after {turn} rounds. "
                         + ("What I had built by then is in the room." if changed
                            else "Nothing in the room was changed."))
                break
            # How long each round's answer took, kept with the turn: asked to build
            # a ski jump it had just declared, the model's second round passed the
            # 90 s timeout, and the turn's log said only that it failed.
            asked_at = time.perf_counter()
            try:
                result = _call(api_key, model, conversation)
            except ValueError as failure:
                if trace is not None:
                    trace.append({"round": turn + 1, "failed": str(failure),
                                  "took_s": round(time.perf_counter() - asked_at, 1), "calls": []})
                raise
            rounds = turn + 1
            spent = result.get("usage") or {}
            usage["input_tokens"] += int(spent.get("input_tokens") or 0)
            usage["output_tokens"] += int(spent.get("output_tokens") or 0)
            this_round_asked_again = False
            if ran_out(result) and not asked_again:
                # A burst of the model's thinking can use up a whole answer on a
                # request that needs a few hundred tokens the next time. On
                # Render, 2026-09-13, "build a tower like the washington
                # monument" ran out at 6000 tokens in its first round; asked
                # again on a desktop it took 727 over three rounds. Nothing of
                # an unfinished answer is kept, so the same round is asked for
                # once more -- once a turn, so a turn costs one extra request at
                # most, and only when this happens.
                asked_again = this_round_asked_again = True
                result = _call(api_key, model, conversation)
                spent = result.get("usage") or {}
                usage["input_tokens"] += int(spent.get("input_tokens") or 0)
                usage["output_tokens"] += int(spent.get("output_tokens") or 0)
            if result.get("status") != "completed":
                raise ValueError(unfinished(result, asked_again=this_round_asked_again))

            outputs = result.get("output", [])
            calls = [o for o in outputs if o.get("type") == "function_call"]
            said: list[str] = []
            for output in outputs:
                for content in output.get("content", []) or []:
                    if content.get("type") == "refusal":
                        raise ValueError("the model declined this request")
                    if content.get("type") == "output_text":
                        said.append(content.get("text", ""))
            round_record: dict[str, Any] = {"round": rounds, "said": "".join(said).strip(),
                                            "calls": [], "took_s": round(time.perf_counter() - asked_at, 1)}
            if this_round_asked_again:
                round_record["asked_again"] = True
            if trace is not None:
                trace.append(round_record)

            if not calls:
                reply = "".join(said).strip() or "Done."
                # A structure it declared or changed this turn is measured
                # before the turn is done, and what fails goes back to it, at
                # most MAX_REPAIRS times a turn (NOT_FINISHED).
                failing = [c for c in _measured(world_id, entry, declared_now, changed_names)
                           if not c.get("passed")]
                if failing and repairs < MAX_REPAIRS:
                    repairs += 1
                    round_record["repair_asked"] = [c["construction"] for c in failing]
                    conversation.extend(o for o in outputs
                                        if o.get("type") in ("reasoning", "message"))
                    conversation.append({"role": "user", "content": NOT_FINISHED.format(
                        failed="; ".join(constructions.summary(c) for c in failing),
                        nothing=NOTHING_BUILT if any("parts" in c["failed"] for c in failing) else "")
                        + "\n" + json.dumps({"measured": failing}, allow_nan=False)})
                    continue
                # Made something and gave it nothing to do: asked once more.
                # Asked for a latched gate, the chat spent 21 calls on where its
                # posts went and answered without offer_actions, so the gate had
                # nothing on its menu but the page's own turns. Only for things
                # made: asked after digging a channel, it told the person "You're
                # right" and offered to put a marker post up to hang actions on.
                # And only for a thing to take: asked for a ski ramp, the chat
                # was asked this and gave its anchored board a "Use the ramp"
                # action, so a structure's parts and scenery are not asked about.
                if _loose(entry, made_names) and not offered and not reminded:
                    reminded = True
                    conversation.extend(o for o in outputs
                                        if o.get("type") in ("reasoning", "message"))
                    conversation.append({"role": "user", "content": NOTHING_OFFERED})
                    continue
                # Said it built something, and nothing changed: asked once more.
                # Asked for a table and a chair, the chat called no tool and
                # answered "Built a small oak table ..." in its recipe's words.
                # Working something on the room as it stands is doing something
                # too: "put its brake on" is not a claim to have built it.
                if not changed and not worked and not reminded and CLAIMS.search(reply):
                    reminded = True
                    conversation.extend(o for o in outputs
                                        if o.get("type") in ("reasoning", "message"))
                    conversation.append({"role": "user", "content": NOTHING_DONE})
                    continue
                break

            # Carry the model's own turn forward -- its reasoning and its calls --
            # then answer each call. Dropping the call leaves the next request
            # describing an answer to a question that was never asked.
            conversation.extend(o for o in outputs
                                if o.get("type") in ("reasoning", "function_call"))
            for call in calls:
                name = call.get("name", "")
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                # After a change this turn the running room is not yet the room
                # the model's copy is: what works it is held back until the
                # change is in it (HELD_BACK), and done then by the server.
                held = changed and live is not None and name in room_world.LIVE
                if name == "use_action" and held:
                    deferred.append({"name": name, "args": dict(args)})
                    answer = {"used": args.get("name"), "action": args.get("action"), "held_back": HELD_BACK}
                elif name == "use_action" and live is not None:
                    # A thing's action, pressed on the room as it stands -- the
                    # page's own action runner, as the person's E runs it. The
                    # model's copy is the room as it was made, which is not
                    # where the room is now.
                    answer = live(name, args)
                else:
                    answer = room_world.call(world_id, name, args)
                    told = None
                    if name == "drive" and live is not None and "error" not in answer:
                        # Told in the model's copy, which writes it into the
                        # room, and told to the running room's motor.
                        told = {**args, "command": answer["command"], "brake": answer["brake"]}
                    if name == "operate" and live is not None and "error" not in answer:
                        # The same for a machine's controller: what the
                        # model's copy made of the words -- power, a
                        # direction, a setting -- told to the running room's.
                        told = {**args, **answer["told"]}
                    if told is not None and held:
                        deferred.append({"name": name, "args": told})
                        answer = {**answer, "held_back": HELD_BACK}
                    elif told is not None:
                        answer = {**answer, **live(name, told)}
                if name in room_world.LIVE and "error" not in answer:
                    worked = True
                    recorded = recorded or name in ("drive", "operate")
                    did.append(_did(name, args, answer)
                               + (" once the change was in" if answer.get("held_back") else ""))
                if name in room_world.AUTHORING and "error" not in answer:
                    changed = True
                    did.append(_did(name, args, answer))
                # Controls given: actions, or a profile (interaction), whose
                # controls are the page's -- a pick built part by part was
                # asked to offer actions no step can drive.
                if name in ("offer_actions", "interaction") and "error" not in answer:
                    offered = True
                if "error" not in answer:
                    # What it declared, made and changed, by name.
                    if name == "plan_construction":
                        declared_now.add(str(answer.get("construction")))
                    if name == "add_object" and answer.get("added"):
                        made_names.append(str(answer["added"]))
                    if name == "duplicate":
                        made_names.extend(str(n) for n in answer.get("copied") or [])
                    changed_names.update(str(answer[key]) for key in ("added", "removed", "moved", "turned")
                                         if isinstance(answer.get(key), str))
                    changed_names.update(str(n) for n in answer.get("copied") or [])
                round_record["calls"].append({"name": name, "arguments": args,
                                              "answer": answer})
                conversation.append({"type": "function_call_output",
                                     "call_id": call.get("call_id"),
                                     "output": json.dumps(answer, allow_nan=False)})
        else:
            reply = (f"I was still working after {MAX_ROUNDS} rounds. "
                     + ("What I had built by then is in the room." if changed
                        else "Nothing in the room was changed."))

        # What it declared or changed, as it stands now. What still fails is
        # said first, whatever the answer says.
        checked = _measured(world_id, entry, declared_now, changed_names)
        still_failing = [c for c in checked if not c.get("passed")]
        if still_failing:
            reply = ("Not finished: " + "; ".join(constructions.summary(c) for c in still_failing) + ".\n\n"
                     + reply).strip()

        if changed or recorded:
            # What a motor was told is written into the room either way, so it
            # goes on doing it if the room is opened again; only a change to
            # what the room IS opens it again.
            room.spec = room_world.export_spec(entry)
        # And where the person was, as the model was told it -- with the
        # places it was given for new things -- for the turn's log.
        # And what was measured, for the page to show under the answer, and
        # the calls held back for the server to make once the change is in.
        return {"reply": reply, "did": did, "changed": changed, "worked": worked,
                "wall_s": round(time.perf_counter() - started, 2), "rounds": rounds,
                "usage": usage, "the_person": opening.get("the_person"),
                "checked": checked, "deferred": deferred}
    finally:
        room_world.close_room(world_id)
