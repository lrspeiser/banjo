import * as THREE from "./vendor/three.module.js";

// Nearest-column material lookup on the existing collider triangles. This
// creates sharp material boundaries without adding steps or changing heights.
// RGBA stores linear color and the RunKind (255 means unexplored).
export function terrainMaterial(grid, colors, kindAt, seenAt) {
  const pixels=new Uint8Array(grid.nx*grid.nz*4);
  const texture=new THREE.DataTexture(pixels,grid.nx,grid.nz);
  texture.minFilter=texture.magFilter=THREE.NearestFilter;
  texture.generateMipmaps=false;
  const write=index=>{
    for(let c=0;c<3;c++) pixels[4*index+c]=Math.round(colors[3*index+c]*255);
    pixels[4*index+3]=seenAt(index)?kindAt(index):255;
  };
  for(let k=0;k<grid.nx*grid.nz;k++)write(k);
  texture.needsUpdate=true;
  const material=new THREE.MeshStandardMaterial({roughness:.96,metalness:0});
  material.userData.terrainTexture=texture;
  material.onBeforeCompile=shader=>{
    shader.uniforms.terrainCells={value:texture};
    shader.uniforms.terrainGrid={value:new THREE.Vector4(grid.x0,grid.z0,grid.dx,0)};
    shader.uniforms.terrainSize={value:new THREE.Vector2(grid.nx,grid.nz)};
    shader.vertexShader="varying vec3 terrainAt;\n"+shader.vertexShader.replace(
      "#include <begin_vertex>","#include <begin_vertex>\nterrainAt=(modelMatrix*vec4(transformed,1.0)).xyz;");
    shader.fragmentShader=`
varying vec3 terrainAt;
uniform sampler2D terrainCells;
uniform vec4 terrainGrid;
uniform vec2 terrainSize;
float terrainHash(vec2 p) { return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453); }
`+shader.fragmentShader.replace("#include <color_fragment>",`
#include <color_fragment>
vec2 column=(terrainAt.xz-terrainGrid.xy)/terrainGrid.z+.5;
vec2 cell=floor(column);
vec2 within=fract(column);
vec4 sampleCell=texture2D(terrainCells,(clamp(cell,vec2(0.),terrainSize-1.)+.5)/terrainSize);
float kind=floor(sampleCell.a*255.+.5);
float pattern=1.;
float noise=terrainHash(floor(terrainAt.xz/terrainGrid.z*12.));
if(kind<254.) {
  if(kind==2.) pattern=1.-.16*step(.8,noise);
  else if(kind==5.) pattern=1.-.20*step(.72,fract((within.x+within.y)*4.));
  else if(kind==6. || kind==7.) pattern=1.-.32*step(.74,noise);
  else if(kind==0. || kind==4.) {
    float crack=abs(within.x-.3-.16*sin(within.y*7.));
    pattern=1.-.22*(1.-smoothstep(.015,.035,crack));
  } else pattern=.91+.09*noise;
  // fwidth prevents a carpet of flickering fine lines in the distance.
  vec2 edge=min(within,1.-within);
  vec2 pixel=max(fwidth(column),vec2(.001));
  float line=1.-min(smoothstep(vec2(.015),vec2(.015)+pixel,edge).x,
                   smoothstep(vec2(.015),vec2(.015)+pixel,edge).y);
  float close=1.-smoothstep(.12,.45,max(pixel.x,pixel.y));
  pattern*=1.-.18*line*close;
}
diffuseColor.rgb=sampleCell.rgb*pattern;
`);
  };
  material.customProgramCacheKey=()=>"banjo-terrain-cells-1";
  return {material,update(index){write(index);texture.needsUpdate=true;},dispose(){texture.dispose();}};
}
