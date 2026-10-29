const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'templates/catalogo.html'),'utf8');
const artist={src:'',parentElement:{dataset:{}}},backdrop={src:'original-patchbay.jpg'},hero={src:''},header={style:{}},nodes={creatorArtistMark:artist,heroBannerImg:hero};
const rack=[{sample:'original.wav',muteGroup:0,tune:3}];
const context=vm.createContext({document:{documentElement:{setAttribute(){}},body:{setAttribute(){},style:{}},getElementById:id=>nodes[id]||null,querySelector:selector=>selector==='.hero-banner'?header:null},localStorage:{setItem(){}},RACK_PADS:rack,fetch(){throw Error('A local theme preview must not update the backend');}});
vm.runInContext(html.slice(html.indexOf('const ECOSYSTEM_THEMES ='),html.indexOf('function cycleEcosystemTheme('))+'\nthis.themes=ECOSYSTEM_THEMES;this.apply=setEcosystemTheme;',context);
const seen=new Set();
for(const theme of context.themes){
 context.apply(theme.id,false);seen.add(artist.src);
 assert.equal(artist.parentElement.dataset.art,theme.creatorArt);
 assert.equal(hero.src,theme.banner);assert.equal(backdrop.src,'original-patchbay.jpg');
 assert.deepEqual(rack,[{sample:'original.wav',muteGroup:0,tune:3}]);
 const data=fs.readFileSync(path.join(root,artist.src));assert.equal(data.subarray(1,4).toString(),'PNG');
}
assert.equal(context.themes.length,8);assert.equal(seen.size,5);
context.apply('invalid-theme',false);assert.equal(artist.parentElement.dataset.art,'eye-mirror-compact');
delete nodes.creatorArtistMark;assert.doesNotThrow(()=>context.apply('makerlicious-bone',false));
assert.equal((html.match(/id="creatorArtistMark"/g)||[]).length,1);
assert.match(html,/<h1>BeatOS<\/h1>\s*<p class="brand-edition">The MakerLicious<\/p>\s*<p class="brand-description">\[universal beatmaker station\]<\/p>/);
assert.match(html,/alt="Cohete del sello digital"/);assert.ok(fs.existsSync(path.join(root,'docs/assets/branding/creator/label-rocket.png')));
console.log('Creator identity: eight themes, five original eye variants, stable banner/backdrop/rack, safe theme fallback and legacy markup OK');

const head=html.slice(html.indexOf('<header class="beatos-brand"'),html.indexOf('</header>'));
assert.ok(!head.includes('creator-signature'));assert.ok(!html.includes('creator-caption'));
const footer=html.slice(html.indexOf('<div class="audio-player-bar"'),html.indexOf('<div id="toast"'));
assert.ok(footer.indexOf('id="creatorArtistMark"') < footer.indexOf('id="audioPlayer"'));
assert.ok(footer.indexOf('id="audioPlayer"') < footer.indexOf('creator/label-rocket.png'));assert.ok(!footer.includes('Diseño y desarrollo'));
assert.match(html,/mix-blend-mode:screen/);assert.match(html,/mix-blend-mode:multiply/);
console.log('Player branding: eye before audio, rocket after audio, no header credits or caption typography OK');
