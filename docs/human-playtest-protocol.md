# Playtest with new players

This is the plan for the test the owner's October 3 list asks for: 8–12 people
who have never played Banjo. It has not been run. It needs people, and an
agent cannot recruit them or stand in for them. Everything below is ready for
whoever runs it.

## What it answers

1. **Can people name what the ground is made of?** Target: at least 80% of
   answers right within 3 seconds, by day and at dusk, on each ground type.
2. **Can they make a first tool without help?** Target: within 5 minutes of
   joining.
3. **Can they make a processed product without help?** Target: their first
   batch from a machine within 15 minutes of joining.

A run that misses a target is a result, not a failure of the test. Write down
where people got stuck; that is what the next change should fix.

## Who and how many

- 8–12 people who have not seen Banjo. Avoid people who have read about it or
  watched someone play.
- Split them across the ground types: about a third each on **Smooth slopes**,
  **Material cells** (25 cm) and **Material cells · 12.5 cm**. Both valleys
  (terrain 4 and 7) should appear.
- One person at a time, on their own world. No one else in the room says
  anything about the game.

## Before each session

1. Start a server on a port nobody else uses and make a **new game** from
   Menu → New game, choosing that person's ground type. To give two people
   the same map, create the world with fixed seeds:
   `POST /api/worlds {"name": "...", "surface": "columns", "seeds": {"terrain": 7, "goods": 851269742}}`.
2. Open the world in a full-size browser window. Note the world id from the
   address bar.
3. Ask permission to record the screen. The game records no names beyond
   the player name they type; use a code such as P01, not their real name.

## Part 1: naming materials (about 5 minutes)

The observer runs this before the person plays, so they have learned nothing
yet.

1. Stand the player at four places chosen beforehand, each looking at a
   different material: **sand**, **soil**, **rock** and **water**. Use the
   same four places for every person on that map.
2. At each place ask: "What is the ground right in front of you made of?"
   Start a stopwatch when you finish asking; stop it when they name something.
3. Record the answer, the time, and whether it was right.
4. Repeat at dusk. Wait for the world clock to bring the sun low (one game
   day is 10 minutes), or use a second world created at the same seeds and
   opened later.
5. Repeat once with the colours ignored: ask how they would tell sand from
   soil if they could not see colour. This tells us whether pattern and
   shape carry the material, not only hue.

Score: percentage named correctly within 3 seconds, per ground type and per
lighting.

## Part 2: unaided opening (up to 25 minutes)

Say only this: "This is a building game. Please think aloud. I can't help, but
tell me when you'd give up." Then do not help. If they are stuck for five
minutes, note it and say "Try something else", nothing more.

Note each time they:

- go to a wrong screen or take a wrong turn;
- read a refusal (copy its words exactly);
- wait on energy or on a machine;
- open the AI Guide or the chat, and what they ask.

Stop at 25 minutes, or when they light their camp.

## Part 3: afterwards (5 minutes)

Ask:

- What was the hardest moment?
- Was anything on screen misleading?
- Did the night look readable?

## Timings from the game

The game records when each player joined and when each goal completed. After
the session, run:

```bash
python tools/playtest_report.py build/playground-rooms/<port>/worlds/<world-id> --json playtest-P01.json
```

It prints minutes from joining to:

- own tool made;
- own tool used;
- first processed batch watched;
- camp lit;
- sun charged a battery.

It also says whether the 5- and 15-minute targets were met. Players who joined
before this was added have no join time and cannot be timed.

## What to hand back

For each person:

- their code;
- ground type, valley and seeds;
- the Part 1 table;
- the report JSON;
- the wrong turns, refusals and waits;
- their answers to Part 3.

Then one summary per ground type: recognition percentage by day and dusk,
median and worst minutes to first tool and to first batch, and the three most
common sticking points.

## What this is not

It does not test multiplayer contention, the AI players, or anything after
the opening chapters. A result from one ground type does not carry over to
another: compare them only on the same valley and seeds.
