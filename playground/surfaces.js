// What a substance looks like close up.
//
// Every material in the room was one flat colour with one roughness, so oak was
// a brown swatch, concrete was a grey one, and a wooden table and a concrete
// one differed only in hue. Nothing about a surface said what it was made of.
//
// This gives each substance a grain: a little noise, evaluated IN THE BODY'S
// OWN SPACE, that moves its colour and its roughness about by a few per cent.
// Solid, not wrapped on: the noise is a property of the volume, so a face that
// was on the outside and a face that has just been broken open are both cut out
// of the same block, and the grain runs through the piece rather than being
// pasted onto it. That is also why there are no seams and nothing to unwrap --
// a shard the engine has just made is drawn correctly with no work at all.
//
// IT CHANGES NOTHING PHYSICAL. It is arithmetic in a fragment shader on the
// colour and the roughness the page already chose. The engine neither knows nor
// could know; the mass, the strength and the temperature are what they were.
//
// Sizes are in METRES, because a grain has a real size: oak's is about twelve
// millimetres across and nine times that along, which is what oak's is. A
// picture whose grain is sized in pixels tells you how far away the camera is
// and nothing about the wood.

// across_m  how big a grain feature is ACROSS the grain, in metres
// along     how many times longer it is ALONG the grain axis
// axis      the direction the grain runs, in the body's own frame
// tint      how much the colour swings with the grain (a share of it)
// rough     how much the roughness swings with the grain
// fleck_m   the size of the fine speckle over the top, in metres
// fleck     how much the colour swings with the speckle
export const SURFACE = {
  // Wood is LINES, not fog: growth rings, cut through at whatever angle the
  // board was sawn at. Ring spacing is oak's own, about thirty millimetres, and
  // the rings are centred well off the board so that what you see across a
  // table top is a set of gently curved near-parallel lines rather than the end
  // of a log.
  "oak":             { axis: [0, 0, 1], across_m: 0.014, along: 9, tint: 0.26, rough: 0.18,
                       fleck_m: 0.0022, fleck: 0.06,
                       rings_m: 0.038, wobble: 0.95, ringy: 0.58, ring_from_m: 0.42 },
  // Cast and rolled metal: barely any colour in it, but the roughness moves,
  // and moving roughness on a metal is the whole of what reads as metal.
  "iron":            { axis: [0, 1, 0], across_m: 0.045, along: 4, tint: 0.09, rough: 0.32,
                       fleck_m: 0.0030, fleck: 0.05 },
  "aluminum":        { axis: [0, 1, 0], across_m: 0.050, along: 8, tint: 0.06, rough: 0.26,
                       fleck_m: 0.0030, fleck: 0.03 },
  // Aggregate: lumps of stone in cement, so the colour moves in patches the
  // size of the stones and the roughness hardly at all.
  "concrete":        { axis: [0, 1, 0], across_m: 0.028, along: 1, tint: 0.20, rough: 0.12,
                       fleck_m: 0.0055, fleck: 0.17 },
  // Fired clay: nearly uniform, which is what makes it read as manufactured.
  "alumina ceramic": { axis: [0, 1, 0], across_m: 0.060, along: 1, tint: 0.05, rough: 0.09,
                       fleck_m: 0.0040, fleck: 0.03 },
  "rubber":          { axis: [0, 1, 0], across_m: 0.020, along: 1, tint: 0.07, rough: 0.06,
                       fleck_m: 0.0014, fleck: 0.06 },
  // Clear things get the least: the eye reads them through what is behind them,
  // and a grain in glass would be a flaw rather than a finish.
  "ice":             { axis: [0, 1, 0], across_m: 0.075, along: 2, tint: 0.08, rough: 0.14,
                       fleck_m: 0.0090, fleck: 0.04 },
  "glass":           { axis: [0, 1, 0], across_m: 0.200, along: 1, tint: 0.02, rough: 0.04,
                       fleck_m: 0.0200, fleck: 0.01 },
  // Not a substance in the engine's catalogue: the room's own ground, which is
  // the biggest surface anybody looks at and was the flattest.
  "ground":          { axis: [0, 1, 0], across_m: 0.340, along: 1, tint: 0.14, rough: 0.10,
                       fleck_m: 0.0450, fleck: 0.10 },
};

const NOTHING = { axis: [0, 1, 0], across_m: 0.05, along: 1, tint: 0.06, rough: 0.09,
                  fleck_m: 0.004, fleck: 0.04 };

// Value noise, two octaves for the grain and one for the speckle. Three octaves
// looked no better and cost a third more; this is drawn for every pixel of
// every surface in the room, so the octave that adds nothing is not free.
const NOISE = `
float bnHash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float bnNoise(vec3 x) {
  vec3 i = floor(x), f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(bnHash(i), bnHash(i + vec3(1.0, 0.0, 0.0)), f.x),
                 mix(bnHash(i + vec3(0.0, 1.0, 0.0)), bnHash(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
             mix(mix(bnHash(i + vec3(0.0, 0.0, 1.0)), bnHash(i + vec3(1.0, 0.0, 1.0)), f.x),
                 mix(bnHash(i + vec3(0.0, 1.0, 1.0)), bnHash(i + vec3(1.0, 1.0, 1.0)), f.x), f.y), f.z);
}
`;

const FRAGMENT_HEAD = `
varying vec3 vGrainAt;
uniform vec3 uGrainAxis;
uniform vec4 uGrain;     // across (cycles/m), along (stretch), tint, roughness
uniform vec2 uFleck;     // fleck (cycles/m), tint
uniform vec4 uRing;      // rings/m, wobble, how much of it is rings, centre offset (m)
${NOISE}
// Value noise crowds around its middle -- two octaves of it barely leave the
// halfway mark -- so it is stretched out to -1..1 and the swing written in the
// table is the swing you actually get. Without this, a grain asked for at a
// quarter came out at about three per cent, which is to say invisible.
float bnSpread(float n, float by) { return clamp((n - 0.5) * by, -1.0, 1.0); }

float bnGrain(vec3 p) {
  vec3 a = normalize(uGrainAxis);
  float along = dot(p, a);
  vec3 across = p - a * along;
  // Stretched along the grain, so features are longer that way than across it,
  // which is the difference between wood and porridge.
  float n = bnSpread(0.62 * bnNoise((across + a * (along / max(uGrain.y, 0.001))) * uGrain.x)
                   + 0.38 * bnNoise((across + a * (along / max(uGrain.y, 0.001))) * uGrain.x
                                    * 2.17 + 13.7), 2.8);
  if (uRing.x <= 0.0) return n;
  // Growth rings. Counted out from a centre set well off the body, so a board
  // shows gently curved near-parallel lines rather than the end of a log, and
  // wobbled by the noise so they are not drawn with a compass. A ring is a
  // LINE: dark where the count turns over, pale between.
  vec3 side = normalize(cross(a, abs(a.y) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0)));
  float r = fract(length(across + side * uRing.w) * uRing.x + n * uRing.y);
  float line = smoothstep(0.0, 0.34, abs(r - 0.5) * 2.0) * 2.0 - 1.0;
  return mix(n, line, uRing.z);
}
`;

const VERTEX_HEAD = `
varying vec3 vGrainAt;
`;

// The body's own position, before anything moves it into the world. A body that
// is turning keeps its grain: the grain belongs to the matter, not to the room.
// An instanced cube cloud is one body too, so its instance offset counts as
// part of where the cell sits in that body and goes in here as well.
const VERTEX_WRITE = `
#include <begin_vertex>
vGrainAt = transformed;
#ifdef USE_INSTANCING
  vGrainAt = ( instanceMatrix * vec4( transformed, 1.0 ) ).xyz;
#endif
`;

const COLOUR_WRITE = `
#include <color_fragment>
{
  float grain = bnGrain(vGrainAt);
  float fleck = bnSpread(bnNoise(vGrainAt * uFleck.x), 2.4);
  diffuseColor.rgb *= clamp(1.0 + grain * uGrain.z + fleck * uFleck.y, 0.0, 2.0);
}
`;

const ROUGH_WRITE = `
#include <roughnessmap_fragment>
roughnessFactor = clamp(roughnessFactor + bnGrain(vGrainAt) * uGrain.w, 0.02, 1.0);
`;

// One set of uniform values per SUBSTANCE, shared by every material dressed
// with it -- the shared one, and any copy a glowing log or a see-through held
// thing needed of its own. Sharing the arrays rather than keeping a list of the
// materials means turning the room's grain down reaches every copy and that
// nothing here holds a material alive after the room has finished with it. A
// room where things break makes and drops these all day.
const LEVELS = new Map();
let showing = 1.0;

function levelsFor(name) {
  let held = LEVELS.get(name);
  if (!held) {
    const s = SURFACE[name] || NOTHING;
    held = { axis: [s.axis[0], s.axis[1], s.axis[2]],
             grain: [1 / s.across_m, s.along, s.tint * showing, s.rough * showing],
             fleck: [1 / s.fleck_m, s.fleck * showing],
             ring: [s.rings_m ? 1 / s.rings_m : 0, s.wobble || 0, s.ringy || 0,
                    s.ring_from_m || 0],
             of: s };
    LEVELS.set(name, held);
  }
  return held;
}

/**
 * Give a MeshStandardMaterial the grain of the substance named.
 *
 * Returns the same material. Safe to call twice; safe to call with a name the
 * table has never heard of, which gets the plainest grain there is rather than
 * nothing, because a substance nobody has described is still not a flat swatch.
 */
export function dress(material, name) {
  if (!material || material.userData.grainOf === name) return material;
  const levels = levelsFor(name);
  material.userData.grainOf = name;
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uGrainAxis = { value: levels.axis };
    shader.uniforms.uGrain = { value: levels.grain };
    shader.uniforms.uFleck = { value: levels.fleck };
    shader.uniforms.uRing = { value: levels.ring };
    shader.vertexShader = VERTEX_HEAD + shader.vertexShader
      .replace("#include <begin_vertex>", VERTEX_WRITE);
    shader.fragmentShader = FRAGMENT_HEAD + shader.fragmentShader
      .replace("#include <color_fragment>", COLOUR_WRITE)
      .replace("#include <roughnessmap_fragment>", ROUGH_WRITE);
    material.userData.grain = shader;
  };
  // Every dressed material injects the same source and differs only in what its
  // uniforms hold, so they can all share one compiled program -- which is the
  // point, because a material three has not seen before is a shader to compile
  // in the middle of a frame, and a pane coming apart makes a lot of materials
  // at once.
  material.customProgramCacheKey = () => "banjo-grain-1";
  material.needsUpdate = true;
  return material;
}

/** A dressed copy of a dressed material, for a body that needs one of its own. */
export function dressedClone(material) {
  const made = material.clone();
  // clone() carries the data but not the function, so a clone comes back plain
  // -- which is how a glowing log and a see-through held thing quietly lost
  // their grain the first time this was tried.
  made.userData.grainOf = undefined;
  return dress(made, material.userData.grainOf);
}

/** Turn the whole room's grain up or down. 1 is as written, 0 is flat. */
export function showGrain(amount) {
  showing = Math.max(0, Math.min(1, Number(amount)));
  for (const levels of LEVELS.values()) {
    levels.grain[2] = levels.of.tint * showing;
    levels.grain[3] = levels.of.rough * showing;
    levels.fleck[1] = levels.of.fleck * showing;
  }
  return showing;
}

/** Which substances are being drawn with a grain, and how much: for the tests. */
export function grainState() {
  return { substances: [...LEVELS.keys()].sort(), showing,
           grain: Object.fromEntries([...LEVELS].map(([name, l]) => [name, l.grain.slice()])) };
}
