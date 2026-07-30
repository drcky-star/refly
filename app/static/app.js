// Refly istemci tarafı (çok dilli — metinler t() ile çevrilir)
let state = { collection: "all", tag: "", view: "library", refs: [], selected: new Set() };

const $ = (s) => document.querySelector(s);
const api = async (url, opts = {}) => {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.error || t("Hata")); }
  return r.json();
};
const esc = (s) => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function toast(msg, ms = 2400) {
  const el = $("#toast"); el.textContent = msg; el.classList.remove("hidden");
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.add("hidden"), ms);
}

// ---------------------------------------------------------- kullanım / kota göstergesi
function renderUsage(u) {
  const box = $("#usageBox");
  if (!box || !u) return;
  const m = u.metrics || {};
  const row = (key, label) => {
    const it = m[key];
    if (!it || it.limit == null) return "";   // sınırsız → gösterme
    const pct = Math.min(100, Math.round((it.used / it.limit) * 100));
    const col = pct >= 100 ? "#f87171" : pct >= 80 ? "#fbbf24" : "#4ade80";
    return `<div class="u-row"><span>${esc(label)}</span><span>${it.used}/${it.limit}</span></div>
      <div class="u-bar"><span style="width:${pct}%;background:${col}"></span></div>`;
  };
  const rows = row("autocite", "AI citations") + row("autotag", "Auto-tag") + row("refs", "Library");
  const upg = (u.plan && u.plan !== "unlimited")
    ? `<button onclick="openUpgrade()" style="width:100%;margin-top:9px;padding:8px;border:none;border-radius:10px;font-weight:600;color:#fff;background:linear-gradient(135deg,#6366f1,#8b5cf6);cursor:pointer">⬆ ${t("Planı yükselt")}</button>`
    : "";
  box.innerHTML = `<div class="u-plan">Plan: <b>${esc(u.plan)}</b>${rows ? "" : " · ∞"}</div>${rows}${upg}`;
}

// -------------------------------------------------- plan yükseltme (Stripe checkout)
async function openUpgrade() {
  let cfg = {}; try { cfg = await api("/api/billing/config"); } catch (e) {}
  const PLANS = {
    student: { name: "Student", price: "$7/mo", feats: ["25 AI citations / month", "Up to 5,000 sources", "All exports + Word add-in"] },
    pro: { name: "Pro", price: "$14.99/mo", feats: ["40 AI citations / month", "Up to 50,000 sources", "Priority speed"] },
  };
  const buyable = cfg.buyable || [];
  const cards = ["student", "pro"].map(p => {
    const pl = PLANS[p], can = buyable.includes(p);
    return `<div style="flex:1;min-width:200px;border:1px solid ${p === "pro" ? "#6366f1" : "#e6e9f2"};border-radius:14px;padding:16px">
      <div style="font-weight:700">${pl.name}${p === "pro" ? ` <span style="font-size:11px;color:#6366f1">★</span>` : ""}</div>
      <div style="font-size:22px;font-weight:800;margin:4px 0">${pl.price}</div>
      <ul style="font-size:12px;color:#6b7785;padding-left:16px;margin:8px 0;line-height:1.6">${pl.feats.map(f => `<li>${t(f)}</li>`).join("")}</ul>
      <button class="primary" style="width:100%" ${can ? "" : "disabled"} onclick="startCheckout('${p}')">${can ? t("Yükselt") : t("Yakında")}</button>
    </div>`;
  }).join("");
  const note = cfg.enabled ? `<p style="font-size:12px;color:#6b7785;margin-top:10px">${t("Güvenli ödeme Stripe ile. İstediğin zaman iptal edebilirsin.")}</p>`
    : `<p style="font-size:12px;color:#d98c00;margin-top:10px">${t("Ödeme sistemi yakında aktifleşecek — bu arada ihtiyaçların için bize yazabilirsin.")}</p>`;
  showModal(`<h2>${t("⬆ Planı yükselt")}</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap">${cards}</div>${note}
    <div class="modal-actions"><button onclick="closeModal()">${t("Kapat")}</button></div>`, true);
}
async function startCheckout(plan) {
  toast(t("Ödeme sayfası hazırlanıyor…"), 5000);
  const r = await api("/api/billing/checkout", { method: "POST", body: JSON.stringify({ plan }) });
  if (r.error) return toast(r.error);
  if (r.url) window.location.href = r.url;   // Stripe Checkout'a yönlendir
}

// Baştaki emoji'yi ikon-chip'e, kalan metni etikete ayırır (premium kenar çubuğu ikonları)
function splitIcon(label, fallback) {
  const m = String(label).match(/^(\p{Extended_Pictographic}(?:️|‍\p{Extended_Pictographic})*)\s+(.*)$/u);
  if (m) return { ic: m[1], text: m[2] };
  return { ic: fallback || "📁", text: String(label) };
}

// ---------------------------------------------------------- koleksiyonlar + etiketler
async function loadCollections() {
  const { collections, total, trash, tags, usage } = await api("/api/collections");
  renderUsage(usage);
  const nav = $("#collections");
  nav.innerHTML = "";
  const add = (key, label, n, special) => {
    const div = document.createElement("div");
    const active = state.view === "library" && state.collection === key && !state.tag;
    div.className = "coll" + (active ? " active" : "");
    div.onclick = () => selectView("library", key);
    const { ic, text } = splitIcon(label, "📁");
    div.innerHTML = `<span class="cic">${ic}</span><span class="cl">${esc(text)}</span><span class="n">${n ?? ""}</span>`;
    if (!special) {
      const del = document.createElement("span");
      del.className = "del"; del.textContent = "🗑";
      del.onclick = (e) => { e.stopPropagation(); deleteCollection(key, label); };
      div.appendChild(del);
    }
    nav.appendChild(div);
  };
  add("all", t("📑 Tüm kaynaklar"), total, true);
  add("none", t("📂 Koleksiyonsuz"), "", true);
  collections.forEach(c => add(String(c.id), c.name, c.n));

  const star = document.createElement("div");
  star.className = "coll" + (state.view === "starred" ? " active" : "");
  star.onclick = () => selectView("starred");
  const si = splitIcon(t("⭐ Yıldızlılar"), "⭐");
  star.innerHTML = `<span class="cic">${si.ic}</span><span class="cl">${esc(si.text)}</span>`;
  nav.appendChild(star);
  const tr = document.createElement("div");
  tr.className = "coll" + (state.view === "trash" ? " active" : "");
  tr.onclick = () => selectView("trash");
  const ti = splitIcon(t("🗑 Çöp kutusu"), "🗑");
  tr.innerHTML = `<span class="cic">${ti.ic}</span><span class="cl">${esc(ti.text)}</span><span class="n">${trash || ""}</span>`;
  nav.appendChild(tr);

  const tb = $("#tagBox");
  tb.innerHTML = (tags || []).map(tg =>
    `<span class="tg ${state.tag === tg.tag ? "active" : ""}" onclick="filterTag('${esc(tg.tag)}')">#${esc(tg.tag)} ${tg.n}</span>`).join("");
}

function selectView(view, collection = "all") {
  state.view = view; state.collection = collection; state.tag = "";
  state.selected.clear();
  loadCollections(); loadRefs();
}
function filterTag(tg) {
  state.tag = state.tag === tg ? "" : tg; state.view = "library";
  state.selected.clear(); loadCollections(); loadRefs();
}

async function newCollection() {
  const name = prompt(t("Koleksiyon adı:"));
  if (!name) return;
  await api("/api/collections", { method: "POST", body: JSON.stringify({ name }) });
  loadCollections();
}
async function deleteCollection(id, name) {
  if (!confirm(t("\"{0}\" koleksiyonu silinsin mi? (İçindeki kaynaklar 'Koleksiyonsuz'a taşınır)", name))) return;
  await api(`/api/collections/${id}/delete`, { method: "POST" });
  if (state.collection === String(id)) state.collection = "all";
  loadCollections(); loadRefs();
}

// ---------------------------------------------------------- referans listesi
let _deb;
function debouncedLoad() { clearTimeout(_deb); _deb = setTimeout(loadRefs, 280); }

function _skeletonRows(n) {
  let s = "";
  for (let i = 0; i < n; i++) s += '<div class="skel-row"><div class="skel w70"></div><div class="skel w40"></div><div class="skel w90"></div></div>';
  return s;
}

async function loadRefs() {
  const search = $("#search").value.trim();
  if (state.view === "trash") {
    const { refs } = await api("/api/trash");
    state.refs = refs; renderTrash(); return;
  }
  const _box = $("#refList");
  if (_box) _box.innerHTML = _skeletonRows(4);   // yüklenirken iskelet göster
  let url = `/api/refs?collection=${state.collection}&search=${encodeURIComponent(search)}`;
  if (state.view === "starred") url += "&starred=1";
  if (state.tag) url += `&tag=${encodeURIComponent(state.tag)}`;
  const { refs } = await api(url);
  state.refs = refs;
  renderRefs();
}

function renderRefs() {
  const box = $("#refList");
  if (!state.refs.length) {
    // İlk kez / boş kütüphane → onboarding (yalnızca ana görünümde, arama/filtre yokken)
    const pristine = state.view === "library" && state.collection === "all" && !state.tag && !$("#search").value.trim();
    if (pristine) {
      box.innerHTML = `<div class="empty onboard">
        <h3>${t("Refly'a hoş geldin 👋")}</h3>
        <p style="color:#6b7785;margin:-4px 0 18px">${t("Başlamak için iki yol:")}</p>
        <div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center">
          <div style="flex:1;min-width:240px;max-width:320px;background:#fff;border:1px solid #e6e9ef;border-radius:14px;padding:18px;text-align:left">
            <div style="font-size:24px">✨</div>
            <b style="display:block;margin:6px 0 4px">${t("Otomatik referansla")}</b>
            <span style="font-size:13px;color:#6b7785;display:block;margin-bottom:12px">${t("ChatGPT'yle yazdığın metni yapıştır; Refly gerçek kaynakları bulup atıfları yerleştirsin.")}</span>
            <button class="primary magic" onclick="openAutoCiteSample()">${t("Örnekle dene")}</button>
          </div>
          <div style="flex:1;min-width:240px;max-width:320px;background:#fff;border:1px solid #e6e9ef;border-radius:14px;padding:18px;text-align:left">
            <div style="font-size:24px">＋</div>
            <b style="display:block;margin:6px 0 4px">${t("Kaynak ekle")}</b>
            <span style="font-size:13px;color:#6b7785;display:block;margin-bottom:12px">${t("DOI/PMID, toplu liste, PubMed araması, PDF ya da RIS/BibTeX ile kütüphaneni kur.")}</span>
            <button onclick="openImport('id')">${t("Referans ekle")}</button>
          </div>
        </div></div>`;
    } else {
      box.innerHTML = `<div class="empty"><h3>${t("Henüz kaynak yok")}</h3>
        <p>${t("Sağ üstten <b>+ Referans ekle</b> ile DOI/PMID, toplu liste, PubMed araması, PDF veya RIS/BibTeX ile başla.")}</p></div>`;
    }
    updateSel(); return;
  }
  box.innerHTML = "";
  for (const r of state.refs) {
    const authors = (r.authors || []).slice(0, 4).join(", ") + ((r.authors || []).length > 4 ? ", et al." : "");
    const journal = r.iso || r.journal || "";
    const integ = r.integrity;
    const row = document.createElement("div");
    row.className = "ref-row" + (integ && integ.severity === "high" ? " flagged" : "");
    row.innerHTML = `
      <input type="checkbox" ${state.selected.has(r.id) ? "checked" : ""} onchange="toggleSel(${r.id})">
      <span class="star ${r.starred ? "on" : ""}" onclick="toggleStar(${r.id})" title="${t("Yıldızla")}">${r.starred ? "★" : "☆"}</span>
      <div class="ref-main">
        <div class="ref-title" onclick="openEdit(${r.id})">${esc(r.title) || t("(başlıksız)")}</div>
        <div class="ref-meta">${esc(authors)}${authors ? " · " : ""}<i>${esc(journal)}</i>${r.year ? " · " + esc(r.year) : ""}</div>
        <div class="ref-badges">
          ${r.doi ? `<span class="badge doi">DOI</span>` : ""}
          ${r.pmid ? `<span class="badge">PMID ${esc(r.pmid)}</span>` : ""}
          ${r.has_attachment ? `<span class="badge pdf" onclick="openPdf(event,${r.id})" title="${t("PDF'i aç")}">📎 PDF</span>` : ""}
          ${integ ? `<span class="badge ${integ.kind}" title="${esc(integ.note)}">${integ.kind === "retracted" ? t("⚠ GERİ ÇEKİLMİŞ") : integ.kind === "concern" ? t("⚠ Endişe ifadesi") : t("Erratum")}</span>` : ""}
          ${(r.tags || []).map(tg => `<span class="badge">#${esc(tg)}</span>`).join("")}
        </div>
      </div>
      <div class="row-actions">
        ${isIncomplete(r) ? `<button onclick="enrichOne(${r.id})" title="${t("Eksik alanları CrossRef/PubMed'den doldur")}">${t("🩹 Tamamla")}</button>` : ""}
        <button onclick="showRelated(${r.id})" title="${t("Benzer/ilgili makaleler öner")}">${t("🔗 İlgili")}</button>
        <button onclick="showMetrics(${r.id})" title="${t("Dergi metrikleri (etki, h-index)")}">📊</button>
        <button onclick="copyOne(${r.id})">${t("Kopyala")}</button>
        <button onclick="openEdit(${r.id})">${t("Düzenle")}</button>
        <button onclick="removeRef(${r.id})">${t("Sil")}</button>
      </div>`;
    box.appendChild(row);
  }
  updateSel();
}

function renderTrash() {
  const box = $("#refList");
  if (!state.refs.length) { box.innerHTML = `<div class="empty"><h3>${t("Çöp kutusu boş")}</h3></div>`; updateSel(); return; }
  box.innerHTML = `<div style="padding:8px 0;color:#6b7785">${t("Silinen kayıtlar — geri yükleyebilirsin.")}</div>`;
  for (const r of state.refs) {
    const row = document.createElement("div");
    row.className = "ref-row";
    row.innerHTML = `<div class="ref-main">
        <div class="ref-title">${esc(r.title) || t("(başlıksız)")}</div>
        <div class="ref-meta">${esc((r.authors || []).slice(0, 3).join(", "))} · ${esc(r.iso || r.journal)} · ${esc(r.year)}</div></div>
      <div class="row-actions" style="opacity:1"><button class="primary" onclick="restoreRef(${r.id})">${t("↩ Geri yükle")}</button></div>`;
    box.appendChild(row);
  }
  $("#selInfo").textContent = t("{0} silinmiş kayıt", state.refs.length);
}

function toggleSel(id) { state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id); updateSel(); }
function updateSel() {
  const n = state.selected.size;
  $("#selInfo").textContent = n ? t("{0} kaynak seçili", n) : t("{0} kaynak", state.refs.length);
}

function openPdf(e, id) { e.stopPropagation(); window.open(`/api/refs/${id}/attachment`, "_blank"); }
function isIncomplete(r) {
  return !r.doi || !r.year || !r.volume || !r.pages || !(r.journal || r.iso) || !(r.authors || []).length;
}
async function enrichOne(id) {
  toast(t("Tamamlanıyor…"), 4000);
  const j = await api(`/api/refs/${id}/enrich`, { method: "POST" });
  toast(j.filled.length ? t("Dolduruldu: {0} ✓", j.filled.join(", ")) : t("Yeni bilgi bulunamadı"));
  loadRefs();
}
async function enrichAll() {
  const { count } = await api(`/api/incomplete?collection=${state.collection}`);
  if (!count) return toast(t("Tüm kayıtlar zaten tam 🎉"));
  if (!confirm(t("{0} eksik kayıt CrossRef + PubMed'den tamamlanacak. Devam?", count))) return;
  toast(t("Kütüphane tamamlanıyor… (biraz sürebilir)"), 8000);
  const j = await api("/api/enrich/all", { method: "POST", body: JSON.stringify({ collection: state.collection }) });
  let m = t("{0}/{1} kayıt zenginleştirildi ({2} alan)", j.enriched, j.processed, j.fields_filled);
  if (j.remaining) m += t(" · {0} kaldı, tekrar çalıştır", j.remaining);
  toast(m, 5000); loadRefs();
}
async function toggleStar(id) { await api(`/api/refs/${id}/star`, { method: "POST" }); loadRefs(); loadCollections(); }
async function restoreRef(id) { await api(`/api/refs/${id}/restore`, { method: "POST" }); toast(t("Geri yüklendi ✓")); loadRefs(); loadCollections(); }

async function removeRef(id) {
  if (!confirm(t("Bu kaynak silinsin mi? (Çöp kutusundan geri alınabilir)"))) return;
  await api(`/api/refs/${id}/delete`, { method: "POST" });
  state.selected.delete(id); loadRefs(); loadCollections();
}

async function copyOne(id) {
  const { entries } = await api("/api/format", { method: "POST", body: JSON.stringify({ ids: [id], style: $("#style").value }) });
  const text = (entries[0] || "").replace(/^\d+\.\s*/, "");
  navigator.clipboard.writeText(text).then(() => toast(t("Kaynak panoya kopyalandı ✓")));
}

// ---------------------------------------------------------- ekle menüsü
function toggleAdd() { $("#addDropdown").classList.toggle("hidden"); }
document.addEventListener("click", (e) => {
  if (!e.target.closest(".add-menu")) $("#addDropdown").classList.add("hidden");
});

// ---------------------------------------------------------- modal yardımcıları
function showModal(html, wide) {
  $("#modal").innerHTML = html;
  $("#modal").style.width = wide ? "820px" : "560px";
  $("#modalBg").classList.remove("hidden");
}
function closeModal() { $("#modalBg").classList.add("hidden"); }
function closePanel(id) { $("#" + id).classList.add("hidden"); }
function collForImport() { return ["all", "none"].includes(state.collection) || state.view !== "library" ? null : state.collection; }
function importedMsg(j) {
  let m = t("{0} kaynak eklendi ✓", j.added);
  if (j.skipped_duplicates) m += t(" · {0} kopya atlandı", j.skipped_duplicates);
  if (j.failed && j.failed.length) m += t(" · {0} çekilemedi", j.failed.length);
  return m;
}

// ---------------------------------------------------------- import akışları
function openImport(kind) {
  $("#addDropdown").classList.add("hidden");
  const cancel = t("Vazgeç");
  if (kind === "id") showModal(`
    <h2>${t("DOI / PMID ile ekle")}</h2>
    <div class="field"><label>${t("DOI veya PMID")}</label>
      <input id="idVal" placeholder="10.1056/NEJMoa2034577  ·  …  ·  33301246" autofocus></div>
    <div class="modal-actions"><button onclick="closeModal()">${cancel}</button>
      <button class="primary" onclick="doImportId()">${t("Ekle")}</button></div>`);
  if (kind === "bulk") showModal(`
    <h2>${t("Toplu ekle")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Her satıra bir DOI veya PMID yapıştır. Kopyalar otomatik atlanır.")}</p>
    <div class="field"><textarea id="bulkVal" style="min-height:160px" placeholder="10.1056/NEJMoa2034577&#10;33301246&#10;10.1016/S0140-6736(20)31180-6" autofocus></textarea></div>
    <div class="modal-actions"><button onclick="closeModal()">${cancel}</button>
      <button class="primary" onclick="doImportBulk()">${t("Hepsini ekle")}</button></div>`);
  if (kind === "search") showModal(`
    <h2>${t("🔍 PubMed'de ara")}</h2>
    <div class="field"><label>${t("Arama terimi")}</label>
      <input id="q" placeholder="${t("ör: lumbar disc herniation microdiscectomy")}" autofocus></div>
    <div class="modal-actions"><button onclick="closeModal()">${cancel}</button>
      <button class="primary" onclick="doSearch()">${t("Ara")}</button></div>
    <div id="cands"></div>`);
  if (kind === "pdf") showModal(`
    <h2>${t("PDF'ten ekle")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Makale PDF'ini seç; Refly içindeki DOI'yi bulup kaydı çeker.")}</p>
    <div class="field"><input type="file" id="pdfFile" accept=".pdf"></div>
    <div class="modal-actions"><button onclick="closeModal()">${cancel}</button>
      <button class="primary" onclick="doImportPdf()">${t("Yükle")}</button></div>`);
  if (kind === "pdfbulk") showModal(`
    <h2>${t("Toplu PDF import")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Bir klasördeki tüm makale PDF'lerini seç. Refly her birinin DOI'sini bulup kaydı çeker <b>ve PDF'i kayda ekler</b>. DOI bulunamayanlar atlanır.")}</p>
    <div class="field"><input type="file" id="pdfBulkFiles" accept=".pdf" multiple></div>
    <div class="modal-actions"><button onclick="closeModal()">${cancel}</button>
      <button class="primary" onclick="doImportPdfBulk()">${t("Hepsini içe aktar")}</button></div>`);
  if (kind === "file") showModal(`
    <h2>${t("RIS / BibTeX yükle")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("EndNote, Zotero veya Mendeley'den dışa aktardığın <b>.ris</b> / <b>.bib</b> dosyasını seç.")}</p>
    <div class="field"><input type="file" id="impFile" accept=".ris,.bib,.txt,.nbib"></div>
    <div class="modal-actions"><button onclick="closeModal()">${cancel}</button>
      <button class="primary" onclick="doImportFile()">${t("Yükle")}</button></div>`);
}

async function doImportId(force) {
  const value = $("#idVal").value.trim();
  if (!value) return;
  const btn = $("#modal .primary"); btn.innerHTML = '<span class="spin"></span>';
  try {
    const j = await api("/api/import/identifier", { method: "POST", body: JSON.stringify({ value, collection: collForImport(), force: !!force }) });
    if (j.duplicate) {
      if (confirm(t("Bu kaynak zaten kütüphanede:\n\"{0}\"\n\nYine de eklensin mi?", j.title))) return doImportId(true);
      btn.innerHTML = t("Ekle"); return;
    }
    closeModal(); toast(t("Eklendi ✓")); loadRefs(); loadCollections();
  } catch (e) { toast(e.message); btn.innerHTML = t("Ekle"); }
}

async function doImportBulk() {
  const text = $("#bulkVal").value.trim();
  if (!text) return;
  const btn = $("#modal .primary"); btn.innerHTML = `<span class="spin"></span> ${t("İşleniyor…")}`;
  try {
    const j = await api("/api/import/bulk", { method: "POST", body: JSON.stringify({ text, collection: collForImport() }) });
    closeModal(); toast(importedMsg(j)); loadRefs(); loadCollections();
  } catch (e) { toast(e.message); btn.innerHTML = t("Hepsini ekle"); }
}

let _cands = [];
async function doSearch() {
  const query = $("#q").value.trim();
  if (!query) return;
  const btn = $("#modal .primary"); btn.innerHTML = '<span class="spin"></span>';
  try {
    const { candidates } = await api("/api/import/search", { method: "POST", body: JSON.stringify({ query }) });
    _cands = candidates;
    $("#cands").innerHTML = candidates.length ? candidates.map((c, i) => `
      <div class="cand"><input type="checkbox" id="c${i}" checked>
        <div><div class="cand-title">${esc(c.title)}</div>
        <div class="cand-meta">${esc((c.authors || []).slice(0, 3).join(", "))} · ${esc(c.iso || c.journal)} · ${esc(c.year)}</div></div></div>`).join("") +
      `<div class="modal-actions"><button onclick="closeModal()">${t("Kapat")}</button>
        <button class="primary" onclick="addSelectedCands()">${t("Seçilenleri ekle")}</button></div>`
      : `<p>${t("Sonuç bulunamadı.")}</p>`;
  } catch (e) { toast(e.message); }
  btn.innerHTML = t("Ara");
}
async function addSelectedCands() {
  const items = _cands.filter((_, i) => $("#c" + i)?.checked);
  if (!items.length) return;
  const j = await api("/api/import/add", { method: "POST", body: JSON.stringify({ items, collection: collForImport() }) });
  closeModal(); toast(importedMsg(j)); loadRefs(); loadCollections();
}

async function doImportFile() {
  const f = $("#impFile").files[0];
  if (!f) return toast(t("Dosya seç"));
  await uploadFile("/api/import/file", f);
}
async function doImportPdf() {
  const f = $("#pdfFile").files[0];
  if (!f) return toast(t("PDF seç"));
  await uploadFile("/api/import/pdf", f);
}
async function doImportPdfBulk() {
  const files = $("#pdfBulkFiles").files;
  if (!files.length) return toast(t("PDF seç"));
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  if (collForImport()) fd.append("collection", collForImport());
  const btn = $("#modal .primary"); btn.innerHTML = `<span class="spin"></span> ${t("İşleniyor…")}`;
  try {
    const r = await fetch("/api/import/pdf-bulk", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    let m = t("{0} PDF eklendi ✓", j.added);
    if (j.skipped_duplicates) m += t(" · {0} kopya", j.skipped_duplicates);
    if (j.no_doi && j.no_doi.length) m += t(" · {0} DOI'siz atlandı", j.no_doi.length);
    closeModal(); toast(m); loadRefs(); loadCollections();
  } catch (e) { toast(e.message); btn.innerHTML = t("Hepsini içe aktar"); }
}
async function uploadFile(url, f) {
  const fd = new FormData(); fd.append("file", f);
  if (collForImport()) fd.append("collection", collForImport());
  const btn = $("#modal .primary"); btn.innerHTML = '<span class="spin"></span>';
  try {
    const r = await fetch(url, { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    if (j.duplicate) { toast(t("Zaten kütüphanede: \"{0}\"", j.title)); }
    else { toast(j.added != null ? importedMsg(j) : t("Eklendi ✓")); }
    closeModal(); loadRefs(); loadCollections();
  } catch (e) { toast(e.message); btn.innerHTML = t("Yükle"); }
}

// ---------------------------------------------------------- elle gir / düzenle
async function openEdit(id) {
  $("#addDropdown").classList.add("hidden");
  let r = { authors: [], tags: [] };
  if (id) r = await api(`/api/refs/${id}`);
  const v = (k) => esc(r[k] || "");
  showModal(`
    <h2>${id ? t("Referansı düzenle") : t("Yeni referans")}</h2>
    <div class="field"><label>${t("Başlık *")}</label><textarea id="f_title">${v("title")}</textarea></div>
    <div class="field"><label>${t("Yazarlar (her satıra biri, ör: Smith J)")}</label>
      <textarea id="f_authors">${esc((r.authors || []).join("\n"))}</textarea></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
      <div class="field"><label>${t("Dergi")}</label><input id="f_journal" value="${v("journal")}"></div>
      <div class="field"><label>${t("Kısaltma (ISO)")}</label><input id="f_iso" value="${v("iso")}"></div>
      <div class="field"><label>${t("Yıl")}</label><input id="f_year" value="${v("year")}"></div>
      <div class="field"><label>${t("Cilt")}</label><input id="f_volume" value="${v("volume")}"></div>
      <div class="field"><label>${t("Sayı")}</label><input id="f_issue" value="${v("issue")}"></div>
      <div class="field"><label>${t("Sayfa")}</label><input id="f_pages" value="${v("pages")}"></div>
      <div class="field"><label>DOI</label><input id="f_doi" value="${v("doi")}"></div>
      <div class="field"><label>PMID</label><input id="f_pmid" value="${v("pmid")}"></div>
    </div>
    <div class="field"><label>${t("Etiketler (virgülle)")} ${id ? `<button type="button" style="float:right;padding:2px 8px;font-size:12px" onclick="autotagOne(${id})">${t("🏷 Öner")}</button>` : ""}</label>
      <input id="f_tags" value="${esc((r.tags || []).join(", "))}"></div>
    <div class="field"><label>${t("Not")}</label><textarea id="f_notes">${v("notes")}</textarea></div>
    ${id ? `<div class="field"><label>${t("PDF eki")}</label>
      <div id="pdfZone" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        ${r.has_attachment ? `<button onclick="openPdf(event,${id})">${t("📎 PDF'i aç")}</button>
          <button onclick="detachPdf(${id})">${t("Kaldır")}</button>
          <span style="color:#6b7785;font-size:12px">${t("değiştirmek için yeni PDF seç:")}</span>` : ""}
        <input type="file" id="f_pdf" accept=".pdf" onchange="attachPdf(${id})">
      </div></div>` : ""}
    <div class="modal-actions"><button onclick="closeModal()">${t("Vazgeç")}</button>
      <button class="primary" onclick="saveRef(${id || "null"})">${t("Kaydet")}</button></div>`);
}

async function attachPdf(id) {
  const f = $("#f_pdf").files[0];
  if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch(`/api/refs/${id}/attach`, { method: "POST", body: fd });
  if (r.ok) { toast(t("PDF eklendi ✓")); openEdit(id); loadRefs(); }
  else toast(t("PDF eklenemedi"));
}
async function detachPdf(id) {
  if (!confirm(t("PDF eki kaldırılsın mı?"))) return;
  await api(`/api/refs/${id}/detach`, { method: "POST" });
  toast(t("Kaldırıldı")); openEdit(id); loadRefs();
}

async function saveRef(id) {
  const val = (k) => ($("#f_" + k)?.value || "").trim();
  const data = {
    title: val("title"), journal: val("journal"), iso: val("iso"), year: val("year"),
    volume: val("volume"), issue: val("issue"), pages: val("pages"), doi: val("doi"), pmid: val("pmid"),
    notes: val("notes"),
    authors: val("authors").split("\n").map(s => s.trim()).filter(Boolean),
    tags: val("tags").split(",").map(s => s.trim()).filter(Boolean),
    collection_id: collForImport(),
  };
  if (!data.title) return toast(t("Başlık gerekli"));
  try {
    if (id) await api(`/api/refs/${id}`, { method: "PUT", body: JSON.stringify(data) });
    else await api("/api/refs", { method: "POST", body: JSON.stringify(data) });
    closeModal(); toast(t("Kaydedildi ✓")); loadRefs(); loadCollections();
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------- stiller + kaynakça
async function loadStyles() {
  const { styles } = await api("/api/styles");
  $("#style").innerHTML = styles.map(([id, label]) => `<option value="${esc(id)}">${esc(label)}</option>`).join("");
}

function openStyleSearch() {
  showModal(`<h2>${t("Dergi stili ara")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("2000+ dergi stili (Vancouver, AMA, Spine, Neurosurgery…). Seçince stil listesine eklenir.")}</p>
    <div class="field"><input id="styleQ" placeholder="${t("ör: spine, neurosurgery, jama…")}" autofocus oninput="runStyleSearch()"></div>
    <div id="styleResults" style="max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:8px"></div>`);
  runStyleSearch();
}
let _sdeb;
function runStyleSearch() {
  clearTimeout(_sdeb);
  _sdeb = setTimeout(async () => {
    const { results } = await api(`/api/styles/search?q=${encodeURIComponent($("#styleQ").value.trim())}`);
    $("#styleResults").innerHTML = results.map(r =>
      `<div class="style-result" onclick="pickStyle('${esc(r.id)}','${esc(r.label)}')">${esc(r.label)}</div>`).join("") || `<div style='padding:12px'>${t("Sonuç yok.")}</div>`;
  }, 220);
}
function pickStyle(id, label) {
  const sel = $("#style");
  if (![...sel.options].some(o => o.value === id)) {
    const o = document.createElement("option"); o.value = id; o.textContent = label + " ✓"; sel.appendChild(o);
  }
  sel.value = id; closeModal(); toast(t("Stil seçildi: {0}", label));
}

function formatPayload() {
  const ids = [...state.selected];
  return ids.length ? { ids, style: $("#style").value } : { collection: state.collection, style: $("#style").value };
}

async function buildBibliography() {
  const { entries } = await api("/api/format", { method: "POST", body: JSON.stringify(formatPayload()) });
  $("#biblioList").innerHTML = entries.length
    ? entries.map(e => `<li>${esc(e.replace(/^\d+\.\s*/, ""))}</li>`).join("")
    : `<p style='padding:16px'>${t("Kaynak yok.")}</p>`;
  $("#biblioPanel").classList.remove("hidden");
}
function copyBiblio() {
  const text = [...$("#biblioList").querySelectorAll("li")].map((li, i) => `${i + 1}. ${li.textContent}`).join("\n");
  navigator.clipboard.writeText(text).then(() => toast(t("Kaynakça panoya kopyalandı ✓")));
}

async function exportAs(format) {
  const body = JSON.stringify({ ...formatPayload(), format });
  const r = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body });
  if (!r.ok) return toast(t("Dışa aktarma hatası"));
  downloadBlob(await r.blob(), r);
}
function downloadBlob(blob, r) {
  const cd = r.headers.get("Content-Disposition") || "";
  const name = ((cd.match(/filename=([^;]+)/) || [])[1] || "refly-export").replace(/"/g, "");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------------------------------------------------- çok stilde kopyala
const STYLE_LABELS = { vancouver: "Vancouver", ama: "AMA / JAMA", apa: "APA 7", harvard: "Harvard", "the-lancet": "Lancet", nature: "Nature" };
async function openMultiStyle() {
  const ids = [...state.selected];
  const payload = ids.length ? { ids: ids.slice(0, 1) } : { collection: state.collection };
  if (!ids.length && !state.refs.length) return toast(t("Önce bir kaynak seç"));
  if (!ids.length) payload.ids = [state.refs[0].id];
  const styles = Object.keys(STYLE_LABELS);
  const { styles: res } = await api("/api/format/multi", { method: "POST", body: JSON.stringify({ ...payload, styles }) });
  showModal(`<h2>${t("🎨 Çok stilde")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Aynı kaynağın farklı dergi stillerinde hali — tıkla, kopyala.")}</p>
    ${styles.map(s => {
      const txt = (res[s] && res[s][0]) || "";
      return `<div style="margin-bottom:10px"><div style="font-size:12px;color:#6d28d9;font-weight:600">${STYLE_LABELS[s]}</div>
        <div style="display:flex;gap:8px;align-items:flex-start">
          <div style="flex:1;font-size:13px;line-height:1.5">${esc(txt)}</div>
          <button onclick="copyText(${JSON.stringify(txt).replace(/"/g, "&quot;")})">${t("Kopyala")}</button></div></div>`;
    }).join("")}
    <div class="modal-actions"><button class="primary" onclick="closeModal()">${t("Kapat")}</button></div>`);
}
function copyText(x) { navigator.clipboard.writeText(x).then(() => toast(t("Kopyalandı ✓"))); }

// ---------------------------------------------------------- atıf aracı
function openManuscript() {
  showModal(`<h2>${t("Atıf aracı")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Metnine kaynak no'larını <b>{{id}}</b> veya <b>[#id]</b> olarak yaz. (id = listedeki kaynak; satırın üstüne gelince PMID rozetinde görünür.) Refly sırayla [1],[2]… numaralar ve kaynakçayı üretir.")}</p>
    <div class="ms-grid">
      <textarea id="msText" oninput="msPreview()" placeholder="{{1}} … {{2}} …"></textarea>
      <div class="ms-preview" id="msOut"><i style="color:#9aa6b2">${t("Önizleme burada görünecek…")}</i></div>
    </div>
    <div class="modal-actions">
      <button onclick="closeModal()">${t("Kapat")}</button>
      <button onclick="copyManuscriptText()">${t("📋 Metni kopyala")}</button>
      <button class="primary" onclick="msExport()">${t("Word olarak indir")}</button>
    </div>`, true);
}
// ---------------------------------------------------------- yaz & atıfla editörü (#8)
function openWriter() {
  showModal(`<h2>${t("✍️ Yaz & atıfla")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Yaz; imlecin olduğu yere kütüphaneden atıf ekle. Sağda numaralı metin + kaynakça canlı oluşur, Word olarak indir.")}</p>
    <div style="display:flex;gap:6px;margin-bottom:6px;position:relative">
      <input id="wCite" placeholder="${t("➕ Atıf ekle: kütüphanede ara…")}" oninput="wSearch()" autocomplete="off" style="flex:1">
      <select id="wStyle" onchange="wPreview()" style="max-width:150px"></select>
      <div id="wResults" class="dropdown hidden" style="top:42px;left:0;right:auto;max-height:230px;overflow:auto;min-width:280px"></div>
    </div>
    <div class="ms-grid">
      <textarea id="wText" oninput="wPreview()" placeholder="${t("Metnini buraya yaz…")}" style="min-height:300px"></textarea>
      <div class="ms-preview" id="wOut" style="min-height:300px"><i style="color:#9aa6b2">${t("Önizleme burada görünecek…")}</i></div>
    </div>
    <div class="modal-actions">
      <button onclick="closeModal()">${t("Kapat")}</button>
      <button id="wRephraseBtn" class="magic" onclick="wRephrase()" title="${t("Seçili metni (yoksa tümünü) daha net/akademik yaz — atıflar korunur")}">${t("✍️ Yeniden ifade et")}</button>
      <button onclick="wCopy()">${t("📋 Metni kopyala")}</button>
      <button class="primary" onclick="wExport()">${t("Word olarak indir")}</button>
    </div>`, true);
  const ws = $("#wStyle"); ws.innerHTML = $("#style").innerHTML; ws.value = $("#style").value;
}
let _wDeb, _wResult = null;
async function wSearch() {
  const q = $("#wCite").value.trim(), box = $("#wResults");
  if (q.length < 2) { box.classList.add("hidden"); return; }
  const { refs } = await api(`/api/refs?collection=all&search=${encodeURIComponent(q)}`);
  box.innerHTML = refs.length
    ? refs.slice(0, 8).map(r => `<a onclick="insertCite(${r.id})">${esc((r.authors || [])[0] || "")} ${esc(r.year || "")} — ${esc((r.title || "").slice(0, 52))}</a>`).join("")
    : `<a style="color:#8a97a8">${t("Sonuç yok — önce kütüphanene ekle")}</a>`;
  box.classList.remove("hidden");
}
function insertCite(id) {
  const ta = $("#wText"), pos = ta.selectionStart ?? ta.value.length, marker = `[#${id}]`;
  ta.value = ta.value.slice(0, pos) + marker + ta.value.slice(pos);
  ta.focus(); ta.selectionStart = ta.selectionEnd = pos + marker.length;
  $("#wResults").classList.add("hidden"); $("#wCite").value = "";
  wPreview();
}
function wPreview() {
  clearTimeout(_wDeb);
  _wDeb = setTimeout(async () => {
    const text = $("#wText").value;
    if (!text.trim()) { $("#wOut").innerHTML = `<i style='color:#9aa6b2'>${t("Önizleme…")}</i>`; _wResult = null; return; }
    const d = await api("/api/manuscript", { method: "POST", body: JSON.stringify({ text, style: $("#wStyle").value }) });
    _wResult = d;
    let html = `<div style="white-space:pre-wrap">${esc(d.text)}</div>`;
    if (d.missing && d.missing.length) html += `<p style="color:#c0392b">${t("⚠ Bulunamayan id: {0}", d.missing.join(", "))}</p>`;
    if (d.entries.length) html += `<hr><b>${t("Kaynaklar")}</b><ol style="padding-left:18px">${d.entries.map(e => `<li>${esc(e.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol>`;
    $("#wOut").innerHTML = html;
  }, 300);
}
function wCopy() {
  if (!_wResult) return toast(t("Önce yaz"));
  let txt = _wResult.text || "";
  if (_wResult.entries && _wResult.entries.length) txt += "\n\n" + t("Kaynaklar") + "\n" + _wResult.entries.join("\n");
  copyStr(txt);
}
async function wExport() {
  const text = $("#wText").value;
  if (!text.trim()) return toast(t("Önce metin yaz"));
  const r = await fetch("/api/manuscript/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, style: $("#wStyle").value }) });
  if (!r.ok) return toast(t("Hata"));
  downloadBlob(await r.blob(), r); toast(t("İndirildi ✓"));
}
async function wRephrase() {
  const ta = $("#wText");
  let s = ta.selectionStart, e = ta.selectionEnd;
  if (s === e) { s = 0; e = ta.value.length; }        // seçim yoksa tüm metin
  const sel = ta.value.slice(s, e).trim();
  if (!sel) return toast(t("Önce yaz"));
  const btn = $("#wRephraseBtn"), lbl = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "…"; }
  try {
    const d = await api("/api/rephrase", { method: "POST", body: JSON.stringify({ text: sel }) });
    if (d && d.text) {
      ta.value = ta.value.slice(0, s) + d.text + ta.value.slice(e);
      ta.selectionStart = s; ta.selectionEnd = s + d.text.length;
      wPreview();
      toast(t("Yeniden yazıldı ✓"));
    }
  } catch (err) { toast(err.message || t("Hata")); }
  if (btn) { btn.disabled = false; btn.textContent = lbl; }
  ta.focus();
}

let _mdeb, _msResult = null;
function msPreview() {
  clearTimeout(_mdeb);
  _mdeb = setTimeout(async () => {
    const text = $("#msText").value;
    if (!text.trim()) { $("#msOut").innerHTML = `<i style='color:#9aa6b2'>${t("Önizleme…")}</i>`; _msResult = null; return; }
    const d = await api("/api/manuscript", { method: "POST", body: JSON.stringify({ text, style: $("#style").value }) });
    _msResult = d;
    let html = `<div style="white-space:pre-wrap">${esc(d.text)}</div>`;
    if (d.missing && d.missing.length) html += `<p style="color:#c0392b">${t("⚠ Bulunamayan id: {0}", d.missing.join(", "))}</p>`;
    if (d.entries.length) html += `<hr><b>${t("Kaynaklar")}</b><ol style="padding-left:18px">${d.entries.map(e => `<li>${esc(e.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol>`;
    $("#msOut").innerHTML = html;
  }, 300);
}
async function msExport() {
  const text = $("#msText").value;
  if (!text.trim()) return toast(t("Önce metin yaz"));
  const r = await fetch("/api/manuscript/export", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, style: $("#style").value }) });
  if (!r.ok) return toast(t("Hata")); downloadBlob(await r.blob(), r); toast(t("İndirildi ✓"));
}
function copyManuscriptText() {
  if (!_msResult) return toast(t("Önce metin yaz"));
  let txt = (_msResult.text || "").trim();
  if (_msResult.entries && _msResult.entries.length) txt += "\n\n" + t("Kaynaklar") + "\n" + _msResult.entries.join("\n");
  navigator.clipboard.writeText(txt).then(() => toast(t("Metin kopyalandı ✓")));
}

// ---------------------------------------------------------- ilgili makale öner
let _relCands = [];
async function showRelated(id) {
  showModal(`<h2>${t("🔗 İlgili makaleler")}</h2><div id="relBody"><span class="spin"></span> ${t("PubMed taranıyor…")}</div>`);
  try {
    const j = await api(`/api/refs/${id}/related`);
    _relCands = j.candidates;
    if (!j.candidates.length) { $("#relBody").innerHTML = `<p>${t("Yeni öneri bulunamadı (hepsi zaten kütüphanende olabilir).")}</p>`; return; }
    $("#relBody").innerHTML = `<p style="color:#6b7785;font-size:13px">${t("\"{0}…\" makalesine benzer, kütüphanende olmayan makaleler. Atıf sayısı = etki göstergesi.", esc(j.source_title.slice(0, 70)))}</p>` +
      j.candidates.map((c, i) => `<div class="cand"><input type="checkbox" id="r${i}">
        <div><div class="cand-title">${esc(c.title)}</div>
        <div class="cand-meta">${esc((c.authors || []).slice(0, 3).join(", "))} · ${esc(c.iso || c.journal)} · ${esc(c.year)}
          <b style="color:#2257c5"> · ${t("{0} atıf", c.citations)}</b>${refLinks(c)}</div></div></div>`).join("") +
      `<div class="modal-actions"><button onclick="closeModal()">${t("Kapat")}</button>
        <button class="primary" onclick="addSelectedRelated()">${t("Seçilenleri ekle")}</button></div>`;
  } catch (e) { $("#relBody").innerHTML = `<p style="color:#c0392b">${esc(e.message)}</p>`; }
}
async function addSelectedRelated() {
  const items = _relCands.filter((_, i) => $("#r" + i)?.checked);
  if (!items.length) return toast(t("Seçim yok"));
  const j = await api("/api/import/add", { method: "POST", body: JSON.stringify({ items, collection: collForImport() }) });
  closeModal(); toast(importedMsg(j)); loadRefs(); loadCollections();
}

// ---------------------------------------------------------- otomatik etiketleme
async function autotagAll() {
  if (!confirm(t("Etiketsiz kayıtlar Claude ile otomatik etiketlenecek. Devam?"))) return;
  toast(t("Etiketleniyor… (biraz sürebilir)"), 8000);
  try {
    const j = await api("/api/autotag/all", { method: "POST", body: JSON.stringify({ collection: state.collection }) });
    let m = t("{0}/{1} kayıt etiketlendi", j.tagged, j.processed);
    if (j.remaining) m += t(" · {0} kaldı, tekrar çalıştır", j.remaining);
    toast(m, 5000); loadRefs(); loadCollections();
  } catch (e) { toast(e.message); }
}
async function autotagOne(id) {
  toast(t("Etiket öneriliyor…"), 4000);
  const j = await api(`/api/refs/${id}/autotag`, { method: "POST" });
  const inp = $("#f_tags");
  if (inp) inp.value = j.tags.join(", ");
  toast(j.added.length ? t("Önerilen: {0} ✓", j.added.join(", ")) : t("Etiket önerilemedi"));
  loadCollections();
}

// ---------------------------------------------------------- otomatik referanslama
let _acJob = null, _acTimer = null, _acResult = null;
function openAutoCite() {
  showModal(`<h2>${t("✨ Otomatik referansla")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("ChatGPT'yle yazdığın (referanssız ya da <b>sahte referanslı</b>) metni yapıştır ya da Word/PDF olarak yükle. Refly her iddiayı okur, PubMed'de <b>gerçek</b> kaynağı bulur, özetini doğrular ve atıfları yerleştirir.")}</p>
    <div class="field"><textarea id="acText" style="min-height:170px" placeholder="${t("Metnini buraya yapıştır…")}"></textarea></div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px">
      <label style="font-size:13px;color:#6b7785">${t("📎 ya da dosya:")} <input type="file" id="acFile" accept=".docx,.pdf,.txt"></label>
      <label style="font-size:13px;color:#6b7785"><input type="checkbox" id="acClean" checked> ${t("Mevcut/sahte atıfları temizle")}</label>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <label style="font-size:13px;color:#6b7785">${t("Stil:")} <b id="acStyle"></b></label>
      <span style="flex:1"></span>
      <button onclick="closeModal()">${t("Vazgeç")}</button>
      <button class="primary magic" onclick="startAutoCite()">${t("Tara ve referansla")}</button>
    </div>
    <div id="acBody"></div>`, true);
  $("#acStyle").textContent = $("#style").options[$("#style").selectedIndex]?.text || "Vancouver";
}

// Onboarding: auto-cite modalını örnek metinle açar (kullanıcı sihri hemen görsün)
const _AC_SAMPLE = "Chronic low back pain is one of the leading causes of disability worldwide. " +
  "Exercise therapy reduces pain and improves function in patients with chronic low back pain. " +
  "Lumbar disc herniation is a common cause of sciatica. " +
  "Microdiscectomy provides faster short-term relief of sciatica than conservative care.";
function openAutoCiteSample() {
  openAutoCite();
  const ta = $("#acText");
  if (ta) { ta.value = _AC_SAMPLE; ta.focus(); }
}

async function startAutoCite() {
  const file = $("#acFile").files[0];
  const text = $("#acText").value.trim();
  if (!file && text.length < 40) return toast(t("Metin yapıştır ya da dosya seç"));
  $("#acBody").innerHTML = `<div class="progress"><div class="fill" id="acFill"></div></div>
    <div class="ac-prog-label" id="acLabel"><span class="spin"></span> ${t("Başlatılıyor…")}</div>`;
  const clean = $("#acClean").checked;
  try {
    let resp;
    if (file) {
      const fd = new FormData();
      fd.append("file", file); fd.append("style", $("#style").value);
      fd.append("clean_existing", clean ? "1" : "0");
      resp = await (await fetch("/api/autocite/start", { method: "POST", body: fd })).json();
    } else {
      resp = await api("/api/autocite/start", { method: "POST",
        body: JSON.stringify({ text, style: $("#style").value, clean_existing: clean }) });
    }
    if (resp.error) throw new Error(resp.error);
    _acJob = resp.job_id;
    _acTimer = setInterval(pollAutoCite, 1500);
  } catch (e) { $("#acBody").innerHTML = `<p style="color:#c0392b">${esc(e.message)}</p>`; }
}

async function pollAutoCite() {
  if (!_acJob) return;
  const j = await api(`/api/autocite/status/${_acJob}`);
  if (j.state === "running") {
    const pct = j.total ? Math.round(j.done / j.total * 100) : 8;
    $("#acFill").style.width = pct + "%";
    $("#acLabel").innerHTML = `<span class="spin"></span> ${esc(t(j.stage || ""))} ${j.total ? `(${j.done}/${j.total})` : ""}`;
    return;
  }
  clearInterval(_acTimer); _acTimer = null;
  if (j.state === "error") { $("#acBody").innerHTML = `<p style="color:#c0392b">${t("Hata")}: ${esc(j.error)}</p>`; return; }
  _acResult = j.result;
  renderAutoCiteResult(j.result);
}

function confColor(c) { return c >= 85 ? "#1f9d57" : c >= 70 ? "#d98c00" : "#c0392b"; }

// Bir kayda erişim/indirme linkleri (DOI yayıncıya, PubMed özet+tam metin linklerine)
function refLinks(c) {
  if (!c) return "";
  const parts = [];
  if (c.doi) parts.push(`<a href="https://doi.org/${encodeURIComponent(c.doi)}" target="_blank" rel="noopener" style="color:#2257c5">DOI</a>`);
  if (c.pmid) parts.push(`<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(c.pmid)}/" target="_blank" rel="noopener" style="color:#2257c5">PubMed</a>`);
  return parts.length ? ` <span style="font-size:12px;white-space:nowrap">🔗 ${parts.join(" · ")}</span>` : "";
}

// İnceleme paneli durumu: atıf stili + reddedilen atıf numaraları (kabul/ret)
var _acStyle = "num";        // "num" | "authoryear"
var _acRejected = new Set();

function renderAutoCiteResult(r) {
  _acResult = r; _acStyle = "num"; _acRejected = new Set();
  drawAutoCiteResult();
}
function acSetStyle(s) { _acStyle = s; drawAutoCiteResult(); }
function acToggle(num) { _acRejected.has(num) ? _acRejected.delete(num) : _acRejected.add(num); drawAutoCiteResult(); }
function acAccepted() { return (_acResult.citations || []).filter(c => !_acRejected.has(c.num)); }

function acLabel(c, newNum) {
  if (_acStyle === "authoryear") {
    const fam = ((c && c.author) || "").split(/\s+/)[0] || "?";
    return `(${fam}${c && c.year ? " " + c.year : ""})`;
  }
  return `[${newNum}]`;
}
// annotated_text'i güncel stil + kabul/ret'e göre yeniden kurar (html=true → önizleme)
function acRenderText(html) {
  const r = _acResult, accepted = acAccepted(), map = {};
  accepted.forEach((c, i) => map[c.num] = i + 1);
  return (html ? esc(r.annotated_text) : r.annotated_text).replace(/\s*\[(\d+)\]/g, (m, n) => {
    n = +n;
    if (_acRejected.has(n)) return "";           // reddedilen: işaretçi + öndeki boşluk çıkar
    const c = (r.citations || []).find(x => x.num === n);
    const lab = acLabel(c, map[n]);
    return html ? ` <span class="cite" title="${esc(c ? c.title + ' (%' + c.confidence + ')' : '')}">${esc(lab)}</span>` : ` ${lab}`;
  });
}

function drawAutoCiteResult() {
  const r = _acResult, accepted = acAccepted(), map = {};
  accepted.forEach((c, i) => map[c.num] = i + 1);
  let html = `<div class="ac-stats">
      <div><b>${r.n_claims}</b>${t("iddia bulundu")}</div>
      <div><b style="color:#1f9d57">${accepted.length}</b>${t("kaynak (kabul)")}</div>
      ${_acRejected.size ? `<div><b style="color:#c0392b">${_acRejected.size}</b>${t("reddedildi")}</div>` : ""}
      <div><b style="color:${r.unmatched.length ? '#d98c00' : '#6b7785'}">${r.unmatched.length}</b>${t("eşleşmedi")}</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px;margin:8px 0 4px">
      <span style="font-size:12px;color:#6b7785">${t("Atıf stili:")}</span>
      <button class="${_acStyle === 'num' ? 'primary' : ''}" style="padding:4px 11px;font-size:12px" onclick="acSetStyle('num')">[1]</button>
      <button class="${_acStyle === 'authoryear' ? 'primary' : ''}" style="padding:4px 11px;font-size:12px" onclick="acSetStyle('authoryear')">(Smith 2020)</button>
    </div>
    <div class="ac-text">${acRenderText(true)}</div>`;
  if (r.citations && r.citations.length) {
    html += `<b style="display:block;margin:12px 0 4px">${t("Kaynakları incele — kutucuğu kaldırınca atıf metinden çıkar")}</b>
      <div style="font-size:13px">` + r.citations.map((c, i) => {
      const rej = _acRejected.has(c.num), col = confColor(c.confidence);
      const entry = (r.entries[i] || c.title || "").replace(/^\d+\.\s*/, "");
      const alts = (c.alternatives || []).length
        ? `<div style="font-size:11px;color:#98a3b3;margin-top:3px">${t("Diğer adaylar:")} ${c.alternatives.map(a => esc((a.title || "").slice(0, 55))).join(" · ")}</div>` : "";
      return `<div style="display:flex;gap:9px;padding:8px 0;border-bottom:1px solid #eef2f7;${rej ? 'opacity:.5' : ''}">
        <input type="checkbox" ${rej ? '' : 'checked'} onchange="acToggle(${c.num})" style="margin-top:3px;accent-color:var(--brand)">
        <div style="flex:1">
          <div style="${rej ? 'text-decoration:line-through' : ''}">${rej ? '' : `<b>${map[c.num]}.</b> `}${esc(entry)}${refLinks(c)}</div>
          <div style="display:flex;align-items:center;gap:6px;margin-top:4px">
            <div style="height:5px;width:74px;background:#eef2f7;border-radius:4px;overflow:hidden"><div style="height:100%;width:${c.confidence}%;background:${col}"></div></div>
            <span style="font-size:11px;color:${col};font-weight:600">${t("güven")} %${c.confidence}</span>
          </div>${alts}
        </div></div>`;
    }).join("") + `</div>`;
  }
  if (r.unmatched.length) html += `<div class="ac-unmatched"><b>${t("Kaynak bulunamayan iddialar (uydurma atmamak için boş bırakıldı):")}</b>
    <ul>${r.unmatched.map(u => `<li>"${esc(u.sentence)}" — ${esc(u.reason)}</li>`).join("")}</ul></div>`;
  html += `<div style="margin-top:12px">
      <label style="font-size:12px;color:#6b7785;display:block;margin-bottom:4px">${t("Kopyalanabilir metin (seçip kopyala):")}</label>
      <textarea id="acPlain" readonly onclick="this.select()" style="width:100%;min-height:150px;font-size:13px;line-height:1.55;border:1px solid var(--line);border-radius:8px;padding:10px;box-sizing:border-box;resize:vertical">${esc(autociteToText())}</textarea>
    </div>`;
  html += `<div class="modal-actions" style="flex-wrap:wrap">
      <button onclick="closeModal()">${t("Kapat")}</button>
      <button onclick="saveAutoCite()">${t("📚 Kaynakları kütüphaneye ekle")}</button>
      <button onclick="exportAutoCite('docx')">${t("📄 Word indir")}</button>
      <button onclick="exportAutoCite('endnote')" title="EndNote'a import edilebilir (.xml)">📚 EndNote</button>
      <button onclick="exportAutoCite('ris')" title="EndNote/Zotero/Mendeley (.ris)">RIS</button>
      <button class="primary" onclick="copyAutoCiteText()">${t("📋 Metni kopyala")}</button>
    </div>`;
  $("#acBody").innerHTML = html;
}

// Kopyalanabilir metin — güncel stil + kabul edilen atıflara göre yeniden numaralı kaynakça
function autociteToText() {
  const r = _acResult, accepted = acAccepted();
  let txt = acRenderText(false).trim();
  if (accepted.length) {
    txt += "\n\n" + t("Kaynaklar") + "\n" + accepted.map((c, i) => {
      const entry = (r.entries[(r.citations || []).indexOf(c)] || c.title || "").replace(/^\d+\.\s*/, "");
      const url = c.doi ? "https://doi.org/" + c.doi : (c.pmid ? "https://pubmed.ncbi.nlm.nih.gov/" + c.pmid + "/" : "");
      const prefix = _acStyle === "authoryear" ? "• " : (i + 1) + ". ";
      return url ? `${prefix}${entry}  ${url}` : `${prefix}${entry}`;
    }).join("\n");
  }
  return txt;
}
function copyAutoCiteText() {
  const ta = $("#acPlain");
  if (!ta) return;
  ta.select();
  navigator.clipboard.writeText(ta.value).then(() => toast(t("Metin kopyalandı ✓")));
}

async function saveAutoCite() {
  const j = await api(`/api/autocite/save/${_acJob}`, { method: "POST", body: JSON.stringify({ collection: collForImport() }) });
  toast(importedMsg(j)); loadRefs(); loadCollections();
}
async function exportAutoCite(format) {
  const r = await fetch(`/api/autocite/export/${_acJob}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ format: format || "docx" }) });
  if (!r.ok) return toast(t("Hata")); downloadBlob(await r.blob(), r); toast(t("İndirildi ✓"));
}

// ---------------------------------------------------------- atıf denetleyici (Citation Audit)
var _auditJob = null, _auditTimer = null;
function openAudit() {
  showModal(`<h2>${t("🕵️ Atıf denetle")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Bir makalenin kaynakçasını ya da metindeki atıfları yapıştır. Refly her referansın <b>gerçekten var olup olmadığını</b> CrossRef ve PubMed'de doğrular — ChatGPT'nin uydurduğu sahte atıfları yakalar.")}</p>
    <div class="field"><textarea id="auditText" style="min-height:170px" placeholder="${t("Kaynakçayı buraya yapıştır (her satır bir referans)…")}"></textarea></div>
    <div style="display:flex;align-items:center;gap:10px">
      <span style="flex:1"></span>
      <button onclick="closeModal()">${t("Vazgeç")}</button>
      <button class="primary magic" onclick="startAudit()">${t("Referansları doğrula")}</button>
    </div>
    <div id="auditBody"></div>`, true);
}
async function startAudit() {
  const text = $("#auditText").value.trim();
  if (text.length < 30) return toast(t("Kaynakça yapıştır"));
  $("#auditBody").innerHTML = `<div class="progress"><div class="fill" id="auditFill"></div></div>
    <div class="ac-prog-label" id="auditLabel"><span class="spin"></span> ${t("Başlatılıyor…")}</div>`;
  try {
    const resp = await api("/api/audit/start", { method: "POST", body: JSON.stringify({ text }) });
    if (resp.error) throw new Error(resp.error);
    _auditJob = resp.job_id;
    _auditTimer = setInterval(pollAudit, 1500);
  } catch (e) { $("#auditBody").innerHTML = `<p style="color:#c0392b">${esc(e.message)}</p>`; }
}
async function pollAudit() {
  if (!_auditJob) return;
  const j = await api(`/api/audit/status/${_auditJob}`);
  if (j.state === "running") {
    const pct = j.total ? Math.round(j.done / j.total * 100) : 8;
    $("#auditFill").style.width = pct + "%";
    $("#auditLabel").innerHTML = `<span class="spin"></span> ${esc(t(j.stage || ""))} ${j.total ? `(${j.done}/${j.total})` : ""}`;
    return;
  }
  clearInterval(_auditTimer); _auditTimer = null;
  if (j.state === "error") { $("#auditBody").innerHTML = `<p style="color:#c0392b">${t("Hata")}: ${esc(j.error)}</p>`; return; }
  renderAuditResult(j.result);
}
function renderAuditResult(r) {
  const meta = { real: ["#1f9d57", "✓", t("Gerçek")], uncertain: ["#d98c00", "?", t("Belirsiz")],
                 fabricated: ["#c0392b", "✗", t("Bulunamadı")] };
  let html = `<h2>${t("🕵️ Atıf denetimi")}</h2>
    <div class="ac-stats">
      <span>✅ <b style="color:#1f9d57">${r.n_real}</b> ${t("gerçek")}</span>
      <span>⚠️ <b style="color:#d98c00">${r.n_uncertain}</b> ${t("belirsiz")}</span>
      <span>❌ <b style="color:#c0392b">${r.n_fabricated}</b> ${t("şüpheli")}</span>
      <span style="color:#6b7785;align-self:center">${t("Toplam {0}", r.n)}</span>
    </div>`;
  if (r.n_fabricated) html += `<div class="ac-unmatched" style="margin-top:0">${t("⚠ {0} referans CrossRef/PubMed'de bulunamadı — uydurma (ör. ChatGPT) olabilir, elle doğrula.", r.n_fabricated)}</div>`;
  html += r.references.map(x => {
    const [col, ic, lbl] = meta[x.status] || meta.uncertain;
    let m = "";
    if (x.match) m = `<div style="font-size:12px;color:#5a6675;margin-top:5px;padding-top:5px;border-top:1px dashed #e6e9f2">
      ${t("Eşleşen gerçek kaynak:")} <b>${esc(x.match.title)}</b> — ${esc(x.match.journal || "")} ${esc(x.match.year || "")}
      ${x.match.link ? `· <a href="${esc(x.match.link)}" target="_blank" rel="noopener" style="color:#2257c5">${t("aç")} ↗</a>` : ""}</div>`;
    return `<div style="border-left:3px solid ${col};background:#fbfcfe;border-radius:8px;padding:10px 12px;margin-bottom:8px">
      <div style="display:flex;gap:8px;align-items:baseline"><b style="color:${col};white-space:nowrap">${ic} ${lbl}</b>
        <span style="font-size:12px;color:#8a97a8">${esc(x.reason)}</span></div>
      <div style="font-size:13px;margin-top:4px;color:#1c2530">${esc(x.given.raw)}</div>${m}
    </div>`;
  }).join("");
  html += `<div class="modal-actions"><button class="primary" onclick="closeModal()">${t("Kapat")}</button></div>`;
  showModal(html, true);
}

// ------------------------------------------- AI derleme + kütüphaneye sor + dergi metrikleri
function refScope() {
  const ids = [...state.selected];
  return ids.length ? { ids } : { collection: state.collection };
}
function scopeLabel() {
  const n = state.selected.size;
  return n ? t("{0} seçili kaynak", n) : t("bu koleksiyondaki tüm kaynaklar");
}
function copyStr(s) { navigator.clipboard.writeText(s).then(() => toast(t("Kopyalandı ✓"))); }
var _synText = "";

function openSynthesize() {
  showModal(`<h2>${t("🧪 AI literatür derlemesi")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Claude, {0} üzerinden atıflı bir sentez paragrafı yazar. İstersen bir odak sorusu ekle.", scopeLabel())}</p>
    <div class="field"><input id="synQ" placeholder="${t("Odak sorusu (opsiyonel)")}"></div>
    <div style="display:flex;gap:10px"><span style="flex:1"></span>
      <button onclick="closeModal()">${t("Vazgeç")}</button>
      <button class="primary magic" onclick="runSynthesize()">${t("Derle")}</button></div>
    <div id="synBody"></div>`, true);
}
async function runSynthesize() {
  $("#synBody").innerHTML = `<div class="ac-prog-label" style="margin-top:12px"><span class="spin"></span> ${t("Derleniyor…")}</div>`;
  try {
    const r = await api("/api/synthesize", { method: "POST", body: JSON.stringify({ ...refScope(), question: $("#synQ").value.trim() }) });
    if (r.error) throw new Error(r.error);
    _synText = r.synthesis || "";
    let html = `<div class="ac-text" style="margin-top:12px">${esc(_synText)}</div>`;
    if (r.sources && r.sources.length) html += `<div style="margin-top:10px;font-size:12px;color:#6b7785"><b>${t("Kullanılan kaynaklar:")}</b><br>` +
      r.sources.map(s => `[${s.n}] ${esc(s.title)} ${s.year ? "(" + esc(s.year) + ")" : ""}${refLinks(s)}`).join("<br>") + `</div>`;
    html += `<div class="modal-actions"><button onclick="copyStr(_synText)">${t("📋 Kopyala")}</button><button class="primary" onclick="closeModal()">${t("Kapat")}</button></div>`;
    $("#synBody").innerHTML = html;
  } catch (e) { $("#synBody").innerHTML = `<p style="color:#c0392b">${esc(e.message)}</p>`; }
}

function openAskLibrary() {
  showModal(`<h2>${t("💬 Kütüphanene sor")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Claude, {0} özet/PDF metnine dayanarak sorunu ATIFLI yanıtlar — kütüphanende olmayanı uydurmaz.", scopeLabel())}</p>
    <div class="field"><input id="askQ" placeholder="${t("Sorunu yaz…")}" onkeydown="if(event.key==='Enter')runAsk()"></div>
    <div style="display:flex;gap:10px"><span style="flex:1"></span>
      <button onclick="closeModal()">${t("Vazgeç")}</button>
      <button class="primary magic" onclick="runAsk()">${t("Sor")}</button></div>
    <div id="askBody"></div>`, true);
}
async function runAsk() {
  const q = $("#askQ").value.trim();
  if (q.length < 4) return toast(t("Soru yaz"));
  $("#askBody").innerHTML = `<div class="ac-prog-label" style="margin-top:12px"><span class="spin"></span> ${t("Kütüphane taranıyor…")}</div>`;
  try {
    const r = await api("/api/library/ask", { method: "POST", body: JSON.stringify({ ...refScope(), question: q }) });
    if (r.error) throw new Error(r.error);
    let html = `<div class="ac-text" style="margin-top:12px">${esc(r.answer)}</div>`;
    if (r.sources && r.sources.length) html += `<div style="margin-top:10px;font-size:12px;color:#6b7785"><b>${t("Kaynaklar:")}</b><br>` +
      r.sources.map(s => `${esc(s.title)}${refLinks(s)}`).join("<br>") + `</div>`;
    else html += `<div style="margin-top:8px;font-size:12px;color:#8a97a8">${t("(Yanıtta kütüphane kaynağı kullanılmadı)")}</div>`;
    $("#askBody").innerHTML = html;
  } catch (e) { $("#askBody").innerHTML = `<p style="color:#c0392b">${esc(e.message)}</p>`; }
}

async function showMetrics(id) {
  toast(t("Metrikler alınıyor…"), 4000);
  try {
    const { metrics: m } = await api(`/api/refs/${id}/metrics`);
    if (!m) return toast(t("Bu dergi için metrik bulunamadı"));
    showModal(`<h2>${t("📊 Dergi metrikleri")}</h2>
      <div style="font-size:15px;font-weight:600">${esc(m.name)}</div>
      <div style="color:#6b7785;font-size:13px;margin-bottom:12px">${esc(m.publisher || "")}${m.issn ? " · ISSN " + esc(m.issn) : ""}</div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr)">
        <div class="stat-card"><div class="num">${m.impact ?? "–"}</div><div class="lbl">${t("Etki (2y ort. atıf)")}</div></div>
        <div class="stat-card"><div class="num">${m.h_index ?? "–"}</div><div class="lbl">h-index</div></div>
        <div class="stat-card"><div class="num" style="font-size:16px">${esc(m.tier || "–")}</div><div class="lbl">${t("Seviye")}</div></div>
      </div>
      <p style="font-size:11px;color:#8a97a8;margin-top:10px">${t("Kaynak: OpenAlex. 'Etki' 2 yıllık ortalama atıftır (JCR Impact Factor değil); seviye yaklaşıktır.")}</p>
      <div class="modal-actions"><button class="primary" onclick="closeModal()">${t("Kapat")}</button></div>`, true);
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------- ekip / paylaşımlı kütüphaneler
async function openSharing() {
  showModal(`<h2>${t("👥 Paylaşımlı kütüphaneler")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Koleksiyonlarını iş arkadaşlarınla paylaş (çok kullanıcılı sürümde). Kişi kendi Refly hesabıyla girince koleksiyonu görür.")}</p>
    <div id="shareBody"><div class="ac-prog-label"><span class="spin"></span></div></div>`, true);
  const [a, b] = await Promise.all([api("/api/collections"), api("/api/shared")]);
  const collections = a.collections || [], shared = b.shared || [];
  let html = `<h3 style="margin:8px 0 4px;font-size:14px">${t("Koleksiyonlarım")}</h3>`;
  html += collections.length ? collections.map(c => `<div style="border:1px solid #eef2f7;border-radius:10px;padding:10px;margin-bottom:8px">
      <b>${esc(c.name)}</b> <span style="color:#8a97a8;font-size:12px">(${c.n} ${t("kaynak")})</span>
      <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
        <input id="se${c.id}" placeholder="${t("e-posta")}" style="flex:1;min-width:140px">
        <select id="sr${c.id}"><option value="viewer">${t("Görüntüleyen")}</option><option value="editor">${t("Düzenleyen")}</option></select>
        <button class="primary" onclick="doShare(${c.id})">${t("Paylaş")}</button>
      </div><div id="sl${c.id}" style="margin-top:6px"></div></div>`).join("")
    : `<p style="color:#8a97a8;font-size:13px">${t("Henüz koleksiyon yok.")}</p>`;
  html += `<h3 style="margin:14px 0 4px;font-size:14px">${t("Bana paylaşılanlar")}</h3>`;
  html += shared.length ? shared.map(s => `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #eef2f7">
      <div style="flex:1;min-width:0"><b>${esc(s.name)}</b> <span style="font-size:12px;color:#8a97a8">· ${esc(s.owner)} · ${s.n} ${t("kaynak")} · ${s.role === "editor" ? t("düzenleyen") : t("görüntüleyen")}</span></div>
      <button onclick="viewShared(${s.collection_id})">${t("Aç")}</button></div>`).join("")
    : `<p style="color:#8a97a8;font-size:13px">${t("Sana paylaşılan koleksiyon yok.")}</p>`;
  $("#shareBody").innerHTML = html;
  collections.forEach(c => loadShares(c.id));
}
async function loadShares(cid) {
  const el = $("#sl" + cid);
  if (!el) return;
  const { shares } = await api(`/api/collections/${cid}/shares`);
  el.innerHTML = shares.length ? shares.map(s => `<span style="display:inline-flex;align-items:center;gap:4px;background:#eef2ff;color:#4f46e5;border-radius:14px;padding:2px 9px;margin:2px;font-size:12px">
      ${esc(s.email)} · ${s.role === "editor" ? t("düz.") : t("gör.")} <span onclick="revokeShare(${s.id},${cid})" style="cursor:pointer;font-weight:700">✕</span></span>`).join("")
    : `<span style="color:#98a3b3;font-size:12px">${t("Kimseyle paylaşılmadı")}</span>`;
}
async function doShare(cid) {
  const email = $("#se" + cid).value.trim();
  if (!email) return toast(t("E-posta gir"));
  const r = await api(`/api/collections/${cid}/share`, { method: "POST", body: JSON.stringify({ email, role: $("#sr" + cid).value }) });
  if (r.error) return toast(r.error);
  $("#se" + cid).value = ""; toast(t("Paylaşıldı ✓")); loadShares(cid);
}
async function revokeShare(sid, cid) { await api(`/api/shares/${sid}`, { method: "DELETE" }); loadShares(cid); }
async function viewShared(cid) {
  const { refs, role } = await api(`/api/shared/${cid}/refs`);
  showModal(`<h2>👥 ${t("Paylaşılan koleksiyon")}</h2>
    <p style="color:#8a97a8;font-size:12px">${role === "editor" ? t("Düzenleyen erişimi") : t("Görüntüleyen erişimi")} · ${refs.length} ${t("kaynak")}</p>
    <div style="font-size:13px;max-height:50vh;overflow:auto">${refs.map(r => `<div style="padding:7px 0;border-bottom:1px solid #eef2f7">
      <b>${esc(r.title)}</b><div style="font-size:12px;color:#6b7785">${esc((r.authors || []).slice(0, 3).join(", "))} · ${esc(r.iso || r.journal || "")} · ${esc(r.year || "")}${refLinks(r)}</div></div>`).join("")}</div>
    <div class="modal-actions"><button onclick="openSharing()">${t("← Paylaşımlar")}</button><button class="primary" onclick="closeModal()">${t("Kapat")}</button></div>`, true);
}

// ---------------------------------------------------------- konu alarmları
async function openAlerts() {
  showModal(`<h2>${t("🔔 Konu alarmları")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Bir PubMed araması kaydet; yeni makale çıkınca öğren. E-posta girersen (SMTP ayarlıysa) özet gönderilir.")}</p>
    <div style="display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap">
      <input id="alQuery" placeholder="${t("PubMed araması, ör. lumbar disc herniation")}" style="flex:2;min-width:180px">
      <input id="alEmail" placeholder="${t("e-posta (opsiyonel)")}" style="flex:1;min-width:120px">
      <button class="primary" onclick="addAlert()">${t("Ekle")}</button>
    </div>
    <div id="alList" style="margin-top:8px"></div>`, true);
  renderAlerts();
}
async function renderAlerts() {
  const box = $("#alList");
  box.innerHTML = `<div class="ac-prog-label"><span class="spin"></span></div>`;
  const { alerts } = await api("/api/alerts");
  if (!alerts.length) { box.innerHTML = `<p style="color:#8a97a8;font-size:13px">${t("Henüz alarm yok.")}</p>`; return; }
  box.innerHTML = alerts.map(a => `<div style="display:flex;align-items:center;gap:8px;padding:9px 0;border-bottom:1px solid #eef2f7">
      <div style="flex:1;min-width:0"><b>${esc(a.query)}</b>
        <div style="font-size:11px;color:#8a97a8">${a.email ? "✉ " + esc(a.email) + " · " : ""}${a.last_checked ? t("son: {0}", esc(a.last_checked)) : t("henüz kontrol edilmedi")}</div></div>
      <button onclick="checkAlert(${a.id})" title="${t("Şimdi kontrol et")}">🔄</button>
      <button onclick="deleteAlert(${a.id})" title="${t("Sil")}">✕</button>
    </div>`).join("");
}
async function addAlert() {
  const query = $("#alQuery").value.trim();
  if (query.length < 3) return toast(t("Arama yaz"));
  await api("/api/alerts", { method: "POST", body: JSON.stringify({ query, email: $("#alEmail").value.trim() }) });
  $("#alQuery").value = ""; $("#alEmail").value = "";
  toast(t("Alarm eklendi ✓ (temel kuruldu)")); renderAlerts();
}
async function checkAlert(id) {
  toast(t("PubMed kontrol ediliyor…"), 6000);
  const r = await api(`/api/alerts/${id}/check`, { method: "POST", body: "{}" });
  if (r.first_run) toast(t("Temel kuruldu — sonraki kontrolde yeniler bildirilecek"));
  else if (!r.n_new) toast(t("Yeni makale yok"));
  else showAlertResults(r.new);
  renderAlerts();
}
function showAlertResults(recs) {
  showModal(`<h2>${t("🆕 {0} yeni makale", recs.length)}</h2>
    <div style="font-size:13px">${recs.map(r => `<div style="padding:8px 0;border-bottom:1px solid #eef2f7">
      <b>${esc(r.title)}</b><div style="font-size:12px;color:#6b7785">${esc((r.authors || []).slice(0, 3).join(", "))} · ${esc(r.iso || r.journal || "")} · ${esc(r.year || "")}${refLinks(r)}</div></div>`).join("")}</div>
    <div class="modal-actions"><button onclick="openAlerts()">${t("← Alarmlar")}</button><button class="primary" onclick="closeModal()">${t("Kapat")}</button></div>`, true);
}
async function deleteAlert(id) { await api(`/api/alerts/${id}`, { method: "DELETE" }); renderAlerts(); }

// ---------------------------------------------------------- geri çekilme kontrolü
async function checkIntegrity() {
  toast(t("PubMed taranıyor…"), 6000);
  try {
    const j = await api("/api/integrity/check", { method: "POST", body: JSON.stringify({ collection: state.collection }) });
    if (!j.flagged.length) toast(t("{0} kaynak tarandı — sorun yok 🎉", j.checked));
    else toast(t("⚠ {0} sorunlu kaynak işaretlendi ({1} tarandı)", j.flagged.length, j.checked));
    loadRefs();
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------- panel / istatistik
async function openStats() {
  const s = await api("/api/stats");
  const maxJ = Math.max(1, ...s.by_journal.map(x => x.n));
  const maxY = Math.max(1, ...s.by_year.map(x => x.n));
  showModal(`<h2>${t("📊 Kütüphane paneli")}</h2>
    <div class="stat-grid">
      <div class="stat-card"><div class="num">${s.total}</div><div class="lbl">${t("Kaynak")}</div></div>
      <div class="stat-card"><div class="num">${s.with_doi}</div><div class="lbl">${t("DOI'li")}</div></div>
      <div class="stat-card"><div class="num">${s.starred}</div><div class="lbl">${t("Yıldızlı")}</div></div>
      <div class="stat-card"><div class="num" style="color:${s.flagged ? '#c0392b' : 'inherit'}">${s.flagged}</div><div class="lbl">${t("İşaretli")}</div></div>
    </div>
    <b>${t("En çok dergi")}</b>
    ${s.by_journal.map(x => `<div class="bar-row"><span class="k">${esc(x.journal)}</span><span class="bar" style="width:${x.n / maxJ * 240}px"></span> ${x.n}</div>`).join("") || "<p style='color:#9aa6b2'>—</p>"}
    <b style="display:block;margin-top:14px">${t("Yıllara göre")}</b>
    ${s.by_year.map(x => `<div class="bar-row"><span class="k">${esc(x.year)}</span><span class="bar" style="width:${x.n / maxY * 240}px"></span> ${x.n}</div>`).join("") || "<p style='color:#9aa6b2'>—</p>"}
    <div class="modal-actions"><button class="primary" onclick="closeModal()">${t("Kapat")}</button></div>`);
}

// ---------------------------------------------------------- yedekleme
async function openBackup() {
  const { snapshots } = await api("/api/backups");
  showModal(`<h2>${t("💾 Yedekleme")}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Kütüphane + PDF ekleri tek zip'te. Refly her birkaç saatte bir otomatik yedek alır.")}</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
      <button class="primary" onclick="downloadBackup()">${t("⬇ Yedeği indir")}</button>
      <button onclick="snapshotNow()">${t("📸 Şimdi yedek al")}</button>
      <label class="button" style="border:1px solid var(--line);border-radius:7px;padding:7px 12px;cursor:pointer">
        ${t("⬆ Geri yükle")}<input type="file" id="restoreFile" accept=".zip" style="display:none" onchange="restoreBackup()"></label>
    </div>
    <b style="font-size:13px">${t("Otomatik yedekler")}</b>
    <div style="max-height:200px;overflow:auto;margin-top:6px;font-size:13px">
      ${snapshots.length ? snapshots.map(s => `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line)">
        <span>${esc(s.name)}</span><span style="color:#9aa6b2">${esc(s.when)} · ${s.size_kb} KB</span></div>`).join("")
      : `<p style='color:#9aa6b2'>${t("Henüz otomatik yedek yok.")}</p>`}
    </div>
    <div class="modal-actions"><button onclick="closeModal()">${t("Kapat")}</button></div>`);
}
function downloadBackup() { window.location = "/api/backup"; toast(t("Yedek indiriliyor ✓")); }
async function snapshotNow() {
  const j = await api("/api/backup/now", { method: "POST" });
  toast(t("Yedek alındı: {0} ✓", j.name)); openBackup();
}
async function restoreBackup() {
  const f = $("#restoreFile").files[0];
  if (!f) return;
  if (!confirm(t("DİKKAT: Mevcut kütüphanenin üzerine yazılacak (önce otomatik güvenlik yedeği alınır). Devam?"))) return;
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch("/api/restore", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) return toast(j.error);
  toast(t("Geri yüklendi ({0} PDF) ✓", j.restored_pdf)); closeModal(); loadRefs(); loadCollections();
}

// ---------------------------------------------------------- kopyalar (dedup)
async function openDuplicates() {
  const { groups } = await api(`/api/duplicates?collection=${state.collection}`);
  if (!groups.length) { showModal(`<h2>${t("Kopya yok 🎉")}</h2><p>${t("Bu görünümde yinelenen kayıt bulunamadı.")}</p>
    <div class="modal-actions"><button class="primary" onclick="closeModal()">${t("Tamam")}</button></div>`); return; }
  let html = `<h2>${t("{0} kopya grubu bulundu", groups.length)}</h2>
    <p style="color:#6b7785;font-size:13px">${t("Her grupta tutulacak kaydı seç; diğerleri silinecek (geri alınabilir).")}</p>`;
  groups.forEach((g, gi) => {
    html += `<div class="dupgroup">` + g.map((r, ri) => `
      <label class="opt"><input type="radio" name="g${gi}" value="${r.id}" ${ri === 0 ? "checked" : ""}>
        <span><b>${esc(r.title)}</b><br><span class="cand-meta">${esc(r.journal)} · ${esc(r.year)} ${r.doi ? "· DOI" : ""}</span></span>
      </label>`).join("") + `</div>`;
  });
  html += `<div class="modal-actions"><button onclick="closeModal()">${t("Vazgeç")}</button>
    <button class="primary" onclick='mergeDupes(${JSON.stringify(groups.map(g => g.map(r => r.id)))})'>${t("Kopyaları temizle")}</button></div>`;
  showModal(html);
}
async function mergeDupes(groups) {
  let dropped = 0;
  for (let gi = 0; gi < groups.length; gi++) {
    const keep = +document.querySelector(`input[name="g${gi}"]:checked`).value;
    const drop = groups[gi].filter(id => id !== keep);
    if (drop.length) { await api("/api/duplicates/merge", { method: "POST", body: JSON.stringify({ keep_id: keep, drop_ids: drop }) }); dropped += drop.length; }
  }
  closeModal(); toast(t("{0} kopya temizlendi ✓", dropped)); loadRefs(); loadCollections();
}

// ---------------------------------------------------------- e-posta doğrulama bandı
async function checkAccount() {
  let me; try { me = await api("/api/me"); } catch { return; }
  if (!me.verify_required || me.verified) return;
  if (document.getElementById("verifyBanner")) return;
  const bar = document.createElement("div");
  bar.id = "verifyBanner";
  bar.style.cssText = "background:#fff7ed;border-bottom:1px solid #fed7aa;color:#9a3412;" +
    "padding:9px 16px;font-size:13.5px;display:flex;align-items:center;gap:12px;justify-content:center;flex-wrap:wrap";
  bar.innerHTML = `<span>${t("✉️ E-postanı doğrula — bağlantıyı {0} adresine gönderdik. Otomatik referanslama doğruladıktan sonra açılır.", "<b>" + esc(me.email || "") + "</b>")}</span>
    <button id="resendBtn" style="background:#9a3412;color:#fff;border:0;border-radius:7px;padding:6px 12px;font-weight:600;cursor:pointer">${t("Tekrar gönder")}</button>`;
  document.body.prepend(bar);
  $("#resendBtn").onclick = resendVerification;
}
async function resendVerification() {
  const b = $("#resendBtn");
  if (b) { b.disabled = true; b.textContent = t("Gönderiliyor…"); }
  try {
    const r = await api("/resend-verification", { method: "POST" });
    toast(r.already_verified ? t("Zaten doğrulanmış ✓") : t("Doğrulama e-postası gönderildi ✓"));
    if (r.already_verified) { const bar = $("#verifyBanner"); if (bar) bar.remove(); }
  } catch (e) { toast(e.message); }
  if (b) { b.disabled = false; b.textContent = t("Tekrar gönder"); }
}

// ---------------------------------------------------------- başlat
applyStatic();
const _ls = $("#langSel"); if (_ls) _ls.value = reflyLang();
loadCollections(); loadRefs(); loadStyles(); checkAccount();
