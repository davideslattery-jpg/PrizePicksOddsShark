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
    dfsFilter: document.getElementById("dfsFilter"),
    sportFilters: document.getElementById("sportFilters"),
    minEdge: document.getElementById("minEdge"),
    refreshBtn: document.getElementById("refreshBtn"),
    staleBanner: document.getElementById("staleBanner"),
    slipProbs: document.getElementById("slipProbs"),
    slipFromSelection: document.getElementById("slipFromSelection"),
    slipRun: document.getElementById("slipRun"),
    slipStatus: document.getElementById("slipStatus"),
    slipBody: document.getElementById("slipBody"),
  };

  let board = null;
  let sortKey = "edge_pct";
  let sortDir = -1;
  const selectedKeys = new Set();
  const DFS_STORAGE_KEY = "pp-odds-dfs-platform";
  const SPORT_STORAGE_KEY = "pp-odds-sport-filters";

  /** Full seasonal catalog (PGA omitted — Odds API outrights only, no player props). */
  const SPORT_CATALOG = [
    "americanfootball_nfl",
    "americanfootball_ncaaf",
    "basketball_nba",
    "basketball_ncaab",
    "baseball_mlb",
    "icehockey_nhl",
  ];

  const SPORT_LABELS = {
    basketball_nba: "NBA",
    americanfootball_nfl: "NFL",
    baseball_mlb: "MLB",
    icehockey_nhl: "NHL",
    americanfootball_ncaaf: "NCAAF",
    basketball_ncaab: "NCAAB",
  };

  const POWER_MULT = { 2: 3, 3: 6, 4: 10, 5: 20, 6: 37.5 };
  const FLEX_PAY = {
    2: { 2: 2, 1: 0.5 },
    3: { 3: 3, 2: 1 },
    4: { 4: 6, 3: 1.5 },
    5: { 5: 10, 4: 2, 3: 0.4 },
    6: { 6: 25, 5: 2, 4: 0.4 },
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

  function edgeKey(r) {
    return [r.platform || "prizepicks", r.event_id, r.player, r.market, r.side, r.pp_line, r.tier].join("|");
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


  function activePlatform() {
    const v = (els.dfsFilter && els.dfsFilter.value) || "prizepicks";
    return v === "underdog" ? "underdog" : "prizepicks";
  }

  function edgePlatform(e) {
    return (e && e.platform) || "prizepicks";
  }

  function loadSavedPlatform() {
    if (!els.dfsFilter) return;
    try {
      const saved = localStorage.getItem(DFS_STORAGE_KEY);
      if (saved === "prizepicks" || saved === "underdog") {
        els.dfsFilter.value = saved;
      }
    } catch (_) {
      /* private mode */
    }
  }

  function persistPlatform() {
    if (!els.dfsFilter) return;
    try {
      localStorage.setItem(DFS_STORAGE_KEY, activePlatform());
    } catch (_) {
      /* private mode */
    }
  }

  function platformLabel(p) {
    return p === "underdog" ? "Underdog" : "PrizePicks";
  }

  function loadSavedSportFilters() {
    try {
      const raw = localStorage.getItem(SPORT_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return null;
      return parsed.filter((s) => typeof s === "string");
    } catch (_) {
      return null;
    }
  }

  function persistSportFilters(keys) {
    try {
      localStorage.setItem(SPORT_STORAGE_KEY, JSON.stringify(keys));
    } catch (_) {
      /* private mode */
    }
  }

  function checkedSports() {
    if (!els.sportFilters) return new Set();
    const set = new Set();
    els.sportFilters.querySelectorAll('input[type=checkbox][data-sport]').forEach((box) => {
      if (box.checked) set.add(box.getAttribute("data-sport"));
    });
    return set;
  }

  function populateSports(edges) {
    if (!els.sportFilters) return;
    const inData = [...new Set(edges.map((e) => e.sport).filter(Boolean))];
    // Prefer sports present in data; fall back to full catalog if empty
    const sports = (inData.length ? inData : SPORT_CATALOG).slice().sort((a, b) =>
      prettySport(a).localeCompare(prettySport(b))
    );
    const saved = loadSavedSportFilters();
    // Default: all sports that currently have edges (or all catalog if none)
    const defaultOn = new Set(inData.length ? inData : sports);
    const enabled = new Set(
      saved && saved.length
        ? saved.filter((s) => sports.includes(s))
        : [...defaultOn]
    );
    // If saved filters exclude everything visible, re-default to all with data
    if (![...enabled].some((s) => sports.includes(s))) {
      sports.forEach((s) => enabled.add(s));
    }

    els.sportFilters.innerHTML = "";
    for (const s of sports) {
      const id = `sport-${s}`;
      const label = document.createElement("label");
      label.className = "sport-check";
      label.htmlFor = id;
      const input = document.createElement("input");
      input.type = "checkbox";
      input.id = id;
      input.setAttribute("data-sport", s);
      input.checked = enabled.has(s);
      const span = document.createElement("span");
      span.textContent = prettySport(s);
      label.appendChild(input);
      label.appendChild(span);
      els.sportFilters.appendChild(label);
    }

    els.sportFilters.querySelectorAll("input[type=checkbox][data-sport]").forEach((box) => {
      box.addEventListener("change", () => {
        persistSportFilters([...checkedSports()]);
        render();
      });
    });
  }

  function filteredRows() {
    if (!board || !Array.isArray(board.edges)) return [];
    const sports = checkedSports();
    const platform = activePlatform();
    const minEdge = Number(els.minEdge.value);
    const floor = Number.isFinite(minEdge) ? minEdge : 0;
    let rows = board.edges.filter(
      (e) => Number(e.edge_pct) >= floor && edgePlatform(e) === platform
    );
    if (sports.size > 0) {
      rows = rows.filter((e) => sports.has(e.sport));
    } else {
      // Nothing checked → show none (clear empty state)
      rows = [];
    }
    rows = [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * sortDir;
      return String(av ?? "").localeCompare(String(bv ?? "")) * sortDir;
    });
    return rows;
  }

  function combinations(n, k) {
    const out = [];
    const idx = Array.from({ length: k }, (_, i) => i);
    const push = () => out.push(idx.slice());
    if (k === 0) return [[]];
    if (k > n) return out;
    push();
    while (true) {
      let i = k - 1;
      while (i >= 0 && idx[i] === i + n - k) i -= 1;
      if (i < 0) break;
      idx[i] += 1;
      for (let j = i + 1; j < k; j++) idx[j] = idx[j - 1] + 1;
      push();
    }
    return out;
  }

  function probExactlyK(probs, k) {
    const n = probs.length;
    let total = 0;
    for (const hit of combinations(n, k)) {
      const set = new Set(hit);
      let p = 1;
      for (let i = 0; i < n; i++) p *= set.has(i) ? probs[i] : 1 - probs[i];
      total += p;
    }
    return total;
  }

  function evaluateSlips(probs) {
    const n = probs.length;
    const rows = [];
    if (POWER_MULT[n] != null) {
      const pAll = probs.reduce((a, b) => a * b, 1);
      const mult = POWER_MULT[n];
      const expected = pAll * mult;
      rows.push({
        label: `${n} Power`,
        ev: expected - 1,
        expected,
        pCash: pAll,
        pMax: pAll,
        maxMult: mult,
      });
    }
    if (FLEX_PAY[n]) {
      const pay = FLEX_PAY[n];
      let expected = 0;
      let pCash = 0;
      for (const [kStr, mult] of Object.entries(pay)) {
        const k = Number(kStr);
        const pk = probExactlyK(probs, k);
        expected += pk * mult;
        if (mult > 0) pCash += pk;
      }
      rows.push({
        label: `${n} Flex`,
        ev: expected - 1,
        expected,
        pCash,
        pMax: probExactlyK(probs, n),
        maxMult: pay[n] || 0,
      });
    }
    rows.sort((a, b) => b.ev - a.ev);
    return rows;
  }

  function renderSlip(probs) {
    if (!els.slipBody) return;
    els.slipBody.innerHTML = "";
    if (!probs || probs.length < 2 || probs.length > 6) {
      if (els.slipStatus) {
        els.slipStatus.textContent = "Enter 2–6 probabilities between 0 and 1.";
      }
      return;
    }
    const ranked = evaluateSlips(probs);
    if (els.slipStatus) {
      els.slipStatus.textContent =
        `n=${probs.length} · probs=[${probs.map((p) => p.toFixed(3)).join(", ")}] · ` +
        `recommended ${ranked[0]?.label || "—"} (independence assumed)`;
    }
    const frag = document.createDocumentFragment();
    ranked.forEach((r, i) => {
      const tr = document.createElement("tr");
      if (i === 0) tr.classList.add("slip-best");
      tr.innerHTML = `
        <td>${escapeHtml(r.label)}</td>
        <td class="num">${r.ev >= 0 ? "+" : ""}${r.ev.toFixed(4)}</td>
        <td class="num">${r.expected.toFixed(4)}</td>
        <td class="num">${fmtPct(r.pCash)}</td>
        <td class="num">${fmtPct(r.pMax)}</td>
        <td class="num">${r.maxMult}x</td>
      `;
      frag.appendChild(tr);
    });
    els.slipBody.appendChild(frag);
  }

  function parseProbsInput(text) {
    return String(text || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number)
      .filter((n) => Number.isFinite(n));
  }

  function selectedFairProbs() {
    if (!board) return [];
    const platform = activePlatform();
    const sports = checkedSports();
    const byKey = new Map(
      (board.edges || [])
        .filter(
          (e) =>
            edgePlatform(e) === platform &&
            (sports.size === 0 || sports.has(e.sport))
        )
        .map((e) => [edgeKey(e), e])
    );
    const probs = [];
    for (const k of selectedKeys) {
      const e = byKey.get(k);
      const p = Number(e?.fair_prob);
      if (Number.isFinite(p)) probs.push(p);
    }
    return probs;
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
    const platform = activePlatform();
    const platformEdges = (board.edges || []).filter((e) => edgePlatform(e) === platform);
    const sportsInData = [...new Set((board.edges || []).map((e) => e.sport).filter(Boolean))].sort();
    const existingBoxes = els.sportFilters
      ? [...els.sportFilters.querySelectorAll("input[data-sport]")].map((b) => b.getAttribute("data-sport")).sort()
      : [];
    if (JSON.stringify(sportsInData) !== JSON.stringify(existingBoxes)) {
      // Use all board edges for sport list (not just active platform) so filters stay stable
      populateSports(board.edges || []);
    }

    const rows = filteredRows();
    const sportSet = checkedSports();
    const platformSportEdges = platformEdges.filter(
      (e) => sportSet.size === 0 || sportSet.has(e.sport)
    );
    els.countLabel.textContent =
      `${rows.length} shown` +
      ` / ${platformSportEdges.length} ${platformLabel(platform)}` +
      (sportSet.size ? ` · ${sportSet.size} sport${sportSet.size === 1 ? "" : "s"}` : "") +
      (board.count != null ? ` (${board.count} all platforms)` : "");
    els.body.innerHTML = "";

    const dfsProbHdr = document.getElementById("dfsProbHeader");
    if (dfsProbHdr) {
      dfsProbHdr.textContent = platform === "underdog" ? "UD prob" : "PP prob";
    }

    if (!rows.length) {
      els.emptyBox.classList.remove("hidden");
      const strong = els.emptyBox.querySelector("strong");
      if (strong) {
        const sportHint =
          checkedSports().size === 0
            ? " (no sports checked)"
            : "";
        strong.textContent =
          `No edges above the filter for ${platformLabel(platform)}${sportHint} ` +
          `(or no overlapping ${platformLabel(platform)} + FanDuel props).`;
      }
      return;
    }
    els.emptyBox.classList.add("hidden");

    const frag = document.createDocumentFragment();
    for (const r of rows) {
      const tr = document.createElement("tr");
      const tier = (r.tier || "standard").toLowerCase();
      const probClass =
        Number(r.prob_delta) > 0 ? "edge-pos" : Number(r.prob_delta) < 0 ? "edge-neg" : "";
      const key = edgeKey(r);
      const checked = selectedKeys.has(key) ? "checked" : "";
      tr.innerHTML = `
        <td class="chk-col"><input type="checkbox" data-key="${escapeHtml(key)}" ${checked} aria-label="Select for slip" /></td>
        <td class="num edge-pos">${fmtEdge(r.edge_pct)}</td>
        <td>${escapeHtml(r.player)}</td>
        <td class="market">${escapeHtml(prettyMarket(r.market))}</td>
        <td>${escapeHtml(r.side)}</td>
        <td class="tier-${tier}">${escapeHtml(r.tier || "standard")}</td>
        <td class="num">${fmtLine(r.pp_line)}</td>
        <td class="num">${fmtLine(r.book_line)}</td>
        <td class="num">${fmtSignedLine(r.line_diff)}</td>
        <td class="num" title="Book probability of this outcome">${fmtPct(r.fair_prob)}</td>
        <td class="num" title="DFS implied / proxy probability">${fmtPct(r.offered_prob)}</td>
        <td class="num ${probClass}" title="Book prob − DFS prob">${fmtSignedPctPoints(r.prob_delta)}</td>
        <td>${escapeHtml(r.game || r.matchup || "")}</td>
        <td>${escapeHtml(prettySport(r.sport))}</td>
      `;
      frag.appendChild(tr);
    }
    els.body.appendChild(frag);
    els.body.querySelectorAll("input[type=checkbox][data-key]").forEach((box) => {
      box.addEventListener("change", () => {
        const k = box.getAttribute("data-key");
        if (!k) return;
        if (box.checked) {
          if (selectedKeys.size >= 6) {
            box.checked = false;
            return;
          }
          selectedKeys.add(k);
        } else {
          selectedKeys.delete(k);
        }
      });
    });
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

  loadSavedPlatform();
  els.refreshBtn.addEventListener("click", () => loadData({ manual: true }));
  if (els.dfsFilter) {
    els.dfsFilter.addEventListener("change", () => {
      selectedKeys.clear();
      persistPlatform();
      render();
    });
  }
  // Sport checkboxes bind in populateSports()
  els.minEdge.addEventListener("input", render);

  // Auto-rank pasted probs on load when the field already has 2–6 values
  if (els.slipProbs) {
    const initial = parseProbsInput(els.slipProbs.value);
    if (initial.length >= 2 && initial.length <= 6) {
      renderSlip(initial);
    }
  }

  if (els.slipRun) {
    els.slipRun.addEventListener("click", () => {
      const probs = parseProbsInput(els.slipProbs?.value);
      renderSlip(probs);
    });
  }
  if (els.slipFromSelection) {
    els.slipFromSelection.addEventListener("click", () => {
      const probs = selectedFairProbs();
      if (probs.length < 2) {
        if (els.slipStatus) {
          els.slipStatus.textContent = `Select 2–6 ${platformLabel(activePlatform())} rows (checkbox) with book probs first.`;
        }
        return;
      }
      if (els.slipProbs) els.slipProbs.value = probs.map((p) => p.toFixed(3)).join(",");
      renderSlip(probs.slice(0, 6));
    });
  }

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
