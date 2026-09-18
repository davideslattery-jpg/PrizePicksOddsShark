(() => {
  const DATA_URL = "data/edges.json";
  const RELOAD_MS = 3 * 60 * 1000; // ~3 minutes
  const STALE_MS = 2 * 60 * 60 * 1000; // ~2 hours
  const MEANINGFUL_LINE_GAP = 0.5;

  const els = {
    body: document.getElementById("edgesBody"),
    updatedAt: document.getElementById("updatedAt"),
    modeBadge: document.getElementById("modeBadge"),
    countLabel: document.getElementById("countLabel"),
    errorBox: document.getElementById("errorBox"),
    emptyBox: document.getElementById("emptyBox"),
    dfsFilter: document.getElementById("dfsFilter"),
    sportFilters: document.getElementById("sportFilters"),
    marketFilters: document.getElementById("marketFilters"),
    playerSearch: document.getElementById("playerSearch"),
    minEdge: document.getElementById("minEdge"),
    minLineGap: document.getElementById("minLineGap"),
    refreshBtn: document.getElementById("refreshBtn"),
    staleBanner: document.getElementById("staleBanner"),
    sortChips: document.getElementById("sortChips"),
    kpiVisible: document.getElementById("kpiVisible"),
    kpiBest: document.getElementById("kpiBest"),
    kpiStrong: document.getElementById("kpiStrong"),
    kpiLineGap: document.getElementById("kpiLineGap"),
    kpiFresh: document.getElementById("kpiFresh"),
    slipProbs: document.getElementById("slipProbs"),
    slipFromSelection: document.getElementById("slipFromSelection"),
    slipSuggest: document.getElementById("slipSuggest"),
    slipRun: document.getElementById("slipRun"),
    slipStatus: document.getElementById("slipStatus"),
    slipBody: document.getElementById("slipBody"),
    suggestStatus: document.getElementById("suggestStatus"),
    suggestBody: document.getElementById("suggestBody"),
  };

  let board = null;
  let sortKey = "edge_pct";
  let sortDir = -1;
  const selectedKeys = new Set();

  const DFS_STORAGE_KEY = "pp-odds-dfs-platform";
  const SPORT_STORAGE_KEY = "pp-odds-sport-filters";
  const MARKET_STORAGE_KEY = "pp-odds-market-filters";
  const MIN_EDGE_STORAGE_KEY = "pp-odds-min-edge";
  const MIN_LINE_GAP_STORAGE_KEY = "pp-odds-min-line-gap";
  const PLAYER_SEARCH_STORAGE_KEY = "pp-odds-player-search";
  const SORT_KEY_STORAGE = "pp-odds-sort-key";
  const SORT_DIR_STORAGE = "pp-odds-sort-dir";

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

  /** Suggest slips: candidate pool + junk-match filter (tunable). */
  const SUGGEST_POOL_K = 16;
  const SUGGEST_TOP_N = 6;
  const JUNK_MAX_EDGE_PCT = 15;
  const JUNK_MAX_ABS_LINE_DIFF = 5;

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
    const lineGapAbs = Number.isFinite(lineDiff) ? Math.abs(lineDiff) : null;
    return { ...e, prob_delta: probDelta, line_diff: lineDiff, line_gap_abs: lineGapAbs };
  }

  function edgeTier(edgePct) {
    const n = Number(edgePct);
    if (!Number.isFinite(n)) return { key: "weak", label: "Weak" };
    if (n >= 8) return { key: "elite", label: "Elite" };
    if (n >= 5) return { key: "strong", label: "Strong" };
    if (n >= 2) return { key: "playable", label: "Playable" };
    return { key: "weak", label: "Weak" };
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
    else if (min < 60) rel = `${min}m ago`;
    else if (hr < 48) rel = `${hr}h ago`;
    else rel = `${day}d ago`;
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

  function loadJsonArray(key) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return null;
      return parsed.filter((s) => typeof s === "string");
    } catch (_) {
      return null;
    }
  }

  function persistJsonArray(key, keys) {
    try {
      localStorage.setItem(key, JSON.stringify(keys));
    } catch (_) {
      /* private mode */
    }
  }

  function loadSavedSportFilters() {
    return loadJsonArray(SPORT_STORAGE_KEY);
  }

  function persistSportFilters(keys) {
    persistJsonArray(SPORT_STORAGE_KEY, keys);
  }

  function loadSavedMarketFilters() {
    return loadJsonArray(MARKET_STORAGE_KEY);
  }

  function persistMarketFilters(keys) {
    persistJsonArray(MARKET_STORAGE_KEY, keys);
  }

  function loadSavedNumber(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      if (raw == null || raw === "") return fallback;
      const n = Number(raw);
      return Number.isFinite(n) ? n : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function persistNumber(key, value) {
    try {
      localStorage.setItem(key, String(value));
    } catch (_) {
      /* private mode */
    }
  }

  function loadSavedFilters() {
    if (els.minEdge) {
      els.minEdge.value = String(loadSavedNumber(MIN_EDGE_STORAGE_KEY, Number(els.minEdge.value) || 2));
    }
    if (els.minLineGap) {
      els.minLineGap.value = String(loadSavedNumber(MIN_LINE_GAP_STORAGE_KEY, Number(els.minLineGap.value) || 0));
    }
    if (els.playerSearch) {
      try {
        const saved = localStorage.getItem(PLAYER_SEARCH_STORAGE_KEY);
        if (saved != null) els.playerSearch.value = saved;
      } catch (_) {
        /* private mode */
      }
    }
    try {
      const sk = localStorage.getItem(SORT_KEY_STORAGE);
      const sd = localStorage.getItem(SORT_DIR_STORAGE);
      if (sk) sortKey = sk;
      if (sd === "1" || sd === "-1") sortDir = Number(sd);
    } catch (_) {
      /* private mode */
    }
  }

  function persistSort() {
    try {
      localStorage.setItem(SORT_KEY_STORAGE, sortKey);
      localStorage.setItem(SORT_DIR_STORAGE, String(sortDir));
    } catch (_) {
      /* private mode */
    }
  }

  function checkedSports() {
    if (!els.sportFilters) return new Set();
    const set = new Set();
    els.sportFilters.querySelectorAll("input[type=checkbox][data-sport]").forEach((box) => {
      if (box.checked) set.add(box.getAttribute("data-sport"));
    });
    return set;
  }

  function checkedMarkets() {
    if (!els.marketFilters) return new Set();
    const set = new Set();
    els.marketFilters.querySelectorAll("input[type=checkbox][data-market]").forEach((box) => {
      if (box.checked) set.add(box.getAttribute("data-market"));
    });
    return set;
  }

  function populateSports(edges) {
    if (!els.sportFilters) return;
    const inData = [...new Set(edges.map((e) => e.sport).filter(Boolean))];
    const sports = (inData.length ? inData : SPORT_CATALOG).slice().sort((a, b) =>
      prettySport(a).localeCompare(prettySport(b))
    );
    const saved = loadSavedSportFilters();
    const defaultOn = new Set(inData.length ? inData : sports);
    const enabled = new Set(
      saved && saved.length
        ? saved.filter((s) => sports.includes(s))
        : [...defaultOn]
    );
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

  function populateMarkets(edges) {
    if (!els.marketFilters) return;
    const markets = [...new Set(edges.map((e) => e.market).filter(Boolean))].sort((a, b) =>
      prettyMarket(a).localeCompare(prettyMarket(b))
    );
    const saved = loadSavedMarketFilters();
    const enabled = new Set(
      saved && saved.length
        ? saved.filter((m) => markets.includes(m))
        : markets
    );
    if (markets.length && ![...enabled].some((m) => markets.includes(m))) {
      markets.forEach((m) => enabled.add(m));
    }

    const prevHtml = els.marketFilters.getAttribute("data-markets-sig") || "";
    const sig = markets.join("|");
    if (prevHtml === sig && els.marketFilters.querySelector("input[data-market]")) {
      return;
    }
    els.marketFilters.setAttribute("data-markets-sig", sig);
    els.marketFilters.innerHTML = "";

    if (!markets.length) {
      const span = document.createElement("span");
      span.className = "dim";
      span.style.fontSize = "0.78rem";
      span.textContent = "No markets in data";
      els.marketFilters.appendChild(span);
      return;
    }

    for (const m of markets) {
      const id = `market-${m}`;
      const label = document.createElement("label");
      label.className = "sport-check";
      label.htmlFor = id;
      const input = document.createElement("input");
      input.type = "checkbox";
      input.id = id;
      input.setAttribute("data-market", m);
      input.checked = enabled.has(m);
      const span = document.createElement("span");
      span.textContent = prettyMarket(m);
      label.appendChild(input);
      label.appendChild(span);
      els.marketFilters.appendChild(label);
    }

    els.marketFilters.querySelectorAll("input[type=checkbox][data-market]").forEach((box) => {
      box.addEventListener("change", () => {
        persistMarketFilters([...checkedMarkets()]);
        render();
      });
    });
  }

  function playerQuery() {
    return (els.playerSearch && els.playerSearch.value.trim().toLowerCase()) || "";
  }

  function minLineGapFloor() {
    const n = Number(els.minLineGap && els.minLineGap.value);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function filteredRows() {
    if (!board || !Array.isArray(board.edges)) return [];
    const sports = checkedSports();
    const markets = checkedMarkets();
    const platform = activePlatform();
    const minEdge = Number(els.minEdge.value);
    const floor = Number.isFinite(minEdge) ? minEdge : 0;
    const lineFloor = minLineGapFloor();
    const q = playerQuery();
    const marketBoxesExist = els.marketFilters && els.marketFilters.querySelector("input[data-market]");

    let rows = board.edges.filter(
      (e) => Number(e.edge_pct) >= floor && edgePlatform(e) === platform
    );
    if (sports.size > 0) {
      rows = rows.filter((e) => sports.has(e.sport));
    } else {
      rows = [];
    }
    if (marketBoxesExist) {
      if (markets.size > 0) {
        rows = rows.filter((e) => markets.has(e.market));
      } else {
        rows = [];
      }
    }
    if (lineFloor > 0) {
      rows = rows.filter((e) => Number(e.line_gap_abs) >= lineFloor);
    }
    if (q) {
      rows = rows.filter((e) => String(e.player || "").toLowerCase().includes(q));
    }

    const sortVal = (row) => {
      if (sortKey === "line_gap_abs") return Number(row.line_gap_abs);
      return row[sortKey];
    };
    rows = [...rows].sort((a, b) => {
      const av = sortVal(a);
      const bv = sortVal(b);
      if (typeof av === "number" && typeof bv === "number") {
        if (!Number.isFinite(av) && !Number.isFinite(bv)) return 0;
        if (!Number.isFinite(av)) return 1;
        if (!Number.isFinite(bv)) return -1;
        return (av - bv) * sortDir;
      }
      return String(av ?? "").localeCompare(String(bv ?? "")) * sortDir;
    });
    return rows;
  }

  function updateKpis(rows) {
    if (els.kpiVisible) els.kpiVisible.textContent = String(rows.length);
    if (els.kpiBest) {
      const best = rows.reduce((m, r) => Math.max(m, Number(r.edge_pct) || -Infinity), -Infinity);
      els.kpiBest.textContent = Number.isFinite(best) && rows.length ? `${best.toFixed(1)}%` : "—";
    }
    if (els.kpiStrong) {
      els.kpiStrong.textContent = String(rows.filter((r) => Number(r.edge_pct) >= 5).length);
    }
    if (els.kpiLineGap) {
      els.kpiLineGap.textContent = String(
        rows.filter((r) => Number(r.line_gap_abs) >= MEANINGFUL_LINE_GAP).length
      );
    }
    if (els.kpiFresh && board) {
      const rel = relativeTime(board.updated_at);
      const abs = localTime(board.updated_at);
      els.kpiFresh.textContent = `${rel} · ${abs}`;
      els.kpiFresh.title = abs;
      els.kpiFresh.classList.toggle("kpi-stale", isStale(board.updated_at));
    }
  }

  function updateSortChips() {
    if (!els.sortChips) return;
    els.sortChips.querySelectorAll("[data-sort-chip]").forEach((btn) => {
      const key = btn.getAttribute("data-sort-chip");
      const active =
        (key === "edge_pct" && sortKey === "edge_pct") ||
        (key === "line_gap_abs" && sortKey === "line_gap_abs") ||
        (key === "player" && sortKey === "player");
      btn.classList.toggle("active", active);
    });
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

  function isJunkEdge(e) {
    const fp = Number(e.fair_prob);
    if (!Number.isFinite(fp) || fp <= 0 || fp >= 1) return true;
    const ep = Number(e.edge_pct);
    if (Number.isFinite(ep) && ep > JUNK_MAX_EDGE_PCT) return true;
    const ld = Number(e.line_diff);
    const ald = Number.isFinite(ld) ? Math.abs(ld) : 0;
    if (ald > JUNK_MAX_ABS_LINE_DIFF) return true;
    return false;
  }

  function suggestCandidatePool(rows) {
    const clean = rows.filter((e) => !isJunkEdge(e));
    return [...clean]
      .sort((a, b) => (Number(b.edge_pct) || 0) - (Number(a.edge_pct) || 0))
      .slice(0, SUGGEST_POOL_K);
  }

  function suggestSlipsFromPool(pool) {
    const scored = [];
    const maxN = Math.min(6, pool.length);
    for (let n = 2; n <= maxN; n++) {
      for (const idxs of combinations(pool.length, n)) {
        const picks = idxs.map((i) => pool[i]);
        const probs = picks.map((p) => Number(p.fair_prob));
        const ranked = evaluateSlips(probs);
        if (!ranked.length) continue;
        const best = ranked[0];
        scored.push({
          picks,
          keys: picks.map((p) => edgeKey(p)),
          probs,
          label: best.label,
          ev: best.ev,
          expected: best.expected,
          pCash: best.pCash,
        });
      }
    }
    scored.sort((a, b) => b.ev - a.ev);
    const out = [];
    for (const s of scored) {
      if (out.length >= SUGGEST_TOP_N) break;
      const keySet = new Set(s.keys);
      const tooSimilar = out.some((o) => {
        if (o.keys.length !== s.keys.length) return false;
        const shared = o.keys.filter((k) => keySet.has(k)).length;
        return shared >= s.keys.length - 1;
      });
      if (tooSimilar) continue;
      out.push(s);
    }
    return out;
  }

  function formatSuggestPick(r) {
    const side = String(r.side || "").trim();
    const line = fmtLine(r.pp_line);
    const mkt = prettyMarket(r.market);
    return `${r.player} ${side} ${line} ${mkt}`;
  }

  function useSuggestedSlip(suggestion) {
    selectedKeys.clear();
    for (const k of suggestion.keys.slice(0, 6)) selectedKeys.add(k);
    if (els.slipProbs) {
      els.slipProbs.value = suggestion.probs.map((p) => Number(p).toFixed(3)).join(",");
    }
    render();
    renderSlip(suggestion.probs.slice(0, 6));
    if (els.slipStatus) {
      els.slipStatus.textContent =
        `Loaded suggested ${suggestion.label} (${suggestion.keys.length} picks) · ` +
        `EV ${suggestion.ev >= 0 ? "+" : ""}${suggestion.ev.toFixed(4)} (independence assumed)`;
    }
    const advisor = document.getElementById("slipAdvisor");
    if (advisor && typeof advisor.scrollIntoView === "function") {
      advisor.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function renderSuggestions(list, meta) {
    if (!els.suggestBody) return;
    els.suggestBody.innerHTML = "";
    if (els.suggestStatus) {
      if (!list || !list.length) {
        els.suggestStatus.textContent =
          meta ||
          "No suggestions — need ≥2 filtered non-junk rows with book probs.";
        return;
      }
      els.suggestStatus.textContent = meta || "";
    }
    const frag = document.createDocumentFragment();
    list.forEach((s, i) => {
      const tr = document.createElement("tr");
      if (i === 0) tr.classList.add("slip-best");
      const picksHtml = s.picks
        .map((p) => `<strong>${escapeHtml(formatSuggestPick(p))}</strong>`)
        .join(" · ");
      tr.innerHTML = `
        <td>${escapeHtml(s.label)}</td>
        <td class="num">${s.ev >= 0 ? "+" : ""}${s.ev.toFixed(4)}</td>
        <td class="suggest-picks">${picksHtml}</td>
        <td><button type="button" class="btn btn-secondary btn-use-suggest" data-suggest-idx="${i}">Use these</button></td>
      `;
      frag.appendChild(tr);
    });
    els.suggestBody.appendChild(frag);
    els.suggestBody.querySelectorAll("button[data-suggest-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-suggest-idx"));
        const s = list[idx];
        if (s) useSuggestedSlip(s);
      });
    });
  }

  function runSuggestSlips() {
    const rows = filteredRows();
    const pool = suggestCandidatePool(rows);
    if (pool.length < 2) {
      renderSuggestions([], `Need ≥2 non-junk ${platformLabel(activePlatform())} rows with book probs in the current filter (pool=${pool.length}).`);
      return;
    }
    const suggestions = suggestSlipsFromPool(pool);
    const meta =
      `From ${rows.length} filtered → pool ${pool.length} (top by edge, junk skipped) → ` +
      `${suggestions.length} diverse suggestions · independence assumed; payouts approximate`;
    renderSuggestions(suggestions, meta);
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

  function copyPickText(r) {
    const plat = platformLabel(edgePlatform(r));
    const side = String(r.side || "").trim();
    const line = fmtLine(r.pp_line);
    const mkt = prettyMarket(r.market);
    const edge = fmtEdge(r.edge_pct);
    const bookPct = fmtPct(r.fair_prob);
    return `${r.player} ${side} ${line} ${mkt} (${plat}) · edge ${edge}% · book ${bookPct}`;
  }

  async function copyPick(r, btn) {
    const text = copyPickText(r);
    try {
      await navigator.clipboard.writeText(text);
      if (btn) {
        const prev = btn.textContent;
        btn.textContent = "Copied";
        btn.classList.add("copied");
        setTimeout(() => {
          btn.textContent = prev;
          btn.classList.remove("copied");
        }, 1200);
      }
    } catch (_) {
      // Fallback for older browsers / insecure context
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        if (btn) {
          btn.textContent = "Copied";
          setTimeout(() => {
            btn.textContent = "Copy";
          }, 1200);
        }
      } finally {
        document.body.removeChild(ta);
      }
    }
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
      populateSports(board.edges || []);
    }
    populateMarkets(board.edges || []);

    const rows = filteredRows();
    updateKpis(rows);
    updateSortChips();

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
        const sportHint = checkedSports().size === 0 ? " (no sports checked)" : "";
        const marketHint =
          els.marketFilters &&
          els.marketFilters.querySelector("input[data-market]") &&
          checkedMarkets().size === 0
            ? " (no markets checked)"
            : "";
        strong.textContent =
          `No edges above the filter for ${platformLabel(platform)}${sportHint}${marketHint} ` +
          `(or no overlapping ${platformLabel(platform)} + FanDuel props).`;
      }
      return;
    }
    els.emptyBox.classList.add("hidden");

    const frag = document.createDocumentFragment();
    for (const r of rows) {
      const tr = document.createElement("tr");
      const tier = (r.tier || "standard").toLowerCase();
      const et = edgeTier(r.edge_pct);
      const probClass =
        Number(r.prob_delta) > 0 ? "edge-pos" : Number(r.prob_delta) < 0 ? "edge-neg" : "";
      const key = edgeKey(r);
      const checked = selectedKeys.has(key) ? "checked" : "";
      if (et.key === "elite") tr.classList.add("row-elite");
      else if (et.key === "strong") tr.classList.add("row-strong");
      tr.innerHTML = `
        <td class="chk-col"><input type="checkbox" data-key="${escapeHtml(key)}" ${checked} aria-label="Select for slip" /></td>
        <td class="num edge-cell">
          <span class="edge-pos">${fmtEdge(r.edge_pct)}</span>
          <span class="edge-tier tier-${et.key}" title="${et.label} edge">${et.label}</span>
        </td>
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
        <td class="copy-col"><button type="button" class="btn-copy" data-copy-key="${escapeHtml(key)}" title="Copy pick" aria-label="Copy pick">Copy</button></td>
      `;
      frag.appendChild(tr);
    }
    els.body.appendChild(frag);

    const byKey = new Map(rows.map((r) => [edgeKey(r), r]));
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
    els.body.querySelectorAll("button[data-copy-key]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const k = btn.getAttribute("data-copy-key");
        const row = byKey.get(k);
        if (row) copyPick(row, btn);
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
        updateKpis([]);
      }
    } finally {
      els.refreshBtn.disabled = false;
    }
  }

  loadSavedPlatform();
  loadSavedFilters();
  els.refreshBtn.addEventListener("click", () => loadData({ manual: true }));
  if (els.dfsFilter) {
    els.dfsFilter.addEventListener("change", () => {
      selectedKeys.clear();
      persistPlatform();
      render();
    });
  }
  els.minEdge.addEventListener("input", () => {
    persistNumber(MIN_EDGE_STORAGE_KEY, Number(els.minEdge.value) || 0);
    render();
  });
  if (els.minLineGap) {
    els.minLineGap.addEventListener("input", () => {
      persistNumber(MIN_LINE_GAP_STORAGE_KEY, Number(els.minLineGap.value) || 0);
      render();
    });
  }
  if (els.playerSearch) {
    els.playerSearch.addEventListener("input", () => {
      try {
        localStorage.setItem(PLAYER_SEARCH_STORAGE_KEY, els.playerSearch.value);
      } catch (_) {
        /* private mode */
      }
      render();
    });
  }

  if (els.sortChips) {
    els.sortChips.querySelectorAll("[data-sort-chip]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-sort-chip");
        if (!key) return;
        if (sortKey === key) {
          sortDir *= -1;
        } else {
          sortKey = key;
          sortDir = key === "player" ? 1 : -1;
        }
        persistSort();
        render();
      });
    });
  }

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

  if (els.slipSuggest) {
    els.slipSuggest.addEventListener("click", () => {
      runSuggestSlips();
    });
  }

  document.querySelectorAll("#edgesTable thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-sort");
      if (sortKey === key) sortDir *= -1;
      else {
        sortKey = key;
        sortDir =
          key === "edge_pct" ||
          key === "prob_delta" ||
          key === "fair_prob" ||
          key === "line_gap_abs"
            ? -1
            : 1;
      }
      persistSort();
      render();
    });
  });

  loadData();
  setInterval(() => loadData(), RELOAD_MS);
})();
