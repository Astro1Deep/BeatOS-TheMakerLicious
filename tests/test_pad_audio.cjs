const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '../templates/catalogo.html'), 'utf8');
const source = html.slice(html.indexOf('function defaultMuteGroup('), html.indexOf('function triggerPadAudio('));
const made = [];
const errors = [];
class Audio {
  constructor(src) { this.src = src; this.paused = false; made.push(this); }
  play() { return Promise.resolve(); }
  pause() { this.paused = true; }
}
const ctx = vm.createContext({Audio, URL, document: {baseURI:'http://127.0.0.1:8888/'}, location: {protocol: 'http:', pathname: '/'}, showToast: m => errors.push(m)});
vm.runInContext(source + '\nthis.play = playPadVoice; this.stop = stopPadVoices; this.voices = padVoices; this.group = defaultMuteGroup;', ctx);
const pad = (soundType, muteGroup) => ({soundType, muteGroup, relPath: 'Samples/kick #1.wav', filename: 'kick.wav'});
ctx.play(1, pad('KICK')); ctx.play(2, pad('HIHAT')); ctx.play(3, pad('SNARE')); ctx.play(4, pad('BASS_808'));
assert.equal(ctx.voices.size, 4); assert.ok(made.every(a => !a.paused));
ctx.play(5, pad('KICK')); assert.equal(made[0].paused, true); assert.equal(made[1].paused, false); assert.equal(ctx.voices.size, 4);
ctx.play(6, pad('HIHAT', 0)); ctx.play(7, pad('HIHAT')); assert.equal(made[1].paused, true); assert.equal(made[5].paused, false);
ctx.play(8, pad('FX', 9)); ctx.play(9, pad('VOCAL', 9)); assert.equal(made[7].paused, true);
const previous = made.at(-1); ctx.play(9, pad('VOCAL', 0)); previous.onended(); assert.ok(ctx.voices.has(9));
assert.equal(made[0].src, 'http://127.0.0.1:8888/Samples/kick%20%231.wav');
ctx.stop(); assert.equal(ctx.voices.size, 0); assert.ok(made.every(a => a.paused)); assert.equal(errors.length, 0);
assert.equal(ctx.group('CYMBAL'), 0); assert.equal(ctx.group('SNARE'), 3);
console.log('Pad audio: polyphony, family choke, explicit zero, custom groups, stale callbacks and cleanup OK');

vm.runInContext(html.slice(html.indexOf('function detectSoundTypeFromFilename('), html.indexOf('async function copyLibraryPath(')) + '\nthis.detect = detectSoundTypeFromFilename;', ctx);
for (const name of ['GS_END_Shaker_0_4.wav', 'Crash_01.wav', 'Bass808.wav']) assert.equal(ctx.group(ctx.detect(name)), 0);

vm.runInContext('const RACK_PADS = Array(16).fill(null); RACK_PADS[0] = {filename:"Kick.wav",relPath:"Kick.wav",soundType:"KICK",muteGroup:0,volume:0.3,pan:0.1,tune:-3};\n' + html.slice(html.indexOf('function getActivePadsPayload('),html.indexOf('function exportKitToHardware(')) + '\nthis.payload = getActivePadsPayload;',ctx);
const exported=ctx.payload()[0];assert.equal(exported.mute_group,0);assert.equal(exported.volume,0.3);assert.equal(exported.pan,0.1);assert.equal(exported.tune,-3);

const pans = [];
class AudioContext {
  constructor(){this.destination={};}
  createMediaElementSource(){return {connect(){},disconnect(){}};}
  createStereoPanner(){const node={pan:{value:0},connect(){},disconnect(){}};pans.push(node);return node;}
  resume(){return Promise.resolve();}
}
ctx.AudioContext=AudioContext;
ctx.play(1,{...pad('KICK',0),pan:0});ctx.play(2,{...pad('HIHAT',0),pan:1});
assert.deepEqual(pans.map(p=>p.pan.value),[-1,1]);ctx.stop();
console.log('Pad panorama: left/right graph and cleanup OK');
