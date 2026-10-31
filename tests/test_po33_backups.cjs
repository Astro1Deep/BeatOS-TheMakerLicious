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
const el = id => { if(!elements.has(id)) elements.set(id, {textContent:'',innerHTML:'',value:'',style:{},children:[],append(...nodes){this.children.push(...nodes)},replaceChildren(){this.children=[]},hidden:true,disabled:false,scrollIntoView(){}}); return elements.get(id); };
elements.set('po33RestoreAudio',audio);
let confirmation=false, stopped=0;
let beforeUnload;
const context=vm.createContext({Blob,ArrayBuffer,DataView,Date,URL,setTimeout,clearTimeout,clearInterval,
  document:{getElementById:el,querySelectorAll:()=>[audio],createElement:()=>({style:{},click(){}})}, window:{addEventListener:(_,callback)=>{beforeUnload=callback}},
  currentLang:'en',confirm:()=>confirmation,localizeUiMessage:message=>message,stopPadVoices:()=>stopped++,getApiBaseUrl:()=> 'http://127.0.0.1:8888',
  fetch:async()=>{throw Error('not expected');}});
vm.runInContext(html.slice(html.indexOf('const PO_BACKUP_BUTTONS'),html.indexOf('// Carga de inventario de backups')) + '\nthis.makeWav=po33PcmWav;this.restore=preparePo33Restore;',context);
(async()=>{
  const wav = context.makeWav([new Int16Array([1234,-6789]).buffer],48000);
  const bytes=Buffer.from(await wav.arrayBuffer());
  assert.equal(bytes.toString('ascii',0,4),'RIFF');assert.equal(bytes.readUInt16LE(22),2);
  assert.equal(bytes.readUInt32LE(24),48000);assert.equal(bytes.readUInt32LE(40),4);
  assert.equal(bytes.readInt16LE(44),1234);assert.equal(bytes.readInt16LE(46),-6789);
  el('poBackupModel').value='PO-33';
  const backup={audio_compatible:true,model:'PO-33',path:'/archive/name #1.wav',filename:'name #1.wav'};
  context.restore(backup);assert.equal(audio.src,undefined);
  confirmation=true;context.restore(backup);assert.ok(audio.src.endsWith('%2Farchive%2Fname%20%231.wav'));
  assert.equal(audio.playbackRate,1);assert.equal(audio.loop,false);assert.equal(audio.paused,true);
  assert.equal(audio.play,undefined);assert.equal(stopped,1);assert.equal(el('po33RestoreBox').hidden,false);
  const before=audio.src;
  context.restore({...backup,model:'PO-35',path:'/different-model.wav'});assert.equal(audio.src,before);context.restore({...backup,audio_compatible:false,path:'/bad.wav'});assert.equal(audio.src,before);
  context.restore({...backup,capture_interrupted:true,path:'/partial.wav'});assert.equal(audio.src,before);
  let failUpload;
  context.fetch=()=>new Promise((_,reject)=>{failUpload=reject});
  el('po33RecordingName').value='Take';
  const finished=vm.runInContext('finishPo33Recording({chunks:[new Int16Array([1234,-5678]).buffer],rate:48000,bytes:4})',context);
  assert.equal(vm.runInContext('po33Recorder',context),null);
  assert.equal(vm.runInContext('po33PendingArchives',context),1);
  let warned=false;beforeUnload({preventDefault(){warned=true}});assert.equal(warned,true);
  failUpload(new Error('SD unavailable'));await finished;
  assert.equal(vm.runInContext('po33PendingArchives',context),0);
  assert.equal(vm.runInContext('po33UnsavedCaptures.size',context),1);
  const recovery=el('po33RecoveryDownloads').children[0];assert.match(recovery.href,/^blob:/);assert.match(recovery.textContent,/Descargar grabación/);
  warned=false;beforeUnload({preventDefault(){warned=true}});assert.equal(warned,true);
  URL.revokeObjectURL(recovery.href);
  vm.runInContext('po33UnsavedCaptures.clear();this.loadPo33BackupsList=async()=>{};',context);

  vm.runInContext('const RACK_PADS=[{filename:"kick.wav",durationSec:2,tune:12},{filename:"hat.wav",durationSec:2,tune:0}];',context);
  context.escapeHtml=value=>value;
  vm.runInContext(html.slice(html.indexOf('function getPadDurationSec('),html.indexOf('// PO-33 backup capture and archive:')),context);
  el('poBudget').value='1';el('poGap').value='200';vm.runInContext('updatePo33StudioView()',context);
  assert.match(el('po33SlicesTableBody').innerHTML,/200 ms/);assert.match(el('po33BudgetText').innerHTML,/1\.00s \/ 1\.00s/);
  el('poBudget').value='3';el('poGap').value='0';vm.runInContext('updatePo33StudioView()',context);
  assert.match(el('po33BudgetText').innerHTML,/3\.00s \/ 3\.00s/);assert.match(el('po33SlicesTableBody').innerHTML,/0 ms/);
  el('poBudget').value='1';el('poGap').value='500';vm.runInContext('updatePo33StudioView()',context);
  assert.equal(el('po33FreeTime').textContent,'Presupuesto no válido');

  const responses=[];context.fetch=()=>new Promise(resolve=>responses.push(resolve));
  vm.runInContext('let po33BackupsCache=[];'+html.slice(html.indexOf('// Carga de inventario de backups'),html.indexOf('let poReelBusy =')),context);
  const old=vm.runInContext('loadPo33BackupsList()',context),fresh=vm.runInContext('loadPo33BackupsList()',context);
  responses[1]({ok:true,json:async()=>({success:true,backups:[]})});await fresh;
  responses[0]({ok:false,json:async()=>({success:false,error:'stale error'})});await old;
  assert.equal(el('po33BackupsList').textContent,'No se encontraron WAV en las carpetas de respaldos.');
  console.log('PO-33: stereo PCM order, WAV header, mono refusal, explicit restore confirmation and no autoplay OK');
  console.log('PO-33 recovery: visible retained WAV after failed upload, unload guard, selected reel settings and stale inventory protection OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
