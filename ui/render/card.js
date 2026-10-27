// Card renderer (see card.css). Open render.html?game=classic&id=10001[&lang=english].
// window.renderDone is set once the card and its images are drawn (for screenshots).

const TYPE = { HERO: 6, CREEP: 4, SPELL: 7, IMPROVEMENT: 9, ITEM: 5, ABILITY: 8, MUTATION: 1, STRONGHOLD: 2, PATHING: 3 };
const FILES = ['heroes', 'creeps', 'spells', 'improvements', 'items', 'abilities', 'mutations', 'default', 'other'];
const ITEM_BADGE = { Weapon: 'weapon', Armor: 'armor', Accessory: 'health', Consumable: 'consumable' };

function installFilters() {
  if (document.getElementById('card-filters')) return;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.id = 'card-filters';
  svg.setAttribute('width', '0'); svg.setAttribute('height', '0');
  svg.style.position = 'absolute';
  let html = `<filter id="warm" color-interpolation-filters="sRGB"><feColorMatrix type="matrix"
    values="1.224 0 0 0 0  0 1.147 0 0 0  0 0 1.094 0 0  0 0 0 1 0"/></filter>
    <filter id="title-tint" color-interpolation-filters="sRGB"><feColorMatrix type="matrix"
    values="0.953 0 0 0 0  0 0.925 0 0 0  0 0 0.878 0 0  0 0 0 1 0"/></filter>`;
  svg.innerHTML = html;
  document.body.prepend(svg);
}

// The improvement ring's points, measured on Valve's renders: three for a passive
// improvement (tips at radius 67, 11 degrees wide), six for an active one (radius 62, 11
// degrees); each point's two faces have the grey the render's lighting gives them.
const RING = {
  3: { tip: 67, half: 11, faces: [[85, 111], [215, 87], [88, 110]] },
  6: { tip: 62, half: 11, faces: [[88, 110], [107, 88], [203, 58], [81, 78], [57, 86], [71, 208]] },
};
function ringPoints(n) {
  const { tip, half, faces } = RING[n];
  const pt = (r, deg) => { const a = (deg - 90) * Math.PI / 180; return `${(80 + r * Math.cos(a)).toFixed(2)},${(80 + r * Math.sin(a)).toFixed(2)}`; };
  const grey = (v) => `rgb(${v},${v},${v - 2})`;
  let out = '';
  faces.forEach(([left, right], i) => {
    const d = i * 360 / n;
    out += `<polygon points="${pt(45, d - half)} ${pt(tip, d)} ${pt(40, d)}" fill="${grey(left)}"/>`
         + `<polygon points="${pt(tip, d)} ${pt(45, d + half)} ${pt(40, d)}" fill="${grey(right)}"/>`;
  });
  return `<svg viewBox="0 0 160 160">${out}</svg>`;
}

// URLs relative to this module, so any page (render.html, index.html, ...) can use it
const ASSETS = new URL('../assets/', import.meta.url).href;

const json = async (url) => { const r = await fetch(url); if (!r.ok) throw new Error(url); return r.json(); };
const tryJson = async (url, fallback = {}) => { try { return await json(url); } catch { return fallback; } };
const esc = (s) => String(s ?? '').replace(/&(?!#\d+;)/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export async function loadGame(game, lang = 'english') {
  const base = new URL(`../../${game}`, import.meta.url).href;
  const details = {};
  for (const f of FILES) Object.assign(details, await tryJson(`${base}/${f}.json`));
  const locFile = await tryJson(`${base}/localization/${lang}.json`, { cards: {}, ui: {} });
  const enFile = lang === 'english' ? locFile : await tryJson(`${base}/localization/english.json`, { cards: {}, ui: {} });
  // cards_text.json: English text from any source, for cards the game's localization lacks
  const text = await tryJson(`${base}/cards_text.json`);
  return { game, lang, details, loc: locFile.cards, en: enFile.cards, text, ui: { ...enFile.ui, ...locFile.ui } };
}

// Art: the game's own folder first, then Classic's (Foundry and Reborn reuse Classic art).
function artUrl(game, kind, id) {
  return [`${ASSETS}${game}/art/${kind}/${id}.png`, `${ASSETS}classic/art/${kind}/${id}.png`];
}

function firstExisting(urls) {
  return new Promise((resolve) => {
    const tryNext = (i) => {
      if (i >= urls.length) return resolve(null);
      const img = new Image();
      img.onload = () => resolve(urls[i]);
      img.onerror = () => tryNext(i + 1);
      img.src = urls[i];
    };
    tryNext(0);
  });
}

// Card-text markup -> the render's HTML.
export function markup(raw, names) {
  if (!raw) return '';
  let pos = 0;
  const parse = (inside) => {
    let out = '';
    while (pos < raw.length) {
      if (inside && raw[pos] === ']') break;
      const m = raw[pos] === '[' && /^\[([a-z_]*(?::[A-Za-z0-9_]+)?)\[/.exec(raw.slice(pos));
      if (m) {
        pos += m[0].length;
        const inner = parse(true);
        pos += raw.startsWith(']]', pos) ? 2 : (raw[pos] === ']' ? 1 : 0);
        const tag = m[1];
        if (tag === '') out += `<b>${inner}</b>`;
        else if (tag === 'abilityname') out += `<b class="ability-name">${inner}</b><br>`;
        else if (tag.startsWith('color:') && tag !== 'color:attribute_glyph') out += `<span class="label ${tag.slice(6)}">${inner}</span>`;
        else out += inner;
        continue;
      }
      out += raw[pos++];
    }
    return out;
  };
  let html = parse(false)
    .replace(/\{s:thisCardName\}/g, esc(names.self))
    .replace(/\{s:parentCardName\}/g, esc(names.parent || names.self))
    .replace(/\{s:factionName\}/g, esc(names.faction || ''))
    .replace(/<BR\/?>|<br\s*\/?>/gi, '<br>')
    .replace(/\n/g, '')
    // the game's icons (cooldown, refresh, initiative, attack, armor, health, ...) are glyphs
    // of Radiance itself (U+25A0-25A8), so they take the text's colour, gradient and shadow
    .replace(/&#(963[2-9]|9640);/g, '<span class="g">&#$1;</span>');
  html = html.replace(/^(\s*<br>)+|(<br>\s*)+$/g, '');
  // a blank line is a paragraph break (shorter than a line in Valve's layout)
  // Valve's layout keeps a space before a line break (it shifts a centred line left)
  html = html.replace(/ +(?=<br>|$)/g, '&nbsp;');
  return html.split(/<br>\s*<br>/).map((p) => `<p>${p.replace(/^\s+/, '').replace(/^(&nbsp;)+/, '')}</p>`).join('');
}

// ability frames: active abilities, triggered passives ("reactive"), continuous passives
const bevelOf = (ab) => (!ab.is_passive ? '' : ab.engine?.has_triggers ? '_reactive' : '_passive');

function el(cls, parent, html) {
  const e = document.createElement('div');
  e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  parent.append(e);
  return e;
}

// Shrink the card text until it fits the box (inside its padding, less --fit-slack).
function fitText(box) {
  const inner = box.firstElementChild;
  const cs = getComputedStyle(box);
  const room = box.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
    - (parseFloat(cs.getPropertyValue('--fit-slack')) || 0);
  let size = parseFloat(cs.fontSize);
  while (inner.scrollHeight > room && size > 14) {
    size -= 0.5;
    box.style.fontSize = `${size}px`;
  }
}

// Long titles are narrowed to end before the card's right edge.
function fitTitle(title) {
  let size = parseFloat(getComputedStyle(title).fontSize);
  while (title.getBoundingClientRect().right - title.parentElement.getBoundingClientRect().left > 495 && size > 20) {
    size -= 0.5;
    title.style.fontSize = `${size}px`;
  }
}

export async function render(data, id, target, { art: artOverride } = {}) {
  installFilters();
  const c = data.details[String(id)];
  if (!c) throw new Error(`no card ${id}`);
  const t = { ...data.text?.[String(id)], ...data.en[String(id)], ...data.loc[String(id)] };
  const isUnit = c.type === TYPE.HERO || c.type === TYPE.CREEP;
  // an ability is drawn in its owner's colour
  const owner = data.details[String((c.ability_of || c.signature_of || [])[0])];
  const colour = c.color || (c.type === TYPE.ABILITY ? owner?.color : null);
  const root = document.createElement('div');
  root.className = `render ${c.type === TYPE.PATHING ? 'path' : isUnit ? 'unit' : 'spell'}`;
  if (c.type === TYPE.HERO) root.classList.add('hero');
  if (c.type === TYPE.ITEM) root.classList.add('item');
  if (c.type === TYPE.STRONGHOLD) root.classList.add('stronghold');
  if (colour) root.classList.add(colour.toLowerCase());
  const body = el('body', root);

  const artId = artOverride ?? c.artwork?.artwork_id ?? c.id;
  const art = el('art', body);
  const artSrc = await firstExisting(artUrl(data.game, 'full_art', artId));
  if (artSrc) art.style.backgroundImage = `url("${artSrc}")`, art.style.backgroundSize = '100% 100%';
  else {   // cards with only a mini icon (most abilities): the icon in its frame over a blur of itself
    const mini = await firstExisting([...artUrl(data.game, 'mini_icons', artId), ...artUrl(data.game, 'mini_icons', c.id)]);
    if (mini) {
      root.classList.add('mini-art');
      art.style.setProperty('--mini', `url("${mini}")`);
      const tile = el('ability mini-tile', art);
      el('icon', tile).style.backgroundImage = `url("${mini}")`;
      el('bevel', tile).style.backgroundImage = `url("${ASSETS}classic/ui/card_elements/ability_bevel${bevelOf(c)}.png")`;
    }
  }
  if (c.type === TYPE.PATHING) return finish(root, target);  // path cards are their art alone

  const parentId = (c.ability_of || c.signature_of || [])[0];
  const parentName = parentId ? (data.loc[String(parentId)]?.name || data.details[String(parentId)]?.name) : '';
  const name = t.name || c.name || '';

  // text box: none on heroes (their abilities are the icons) or on units without text
  if (c.type !== TYPE.HERO && !(isUnit && !t.text)) {
    const box = el('textbox', body);
    let text = t.text || '';
    if (c.type === TYPE.ABILITY && !c.is_passive && c.cooldown != null && !/activatedability|&#9632;/.test(text)) {
      // an active ability's line as its owner's text writes it ("Active <cooldown>:"), in this language
      const ownerText = (data.loc[String(c.ability_of?.[0])] || data.en[String(c.ability_of?.[0])] || {}).text || '';
      const word = /\[color:ability\[([^\[\]]*?)\s*&#9632;/.exec(ownerText)?.[1] || 'Active';
      text = `[color:ability[${word} &#9632;${c.cooldown}:]] ${text}`;
    }
    if (c.charges && data.ui.DCG_CardText_Charges) {   // Valve's own template for the charges line
      text = data.ui.DCG_CardText_Charges.replace('{s:cardText}', text).replace('{i:charges}', c.charges);
    }
    const html = markup(text, { self: name, parent: parentName, faction: c.faction });
    const inner = el('inner', box, html);
    if (!t.text) box.classList.add('empty');
    inner.style.width = '100%';
  }

  // header
  const itemLike = c.type === TYPE.ITEM || (c.type === TYPE.ABILITY && owner?.type === TYPE.ITEM);
  const tone = itemLike ? 'item' : (colour || 'none').toLowerCase();
  // the frame material, baked from the card model's textures by scripts/frame.py
  root.style.setProperty('--frame-header', `url("${ASSETS}classic/ui/frame/${tone}_header.png")`);
  root.style.setProperty('--frame-bottom', `url("${ASSETS}classic/ui/frame/${tone}_${isUnit ? 'bar' : 'strip'}.png")`);
  const header = el('header', body);
  el('material', header);
  if (c.type === TYPE.HERO) {
    const icon = el('hero-icon', header, '<i></i>');
    const src = await firstExisting([...artUrl(data.game, 'hero_icons', artId),
      ...artUrl(data.game, 'hero_icons', c.artwork?.artwork_id ?? c.id)]);   // alternate arts reuse the base icon
    if (src) icon.firstChild.style.backgroundImage = `url("${src}")`;
  } else if (c.mana_cost != null || c.type === TYPE.STRONGHOLD) {   // towers show a 0
    const cost = el('cost', header);
    const mana = c.mana_cost ?? 0;
    cost.innerHTML = c.crosslane ? `<i class="lane"></i>${mana}<i class="lane right"></i>` : `${mana}`;
    if (c.quick) cost.insertAdjacentHTML('beforeend', '<i class="quick"></i>');
  }
  el('title', header, esc(name));

  // type badge
  let badge = { [TYPE.HERO]: 'hero', [TYPE.CREEP]: 'creep', [TYPE.SPELL]: 'spell', [TYPE.IMPROVEMENT]: 'improvement' }[c.type];
  if (c.type === TYPE.ITEM) badge = ITEM_BADGE[c.item_subtype] || 'weapon';
  if (badge) el('badge', body).style.backgroundImage = `url("${ASSETS}classic/ui/card/cardtype_${badge}.png")`;

  // signature hero icon / improvement icon
  const heroOf = (c.signature_of || (owner?.type === TYPE.HERO ? c.ability_of : null) || [])[0];
  if (heroOf && c.type !== TYPE.HERO) {
    const hero = data.details[String(heroOf)];
    const src = await firstExisting(artUrl(data.game, 'hero_icons', hero?.artwork?.artwork_id ?? heroOf));
    if (src) el('signature', body, '<i></i>').firstChild.style.backgroundImage = `url("${src}")`;
  }
  if (c.type === TYPE.IMPROVEMENT) {
    const src = await firstExisting(artUrl(data.game, 'mini_icons', artId));
    if (src) {
      const active = /\[activatedability\[/.test(t.text || data.en[String(id)]?.text || '');
      const ring = el('improvement-ring', body);
      ring.innerHTML = ringPoints(active ? 6 : 3);
      const icon = el('improvement-icon', ring);
      icon.style.backgroundImage = `url("${src}")`;
      el('rim', ring);
      if (c.charges) el('charges', ring, `<span>${c.charges}</span>`);
      root.classList.add('has-ring');
    }
  }

  // hero abilities
  if (c.type === TYPE.HERO && c.abilities?.length) {
    const row = el('abilities', body);
    for (const aid of c.abilities) {
      const ab = data.details[String(aid)] || {};
      const box = el('ability', row);
      const src = await firstExisting([...artUrl(data.game, 'mini_icons', ab.artwork?.artwork_id ?? aid),
        ...artUrl(data.game, 'mini_icons', aid)]);
      if (src) el('icon', box).style.backgroundImage = `url("${src}")`;
      el('bevel', box).style.backgroundImage = `url("${ASSETS}classic/ui/card_elements/ability_bevel${bevelOf(ab)}.png")`;
    }
  }

  // bottom
  const bottom = el('bottom', body);
  el('material', bottom);
  if (isUnit) {
    const stats = el('stats', body);
    el('stat attack', stats, `<i></i>${c.attack ?? 0}`);
    el(`stat armor${c.armor ? '' : ' zero'}`, stats, `<i></i>${c.armor ?? 0}`);
    el('stat health', stats, `<i></i>${c.health ?? 0}`);
  }
  // Foundry's rarities are the community database's numbers (0-5): drawn with Classic's emblems
  const FOUNDRY_RARITY = ['basic', 'common', 'uncommon', 'rare', 'rare', 'rare'];
  const named = (r) => (typeof r === 'number' ? FOUNDRY_RARITY[r] : r?.toLowerCase());
  const rarity = named(c.rarity ?? owner?.rarity) || 'basic';   // signature cards and abilities: their owner's
  const set = String(c.set ?? 1).padStart(2, '0');
  const emblem = await firstExisting([`${ASSETS}classic/ui/set_icons/set_${set}_${rarity}.png`,
    `${ASSETS}classic/ui/set_icons/set_01_${rarity}.png`, `${ASSETS}classic/ui/set_icons/set_01_basic.png`]);
  if (emblem) el('emblem', body).style.backgroundImage = `url("${emblem}")`;
  if (c.type === TYPE.ITEM) el('gold', body, `<span>${c.gold_cost ?? ''}</span>`);

  return finish(root, target);
}

// Valve's small preview ("mini", 267x267): the mini icon with a vignette in a 3px frame of the
// card's colour (none for colourless cards). Cards without a mini icon use their art.
export async function renderMini(data, id, target, { art: artOverride } = {}) {
  const c = data.details[String(id)];
  if (!c) throw new Error(`no card ${id}`);
  const owner = data.details[String((c.ability_of || c.signature_of || [])[0])];
  const itemLike = c.type === TYPE.ITEM || (c.type === TYPE.ABILITY && owner?.type === TYPE.ITEM);
  const colour = itemLike ? 'item' : (c.color || (c.type === TYPE.ABILITY ? owner?.color : null) || 'none').toLowerCase();
  const artId = artOverride ?? c.artwork?.artwork_id ?? c.id;
  const root = document.createElement('div');
  root.className = `mini ${colour}`;
  const art = el('mini-art-img', root);
  const src = await firstExisting([...artUrl(data.game, 'mini_icons', artId), ...artUrl(data.game, 'mini_icons', c.id),
    ...artUrl(data.game, 'full_art', artId)]);
  if (src) art.style.backgroundImage = `url("${src}")`;
  el('vignette', art);
  return finish(root, target);
}

async function finish(root, target) {
  target.replaceChildren(root);
  // load the faces explicitly: fonts.ready alone can resolve before a face is in use
  await Promise.all(['400 36px Radiance', '600 36px Radiance', '700 36px Radiance', '400 36px RadianceCondensed']
    .map((f) => document.fonts.load(f).catch(() => null)));
  await document.fonts.ready;
  const box = root.querySelector('.textbox');
  if (box) fitText(box);
  const title = root.querySelector('.title');
  if (title) fitTitle(title);
  await Promise.all([...root.querySelectorAll('*')].map((e) => {
    const st = getComputedStyle(e);
    const m = /url\("(.+?)"\)/.exec(st.backgroundImage + ' ' + (st.maskImage || st.webkitMaskImage || ''));
    if (!m) return null;
    return new Promise((res) => { const i = new Image(); i.onload = i.onerror = res; i.src = m[1]; });
  }));
  return root;
}
