// Inside the Game: welcome flow and the three live experiences.
const MATCH_ID = "match_002";
const LANGS = { en: "English", es: "Español", fr: "Français", pt: "Português", hi: "हिन्दी" };
const PITCH_W = 105, PITCH_H = 68;
const COUNTDOWN_S = 3;
// Only actions worth calling out get a play-by-play line and a name tag.
const KEY_TYPES = new Set(["shot", "own_goal", "save", "card", "corner"]);
// Shown automatically while quiet play is skipped; nothing to click.
const FAST_FORWARD = {
  en: "⏩ Skipping quiet play: the next big moment is coming up", es: "⏩ Saltando el juego tranquilo: se acerca la próxima jugada clave",
  fr: "⏩ On passe les temps calmes : le prochain temps fort arrive", pt: "⏩ Pulando o jogo parado: o próximo lance importante está chegando",
  hi: "⏩ शांत खेल छोड़ रहे हैं: अगला बड़ा पल आने वाला है",
};
// One short line per moment for the fan timeline.
const ICONS = { goal: "⚽", own_goal: "⚽", big_chance: "🎯", card: "🟨", kick_off: "▶️", period_end: "⏸️",
  momentum_swing: "📈", passing_drop: "📉" };
const TITLES = {
  en: { goal: "Goal: {player} ({team})", own_goal: "Own goal: {player}", big_chance: "Big chance: {player}",
    card: "Yellow card: {player}", kick_off: "Kick-off", period_end: "End of period", final: "Full time",
    momentum_swing: "Momentum swing", passing_drop: "{team} losing the ball" },
  es: { goal: "Gol: {player} ({team})", own_goal: "Gol en propia: {player}", big_chance: "Ocasión: {player}",
    card: "Amarilla: {player}", kick_off: "Comienza", period_end: "Fin del periodo", final: "Final del partido",
    momentum_swing: "Cambio de dominio", passing_drop: "{team} pierde el balón" },
  fr: { goal: "But : {player} ({team})", own_goal: "Contre son camp : {player}", big_chance: "Occasion : {player}",
    card: "Carton jaune : {player}", kick_off: "Coup d'envoi", period_end: "Fin de période", final: "Fin du match",
    momentum_swing: "Le match bascule", passing_drop: "{team} perd le ballon" },
  pt: { goal: "Gol: {player} ({team})", own_goal: "Gol contra: {player}", big_chance: "Chance: {player}",
    card: "Amarelo: {player}", kick_off: "Começou", period_end: "Fim do período", final: "Fim de jogo",
    momentum_swing: "Virada no domínio", passing_drop: "{team} perde a bola" },
  hi: { goal: "गोल: {player} ({team})", own_goal: "आत्मघाती गोल: {player}", big_chance: "बड़ा मौका: {player}",
    card: "पीला कार्ड: {player}", kick_off: "किक-ऑफ़", period_end: "पीरियड ख़त्म", final: "फ़ुल टाइम",
    momentum_swing: "खेल का रुख़ बदला", passing_drop: "{team} गेंद गंवा रहा है" },
};

const KICKOFF = {
  en: ["Getting the match ready…", "Kick-off!"],
  es: ["Preparando el partido…", "¡Comienza!"],
  fr: ["Préparation du match…", "Coup d'envoi !"],
  pt: ["Preparando a partida…", "Começou!"],
  hi: ["मैच तैयार हो रहा है…", "किक-ऑफ़!"],
};

const $ = (id) => document.getElementById(id);
const state = { role: null, club: null, player: null, focus: false, language: "en", teams: null };
let source = null;
let overlayFeed = [];

// ---------- welcome ----------

async function init() {
  const match = await (await fetch(`/api/match/${MATCH_ID}`)).json();
  state.teams = match.teams;
  const { home, away } = match.teams;
  $("fixture").textContent = `${home.name} vs ${away.name}`;

  chips($("club-chips"), [
    { value: home.name, label: home.name, color: "var(--home)" },
    { value: away.name, label: away.name, color: "var(--away)" },
    { value: "", label: "Neutral" },
  ], (v) => { state.club = v || null; refresh(); }, "");

  for (const side of ["home", "away"]) {
    const group = document.createElement("optgroup");
    group.label = match.teams[side].name;
    for (const p of match.teams[side].players) {
      const extra = p.note ? `, ${p.note}` : p.age ? `, age ${p.age}` : "";
      group.append(new Option(`${p.name} (${p.position}${extra})`, p.name));
    }
    $("player-select").append(group);
  }
  $("player-select").onchange = (e) => { state.player = e.target.value || null; refresh(); };
  $("focus").onchange = (e) => { state.focus = e.target.checked; refresh(); };

  chips($("lang-chips"), Object.entries(LANGS).map(([value, label]) => ({ value, label })),
    (v) => { state.language = v; refresh(); }, "en");

  document.querySelectorAll(".role").forEach((b) => b.onclick = () => { state.role = b.dataset.role; refresh(); });
  $("ask").onclick = askWelcomeAgent;
  $("free-text").onkeydown = (e) => { if (e.key === "Enter") askWelcomeAgent(); };
  $("start").onclick = startMatch;
  $("back").onclick = () => { stop(); show("welcome"); };
  $("restart").onclick = startMatch;
  $("speed").onchange = startMatch;
  $("checked").onclick = () => $("check-dialog").showModal();
  $("show-json").onclick = () => { $("json-body").textContent = JSON.stringify(overlayFeed, null, 2); $("json-dialog").showModal(); };
  refresh();

  // Deep links for demos: /?role=fan&club=Blue+Sharks&player=Moss&focus=1&language=es
  const q = new URLSearchParams(location.search);
  if (q.get("role")) {
    Object.assign(state, { role: q.get("role"), club: q.get("club"), player: q.get("player"),
      focus: q.has("focus"), language: q.get("language") || "en" });
    if (q.get("speed")) $("speed").value = q.get("speed");
    refresh();
    startMatch();
  }
}

function chips(container, items, onPick, initial) {
  container.innerHTML = "";
  for (const item of items) {
    const b = document.createElement("button");
    b.className = "chip";
    b.dataset.value = item.value;
    b.innerHTML = (item.color ? `<span class="dot" style="background:${item.color}"></span>` : "") + item.label;
    b.onclick = () => { setChip(container, item.value); onPick(item.value); };
    container.append(b);
  }
  setChip(container, initial);
}

function setChip(container, value) {
  container.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.value === (value ?? "")));
}

function refresh() {
  document.querySelectorAll(".role").forEach((b) => b.setAttribute("aria-checked", b.dataset.role === state.role));
  setChip($("club-chips"), state.club ?? "");
  setChip($("lang-chips"), state.language);
  $("player-select").value = state.player ?? "";
  $("focus").checked = state.focus;
  $("start").disabled = !state.role;
  $("preset-hint").textContent = state.role ? `Taking you to the ${{ fan: "fan view", analyst: "analyst desk", broadcaster: "studio" }[state.role]}` : "Pick who you are to start";
}

async function askWelcomeAgent() {
  const message = $("free-text").value.trim();
  if (!message) return;
  const reply = $("agent-reply");
  reply.hidden = false;
  reply.textContent = "Thinking…";
  const picks = {};
  if (state.role) picks.role = state.role;
  const res = await (await fetch("/api/welcome", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ match_id: MATCH_ID, picks, message }),
  })).json();
  const p = res.profile;
  Object.assign(state, { role: p.role ?? state.role, club: p.club, player: p.player, focus: p.player_focus, language: p.language });
  reply.innerHTML = `<strong>${escapeHtml(res.greeting)}</strong>`;
  for (const q of res.follow_ups) {
    const div = document.createElement("div");
    div.className = "q";
    div.innerHTML = `<p>${escapeHtml(q.question)}</p>`;
    const row = document.createElement("div");
    row.className = "chips";
    for (const option of q.options) {
      const b = document.createElement("button");
      b.className = "chip";
      b.textContent = option;
      b.onclick = () => {
        const value = ["neutral", "none"].includes(option) ? null : option;
        if (q.field === "role") state.role = value;
        if (q.field === "club") state.club = value;
        if (q.field === "player") state.player = value;
        div.remove();
        refresh();
      };
      row.append(b);
    }
    div.append(row);
    reply.append(div);
  }
  refresh();
}

// ---------- match ----------

function show(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("active", s.id === id));
  window.scrollTo(0, 0);
}

function stop() {
  if (source) { source.close(); source = null; }
  countdownTimers.forEach(clearTimeout);
  countdownTimers = [];
  $("countdown").hidden = true;
}

function startMatch() {
  stop();
  show("match");
  document.body.dataset.role = state.role;
  const { home, away } = state.teams;
  $("bug-home").textContent = home.short;
  $("bug-away").textContent = away.short;
  $("label-home").textContent = `${home.name} →`;
  $("label-away").textContent = `← ${away.name}`;
  $("tilt-home").textContent = home.short;
  $("tilt-away").textContent = away.short;
  $("viewer-label").textContent = [
    { fan: "Fan", analyst: "Analyst", broadcaster: "Broadcaster" }[state.role],
    state.club || "neutral", state.player ? `★ ${state.player}` : null, LANGS[state.language],
  ].filter(Boolean).join(" · ");
  for (const id of ["fan-feed", "analyst-feed", "cues", "talking", "numbers", "recap-body", "ensemble"]) $(id).innerHTML = "";
  $("bug-score").textContent = "0 – 0";
  $("bug-clock").textContent = "0'";
  $("narration").textContent = " ";
  $("pbp").textContent = " ";
  $("checked").hidden = true;
  $("lower-third").hidden = true;
  $("lower-third").parentElement.classList.remove("lt-on");
  $("fulltime").hidden = true;
  $("fav").hidden = !state.player;
  $("ff").hidden = true;
  $("ff").parentElement.classList.remove("fast");

  overlayFeed = [];

  showCountdown(KICKOFF[state.language][0], "");
  const params = new URLSearchParams({ role: state.role, language: state.language, speed: $("speed").value,
    countdown: COUNTDOWN_S });
  if (state.club) params.set("club", state.club);
  if (state.player) params.set("player", state.player);
  if (state.focus) params.set("focus", "true");
  source = new EventSource(`/api/live/${MATCH_ID}?${params}`);
  source.addEventListener("start", () => runCountdown());
  source.addEventListener("event", (e) => { hideCountdown(); onEvent(JSON.parse(e.data)); });
  source.addEventListener("stats", (e) => onStats(JSON.parse(e.data)));
  source.addEventListener("pace", (e) => onPace(JSON.parse(e.data).pace));
  source.addEventListener("card", (e) => onCard(JSON.parse(e.data)));
  source.addEventListener("end", () => { onPace("slow"); stop(); });
}

// Loading message until the server is ready, then 3, 2, 1, Kick-off! timed to the first event.
let countdownTimers = [];
function showCountdown(text, mode) {
  const box = $("countdown");
  box.hidden = false;
  box.className = `countdown ${mode}`;
  const span = $("countdown-text");
  span.textContent = text;
  span.style.animation = "none"; void span.offsetWidth; span.style.animation = "";
}
function runCountdown() {
  countdownTimers.forEach(clearTimeout);
  countdownTimers = [];
  for (let n = COUNTDOWN_S; n >= 1; n--) {
    countdownTimers.push(setTimeout(() => showCountdown(String(n), "counting"), (COUNTDOWN_S - n) * 1000));
  }
  countdownTimers.push(setTimeout(() => showCountdown(KICKOFF[state.language][1], "go"), COUNTDOWN_S * 1000));
  countdownTimers.push(setTimeout(() => { countdownTimers = []; hideCountdown(); }, COUNTDOWN_S * 1000 + 900));
}
// Events only clear the overlay when no countdown is running (e.g. an older server without one).
function hideCountdown() {
  if (!countdownTimers.length) $("countdown").hidden = true;
}

function toPitch([x, y]) { return [x / 100 * PITCH_W, y / 100 * PITCH_H]; }

function onEvent(e) {
  $("bug-clock").textContent = e.clock;
  const [sx, sy] = toPitch(e.start);
  const [ex, ey] = e.end ? toPitch(e.end) : [sx, sy];
  const ball = $("ball");
  ball.style.setProperty("--move", `${Math.round(700 / Number($("speed").value))}ms`);   // glide, don't jump
  ball.setAttribute("transform", `translate(${ex} ${ey})`);
  const trail = $("trail");
  trail.setAttribute("x1", sx); trail.setAttribute("y1", sy);
  trail.setAttribute("x2", ex); trail.setAttribute("y2", ey);
  // A name only for a key action or the favourite player; after a big moment play pauses,
  // so the name stays up long enough to read.
  const tag = ball.querySelector(".tag");
  const named = KEY_TYPES.has(e.type) || e.player === state.player;
  if (named) $("ball-tag").textContent = e.player;
  tag.setAttribute("class", `tag ${e.side}${named ? "" : " off"}`);
  // keep the name on the pitch: below the ball at the top edge, nudged inwards at the goal lines
  const dx = ex > PITCH_W - 9 ? PITCH_W - 9 - ex : ex < 9 ? 9 - ex : 0;
  tag.setAttribute("transform", `translate(${dx} ${ey < 8 ? 9.5 : 0})`);
  finishEvent(e);
}

function finishEvent(e) {
  if (e.line && KEY_TYPES.has(e.type)) $("pbp").textContent = `${e.clock}  ${e.line}`;
  if ((e.type === "shot" && e.outcome === "goal") || e.type === "own_goal") {
    const flash = $("flash");
    flash.classList.remove("show"); void flash.getBBox(); flash.classList.add("show");
  }
}

function onPace(pace) {
  const fast = pace === "fast";
  $("ff").textContent = FAST_FORWARD[state.language];
  $("ff").hidden = !fast;
  $("ff").parentElement.classList.toggle("fast", fast);
}

function onStats(s) {
  const { home, away } = state.teams;
  $("bug-score").textContent = `${s.score[home.name]} – ${s.score[away.name]}`;
  const tilt = s.territory_last_10_min[home.name].field_tilt_pct;
  $("tilt-fill").style.width = `${tilt}%`;
  $("tilt-words").textContent = tiltWords(tilt, home.name, away.name);
  if (state.player) updateFavourite();
  const row = (label, f, unit = "") => `<tr><th>${label}</th><td class="home">${f(home.name)}${unit}</td><td class="away">${f(away.name)}${unit}</td></tr>`;
  $("numbers").innerHTML =
    `<thead><tr><th></th><td class="home">${home.short}</td><td class="away">${away.short}</td></tr></thead>` +
    row("xG", (t) => s.expected_goals[t].xg.toFixed(2)) +
    row("Shots (on target)", (t) => `${s.expected_goals[t].shots} (${s.expected_goals[t].on_target})`) +
    row("Field tilt, last 10'", (t) => s.territory_last_10_min[t].field_tilt_pct, "%") +
    row("Field tilt, match", (t) => s.territory[t].field_tilt_pct, "%") +
    row("Possession", (t) => s.territory[t].possession_pct, "%") +
    row("Pass accuracy", (t) => s.passing[t].accuracy_pct ?? "–", "%") +
    row("Progressive passes", (t) => s.passing[t].progressive_completed) +
    row("Avg pass difficulty", (t) => s.passing[t].avg_difficulty ?? "–") +
    `<tr><th>Game state, last 10'</th><td colspan="2">${s.control_last_10_min.state}</td></tr>` +
    `<tr><th>Tempo</th><td colspan="2">${s.rhythm_last_10_min.actions_per_min ?? "–"} actions/min</td></tr>`;
}

function updateFavourite() {
  const p = [...state.teams.home.players, ...state.teams.away.players].find((x) => x.name === state.player);
  $("fav").innerHTML = `★ Following <strong>${escapeHtml(state.player)}</strong> · ${p?.position ?? ""}`;
}

function tiltWords(tilt, home, away) {
  if (tilt >= 75) return `${home} have camped in the ${away} half.`;
  if (tilt >= 60) return `${home} are on top right now.`;
  if (tilt > 40) return "It's an even contest right now.";
  if (tilt > 25) return `${away} are on top right now.`;
  return `${away} have camped in the ${home} half.`;
}

function onCard(card) {
  overlayFeed.push(card);
  const c = card.content;
  if (card.kind === "recap") return showRecap(card);
  if (card.mode === "fan") {
    setNarration(c.text, card);
    $("pbp").textContent = "\u00a0";                  // the commentary now says it: one line at a time
    addTimeline(card);
  } else if (card.mode === "analyst") {
    setNarration(c.headline, card);
    const evidence = (c.evidence || []).map((x) => `<span>${escapeHtml(x.label)} <b>${escapeHtml(x.value)}</b></span>`).join("");
    addFeed("analyst-feed", `<span class="h"><span class="t">${card.clock}</span>${escapeHtml(c.headline)}</span>${escapeHtml(c.why_it_matters || "")}<div class="ev">${evidence}</div>`);
  } else if (card.mode === "broadcaster") {
    setNarration(c.talking_point || c.lower_third, card);
    if (c.talking_point) $("narration").innerHTML = `<span class="presenter">Presenter</span>${escapeHtml(c.talking_point)}`;
    $("lt-headline").textContent = c.headline;
    $("lt-text").textContent = c.lower_third;
    const lt = $("lower-third");
    lt.hidden = false; lt.style.animation = "none"; void lt.offsetWidth; lt.style.animation = "";
    lt.parentElement.classList.add("lt-on");
    clearTimeout(onCard.ltTimer);
    onCard.ltTimer = setTimeout(() => { lt.hidden = true; lt.parentElement.classList.remove("lt-on"); }, 6000);
    const cue = c.director_cue || {};
    addFeed("cues", `<span class="cue-action">${escapeHtml((cue.action || "").replaceAll("_", " "))}</span> · <span class="t">${card.clock}</span>${escapeHtml(cue.reason || "")}`, cue.priority);
    if (c.talking_point) addFeed("talking", `<span class="t">${card.clock}</span>${escapeHtml(c.talking_point)}`);
  }
}

function setNarration(text, card) {
  const n = $("narration");
  n.textContent = text || " ";
  n.classList.remove("new"); void n.offsetWidth; n.classList.add("new");
  const fc = card.fact_check || {};
  const badge = $("checked");
  badge.hidden = false;
  const rewrites = (fc.attempts || 1) - 1;
  badge.className = "checked" + (rewrites ? " rewritten" : "");
  badge.textContent = card.source === "ai" ? (rewrites ? "✓ Fact-checked · rewritten" : "✓ Fact-checked") : "✓ Safe line (template)";
  $("check-body").innerHTML = checkHistory(card);
}

function checkHistory(card) {
  const fc = card.fact_check || {};
  const history = fc.history || [];
  if (!history.length) return `<p class="hint">${fc.error ? "The agents were unavailable, so a plain line from the data was shown." : "No history."}</p>`;
  const parts = history.map((h, i) => {
    const text = h.draft.text || h.draft.headline || h.draft.title || "";
    const ok = !h.problems.length;
    return `<div class="attempt"><div class="${ok ? "ok" : "bad"}">${ok ? "✓ Approved" : "✗ Sent back"} · draft ${i + 1}</div>
      <div>${escapeHtml(text)}</div>${ok ? "" : `<ul>${h.problems.map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>`}</div>`;
  }).join("");
  const tail = card.source === "ai" ? "" : `<p class="hint">Rejected twice, so a plain line that is always true was shown instead.</p>`;
  return `<p class="hint">Written by the ${{ fan: "Narrator", analyst: "Analyst", broadcaster: "Studio Producer", recap: "Recap" }[card.mode]} agent, checked by the Fact-Checker agent against the match data.</p>${parts}${tail}`;
}

function addTimeline(card) {
  if (!ICONS[card.kind]) return;                       // check-ins are commentary only
  const titles = TITLES[state.language];
  const title = (card.final ? titles.final : titles[card.kind])
    .replace("{player}", card.player ?? "").replace("{team}", card.team ?? "");
  const li = document.createElement("li");
  if (card.kind === "goal" || card.kind === "own_goal") li.className = "goal";
  li.innerHTML = `<span class="icon">${card.final ? "🏁" : ICONS[card.kind]}</span><span class="t">${card.clock}</span>` +
    `<span class="what">${escapeHtml(title)}</span>`;
  $("fan-feed").prepend(li);
}

function addFeed(id, html, cls) {
  const li = document.createElement("li");
  li.innerHTML = html;
  if (cls) li.className = cls;
  $(id).prepend(li);
}

async function showRecap(card) {
  $("fulltime").hidden = false;
  $("recap-title").textContent = card.content.title;
  $("recap-body").innerHTML = (card.content.paragraphs || []).map((p) => `<p>${escapeHtml(p)}</p>`).join("");
  try {
    const report = await (await fetch(`/api/report/${MATCH_ID}`)).json();
    const r = report.report;
    document.querySelector(".ensemble-head .badge").textContent =
      report.fact_check.approved ? "3 agents · merged · fact-checked" : "3 agents · merged · not fully verified";
    $("ensemble").innerHTML = `<h4>${escapeHtml(r.title)}</h4><p>${escapeHtml(r.summary)}</p>` +
      r.sections.map((s) => `<div class="persp"><h4>${escapeHtml(s.perspective)}</h4><p>${escapeHtml(s.text)}</p></div>`).join("");
  } catch { $("ensemble").innerHTML = `<p class="hint">The ensemble report isn't ready yet.</p>`; }
  $("fulltime").scrollIntoView({ behavior: "smooth" });
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
