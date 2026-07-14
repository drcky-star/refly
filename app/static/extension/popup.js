// Refly tarayıcı eklentisi — aktif sekmedeki makalenin DOI/PMID'sini algılar,
// tek tıkla Refly'ın /capture sayfasını açar (oturumla çalışır, CORS yok).
const $ = (s) => document.querySelector(s);

// Sayfa içinde çalışacak algılama (meta etiketleri + URL + gövdedeki DOI)
function detectInPage() {
  const meta = (n) =>
    document.querySelector(`meta[name="${n}" i]`)?.content ||
    document.querySelector(`meta[property="${n}" i]`)?.content || "";
  let doi = meta("citation_doi") || meta("prism.doi") || meta("dc.identifier.doi") || meta("dc.identifier");
  let pmid = meta("citation_pmid");
  const url = location.href;
  let m;
  if (!pmid && (m = url.match(/pubmed\.ncbi\.nlm\.nih\.gov\/(\d+)/))) pmid = m[1];
  if (!doi && (m = url.match(/doi\.org\/(10\.[^\s?#]+)/i))) doi = m[1];
  if (!doi) {
    const t = (document.body.innerText || "").match(/10\.\d{4,9}\/[-._;()/:A-Za-z0-9]+/);
    if (t) doi = t[0];
  }
  return { doi: (doi || "").replace(/^doi:\s*/i, "").trim(), pmid: (pmid || "").trim() };
}

async function init() {
  const stored = await chrome.storage.local.get("base");
  $("#base").value = stored.base || "https://reflyapp.com";

  let res = { doi: "", pmid: "" };
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const out = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: detectInPage });
    res = out[0]?.result || res;
  } catch (e) { /* bazı sayfalarda script enjekte edilemez */ }

  const id = res.doi ? { k: "doi", v: res.doi } : res.pmid ? { k: "pmid", v: res.pmid } : null;
  if (!id) {
    $("#status").textContent = "Bu sayfada DOI/PMID bulunamadı. Bir makale/özet sayfasında dene.";
    return;
  }
  $("#status").style.display = "none";
  const found = $("#found");
  found.style.display = "block";
  found.textContent = id.k.toUpperCase() + ": " + id.v;
  const btn = $("#save");
  btn.disabled = false;
  btn.onclick = async () => {
    const base = ($("#base").value || "").replace(/\/+$/, "");
    if (!base) return;
    await chrome.storage.local.set({ base });
    chrome.tabs.create({ url: `${base}/capture?${id.k}=${encodeURIComponent(id.v)}` });
    window.close();
  };
}
init();
