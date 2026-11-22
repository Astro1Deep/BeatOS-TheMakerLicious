const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync(path.join(__dirname, '../templates/catalogo.html'), 'utf8');

const nodes = {};
const node = id => nodes[id] ||= {
  value: '', textContent: '', innerHTML: '', hidden: false, dataset: {},
  scrollIntoView() { this.scrolled = true; },
  focus() { this.focused = true; }
};

const RACK_PADS = Array(16).fill(null);
const RACK_BANKS = Array.from({ length: 10 }, () => Array(16).fill(null));
RACK_BANKS[0] = RACK_PADS;

const ctx = vm.createContext({
  document: { getElementById: node, querySelectorAll: () => [] },
  RACK_PADS,
  RACK_BANKS,
  PAD_COLORS: {},
  currentTargetPad: 1,
  currentRackBank: 0,
  getTargetHardwareProfile: () => ({ maxBanks: 8, maxPads: 128, labelEn: 'MPC', labelEs: 'MPC' }),
  getActiveBankLetter: idx => String.fromCharCode(65 + idx),
  formatPadTag: p => 'A0' + p,
  stopPadVoices() {},
  renderRackGrid() {},
  renderDockMatrix() {},
  renderPopoverGrid() {},
  updateRackCounts() {},
  updatePo33StudioView() {},
  switchTab() {},
  escapeHtml: s => s.replaceAll('<', '&lt;'),
  currentExpansionName: 'Test Exp',
  showToast() {},
  updateLibraryRackLinks() {}
});

// Load the rack bank switching logic
const switchLogic = html.slice(html.indexOf('function saveCurrentRackBank()'), html.indexOf('const PAD_KEY_MAP ='));
vm.runInContext(switchLogic + '\nthis.saveCurrentRackBank = saveCurrentRackBank; this.switchRackBank = switchRackBank; this.swapOrMoveRackBanks = swapOrMoveRackBanks; this.setImportedBanksRef = b => {};', ctx);

// Load the imported source mounting logic
const mountLogic = html.slice(html.indexOf('let importedSource ='), html.indexOf('async function loadProjectToRack('));
vm.runInContext(mountLogic + '\nthis.setImportedSource = setImportedSource; this.mountSourceBank = mountSourceBank; this.clearImportedSource = () => { importedSource = null; importedBanks = {}; sourceBank = 0; };', ctx);

// 1. Load Kit 1 into Bank A (targetBank: 0)
const kitA = {
  program_name: 'Drums_A',
  pads: {
    1: { sample_file: 'Kick_A.wav', rel_path: 'Kicks/Kick_A.wav', sound_type: 'kick', mute_group: 0, volume: 1, pan: 0, tune: 0 },
    2: { sample_file: 'Snare_A.wav', rel_path: 'Snares/Snare_A.wav', sound_type: 'snare', mute_group: 0, volume: 1, pan: 0, tune: 0 }
  }
};
ctx.setImportedSource(kitA, 'Drums_A.xpm', 'program', 0);

assert.equal(ctx.RACK_BANKS[0][0].filename, 'Kick_A.wav');
assert.equal(ctx.RACK_BANKS[0][1].filename, 'Snare_A.wav');
assert.equal(ctx.currentRackBank, 0);

// 2. Load Kit 2 into Bank B (targetBank: 1) without wiping Bank A
const kitB = {
  program_name: 'Perc_B',
  pads: {
    1: { sample_file: 'Conga_B.wav', rel_path: 'Perc/Conga_B.wav', sound_type: 'perc', mute_group: 0, volume: 1, pan: 0, tune: 0 },
    2: { sample_file: 'Bongo_B.wav', rel_path: 'Perc/Bongo_B.wav', sound_type: 'perc', mute_group: 0, volume: 1, pan: 0, tune: 0 }
  }
};
ctx.setImportedSource(kitB, 'Perc_B.xpm', 'program', 1);

// Bank B must be populated
assert.equal(ctx.RACK_BANKS[1][0].filename, 'Conga_B.wav');
assert.equal(ctx.RACK_BANKS[1][1].filename, 'Bongo_B.wav');
assert.equal(ctx.currentRackBank, 1);

// Bank A MUST STILL BE INTACT!
assert.equal(ctx.RACK_BANKS[0][0].filename, 'Kick_A.wav');
assert.equal(ctx.RACK_BANKS[0][1].filename, 'Snare_A.wav');

// 3. Switch back to Bank A
ctx.switchRackBank(0);
assert.equal(ctx.currentRackBank, 0);
assert.equal(ctx.RACK_PADS[0].filename, 'Kick_A.wav');
assert.equal(ctx.RACK_PADS[1].filename, 'Snare_A.wav');

// 4. Switch to Bank B
ctx.switchRackBank(1);
assert.equal(ctx.currentRackBank, 1);
assert.equal(ctx.RACK_PADS[0].filename, 'Conga_B.wav');
assert.equal(ctx.RACK_PADS[1].filename, 'Bongo_B.wav');

// 5. Test getActivePadsPayload across both banks
const getActiveLogic = html.slice(html.indexOf('function getActivePadsPayload()'), html.indexOf('function beatosExportDialogLines('));
vm.runInContext(getActiveLogic + '\nthis.getActivePadsPayload = getActivePadsPayload;', ctx);

const payload = ctx.getActivePadsPayload();
assert.equal(payload.length, 4, 'Should contain 2 pads from Bank A and 2 pads from Bank B');
const bankAItems = payload.filter(p => p.pad >= 1 && p.pad <= 16);
const bankBItems = payload.filter(p => p.pad >= 17 && p.pad <= 32);
assert.equal(bankAItems.length, 2);
assert.equal(bankBItems.length, 2);
assert.equal(bankAItems[0].rel_path, 'Kicks/Kick_A.wav');
assert.equal(bankBItems[0].rel_path, 'Perc/Conga_B.wav');

// 6. Test getSourceBankCount for multi-bank kits like #Dr#uMeR#TrES-AsSEs (Bank A + Bank F + Bank H)
vm.runInContext('this.getSourceBankCount = getSourceBankCount;', ctx);
assert.equal(ctx.getSourceBankCount(kitA), 1);
const multiBankKit = {
  program_name: '#Dr#uMeR#TrES-AsSEs',
  pads: {
    1: { sample_file: 'Kick.wav', rel_path: 'A/Kick.wav', sound_type: 'kick', mute_group: 1 },
    81: { sample_file: 'Chop1.wav', rel_path: 'F/Chop1.wav', sound_type: 'melodic', mute_group: 16 },
    118: { sample_file: 'Break.wav', rel_path: 'H/Break.wav', sound_type: 'loop', mute_group: 0 }
  }
};
assert.equal(ctx.getSourceBankCount(multiBankKit), 3);
ctx.setImportedSource(multiBankKit, '#Dr#uMeR#TrES-AsSEs.xpm', 'program', 'all');
ctx.switchRackBank(5);
assert.equal(ctx.RACK_PADS[0].filename, 'Chop1.wav');
ctx.switchRackBank(7);
assert.equal(ctx.RACK_PADS[5].filename, 'Break.wav');

// 7. Test bulk drag-and-drop bank moving and swapping via swapOrMoveRackBanks
ctx.clearImportedSource();
for (let b = 0; b < 8; b++) ctx.RACK_BANKS[b].fill(null);
ctx.RACK_PADS.fill(null);
ctx.currentRackBank = 0;
ctx.RACK_PADS[0] = { filename: 'Kick_01.wav', relPath: 'A/Kick_01.wav', soundType: 'KICK', muteGroup: 1 };
ctx.RACK_PADS[1] = { filename: 'Snare_01.wav', relPath: 'A/Snare_01.wav', soundType: 'SNARE', muteGroup: 3 };
ctx.saveCurrentRackBank();

// Move Bank A -> empty Bank C (idx 2)
assert.equal(ctx.swapOrMoveRackBanks(0, 2), true);
assert.equal(ctx.currentRackBank, 2);
assert.equal(ctx.RACK_BANKS[0].filter(Boolean).length, 0);
assert.equal(ctx.RACK_BANKS[2][0].filename, 'Kick_01.wav');
assert.equal(ctx.RACK_BANKS[2][1].filename, 'Snare_01.wav');
assert.equal(ctx.RACK_PADS[0].filename, 'Kick_01.wav');

// Populate Bank B (idx 1) and swap Bank C (idx 2) <-> Bank B (idx 1)
ctx.switchRackBank(1);
ctx.RACK_PADS[4] = { filename: 'Hat_05.wav', relPath: 'B/Hat_05.wav', soundType: 'HIHAT', muteGroup: 2 };
ctx.saveCurrentRackBank();
assert.equal(ctx.swapOrMoveRackBanks(2, 1), true);
assert.equal(ctx.RACK_BANKS[1][0].filename, 'Kick_01.wav');
assert.equal(ctx.RACK_BANKS[1][1].filename, 'Snare_01.wav');
assert.equal(ctx.RACK_BANKS[2][4].filename, 'Hat_05.wav');
const swappedPayload = ctx.getActivePadsPayload();
assert.equal(swappedPayload.some(p => p.pad === 17 && p.rel_path === 'A/Kick_01.wav'), true);
assert.equal(swappedPayload.some(p => p.pad === 37 && p.rel_path === 'B/Hat_05.wav'), true);

// 8. Swap on multi-bank imported kit before visiting destination bank (Bank F idx 5 <-> Bank D idx 3)
ctx.setImportedSource(multiBankKit, '#Dr#uMeR#TrES-AsSEs.xpm', 'program', 'all');
assert.equal(ctx.swapOrMoveRackBanks(5, 3), true);
assert.equal(ctx.RACK_BANKS[3][0].filename, 'Chop1.wav');
assert.equal(ctx.RACK_BANKS[5].filter(Boolean).length, 0);

console.log('Multi-bank assignment: target bank loading, independent bank preservation and multi-bank export payload OK');
