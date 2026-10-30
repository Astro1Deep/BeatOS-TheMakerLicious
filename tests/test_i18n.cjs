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
ctx.change('es');
ctx.locale.refresh();
assert.equal(text.nodeValue,' Guardar Ajustes ');
assert.equal(sample.nodeValue,'My private sample.wav');
assert.equal(attrs.title,'Reproducir muestra del pad activo');
console.log('BeatOS ES/EN: reversible texts, tooltips and messages; sample paths unchanged OK');
