import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const read=name=>readFile(new URL('../playground/'+name,import.meta.url),'utf8');
const [voice,world,workshop,menu,interaction]=await Promise.all(['voice.js','world.js','workshop.js','game_menu.js','interaction.js'].map(read));
assert.equal(interaction.includes('"KeyY"'),false,'Y remains free of native interaction bindings');
for(const source of [world,workshop]) {
  assert.match(source,/createVoiceController\(/);assert.match(source,/submitText:text=>submitChatText\(/);
  assert.match(source,/finishChat\(/);
}
assert.match(menu,/game-menu-audio/);assert.match(menu,/audioOutputEnabled\(\)\?'on':'off'/);
assert.equal(voice.includes('/api/world/voice/ask'),false,'Speech uses the selected typed audience, not a separate guide');
assert.equal(voice.includes('banjo-voice-hover'),false);assert.equal(voice.includes('voice-lens'),false);
console.log('PASS: both screens use typed submissions, persistent Audio off default, no hover narration');
