(function () {
  "use strict";

  const STORAGE_KEY = "po-juggler-v1";
  const $ = (id) => document.getElementById(id);

  // ---------- state ----------
  let state = load();

  function seedState() {
    return { questions: window.SEED_QUESTIONS.map((q) => ({ ...q })), answers: {} };
  }

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        if (s && Array.isArray(s.questions) && s.answers && typeof s.answers === "object") return s;
      }
    } catch (e) { /* fall through to seed */ }
    return seedState();
  }

  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    catch (e) { showSaved("Không lưu được vào trình duyệt (bộ nhớ bị chặn hoặc đầy)."); }
  }

  const byId = (id) => state.questions.find((q) => q.id === id);
  const answerOf = (id) => state.answers[id] || { text: "", status: "" };
  function statusOf(id) {
    const a = answerOf(id);
    if (a.status) return a.status;           // "done" | "review"
    return a.text.trim() ? "draft" : "todo";
  }
  const STATUS_LABEL = { todo: "Chưa trả lời", draft: "Đang nháp", review: "Cần luyện thêm", done: "Đã ổn" };

  function newId() { return "u" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

  // ---------- deck (shuffled order for practice) ----------
  let deck = [];
  let pos = -1;

  function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function matchingIds() {
    const cat = $("filter-category").value;
    const st = $("filter-status").value;
    return state.questions
      .filter((q) => (cat === "all" || q.category === cat) && (st === "all" || statusOf(q.id) === st))
      .map((q) => q.id);
  }

  // keepId: put this question first so an edit/filter change doesn't yank the card away.
  function rebuildDeck(keepId) {
    const ids = matchingIds();
    shuffle(ids);
    if (keepId && ids.includes(keepId)) {
      ids.splice(ids.indexOf(keepId), 1);
      ids.unshift(keepId);
    }
    deck = ids;
    pos = ids.length ? 0 : -1;
    renderCard();
  }

  function next() {
    flushAnswer();
    if (!deck.length) return;
    if (pos + 1 < deck.length) { pos++; }
    else {
      // end of the pass: reshuffle, avoiding an immediate repeat of the last card
      const last = deck[pos];
      const ids = shuffle(matchingIds());
      if (ids.length > 1 && ids[0] === last) ids.push(ids.shift());
      deck = ids;
      pos = 0;
    }
    renderCard();
  }

  function prev() {
    flushAnswer();
    if (pos > 0) { pos--; renderCard(); }
  }

  // ---------- practice view ----------
  let currentId = null;
  let saveTimer = null;

  function renderCard() {
    const q = pos >= 0 ? byId(deck[pos]) : null;
    $("card").hidden = !q;
    $("empty-practice").hidden = !!q;
    currentId = q ? q.id : null;
    $("deck-info").textContent = deck.length ? `Câu ${pos + 1} / ${deck.length}` : "";
    $("btn-prev").disabled = pos <= 0;
    $("btn-next").disabled = !deck.length;
    if (!q) return;

    $("card-category").textContent = q.category;
    $("card-question").textContent = q.question;
    $("card-hint").textContent = q.hint || "—";
    $("card-draft").textContent = q.draft || "—";
    $("answer").value = answerOf(q.id).text;
    $("reveal").hidden = true;
    $("btn-reveal").textContent = "Xem gợi ý & trả lời nháp";
    showSaved("");
    renderStatus();
  }

  function renderStatus() {
    if (!currentId) return;
    const st = statusOf(currentId);
    const chip = $("card-status");
    chip.textContent = STATUS_LABEL[st];
    chip.className = "chip status " + st;
    $("btn-done").classList.toggle("active-done", st === "done");
    $("btn-review").classList.toggle("active-review", st === "review");
  }

  function showSaved(msg) { $("saved-note").textContent = msg; }

  function setAnswer(patch) {
    if (!currentId) return;
    state.answers[currentId] = { ...answerOf(currentId), ...patch, updatedAt: Date.now() };
    save();
  }

  function flushAnswer() {
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
      if (currentId) setAnswer({ text: $("answer").value });
    }
  }

  $("answer").addEventListener("input", () => {
    clearTimeout(saveTimer);
    showSaved("Đang lưu…");
    saveTimer = setTimeout(() => {
      saveTimer = null;
      setAnswer({ text: $("answer").value });
      showSaved("Đã lưu");
      renderStatus();
    }, 400);
  });

  function toggleStatus(value) {
    flushAnswer();
    const cur = answerOf(currentId).status;
    setAnswer({ status: cur === value ? "" : value });
    renderStatus();
  }

  $("btn-done").addEventListener("click", () => toggleStatus("done"));
  $("btn-review").addEventListener("click", () => toggleStatus("review"));
  $("btn-next").addEventListener("click", next);
  $("btn-prev").addEventListener("click", prev);
  $("btn-reveal").addEventListener("click", () => {
    const r = $("reveal");
    r.hidden = !r.hidden;
    $("btn-reveal").textContent = r.hidden ? "Xem gợi ý & trả lời nháp" : "Ẩn gợi ý & trả lời nháp";
  });
  $("btn-shuffle").addEventListener("click", () => { flushAnswer(); rebuildDeck(); });
  $("filter-category").addEventListener("change", () => { flushAnswer(); rebuildDeck(); });
  $("filter-status").addEventListener("change", () => { flushAnswer(); rebuildDeck(); });
  $("btn-edit").addEventListener("click", () => { if (currentId) openDialog(currentId); });

  function renderCategoryOptions() {
    const cats = [...new Set(state.questions.map((q) => q.category))];
    const sel = $("filter-category");
    const keep = sel.value || "all";
    sel.replaceChildren(new Option("Tất cả nhóm", "all"));
    cats.forEach((c) => sel.append(new Option(c, c)));
    sel.value = cats.includes(keep) ? keep : "all";
    $("category-list").replaceChildren(...cats.map((c) => new Option(c)));
  }

  // ---------- manage view ----------
  function renderList() {
    const term = $("search").value.trim().toLowerCase();
    const items = state.questions.filter((q) =>
      !term || (q.question + " " + q.category + " " + q.draft + " " + q.hint).toLowerCase().includes(term));
    $("manage-count").textContent = `${items.length} / ${state.questions.length} câu hỏi`;
    const ul = $("question-list");
    ul.replaceChildren();
    items.forEach((q) => {
      const li = document.createElement("li");
      li.className = "qitem";
      const body = document.createElement("div");
      body.className = "body";
      const p = document.createElement("p");
      p.className = "q";
      p.textContent = q.question;
      const meta = document.createElement("div");
      meta.className = "meta";
      const cat = document.createElement("span");
      cat.className = "chip";
      cat.textContent = q.category;
      const st = statusOf(q.id);
      const stChip = document.createElement("span");
      stChip.className = "chip status " + st;
      stChip.textContent = STATUS_LABEL[st];
      meta.append(cat, stChip);
      body.append(p, meta);
      const edit = document.createElement("button");
      edit.className = "ghost";
      edit.textContent = "Sửa";
      edit.addEventListener("click", () => openDialog(q.id));
      li.append(body, edit);
      ul.append(li);
    });
  }
  $("search").addEventListener("input", renderList);

  // ---------- in-page confirm (native confirm() is unavailable in embedded viewers) ----------
  function askConfirm(message) {
    return new Promise((resolve) => {
      const d = $("dlg-confirm");
      $("confirm-msg").textContent = message;
      const done = (v) => { d.close(); $("confirm-yes").onclick = $("confirm-no").onclick = null; d.onclose = null; resolve(v); };
      $("confirm-yes").onclick = () => done(true);
      $("confirm-no").onclick = () => done(false);
      d.onclose = () => resolve(false);
      d.showModal();
    });
  }

  // ---------- add / edit dialog ----------
  let editingId = null;
  const dlg = $("dlg");

  function openDialog(id) {
    editingId = id || null;
    const q = id ? byId(id) : null;
    $("dlg-title").textContent = q ? "Sửa câu hỏi" : "Thêm câu hỏi";
    $("f-category").value = q ? q.category : ($("filter-category").value !== "all" ? $("filter-category").value : "");
    $("f-question").value = q ? q.question : "";
    $("f-hint").value = q ? q.hint : "";
    $("f-draft").value = q ? q.draft : "";
    $("dlg-delete").hidden = !q;
    dlg.showModal();
    $("f-question").focus();
  }

  $("btn-add").addEventListener("click", () => openDialog(null));
  $("dlg-cancel").addEventListener("click", () => dlg.close());

  $("dlg-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const data = {
      category: $("f-category").value.trim(),
      question: $("f-question").value.trim(),
      hint: $("f-hint").value.trim(),
      draft: $("f-draft").value.trim(),
    };
    if (!data.category || !data.question) return;
    flushAnswer();
    let focusId;
    if (editingId) {
      Object.assign(byId(editingId), data);
      focusId = editingId;
    } else {
      focusId = newId();
      state.questions.push({ id: focusId, ...data });
    }
    save();
    dlg.close();
    refreshAll(editingId ? currentId : focusId);
  });

  $("dlg-delete").addEventListener("click", async () => {
    const q = byId(editingId);
    if (!q || !(await askConfirm(`Xoá câu hỏi này?\n\n${q.question}`))) return;
    flushAnswer();
    state.questions = state.questions.filter((x) => x.id !== editingId);
    delete state.answers[editingId];
    save();
    dlg.close();
    refreshAll(editingId === currentId ? null : currentId);
  });

  function refreshAll(keepId) {
    renderCategoryOptions();
    rebuildDeck(keepId);
    renderList();
  }

  // ---------- backup / import / reset ----------
  const backupDlg = $("dlg-backup");
  const backupMsg = (m) => { $("backup-msg").textContent = m; };

  $("btn-backup").addEventListener("click", () => {
    flushAnswer();
    $("backup-text").value = JSON.stringify(state, null, 2);
    backupMsg("");
    backupDlg.showModal();
  });
  $("backup-close").addEventListener("click", () => backupDlg.close());

  $("backup-copy").addEventListener("click", async () => {
    const ta = $("backup-text");
    ta.value = JSON.stringify(state, null, 2);
    try { await navigator.clipboard.writeText(ta.value); backupMsg("Đã sao chép vào clipboard."); }
    catch (e) { ta.select(); backupMsg("Không tự sao chép được. Đã chọn sẵn nội dung, hãy nhấn Ctrl/Cmd+C."); }
  });

  $("backup-file").addEventListener("click", () => $("file-import").click());
  $("file-import").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) $("backup-text").value = await file.text();
    backupMsg(file ? "Đã đọc file. Bấm Nhập để áp dụng." : "");
  });

  $("backup-import").addEventListener("click", async () => {
    let s;
    try { s = JSON.parse($("backup-text").value); } catch (err) { backupMsg("JSON không hợp lệ."); return; }
    const ok = s && Array.isArray(s.questions) && s.questions.every((q) =>
      q && typeof q.id === "string" && typeof q.question === "string" && typeof q.category === "string");
    if (!ok) { backupMsg("Dữ liệu thiếu id, nhóm hoặc câu hỏi."); return; }
    backupDlg.close();
    if (!(await askConfirm(`Nhập ${s.questions.length} câu hỏi? Dữ liệu hiện tại sẽ bị thay thế.`))) return;
    state = {
      questions: s.questions.map((q) => ({ id: q.id, category: q.category, question: q.question, hint: q.hint || "", draft: q.draft || "" })),
      answers: s.answers && typeof s.answers === "object" ? s.answers : {},
    };
    save();
    refreshAll();
  });

  $("btn-reset").addEventListener("click", async () => {
    if (!(await askConfirm("Khôi phục 77 câu hỏi mặc định? Câu hỏi bạn đã thêm/sửa sẽ mất; câu trả lời của bạn với các câu mặc định được giữ lại."))) return;
    flushAnswer();
    const fresh = seedState();
    const ids = new Set(fresh.questions.map((q) => q.id));
    fresh.answers = Object.fromEntries(Object.entries(state.answers).filter(([id]) => ids.has(id)));
    state = fresh;
    save();
    refreshAll();
  });

  // ---------- tabs ----------
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      flushAnswer();
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      $("view-practice").hidden = btn.dataset.view !== "practice";
      $("view-manage").hidden = btn.dataset.view !== "manage";
      if (btn.dataset.view === "manage") renderList();
    });
  });

  window.addEventListener("pagehide", flushAnswer);

  // ---------- keyboard: ← → move between cards when not typing ----------
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "textarea" || tag === "input" || tag === "select" || dlg.open || $("view-practice").hidden) return;
    if (e.key === "ArrowRight") next();
    if (e.key === "ArrowLeft") prev();
  });

  refreshAll();
})();
