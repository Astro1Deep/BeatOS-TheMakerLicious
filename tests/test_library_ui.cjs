const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../templates/catalogo.html'),'utf8');
const nodes={}; const node=id=>nodes[id] ||= {value:'',textContent:'',innerHTML:'',hidden:false};
const ctx=vm.createContext({document:{getElementById:node},RACK_PADS:Array(16).fill(null),PAD_COLORS:{},stopPadVoices(){},renderRackGrid(){},renderDockMatrix(){},updateRackCounts(){},updatePo33StudioView(){},switchTab(){},escapeHtml:s=>s.replaceAll('<','&lt;'),currentExpansionName:'Test',updateLibraryRackLinks(){}});
const source=html.slice(html.indexOf('let importedSource ='),html.indexOf('async function loadProjectToRack('));
vm.runInContext(source+'\nthis.set=setImportedSource; this.bank=mountSourceBank;',ctx);
ctx.set({program_name:'Banks',pads:{1:{sample_file:'Kick',rel_path:'Kick.wav',mute_group:0,volume:.4,pan:.3,tune:2},128:{sample_file:'Hat',rel_path:'Hat.wav',mute_group:9},2:{sample_file:'Missing',missing:true}}},'kit.xpm','program');
assert.equal(ctx.RACK_PADS[0].muteGroup,0);assert.equal(ctx.RACK_PADS[1],null);
ctx.RACK_PADS[0].tune=5;ctx.bank(7);assert.equal(ctx.RACK_PADS[15].muteGroup,9);ctx.bank(0);assert.equal(ctx.RACK_PADS[0].tune,5);
assert.match(nodes.rackSourceNotice.textContent,/1 muestras ausentes/);
console.log('Library UI: bank H, pad gaps, explicit mute zero, missing files and edited bank restoration OK');

vm.runInContext(html.slice(html.indexOf('function getLibraryView('),html.indexOf('function filterLibraryCards(')) + '\nthis.libraryView=getLibraryView;',ctx);
const cards=Array.from({length:61},(_,i)=>({dataset:{name:'Kit '+i,search:'Kit '+i+' /Library/Kit'+i,kind:i<13?'sessions':'kits',tempo:String(60+i),count:String(i)}}));
let view=ctx.libraryView(cards,'','','name',1);assert.equal(view.visible.length,24);assert.equal(view.pages,3);assert.equal(view.visible[2].dataset.name,'Kit 2');
view=ctx.libraryView(cards,'','sessions','tempo',9);assert.equal(view.page,1);assert.equal(view.matches.length,13);
view=ctx.libraryView(cards,'Kit 60','','name',3);assert.equal(view.page,1);assert.equal(view.visible.length,1);
view=ctx.libraryView(cards,'missing','','name',1);assert.equal(view.visible.length,0);assert.equal(view.pages,1);
view=ctx.libraryView(cards,'','','count',1);assert.equal(view.visible[0].dataset.name,'Kit 60');
vm.runInContext(html.slice(html.indexOf('function matchesSampleLibraryScope('),html.indexOf('function viewExpansionSamples('))+'\nthis.inScope=matchesSampleLibraryScope;',ctx);
const sample=path=>Array(10).fill('').concat(path);const scope={path:'Expansions/Kit'};
assert.equal(ctx.inScope(sample('Expansions/Kit/a.wav'),scope),true);
assert.equal(ctx.inScope(sample('Expansions/Kit2/a.wav'),scope),false);
assert.equal(ctx.inScope(sample('Elsewhere/a.wav'),null),true);
console.log('Library menus: natural sorting, numeric sorting, page bounds, sessions, empty search and exact expansion scope OK');

const selected=[];ctx.currentExpansionPrograms=[{program_type:'Drum'},{program_type:'Keygroup'},{program_type:'Drum'}];ctx.currentLoadedKitIdx=0;ctx.selectAndLoadExpansionKit=i=>selected.push(i);ctx.showToast=()=>{};
vm.runInContext(html.slice(html.indexOf('function editableExpansionPrograms('),html.indexOf('function openCurrentExpansionModal('))+'\nthis.step=stepExpansionProgram;',ctx);
ctx.step(1);assert.equal(selected.pop(),2);ctx.currentLoadedKitIdx=2;ctx.step(1);assert.equal(selected.pop(),0);ctx.currentLoadedKitIdx=0;ctx.step(-1);assert.equal(selected.pop(),2);
console.log('Expansion navigation skips native Keygroup programs and wraps correctly');

view=ctx.libraryView(cards,'60 Kit','','name',1);assert.equal(view.visible.length,1);assert.equal(view.visible[0].dataset.name,'Kit 60');
let padKeyHandler;const triggered=[];
const keyCtx=vm.createContext({window:{addEventListener:(name,fn)=>padKeyHandler=fn},KEY_TO_PAD_MAP:{z:1},triggerPadAudio:n=>triggered.push(n)});
vm.runInContext(html.slice(html.indexOf('// Captura de teclado QWERTY'),html.indexOf('function getActivePadsPayload(')),keyCtx);
padKeyHandler({key:'z',target:{tagName:'BUTTON',closest:()=>({})}});assert.equal(triggered.length,0);
padKeyHandler({key:'z',target:{tagName:'BODY',closest:()=>null}});assert.deepEqual(triggered,[1]);
console.log('Multiword search and modal isolation from pad keyboard OK');
