// Refly Word eklentisi — cite-while-write
// Kütüphanende ara → imlece atıf ekle → kaynakçayı tek tıkla oluştur/güncelle.
// Atıflar Word "content control" olarak eklenir (tag: refly-cite, title: ref id),
// böylece "Kaynakçayı güncelle" hepsini ilk-görülme sırasına göre [1],[2]… numaralar.

let REFLY = localStorage.getItem("refly_base") || window.location.origin;
const $ = (s) => document.querySelector(s);

Office.onReady(() => {
  $("#base").value = REFLY;
  loadStyles();
  search();
});

function setBase() {
  REFLY = $("#base").value.replace(/\/$/, "");
  localStorage.setItem("refly_base", REFLY);
  loadStyles(); search();
}

async function api(path, opts) {
  const r = await fetch(REFLY + path, opts);
  if (!r.ok) throw new Error("Refly'a ulaşılamadı (" + r.status + ")");
  return r.json();
}

async function loadStyles() {
  try {
    const { styles } = await api("/api/styles");
    $("#style").innerHTML = styles.map(([id, label]) => `<option value="${id}">${label}</option>`).join("");
  } catch (e) { status(e.message, true); }
}

let _deb;
function debounced() { clearTimeout(_deb); _deb = setTimeout(search, 280); }

async function search() {
  const q = $("#q").value.trim();
  try {
    const { refs } = await api("/api/refs?collection=all&search=" + encodeURIComponent(q));
    $("#results").innerHTML = refs.length ? refs.slice(0, 40).map(r => {
      const meta = `${(r.authors || []).slice(0, 2).join(", ")} · ${r.iso || r.journal || ""} · ${r.year || ""}`;
      return `<div class="item"><div class="t">${esc(r.title)}</div><div class="m">${esc(meta)}</div>
        <button onclick="insertCite(${r.id})">+ Atıf ekle</button></div>`;
    }).join("") : "<p class='muted'>Sonuç yok. Refly çalışıyor mu?</p>";
  } catch (e) { status(e.message, true); }
}

// İmlece atıf (content control) ekle
async function insertCite(refId) {
  await Word.run(async (ctx) => {
    const rng = ctx.document.getSelection();
    const cc = rng.insertContentControl();
    cc.tag = "refly-cite";
    cc.title = String(refId);
    cc.appearance = "BoundingBox";
    cc.insertText("[•]", "Replace");
    await ctx.sync();
  });
  status("Atıf eklendi. Bitince ‘Kaynakçayı güncelle’ye bas.");
}

// Tüm atıfları numarala + kaynakçayı yaz/güncelle
async function updateBiblio() {
  status("Güncelleniyor…");
  try {
    await Word.run(async (ctx) => {
      const ccs = ctx.document.contentControls;
      ccs.load("items/tag,items/title,items/text");
      await ctx.sync();

      const citeCCs = ccs.items.filter(c => c.tag === "refly-cite");
      // ilk-görülme sırasına göre numara ata
      const order = [], idToNum = {};
      for (const c of citeCCs) {
        const id = c.title;
        if (!(id in idToNum)) { order.push(id); idToNum[id] = order.length; }
      }
      // her atıfın metnini [n] yap
      for (const c of citeCCs) c.insertText("[" + idToNum[c.title] + "]", "Replace");
      await ctx.sync();

      if (!order.length) { status("Belgede atıf yok."); return; }

      // kaynakçayı Refly'dan al
      const { entries } = await api("/api/format", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: order.map(Number), style: $("#style").value }),
      });

      // kaynakça content control'ünü bul ya da belge sonuna oluştur
      let biblio = ccs.items.find(c => c.tag === "refly-biblio");
      if (!biblio) {
        const body = ctx.document.body;
        body.insertBreak(Word.BreakType.page, "End");
        const p = body.insertParagraph("Kaynaklar", "End");
        p.styleBuiltIn = "Heading1";
        const holder = body.insertParagraph("", "End");
        biblio = holder.insertContentControl();
        biblio.tag = "refly-biblio";
        biblio.title = "Refly kaynakça";
      }
      biblio.clear();
      biblio.insertText(entries.join("\n"), "Replace");
      await ctx.sync();
    });
    status("Kaynakça güncellendi ✓");
  } catch (e) { status(e.message, true); }
}

function status(msg, err) {
  const s = $("#status"); s.textContent = msg; s.className = err ? "err" : "ok";
}
function esc(s) { return (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
