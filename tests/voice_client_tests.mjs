import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { targetNarration } from "../playground/voice.js";

const interaction=await readFile(new URL("../playground/interaction.js",import.meta.url),"utf8");
assert.equal(interaction.includes('"KeyY"'),false,
  "Hold Y must remain free of Banjo's existing interaction bindings");

const plain=targetNarration({
  identity:"body:oak stool:7",
  rows:[{label:"Oak stool",value:"Whole item",action:null,kind:"product"}],
});
assert.equal(plain.text,"Oak stool.");
assert.equal(plain.helpful,false);

const pickup=targetNarration({
  identity:"body:oak stool:7",
  rows:[{label:"Oak stool",value:"Whole item",action:"E · Pick up",kind:"product"}],
});
assert.equal(pickup.text,"Oak stool. Pick up.");
assert.equal(pickup.helpful,true);
assert.notEqual(pickup.key,plain.key);

const pile=targetNarration({
  identity:"pile:copper pile 1",
  rows:[{label:"Copper",value:"4.2 kg",action:"Collect",kind:"pile"}],
});
assert.equal(pile.text,"Copper. 4.2 kg. Collect.");
assert.equal(pile.helpful,true);

const blocked=targetNarration({
  identity:"ground:22:sand",
  rows:[{label:"Sand",value:"Possible yield",action:null,kind:"surface"}],
  feedback:{state:"blocked",ready:false,action:"Move closer",reason:"That point is outside the tool's reach.",
    materials:["sand"]},
});
assert.equal(blocked.helpful,true);
assert.match(blocked.text,/Sand/);
assert.match(blocked.text,/Move closer/);
assert.match(blocked.text,/outside the tool's reach/);

const sameWithIrrelevantPresentation=targetNarration({
  identity:"ground:22:sand",
  rows:[{label:"Sand",value:"Possible yield",action:null,kind:"surface"}],
  feedback:{state:"blocked",ready:false,action:"Move closer",reason:"That point is outside the tool's reach.",
    materials:["sand"]},
  nearby:[["other","iron","Material pile",3]],
  frame:999,
});
assert.equal(sameWithIrrelevantPresentation.key,blocked.key,
  "frame/nearby presentation must not make the same target speak again");

const ready=targetNarration({
  identity:"ground:22:sand",
  rows:[{label:"Sand",value:"Possible yield",action:null,kind:"surface"}],
  feedback:{state:"ready",ready:true,action:"Dig",reason:null,materials:["sand"]},
});
assert.notEqual(ready.key,blocked.key,"a changed useful action must be narratable");
assert.equal(ready.helpful,true);
assert.equal(ready.text,"Sand. Possible yield. Dig.");

const machineInput=targetNarration({
  identity:"pile:mill intake",
  machine_input:true,
  rows:[{label:"Copper",value:"1.0 kg",action:"Machine input",kind:"pile"}],
});
assert.equal(machineInput.helpful,true);

assert.equal(targetNarration(null),null);
assert.equal(targetNarration({identity:"empty",rows:[]}),null);

console.log("PASS: deterministic voice lens narration and semantic dedupe");
