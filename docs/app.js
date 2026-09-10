(() => {
  const DATA_URL = "data/edges.json";
  const RELOAD_MS = 3 * 60 * 1000; // ~3 minutes
  const STALE_MS = 2 * 60 * 60 * 1000; // ~2 hours

  const els = {
    body: document.getElementById("edgesBody"),
    updatedAt: document.getElementById("updatedAt"),
    modeBadge: document.getElementById("modeBadge"),
    countLabel: document.getElementById("countLabel"),
    errorBox: document.getElementById("errorBox"),
    emptyBox: document.getElementById("emptyBox"),
    sportFilter: document.getElementById("sportFilter"),
    minEdge: document.getElementById("minEdge"),
    refreshBtn: document.getElementById("refreshBtn"),
    staleBanner: document.getElementById("staleBanner"),
  };

  let board = null;
  let sortKey = "edge_pct";
  let sortDir = -1;

  const SPORT_LABELS = {
    basketball_nba: "NBA",
    americanfootball_nfl: "NFL",
    baseball_mlb: "MLB",
    icehockey_nhl: "NHL",
    americanfootball_ncaaf: "NCAAF",
    basketball_ncaab: "NCAAB",
  };

  function fmtPct(x) {
    const n = Number(x);
    if (!Number.isFinite(n)) return "—";
    return `${(n * 100).toFixed(1)}%`;
  }

  function fmtEdge(x) {
    const n = Number(x);
    if (!Number.isFinite(n)) return "—";
    return n.toFixed(2);
  }

  function fmtSignedPctPoints(x) {
    const n = Number(x);
    if (!Number.isFinite(n)) return "—";
    const sign = n > 0 ? "+" : "";
    return `${sign}${n.toFixed(1)} pp`;
  }

  function fmtSignedLine(x) {
    const n = Number(x);
    if (!Number.isFinite(n)) return "—";
    const sign = n > 0 ? "+" : "";
    return `${sign}${Number.isInteger(n) ? n : n}`;
  }

  function enrichEdge(e) {
    const fair = Number(e.fair_prob);
    const offered = Number(e.offered_prob);
    const probDelta =
      Number.isFinite(fair) && Number.isFinite(offered) ? (fair - offered) * 100 : null;
    let lineDiff = Number(e.line_diff);
    if (!Number.isFinite(lineDiff)) {
      const pp = Number(e.pp_line);
      const book = Number(e.book_line);
      lineDiff = Number.isFinite(pp) && Number.isFinite(book) ? pp - book : null;
    }
    return { ...e, prob_delta: probDelta, line_diff: lineDiff };
  }

  function fmtLine(x) {
    const n = Number(x);
    if (!Number.isFinite(n)) return "—";
    return Number.isInteger(n) ? String(n) : String(n);
  }

  function prettyMarket(m) {
    return String(m || "")
      .replace(/^player_/, "")
      .replace(/^batter_/, "")
      .replace(/^pitcher_/, "")
      .replace(/_/g, " ");
  }

  function prettySport(s) {
    return SPORT_LABELS[s] || s || "—";
  }

  function localTime(iso) {
    if (!iso) return "unknown";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    });
  }

  function relativeTime(iso) {
    if (!iso) return "unknown";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const diffMs = Date.now() - d.getTime();
    const abs = Math.abs(diffMs);
    const sec = Math.round(abs / 1000);
    const min = Math.round(sec / 60);
    const hr = Math.round(min / 60);
    const day = Math.round(hr / 24);
    let rel;
    if (sec < 45) rel = "just now";
    else if (min < 60) rel = `${min} min ago`;
    else if (hr < 48) rel = `${hr} hr ago`;
    else rel = `${day} day${day === 1 ? "" : "s"} ago`;
    if (diffMs < 0) rel = "in the future";
    return rel;
  }

  function isStale(iso) {
    if (!iso) return true;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return true;
    return Date.now() - d.getTime() > STALE_MS;
  }

  function showError(msg) {
    els.errorBox.textContent = msg;
    els.errorBox.classList.remove("hidden");
  }

  function clearError() {
    els.errorBox.classList.add("hidden");
    els.errorBox.textContent = "";
  }

  function populateSports(edges) {
    const sports = [...new Set(edges.map((e) => e.sport).filter(Boolean))].sort();
    const current = els.sportFilter.value || "all";
    els.sportFilter.innerHTML = "";
    const all = document.createElement("option");
    all.value = "all";
    all.textContent = "All";
    els.sportFilter.appendChild(all);
    for (const s of sports) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = prettySport(s);
      els.sportFilter.appendChild(opt);
    }
    if ([...els.sportFilter.options].some((o) => o.value === current)) {
      els.sportFilter.value = current;
    }
  }

  function filteredRows() {
    if (!board || !Array.isArray(board.edges)) return [];
    const sport = els.sportFilter.value;
    const minEdge = Number(els.minEdge.value);
    const floor = Number.isFinite(minEdge) ? minEdge : 0;
    let rows = board.edges.filter((e) => Number(e.edge_pct) >= floor);
    if (sport && sport !== "all") {
      rows = rows.filter((e) => e.sport === sport);
    }
    rows = [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * sortDir;
      return String(av ?? "").localeCompare(String(bv ?? "")) * sortDir;
    });
    return rows;
  }

  function render() {
    if (!board) return;
    clearError();
    const mode = board.mode || "unknown";
    els.modeBadge.textContent = mode;
    els.modeBadge.className = `badge ${mode === "live" ? "live" : mode === "demo" ? "demo" : ""}`;
    const abs = localTime(board.updated_at);
    const rel = relativeTime(board.updated_at);
    els.updatedAt.textContent = `Updated ${rel} · ${abs}`;
    if (els.staleBanner) {
      if (isStale(board.updated_at)) els.staleBanner.classList.remove("hidden");
      else els.staleBanner.classList.add("hidden");
    }
    populateSports(board.edges || []);

    const rows = filteredRows();
    els.countLabel.textContent = `${rows.length} shown` + (board.count != null ? ` / ${board.count} total` : "");
    els.body.innerHTML = "";

    if (!rows.length) {
      els.emptyBox.classList.remove("hidden");
      return;
    }
    els.emptyBox.classList.add("hidden");

    const frag = document.createDocumentFragment();
    for (const r of rows) {
      const tr = document.createElement("tr");
      const tier = (r.tier || "standard").toLowerCase();
      const probClass =
        Number(r.prob_delta) > 0 ? "edge-pos" : Number(r.prob_delta) < 0 ? "edge-neg" : "";
      tr.innerHTML = `
        <td class="num edge-pos">${fmtEdge(r.edge_pct)}</td>
        <td>${escapeHtml(r.player)}</td>
        <td class="market">${escapeHtml(prettyMarket(r.market))}</td>
        <td>${escapeHtml(r.side)}</td>
        <td class="tier-${tier}">${escapeHtml(r.tier || "standard")}</td>
        <td class="num">${fmtLine(r.pp_line)}</td>
        <td class="num">${fmtLine(r.book_line)}</td>
        <td class="num">${fmtSignedLine(r.line_diff)}</td>
        <td class="num" title="Book probability of this outcome">${fmtPct(r.fair_prob)}</td>
        <td class="num" title="PrizePicks implied / proxy probability">${fmtPct(r.offered_prob)}</td>
        <td class="num ${probClass}" title="Book prob − PP prob">${fmtSignedPctPoints(r.prob_delta)}</td>
        <td>${escapeHtml(r.game || r.matchup || "")}</td>
        <td>${escapeHtml(prettySport(r.sport))}</td>
      `;
      frag.appendChild(tr);
    }
    els.body.appendChild(frag);
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadData({ manual = false } = {}) {
    els.refreshBtn.disabled = true;
    try {
      const url = `${DATA_URL}?t=${Date.now()}`;
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status} loading ${DATA_URL}`);
      const data = await res.json();
      if (!data || !Array.isArray(data.edges)) {
        throw new Error("edges.json missing edges[] — unexpected shape");
      }
      board = {
        ...data,
        edges: (data.edges || []).map(enrichEdge),
      };
      render();
      void manual;
    } catch (err) {
      showError(`Failed to load board: ${err.message || err}`);
      if (!board) {
        els.updatedAt.textContent = "No data loaded";
        els.countLabel.textContent = "";
      }
    } finally {
      els.refreshBtn.disabled = false;
    }
  }

  els.refreshBtn.addEventListener("click", () => loadData({ manual: true }));
  els.sportFilter.addEventListener("change", render);
  els.minEdge.addEventListener("input", render);

  document.querySelectorAll("#edgesTable thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-sort");
      if (sortKey === key) sortDir *= -1;
      else {
        sortKey = key;
        sortDir = key === "edge_pct" || key === "prob_delta" || key === "fair_prob" ? -1 : 1;
      }
      render();
    });
  });

  loadData();
  setInterval(() => loadData(), RELOAD_MS);
})();
