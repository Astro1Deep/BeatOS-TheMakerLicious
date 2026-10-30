const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname,'../templates/catalogo.html'),'utf8');
const sent = [];
let Processor;
class AudioWorkletProcessor { constructor() { this.port = {postMessage: data => sent.push(data)}; } }
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../docs/assets/po33-capture-worklet.js'),'utf8'), {
  AudioWorkletProcessor, Int16Array, Math, registerProcessor: (_, type) => { Processor = type; }
});
const capture = new Processor();
capture.process([[new Float32Array([1,-1,0.5]),new Float32Array([-0.5,0,0.25])]]);
capture.port.onmessage({data:'stop'});
assert.deepEqual([...new Int16Array(sent[0].pcm)],[32767,-16384,-32768,0,16384,8192]);
assert.equal(sent[1].stopped,true);assert.equal(capture.process([]),false);
sent.length = 0;
const mono = new Processor();mono.process([[new Float32Array([0.2])]]);
assert.match(sent[0].error,/dos canales/);assert.equal(sent.some(item=>item.pcm),false);

const elements = new Map(), audio = {pause(){this.paused=true;}};
const el = id => { if(!elements.has(id)) elements.set(id, {textContent:'',hidden:true,disabled:false,scrollIntoView(){}}); return elements.get(id); };
elements.set('po33RestoreAudio',audio);
let confirmation=false, stopped=0;
const context=vm.createContext({Blob,ArrayBuffer,DataView,Date,URL,setTimeout,clearTimeout,clearInterval,
  document:{getElementById:el,querySelectorAll:()=>[audio]}, window:{addEventListener(){}},
  confirm:()=>confirmation,stopPadVoices:()=>stopped++,getApiBaseUrl:()=> 'http://127.0.0.1:8888',
  fetch:async()=>{throw Error('not expected');}});
vm.runInContext(html.slice(html.indexOf('// PO-33 backup capture and archive:'),html.indexOf('// Carga de inventario de backups')) + '\nthis.makeWav=po33PcmWav;this.restore=preparePo33Restore;',context);
(async()=>{
  const wav = context.makeWav([new Int16Array([1234,-6789]).buffer],48000);
  const bytes=Buffer.from(await wav.arrayBuffer());
  assert.equal(bytes.toString('ascii',0,4),'RIFF');assert.equal(bytes.readUInt16LE(22),2);
  assert.equal(bytes.readUInt32LE(24),48000);assert.equal(bytes.readUInt32LE(40),4);
  assert.equal(bytes.readInt16LE(44),1234);assert.equal(bytes.readInt16LE(46),-6789);
  const backup={audio_compatible:true,path:'/archive/name #1.wav',filename:'name #1.wav'};
  context.restore(backup);assert.equal(audio.src,undefined);
  confirmation=true;context.restore(backup);assert.ok(audio.src.endsWith('%2Farchive%2Fname%20%231.wav'));
  assert.equal(audio.playbackRate,1);assert.equal(audio.loop,false);assert.equal(audio.paused,true);
  assert.equal(audio.play,undefined);assert.equal(stopped,1);assert.equal(el('po33RestoreBox').hidden,false);
  const before=audio.src;context.restore({...backup,audio_compatible:false,path:'/bad.wav'});assert.equal(audio.src,before);
  context.restore({...backup,capture_interrupted:true,path:'/partial.wav'});assert.equal(audio.src,before);
  console.log('PO-33: stereo PCM order, WAV header, mono refusal, explicit restore confirmation and no autoplay OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
