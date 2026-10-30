const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync(path.join(__dirname, '../templates/catalogo.html'), 'utf8');
const start = html.indexOf('const BEATOS_UI_EN = ');
const end = html.indexOf('function setLanguage(', start);
assert.ok(start > -1 && end > start, 'reversible locale engine must exist');

const attrs = {title:'Reproducir muestra del pad activo'};
const titleEl = {
  hasAttribute: name => Object.prototype.hasOwnProperty.call(attrs, name),
  getAttribute: name => attrs[name],
  setAttribute: (name, value) => {attrs[name]=value;}
};
const text = {nodeValue:' Guardar Ajustes ',parentElement:{tagName:'BUTTON'}};
const sample = {nodeValue:'My private sample.wav',parentElement:{tagName:'SPAN'}};
const body = {
  hasAttribute:()=>false,
  querySelectorAll:()=>[titleEl]
};
const ctx = vm.createContext({
  document: {
    body,
    createTreeWalker: () => {
      const nodes = [text, sample];
      return {nextNode: () => nodes.shift() || null};
    }
  },
  Promise,
  WeakMap,
  Object,
  MutationObserver:undefined
});
vm.runInContext('let currentLang = "en";\n' + html.slice(start,end) + '\nthis.locale={refresh:refreshBeatOsLocale, message:localizeUiMessage};this.change=(lang)=>{currentLang=lang;};',ctx);
ctx.locale.refresh();
assert.equal(text.nodeValue,' Save settings ');
assert.equal(sample.nodeValue,'My private sample.wav');
assert.equal(attrs.title,'Play active pad sample');
assert.equal(ctx.locale.message('No se pudo reproducir: Kick.wav'),'Could not play: Kick.wav');
assert.equal(ctx.locale.message('⚠️ Asigna al menos 1 sonido a los pads antes de exportar.'),'⚠️ Assign at least one sample before exporting.');
// Regression: each major producer workflow must have translated text in English.
const phrases = [
  ['Quitar filtro de expansión','Clear expansion filter'],
  ['📻 Módem FSK & Restauración de Backups','📻 FSK modem & backup restore'],
  ['⏺ Grabar backup','⏺ Record backup'],
  ['🎹 Mapeo Físico de Teclas EP-133 (12 Teclas por Grupo):','🎹 EP-133 physical key map (12 keys per group):'],
  ['🔄 Ejecutar Reindexación Completa','🔄 Reindex entire library'],
  ['🧹 Optimización para Hardware MPC & SP-404','🧹 MPC & SP-404 maintenance'],
  ['🔄 Comprobar conexión EP Hub','🔄 Check EP Hub connection'],
  ['🎛️ Asignación Específica por Sampler:','🎛️ Sampler-specific mapping:']
];
for (const [spanish,english] of phrases) {
  const actual=vm.runInContext('beatosTranslateExact('+JSON.stringify(spanish)+')',ctx);
  assert.equal(actual,english,'Missing EN translation for: '+spanish);
}
assert.equal(ctx.locale.message('Restaurar en el PO-33 BORRA todos sus sonidos y patrones actuales. ¿Has conservado su backup y quieres preparar la reproducción?'), 'Restoring on the PO-33 ERASES all its current sounds and patterns. Have you backed up the device and do you want to prepare playback?');
ctx.change('es');
ctx.locale.refresh();
assert.equal(text.nodeValue,' Guardar Ajustes ');
assert.equal(sample.nodeValue,'My private sample.wav');
assert.equal(attrs.title,'Reproducir muestra del pad activo');
// Denied browser storage must not stop the audio UI from loading or switching languages.
const deniedStorage={getItem(){throw new Error('storage disabled');},setItem(){throw new Error('storage disabled');}};
const initSource=html.slice(html.indexOf('let currentLang = '),html.indexOf('\n\nconst I18N ='));
const initCtx=vm.createContext({localStorage:deniedStorage});
assert.doesNotThrow(()=>vm.runInContext(initSource+'; this.detected=currentLang;',initCtx));
assert.equal(initCtx.detected,'es');
const setterSource=html.slice(html.indexOf('const I18N ='),html.indexOf('function toggleLanguage()'));
const fakeDoc={documentElement:{lang:'es'},getElementById(){return null;}};
const setterCtx=vm.createContext({localStorage:deniedStorage,document:fakeDoc,refreshBeatOsLocale(){}});
vm.runInContext('let currentLang="es";\n'+setterSource+';\nthis.switchLang=setLanguage;',setterCtx);
assert.doesNotThrow(()=>setterCtx.switchLang('en'));
assert.equal(fakeDoc.documentElement.lang,'en');

// Regression: the visible gain slider must never produce an export-invalid gain.
const gainSlider=html.match(/<input[^>]+id="padEditVol"[^>]+max="([0-9.]+)"/);
assert.ok(gainSlider, 'pad volume slider exists');
assert.ok(Number(gainSlider[1]) / 141.25 <= 1, 'maximum slider gain must not exceed the API limit');

const poSummaryStart = html.indexOf('function beatosPoBackupInfoText(');
assert.ok(poSummaryStart >= 0, 'PO backup metadata needs a locale-safe formatter');
const poSummaryEnd = html.indexOf('async function loadPo33BackupsList(', poSummaryStart);
assert.ok(poSummaryEnd > poSummaryStart, 'PO backup formatter boundary');
const poContext=vm.createContext({});
vm.runInContext('let currentLang="en";\n' + html.slice(poSummaryStart,poSummaryEnd) + ';this.poText=beatosPoBackupInfoText;this.setLanguage=(lang)=>{currentLang=lang;}',poContext);
const sampleBackup={duration_sec:2,channels:2,bit_depth:16,sample_rate:44100,audio_compatible:false,clipping:true};
const enDetail=poContext.poText(sampleBackup);
assert.match(enDetail,/channels/);
assert.match(enDetail,/Modem payload NOT verified/);
assert.match(enDetail,/Unsupported format or incomplete/);
assert.doesNotMatch(enDetail,/canales|Datos del módem/);
poContext.setLanguage('es');
const esDetail=poContext.poText(sampleBackup);
assert.match(esDetail,/canales/);
assert.match(esDetail,/Datos del módem NO verificados/);


// PO-33 critical recorder/restore states must be localized (not just static UI labels).
const poStatusStart=html.indexOf('function setPo33BackupStatus(');
const poStatusEnd=html.indexOf('function po33PcmWav(',poStatusStart);
assert.ok(poStatusStart>0 && poStatusEnd>poStatusStart,'PO backup status function found');
const poStatusEl={textContent:''};
const poStatusCtx=vm.createContext({document:{getElementById:()=>poStatusEl}});
vm.runInContext('let currentLang="en";\n'+html.slice(start,end)+'\n'+html.slice(poStatusStart,poStatusEnd)+';this.report=setPo33BackupStatus;this.refresh=refreshPo33BackupStatus;this.lang=(value)=>{currentLang=value;};',poStatusCtx);
poStatusCtx.report('La grabación está vacía; no se ha guardado.');
assert.equal(poStatusEl.textContent,'The recording is empty; nothing was saved.');
poStatusCtx.report('WAV guardado sin modificar. SHA-256: abc123. Datos del módem no verificados.');
assert.equal(poStatusEl.textContent,'Original WAV saved unmodified. SHA-256: abc123. Modem data not verified.');
poStatusCtx.report('Restaurar en el PO-33 BORRA todos sus sonidos y patrones actuales. ¿Has conservado su backup y quieres preparar la reproducción?');
assert.match(poStatusEl.textContent,/ERASES/);
poStatusCtx.lang('es');
poStatusCtx.refresh();
assert.equal(poStatusEl.textContent,'Restaurar en el PO-33 BORRA todos sus sonidos y patrones actuales. ¿Has conservado su backup y quieres preparar la reproducción?');
poStatusCtx.lang('en');
poStatusCtx.refresh();
assert.match(poStatusEl.textContent,/ERASES/);
poStatusCtx.lang('es');
poStatusCtx.report('La grabación está vacía; no se ha guardado.');
assert.equal(poStatusEl.textContent,'La grabación está vacía; no se ha guardado.');

// Expansion kit cards are generated HTML, not static labels; verify both full renders.
const cardsStart=html.indexOf('function renderExpansionProgramsList(');
const cardsEnd=html.indexOf('function previewExpansionSample(',cardsStart);
assert.ok(cardsStart>=0&&cardsEnd>cardsStart,'Expansion program renderer found');
const expansionNode={innerHTML:''};
const expansionCtx=vm.createContext({
  document:{getElementById:id=>id==='expansionProgramsGrid'?expansionNode:null},
  currentExpansionPrograms:[{rel_path:'kits/Kick.xpm'}],
  currentLoadedKitRelPath:'',
  currentExpansionName:'Artist Samples',
  escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;'),
});
vm.runInContext('let currentLang="en";\n'+html.slice(cardsStart,cardsEnd)+'\nthis.draw=renderExpansionProgramsList;this.lang=v=>{currentLang=v;}',expansionCtx);
const kit={rel_path:'kits/Kick.xpm',program_type:'drum',name:'User Original Kick Kit',sub_category:'Artist Samples',pad_count:1,first_sample_rel:'samples/Kick.wav'};
expansionCtx.draw([kit]);
assert.match(expansionNode.innerHTML,/Edit copy in rack/);
assert.match(expansionNode.innerHTML,/Listen to sample/);
assert.match(expansionNode.innerHTML,/User Original Kick Kit/);
assert.doesNotMatch(expansionNode.innerHTML,/Editar copia|Escuchar muestra|Mostrar archivo|Copiar ruta/);
expansionCtx.lang('es');
expansionCtx.draw([kit]);
assert.match(expansionNode.innerHTML,/Editar copia en rack/);
assert.match(expansionNode.innerHTML,/User Original Kick Kit/);
console.log('BeatOS ES/EN: reversible texts, tooltips and messages; sample paths unchanged OK');
