(() => {
  'use strict';

  const synth = window.speechSynthesis;
  const $ = (id) => document.getElementById(id);
  const els = {
    voice: $('voice'), rate: $('rate'), pitch: $('pitch'), volume: $('volume'),
    rateOut: $('rate-out'), pitchOut: $('pitch-out'), volumeOut: $('volume-out'),
    editor: $('editor'), reader: $('reader'), count: $('count'), status: $('status'),
    play: $('btn-play'), prev: $('btn-prev'), next: $('btn-next'), stop: $('btn-stop'),
    paste: $('btn-paste'), clear: $('btn-clear'),
    engineNote: $('engine-note'), unsupported: $('unsupported'),
    hint: $('lang-hint'), hintText: $('lang-hint-text'), hintBtn: $('lang-hint-btn'),
  };

  if (!synth || typeof SpeechSynthesisUtterance === 'undefined') {
    els.unsupported.hidden = false;
    document.querySelectorAll('button, select, input, textarea').forEach((e) => { e.disabled = true; });
    return;
  }

  // ---------- settings ----------
  const STORE = 'readAloud.v1';
  const settings = Object.assign({ voiceURI: '', rate: 1, pitch: 1, volume: 1, text: '' }, load());
  function load() {
    try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; }
  }
  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(settings)); } catch { /* storage unavailable */ }
  }

  // ---------- voices ----------
  let voices = [];
  const isNatural = (v) => /natural|neural|online/i.test(v.name);
  // "Microsoft Aria Online (Natural) - English (United States)" -> "Aria Online (Natural)"
  const shortName = (v) => v.name.replace(/^Microsoft\s+/, '').replace(/\s+-\s+.*$/, '');

  function loadVoices() {
    voices = synth.getVoices();
    if (!voices.length) return;
    const pref = (navigator.language || 'en').slice(0, 2).toLowerCase();
    const rank = (v) => (v.lang.slice(0, 2).toLowerCase() === pref ? 0 : 1);
    voices = voices.slice().sort((a, b) =>
      rank(a) - rank(b) || a.lang.localeCompare(b.lang) ||
      (isNatural(b) - isNatural(a)) || a.name.localeCompare(b.name));

    const names = typeof Intl.DisplayNames === 'function'
      ? new Intl.DisplayNames([navigator.language || 'en'], { type: 'language' }) : null;
    const langLabel = (lang) => { try { return names ? names.of(lang) : lang; } catch { return lang; } };

    els.voice.textContent = '';
    const groups = new Map();
    for (const v of voices) {
      if (!groups.has(v.lang)) {
        const g = document.createElement('optgroup');
        g.label = `${langLabel(v.lang)} (${v.lang})`;
        groups.set(v.lang, g);
        els.voice.appendChild(g);
      }
      const o = document.createElement('option');
      o.value = v.voiceURI;
      o.textContent = shortName(v);
      groups.get(v.lang).appendChild(o);
    }

    let chosen = voices.find((v) => v.voiceURI === settings.voiceURI);
    if (!chosen) {
      const mine = voices.filter((v) => v.lang.slice(0, 2).toLowerCase() === pref);
      chosen = mine.find(isNatural) || mine[0] || voices.find((v) => v.default) || voices[0];
    }
    els.voice.value = chosen.voiceURI;
    settings.voiceURI = chosen.voiceURI;
    els.engineNote.textContent = voices.some(isNatural)
      ? 'Natural voices available' : `${voices.length} voice${voices.length === 1 ? '' : 's'}`;
    updateHint();
  }
  const currentVoice = () => voices.find((v) => v.voiceURI === els.voice.value) || null;

  // ---------- language hint (Vietnamese <-> English voice) ----------
  const VI_ONLY = /[ăâđêôơưĂÂĐÊÔƠƯạảãậẩẫặẳẵẹẻẽệểễịỉĩọỏộổỗợởỡụủũựửữỳỵỷỹ]/g;
  let hintTarget = null;
  function bestVoice(prefix) {
    const m = voices.filter((v) => v.lang.toLowerCase().startsWith(prefix));
    return m.find(isNatural) || m[0] || null;
  }
  function updateHint() {
    hintTarget = null;
    const text = els.editor.value;
    const v = currentVoice();
    if (v && text.trim().length >= 20) {
      const viChars = (text.match(VI_ONLY) || []).length;
      const voiceIsVi = v.lang.toLowerCase().startsWith('vi');
      const asciiOnly = !/[^\x00-\x7F]/.test(text);
      if (viChars >= 3 && !voiceIsVi && bestVoice('vi')) {
        hintTarget = bestVoice('vi');
        els.hintText.textContent = 'This text looks Vietnamese, but the selected voice is not.';
      } else if (asciiOnly && voiceIsVi && bestVoice('en')) {
        hintTarget = bestVoice('en');
        els.hintText.textContent = 'This text looks English, but a Vietnamese voice is selected.';
      }
    }
    if (hintTarget) els.hintBtn.textContent = `Use ${shortName(hintTarget)}`;
    els.hint.hidden = !hintTarget;
  }
  els.hintBtn.addEventListener('click', () => {
    if (!hintTarget) return;
    els.voice.value = hintTarget.voiceURI;
    onVoiceChange();
  });

  // ---------- chunking ----------
  const MAX_CHUNK = 220; // long utterances get cut off by some engines (Chrome ~15s)
  const TERMINATOR = /[.!?…。！？]/;

  function buildChunks(text) {
    const ranges = [];
    let start = 0;
    const n = text.length;
    for (let i = 0; i < n; i++) {
      const c = text[i];
      const next = text[i + 1];
      const end = c === '\n' ||
        (TERMINATOR.test(c) && (i + 1 >= n || /[\s"'”’)\]]/.test(next) || /[。！？]/.test(c)) && !TERMINATOR.test(next || ''));
      if (end) { ranges.push([start, i + 1]); start = i + 1; }
    }
    if (start < n) ranges.push([start, n]);

    const chunks = [];
    for (let [s, e] of ranges) {
      while (e - s > MAX_CHUNK) {
        const win = text.slice(s, s + MAX_CHUNK);
        let cut = Math.max(win.lastIndexOf(', '), win.lastIndexOf('; '), win.lastIndexOf(': '));
        if (cut < MAX_CHUNK / 3) cut = win.lastIndexOf(' ');
        cut = cut > 0 ? s + cut + 1 : s + MAX_CHUNK;
        chunks.push({ start: s, end: cut });
        s = cut;
      }
      chunks.push({ start: s, end: e });
    }
    return chunks.filter((c) => /\S/.test(text.slice(c.start, c.end)));
  }

  // ---------- player ----------
  let text = '';
  let chunks = [];
  let idx = 0;
  let state = 'idle'; // idle | playing | paused
  let gen = 0;        // bumps on every (re)start so stale utterance events are ignored
  let wordPos = 0;    // absolute offset of the word being spoken (for restarts)
  let utt = null;     // keep a reference: some engines GC utterances and drop onend

  function speakFrom(i, absOffset) {
    gen++;
    const myGen = gen;
    synth.cancel();
    idx = i;
    const ch = chunks[i];
    const from = Math.max(ch.start, Math.min(absOffset ?? ch.start, ch.end - 1));
    wordPos = from;
    paintChunk(i, from, from);

    const u = new SpeechSynthesisUtterance(text.slice(from, ch.end));
    const v = currentVoice();
    if (v) { u.voice = v; u.lang = v.lang; }
    u.rate = +els.rate.value;
    u.pitch = +els.pitch.value;
    u.volume = +els.volume.value;

    u.onboundary = (e) => {
      if (myGen !== gen || (e.name && e.name !== 'word')) return;
      const s = from + e.charIndex;
      let t = e.charLength ? s + e.charLength : s;
      if (t === s) { const m = /^\S+/.exec(text.slice(s, ch.end)); t = s + (m ? m[0].length : 1); }
      wordPos = s;
      paintChunk(i, s, t);
    };
    u.onend = () => {
      if (myGen !== gen) return;
      if (i + 1 < chunks.length) speakFrom(i + 1);
      else finish();
    };
    u.onerror = (e) => {
      if (myGen !== gen || e.error === 'interrupted' || e.error === 'canceled') return;
      finish(`Speech error: ${e.error}`);
    };
    utt = u;
    // Chrome/Edge sometimes ignore speak() issued in the same tick as cancel()
    setTimeout(() => { if (myGen === gen) synth.speak(u); }, 30);
    setState('playing');
  }

  function start() {
    if (!els.editor.hidden) {
      text = els.editor.value;
      chunks = buildChunks(text);
      if (!chunks.length) { setStatus('Nothing to read — paste some text first.'); return; }
      showReader();
    }
    speakFrom(0);
  }

  function togglePlay() {
    if (state === 'idle') return start();
    if (state === 'playing') { synth.pause(); setState('paused'); return; }
    synth.resume();
    setState('playing');
  }

  function stop() {
    gen++;
    synth.cancel();
    finish();
  }

  function finish(msg) {
    gen++;
    state = 'idle';
    showEditor();
    syncUi();
    setStatus(msg || '');
  }

  function step(delta) {
    if (state === 'idle') return;
    const j = Math.max(0, Math.min(chunks.length - 1, idx + delta));
    speakFrom(j);
  }

  function restartHere() {
    if (state === 'idle') return;
    const wasPaused = state === 'paused';
    speakFrom(idx, wordPos);
    if (wasPaused) { synth.pause(); setState('paused'); }
  }

  // ---------- reader view ----------
  function showReader() {
    els.reader.textContent = '';
    chunks.forEach((c, i) => {
      const s = document.createElement('span');
      s.className = 'chunk';
      s.dataset.i = i;
      s.dataset.start = c.start;
      s.textContent = text.slice(c.start, c.end);
      els.reader.appendChild(s);
      // keep inter-chunk whitespace/newlines so the layout matches the editor
      const gapEnd = i + 1 < chunks.length ? chunks[i + 1].start : text.length;
      if (gapEnd > c.end) els.reader.appendChild(document.createTextNode(text.slice(c.end, gapEnd)));
    });
    if (chunks[0].start > 0) els.reader.insertBefore(document.createTextNode(text.slice(0, chunks[0].start)), els.reader.firstChild);
    els.editor.hidden = true;
    els.reader.hidden = false;
    els.reader.scrollTop = 0;
  }
  function showEditor() {
    els.reader.hidden = true;
    els.editor.hidden = false;
  }

  let activeEl = null;
  function paintChunk(i, from, to) {
    const el = els.reader.querySelector(`.chunk[data-i="${i}"]`);
    if (!el) return;
    if (activeEl && activeEl !== el) {
      const pi = +activeEl.dataset.i;
      activeEl.classList.remove('active');
      activeEl.textContent = text.slice(chunks[pi].start, chunks[pi].end);
    }
    activeEl = el;
    el.classList.add('active');
    const c = chunks[i];
    el.textContent = '';
    el.append(text.slice(c.start, from));
    if (to > from) {
      const m = document.createElement('mark');
      m.textContent = text.slice(from, to);
      el.append(m, text.slice(to, c.end));
      keepVisible(m);
    } else {
      el.append(text.slice(from, c.end));
      keepVisible(el);
    }
    const pct = Math.round((c.start / Math.max(1, text.length)) * 100);
    setStatus(`Sentence ${i + 1} of ${chunks.length} · ${pct}%`);
  }
  function keepVisible(node) {
    const r = els.reader, nr = node.getBoundingClientRect(), rr = r.getBoundingClientRect();
    if (nr.top < rr.top + 20 || nr.bottom > rr.bottom - 20) {
      r.scrollTop += nr.top - rr.top - rr.height / 3;
    }
  }

  // click a word in the reader to jump there
  els.reader.addEventListener('click', (e) => {
    if (state === 'idle') return;
    let node, off;
    if (document.caretPositionFromPoint) {
      const p = document.caretPositionFromPoint(e.clientX, e.clientY);
      if (p) { node = p.offsetNode; off = p.offset; }
    } else if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(e.clientX, e.clientY);
      if (r) { node = r.startContainer; off = r.startOffset; }
    }
    const chunkEl = node && (node.nodeType === 1 ? node : node.parentElement).closest('.chunk');
    if (!chunkEl) return;
    const walker = document.createTreeWalker(chunkEl, NodeFilter.SHOW_TEXT);
    let rel = 0;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n === node) { rel += off; break; }
      rel += n.length;
    }
    const abs = +chunkEl.dataset.start + rel;
    let w = abs;
    while (w > chunks[+chunkEl.dataset.i].start && /\S/.test(text[w - 1])) w--;
    speakFrom(+chunkEl.dataset.i, w);
  });

  // ---------- UI wiring ----------
  function setStatus(s) { els.status.textContent = s; }
  function setState(s) { state = s; syncUi(); }
  function syncUi() {
    els.play.textContent = state === 'playing' ? '⏸ Pause' : state === 'paused' ? '▶ Resume' : '▶ Play';
    const active = state !== 'idle';
    els.prev.disabled = els.next.disabled = els.stop.disabled = !active;
    els.paste.disabled = els.clear.disabled = active;
    if (state === 'paused') setStatus('Paused');
  }

  function updateCount() {
    const t = els.editor.value;
    const words = (t.trim().match(/\S+/g) || []).length;
    const mins = words / (150 * +els.rate.value);
    els.count.textContent = words
      ? `${words.toLocaleString()} words · ${t.length.toLocaleString()} characters · ≈ ${mins < 1 ? '<1' : Math.round(mins)} min`
      : '';
  }

  let hintTimer;
  els.editor.value = settings.text;
  els.editor.addEventListener('input', () => {
    settings.text = els.editor.value;
    save();
    updateCount();
    clearTimeout(hintTimer);
    hintTimer = setTimeout(updateHint, 400);
  });

  function onVoiceChange() {
    settings.voiceURI = els.voice.value;
    save();
    updateHint();
    restartHere();
  }
  els.voice.addEventListener('change', onVoiceChange);

  els.rate.value = settings.rate;
  els.pitch.value = settings.pitch;
  els.volume.value = settings.volume;
  function syncSliders() {
    els.rateOut.textContent = `${(+els.rate.value).toFixed(1)}×`;
    els.pitchOut.textContent = (+els.pitch.value).toFixed(1);
    els.volumeOut.textContent = `${Math.round(+els.volume.value * 100)}%`;
  }
  let restartTimer;
  for (const key of ['rate', 'pitch', 'volume']) {
    els[key].addEventListener('input', () => {
      settings[key] = +els[key].value;
      save();
      syncSliders();
      updateCount();
      // rate/pitch/volume are fixed per utterance, so re-speak the current sentence
      clearTimeout(restartTimer);
      restartTimer = setTimeout(restartHere, 250);
    });
  }
  syncSliders();
  updateCount();

  els.play.addEventListener('click', togglePlay);
  els.stop.addEventListener('click', stop);
  els.prev.addEventListener('click', () => step(-1));
  els.next.addEventListener('click', () => step(1));
  els.clear.addEventListener('click', () => {
    els.editor.value = '';
    els.editor.dispatchEvent(new Event('input'));
    els.editor.focus();
  });
  els.paste.addEventListener('click', async () => {
    try {
      const t = await navigator.clipboard.readText();
      if (!t) { setStatus('Clipboard is empty.'); return; }
      els.editor.value = t;
      els.editor.dispatchEvent(new Event('input'));
      setStatus('');
    } catch {
      els.editor.focus();
      setStatus('Clipboard access blocked — press Ctrl+V in the text box instead.');
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { if (state !== 'idle') stop(); return; }
    const tag = e.target.tagName;
    if (tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'INPUT') return;
    if (e.key === ' ' && tag !== 'BUTTON') { e.preventDefault(); togglePlay(); }
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'ArrowLeft') step(-1);
  });

  // stop speaking if the page is closed/reloaded (engines keep talking otherwise)
  window.addEventListener('pagehide', () => synth.cancel());

  loadVoices(); // last: needs the editor text and hint state initialised above
  synth.addEventListener('voiceschanged', loadVoices);
  syncUi();
})();
