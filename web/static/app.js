// @ts-check
/**
 * 치토 웹 화면 — 대화(가운데) + 치토 스테이지(오른쪽, 상황별 표정) + 마이크 + 텍스트 입력.
 * 설계: 웹 화면 설계/chito_web_design.html v0.1 (플랫).
 *
 * 답 글자와 소리는 실시간 연결(/v1/realtime → speech-to-speech serve)로 오고, 출처 카드·연락처·
 * 표정은 답이 끝난 뒤 /api/turn(RAG 서버 턴 기록)으로 받아 붙인다. LLM 답·프롬프트는 바꾸지 않는다.
 * ?mock=answer|contact|sorry|noscope|crisis|en|greet|listen|hello 로 열면 서버 없이 화면만 확인한다.
 */
import { ChitoClient } from "./chito-client.js";
import { MockClient, loadFixtures } from "./mock.js";

const $ = (/** @type {string} */ s) => /** @type {HTMLElement} */ (document.querySelector(s));
const $$ = (/** @type {string} */ s) => /** @type {HTMLElement[]} */ ([...document.querySelectorAll(s)]);
const sleep = (/** @type {number} */ ms) => new Promise((r) => setTimeout(r, ms));
const params = new URLSearchParams(location.search);
const MOCK = params.get("mock");

const FACE_FILE = {
  idle: "chito_idle", hello: "chito_hello", listen: "chito_listen", think: "chito_think", answer: "chito_answer",
  sorry: "chito_sorry", noscope: "chito_noscope", crisis: "chito_crisis", error: "chito_error",
};
const KIND_FACE = { answer: "answer", sorry: "sorry", noscope: "noscope", crisis: "crisis", smalltalk: "hello" };
const HOMEPAGE = "https://www.ajou.ac.kr";

const MIC_SVG = '<svg viewBox="0 0 48 48" fill="none" aria-hidden="true"><rect x="17" y="6" width="14" height="24" rx="7" fill="currentColor"/>'
  + '<path d="M11 22a13 13 0 0 0 26 0" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/>'
  + '<path d="M24 35v6M17 42h14" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/></svg>';
const MIC_OFF_SVG = MIC_SVG.replace("</svg>", '<path d="M9 9l30 30" stroke="currentColor" stroke-width="3.6" stroke-linecap="round"/></svg>');

const T = {
  ko: {
    brandSub: "캠퍼스 안내 치토", newChat: "새 대화", tryAsking: "이렇게 물어보세요", langAuto: "자동",
    foot: "답변은 학칙·학교 안내 자료를 근거로 해요. 개인 성적·신청은 처리하지 않아요.",
    ttsLabel: "음성으로 답 듣기", name: "치토", placeholder: "치토에게 물어보세요",
    hintIdle: "말하려면 오른쪽 마이크를 누르거나 스페이스바를 누르세요",
    hintListen: "말이 끝나면 자동으로 보내요 · 다시 누르면 멈춰요",
    emptyTitle: "무엇이든 물어보세요", emptyBody: "학사 규정, 행정 절차, 캠퍼스 시설을 학교 자료로 찾아 답해요.",
    connIdle: "연결 전", connBusy: "연결하는 중", connOk: "연결됨", connBad: "연결 끊김",
    pill: {
      idle: "", hello: "안녕하세요, 저는 아주대 안내 가이드 치토예요!", listen: "듣고 있어요", think: "찾고 있어요",
      answer: "답하고 있어요", answerDone: "더 궁금한 게 있으면 물어보세요", sorry: "자료에서 확인되지 않았어요",
      noscope: "대신 처리할 수 없는 요청이에요", crisis: "상담 안내", error: "연결이 끊겼어요",
    },
    mic: { idle: "눌러서 말하기 · <kbd>Space</kbd>", rec: "듣는 중 · 다시 누르면 멈춤", speak: "누르면 끊고 바로 말하기", off: "음성 연결 안 됨 · 텍스트로 물어보세요" },
    tag: { answer: "근거 있음", sorry: "자료에 없음", noscope: "처리할 수 없는 요청" },
    via: { voice: "음성으로 질문", text: "텍스트로 질문", live: "듣는 중…" },
    copy: "복사", copied: "복사했어요", srcOpen: "원문 보기", evidence: "근거 원문", showEvidence: "근거 보기", hideEvidence: "접기",
    checkPlace: "확인할 곳 · 학교 홈페이지", portal: "학사서비스 포탈 열기",
    careTitle: "지금 이야기할 수 있는 곳", careCall: "전화",
    care109: ["자살예방상담전화", "24시간 · 무료"], care119: ["긴급 상황", "지금 위험하다면"],
    passBad: "비밀번호가 맞지 않아요",
    errMic: "마이크를 쓸 수 없어요. 텍스트로 물어볼 수 있어요.",
    errSdk: "음성 연결 라이브러리를 불러오지 못했어요 (web/ 에서 npm ci).",
    errConnect: "음성 서버에 연결하지 못했어요. 서버가 켜져 있는지 확인해 주세요.",
    examples: [["휴학 신청 기간이 언제야?", "학사 · 휴/복학 안내"], ["장학금 받으려면 평점 몇 이상이야?", "장학 · 장학금 지급규칙"],
      ["외국인 학생 장학금은 어디에 문의해?", "유학생 · 장학금 안내"], ["Where is the GS25 on campus?", "English · 편의시설"]],
  },
  en: {
    brandSub: "Ajou campus guide", newChat: "New chat", tryAsking: "Try asking", langAuto: "Auto",
    foot: "Answers are based on Ajou's regulations and official guides. Personal records and applications aren't handled here.",
    ttsLabel: "Read answers aloud", name: "Chito", placeholder: "Ask Chito anything",
    hintIdle: "Press the mic on the right or the space bar to talk",
    hintListen: "Sends when you stop talking · press again to stop",
    emptyTitle: "Ask me anything", emptyBody: "I answer questions about academic rules, procedures and campus facilities from Ajou's own documents.",
    connIdle: "Not connected", connBusy: "Connecting", connOk: "Connected", connBad: "Disconnected",
    pill: {
      idle: "", hello: "Hi! I'm Chito, Ajou's campus guide.", listen: "Listening", think: "Looking it up", answer: "Answering",
      answerDone: "Ask me anything else", sorry: "Not in my documents", noscope: "I can't do that for you", crisis: "Support", error: "Disconnected",
    },
    mic: { idle: "Press to talk · <kbd>Space</kbd>", rec: "Listening · press again to stop", speak: "Press to interrupt and talk", off: "Voice unavailable · type your question" },
    tag: { answer: "Sourced", sorry: "Not in documents", noscope: "Can't do that" },
    via: { voice: "Spoken", text: "Typed", live: "Listening…" },
    copy: "Copy", copied: "Copied", srcOpen: "Open source", evidence: "Source text", showEvidence: "Show source", hideEvidence: "Hide",
    checkPlace: "Where to check · university website", portal: "Open the academic services portal",
    careTitle: "Who you can talk to now", careCall: "Call",
    care109: ["Suicide prevention hotline", "24 hours · free"], care119: ["Emergency", "If you're in danger now"],
    passBad: "Wrong passcode",
    errMic: "Microphone unavailable. You can still type.",
    errSdk: "Couldn't load the voice library (run npm ci in web/).",
    errConnect: "Couldn't reach the voice server. Check that it's running.",
    examples: [["How many semesters can I take off at one time?", "Academic · leave guide"], ["What GPA do I need for a scholarship?", "Scholarship rules"],
      ["Which office should international students contact?", "International students"], ["Where is the GS25 on campus?", "Campus facilities"]],
  },
};

/** @typedef {{id: string, role: "user"|"ai", text: string, partial: boolean, via?: string, kind?: string, sources?: any[], contacts?: any[], open?: Set<number>}} Msg */
const state = {
  langSel: "auto", lastLang: "ko",
  /** @type {Msg[]} */ messages: [],
  face: "hello", pill: "hello",
  listening: false, speaking: false,
  conn: "idle", sdkMissing: false,
  lastSeq: 0, tts: true, realMic: false,
};
/** @type {any} */ let client = null;
/** @type {any} */ let config = { needPasscode: false, authed: true, portalUrl: "" };
/** @type {any} */ let fixture = null;
/** @type {AudioContext | null} */ let silentCtx = null;

const t = () => T[state.langSel === "auto" ? state.lastLang : state.langSel] || T.ko;
const esc = (/** @type {string} */ s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c));
const detectLang = (/** @type {string} */ s) => {
  const ko = (s.match(/[가-힣]/g) || []).length;
  const en = (s.match(/[A-Za-z]/g) || []).length;
  return ko === 0 && en > 0 ? "en" : "ko";
};
let toastTimer = 0;
function toast(/** @type {string} */ text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el.classList.remove("show"), 3200);
}

// ── 그리기 ────────────────────────────────────────────────────────
function micState() {
  if (state.sdkMissing) return "off";
  if (state.speaking) return "speak";
  if (state.listening) return "rec";
  return "idle";
}

function renderStatic() {
  const s = t();
  document.documentElement.lang = state.langSel === "auto" ? state.lastLang : state.langSel;
  $$("[data-i18n]").forEach((el) => {
    const key = /** @type {keyof typeof s} */ (el.dataset.i18n);
    if (typeof s[key] === "string") el.textContent = /** @type {string} */ (s[key]);
  });
  $$("[data-i18n-placeholder]").forEach((el) => {
    /** @type {HTMLInputElement} */ (el).placeholder = /** @type {string} */ (s[/** @type {keyof typeof s} */ (el.dataset.i18nPlaceholder)]);
  });
  $$("#lang-seg button").forEach((b) => b.classList.toggle("on", b.dataset.lang === state.langSel));
  $("#examples").innerHTML = s.examples.map(([q]) => `<button class="q" data-ask="${esc(q)}">${esc(q)}</button>`).join("");
}

function renderStage() {
  const s = t();
  const mic = micState();
  $$(".js-face").forEach((img) => { /** @type {HTMLImageElement} */ (img).src = `assets/chito/${FACE_FILE[/** @type {keyof typeof FACE_FILE} */ (state.face)] || FACE_FILE.idle}.png`; });
  $$(".js-pill").forEach((el) => { el.className = `pill js-pill ${state.pill}`; el.textContent = s.pill[/** @type {keyof typeof s.pill} */ (state.pill)] ?? ""; });
  $$(".js-mic").forEach((b) => {
    b.className = `${b.className.replace(/\b(rec|speak|off)\b/g, "").trim()} ${mic === "idle" ? "" : mic}`.trim();
    b.innerHTML = mic === "off" ? MIC_OFF_SVG : MIC_SVG;
  });
  $$(".js-mic-small").forEach((b) => { b.innerHTML = mic === "off" ? MIC_OFF_SVG : MIC_SVG; });
  $$(".js-mic-cap").forEach((el) => { el.innerHTML = s.mic[mic]; });
  $$(".js-wave").forEach((el) => el.classList.toggle("on", state.listening || state.speaking));
  $("#stage").classList.toggle("care-tone", state.face === "crisis");
  $("#hint").textContent = state.listening ? s.hintListen : s.hintIdle;
  document.body.classList.toggle("listening", state.listening);
  const dot = $("#conn-dot");
  dot.className = `dot ${{ ok: "ok", busy: "busy", bad: "bad" }[state.conn] || ""}`;
  $("#conn-text").textContent = { ok: s.connOk, busy: s.connBusy, bad: s.connBad }[state.conn] || s.connIdle;
  const live = [...state.messages].reverse().find((m) => m.role === "user" && m.partial);
  $("#voice-text").textContent = live?.text || "";
  const firstUser = state.messages.find((m) => m.role === "user" && m.text);
  $("#title").textContent = firstUser ? firstUser.text.slice(0, 40) : s.newChat;
}

/** 검색 조각 본문을 목록으로 — 위치 표시 줄·삭제된 조항·빈 칸("-")은 빼고, "[신청 기간]" 같은 제목 줄은 다음 줄과 합친다.
 * @param {string} excerpt */
function evidenceItems(excerpt) {
  const lines = String(excerpt || "").split("\n").map((l) => l.trim()).filter(Boolean);
  // 첫 줄이 "휴/복학 > 휴학 > 휴학 종류" 같은 위치 표시면 뺀다 (본문의 "<개정 …>"과 헷갈리지 않게 " > "로 판단)
  if (lines.length > 1 && /\s>\s/.test(lines[0]) && !/^제\d+조/.test(lines[0])) lines.shift();
  const items = [];
  let label = "";
  for (const line of lines) {
    if (line === "-") { label = ""; continue; } // 빈 칸이면 그 제목도 함께 버린다
    if (/삭제\s*<\d{4}\./.test(line) && line.length < 40) continue;
    const heading = line.match(/^\[(.+)\]$/);
    if (heading) { label = heading[1]; continue; }
    items.push(label ? `<b>${esc(label)}</b> ${esc(line)}` : esc(line));
    label = "";
  }
  return items.slice(0, 8).map((html) => `<li>${html.length > 260 ? `${html.slice(0, 260)}…` : html}</li>`).join("");
}

/** @param {Msg} m */
function cardsHtml(m) {
  const s = t();
  if (m.partial || !m.kind) return "";
  const parts = [];
  if (m.kind === "crisis") {
    const lines = (m.contacts || []).filter((c) => c.phone).map((c) => [c.dept, c.label, c.phone]);
    lines.push([s.care109[0], s.care109[1], "109"], [s.care119[0], s.care119[1], "119"]);
    parts.push(`<div class="care"><h5>${esc(s.careTitle)}</h5>${lines.map(([name, sub, num]) => {
      const tel = String(num).split(/[,·]/)[0].replace(/[^0-9]/g, "");
      return `<div class="line"><div>${esc(name)}<small>${esc(sub)}</small></div><span class="num">${esc(num)}</span><a class="call" href="tel:${tel}">${esc(s.careCall)}</a></div>`;
    }).join("")}</div>`);
    return `<div class="cards">${parts.join("")}</div>`;
  }
  if (m.kind === "answer" || m.kind === "smalltalk") {
    const sources = m.sources || [];
    const shown = sources.filter((g) => g.cited).slice(0, 2);
    if (!shown.length && sources.length && m.kind === "answer") shown.push(sources[0]);
    shown.forEach((g, i) => {
      const open = m.open?.has(i);
      parts.push(`<div class="src"><div class="src-head"><div class="src-ico">▤</div>`
        + `<div style="min-width:0"><div class="src-doc">${esc(g.doc)}</div><div class="src-art">${esc((g.articles || [])[0] || "")}</div></div>`
        + `<div class="src-tools"><button data-toggle="${esc(m.id)}:${i}">${esc(open ? s.hideEvidence : s.showEvidence)}</button>`
        + `${g.url ? `<a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(s.srcOpen)} ↗</a>` : ""}</div></div>`
        + `${open ? `<div class="src-body"><div class="cap">${esc(s.evidence)}</div><ul>${evidenceItems(g.excerpt)}</ul></div>` : ""}</div>`);
    });
  }
  if (m.kind === "sorry" && !(m.contacts || []).length) {
    parts.push(`<a class="src" href="${HOMEPAGE}" target="_blank" rel="noopener"><div class="src-head"><div class="src-ico">⌂</div>`
      + `<div><div class="src-doc">${esc(s.checkPlace)}</div><div class="src-art">${HOMEPAGE.replace("https://", "")}</div></div>`
      + `<div class="src-tools">↗</div></div></a>`);
  }
  if (m.kind === "noscope" && config.portalUrl) {
    parts.push(`<a class="goto" href="${esc(config.portalUrl)}" target="_blank" rel="noopener">${esc(s.portal)} ↗</a>`);
  }
  for (const c of m.contacts || []) {
    parts.push(`<div class="contact"><div class="ico">☎</div><div><b>${esc(c.dept)}</b><div class="sub">${esc(c.label)}</div></div>`
      + `${c.phone ? `<span class="num">${esc(c.phone)}</span>` : ""}</div>`);
  }
  return parts.length ? `<div class="cards">${parts.join("")}</div>` : "";
}

function renderThread() {
  const s = t();
  const thread = $("#thread");
  const stick = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
  const col = $("#col");
  if (!state.messages.length) {
    col.innerHTML = `<div class="empty"><h2>${esc(s.emptyTitle)}</h2><p>${esc(s.emptyBody)}</p><div class="chips">`
      + s.examples.map(([q, sub]) => `<button class="chip" data-ask="${esc(q)}">${esc(q)}<small>${esc(sub)}</small></button>`).join("")
      + "</div></div>";
    col.style.minHeight = "100%";
    return;
  }
  col.style.minHeight = "";
  col.innerHTML = state.messages.map((m) => {
    if (m.role === "user") {
      const via = m.partial ? s.via.live : m.via === "voice" ? s.via.voice : s.via.text;
      const icon = m.via === "voice" ? MIC_SVG.replace("<svg ", '<svg width="13" height="13" ') : "⌨";
      return `<div class="msg-user"><div class="bubble-user${m.partial ? " live" : ""}">${esc(m.text)}</div><div class="via">${icon} ${esc(via)}</div></div>`;
    }
    const face = m.kind ? (KIND_FACE[/** @type {keyof typeof KIND_FACE} */ (m.kind)] || "answer") : "answer";
    const tag = m.kind && s.tag[/** @type {keyof typeof s.tag} */ (m.kind)];
    return `<div class="msg-ai"><div class="avatar"><img src="assets/chito/${FACE_FILE[/** @type {keyof typeof FACE_FILE} */ (face)]}.png" alt=""></div><div>`
      + `<div class="ai-name">${esc(s.name)}${tag ? ` <span class="tag">${esc(tag)}</span>` : ""}</div>`
      + `<div class="ai-text${m.partial ? " typing" : ""}">${esc(m.text)}</div>`
      + `${m.partial ? "" : `<div class="ai-actions"><button data-copy="${esc(m.id)}">⧉ ${esc(s.copy)}</button></div>`}`
      + `${cardsHtml(m)}</div></div>`;
  }).join("");
  if (stick) thread.scrollTop = thread.scrollHeight;
}

function render() { renderStatic(); renderStage(); renderThread(); }

// ── 대화 상태 ─────────────────────────────────────────────────────
/** @param {string} id @param {"user"|"ai"} role */
function msgFor(id, role) {
  let m = state.messages.find((x) => x.id === id);
  if (!m) {
    m = { id, role, text: "", partial: true };
    state.messages.push(m);
  }
  return m;
}

/** @param {string} face @param {string} [pill] */
function setFace(face, pill = face) { state.face = face; state.pill = pill; }

async function fetchTurn() {
  if (MOCK) return fixture ? { ...fixture.turn, seq: state.lastSeq + 1 } : null;
  try {
    const r = await fetch(`api/turn?after=${state.lastSeq}`);
    return r.ok ? (await r.json()).turn : null;
  } catch { return null; }
}

/** 답이 끝나면 RAG 서버 턴 기록으로 출처·연락처·표정을 붙인다. @param {Msg} m */
async function attachTurn(m) {
  for (let i = 0; i < 6; i += 1) {
    const turn = await fetchTurn();
    if (turn && turn.seq > state.lastSeq) {
      state.lastSeq = turn.seq;
      m.kind = turn.kind;
      m.sources = turn.sources || [];
      m.contacts = turn.contacts || [];
      m.open = new Set(MOCK && turn.kind === "answer" ? [0] : []);
      const face = KIND_FACE[/** @type {keyof typeof KIND_FACE} */ (turn.kind)] || "answer";
      setFace(face, turn.kind === "answer" ? "answerDone" : turn.kind === "smalltalk" ? "hello" : turn.kind);
      render();
      return;
    }
    await sleep(350);
  }
  m.kind = "answer";
  setFace("answer", "answerDone");
  render();
}

// ── 연결 ──────────────────────────────────────────────────────────
function silentStream() {
  silentCtx = silentCtx || new AudioContext();
  return silentCtx.createMediaStreamDestination().stream;
}

function wsUrl() {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/realtime`;
}

/** @param {any} c */
function attach(c) {
  c.addEventListener("status", (/** @type {any} */ e) => {
    const st = e.detail.status;
    state.conn = ["connecting", "creating-session"].includes(st) ? "busy"
      : st === "error" ? "bad" : st === "closed" ? "idle" : "ok";
    const speaking = st === "ai-speaking";
    if (speaking !== state.speaking) state.speaking = speaking;
    renderStage();
  });
  c.addEventListener("user-turn-started", (/** @type {any} */ e) => {
    msgFor(`u-${e.detail.itemId}`, "user").via = "voice"; // 받아쓰기 이벤트와 같은 itemId로 묶는다
    setFace("listen");
    render();
  });
  c.addEventListener("user-turn-stopped", () => { setFace("think"); renderStage(); });
  c.addEventListener("transcript", (/** @type {any} */ e) => {
    const d = e.detail;
    if (d.role === "user") {
      const m = msgFor(`u-${d.itemId}`, "user");
      m.via = "voice";
      m.text = d.text;
      m.partial = d.partial;
      if (!d.partial) {
        if (!d.text) state.messages = state.messages.filter((x) => x !== m);
        else state.lastLang = detectLang(d.text);
      }
    } else {
      const m = msgFor(`a-${d.responseId}`, "ai");
      m.text = d.text;
      m.partial = true;
      if (state.face !== "answer") setFace("answer");
    }
    render();
  });
  c.addEventListener("response-finished", (/** @type {any} */ e) => {
    const d = e.detail;
    const m = state.messages.find((x) => x.id === `a-${d.responseId}`) || [...state.messages].reverse().find((x) => x.role === "ai");
    state.speaking = false;
    if (!m) { setFace(state.listening ? "listen" : "hello"); render(); return; }
    m.partial = false;
    if (d.transcript) m.text = d.transcript;
    setFace("answer", "answerDone");
    render();
    void attachTurn(m);
  });
  c.addEventListener("server-error", (/** @type {any} */ e) => toast(String(e.detail?.error?.message || e.detail?.error || "error")));
  c.addEventListener("error", () => {
    state.conn = "bad";
    state.listening = false;
    setFace("error");
    toast(t().errConnect);
    render();
  });
}

/** @param {boolean} wantMic */
async function connect(wantMic) {
  state.conn = "busy";
  renderStage();
  if (MOCK) {
    client = new MockClient(fixture);
    attach(client);
    await client.connect();
    return;
  }
  if (!(/** @type {any} */ (globalThis).OpenAIAgentsRealtime)) {
    state.sdkMissing = true;
    throw new Error(t().errSdk);
  }
  /** @type {MediaStream | null} */ let micStream = null;
  state.realMic = false;
  if (wantMic) {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      state.realMic = true;
    } catch {
      toast(t().errMic);
    }
  }
  const c = new ChitoClient({
    transport: "websocket",
    directUrl: wsUrl(),
    instructions: "AJOU-VIS", // RAG 서버가 system 메시지를 버리므로 프롬프트에 영향 없음 (server/app.py _split_request)
    micStream: micStream || silentStream(),
    noiseGate: { enabled: false, thresholdDb: -45 },
  });
  client = c;
  attach(c);
  c.setMuted(true);
  c.setOutputMuted(!state.tts);
  await c.connect();
  c.setMuted(!state.listening);
}

/** @param {boolean} wantMic */
async function ensureConnected(wantMic) {
  if (client && state.conn === "ok") {
    if (wantMic && !state.realMic && !MOCK) {
      await client.close(); // 텍스트만 쓰다가 마이크를 켜면 새로 연결한다 (음성 서버의 이전 대화 맥락은 사라짐)
      client = null;
      await connect(true);
    }
    return;
  }
  if (client) { try { await client.close(); } catch { /* ignored */ } client = null; }
  await connect(wantMic);
}

/** @param {any} err */
function connectFailed(err) {
  state.listening = false;
  state.conn = "bad";
  setFace("error");
  toast(err?.message && err.message !== "Realtime transport disconnected" ? err.message : t().errConnect);
  render();
}

// ── 사용자 동작 ───────────────────────────────────────────────────
async function onMic() {
  if (state.sdkMissing) { toast(t().errSdk); return; }
  try {
    if (state.speaking && client) {
      client.interrupt();
      state.speaking = false;
      state.listening = true;
      client.setMuted(false);
      setFace("listen");
      render();
      return;
    }
    if (state.listening) {
      state.listening = false;
      client?.setMuted(true);
      setFace(state.messages.length ? "idle" : "hello", state.messages.length ? "idle" : "hello");
      render();
      return;
    }
    state.listening = true;
    setFace("listen");
    render();
    await ensureConnected(true);
    if (!state.realMic && !MOCK) {
      state.listening = false;
      setFace("idle");
      render();
      return;
    }
    client.setMuted(false);
  } catch (err) {
    connectFailed(err);
  }
}

/** @param {string} text */
async function sendText(text) {
  text = text.trim();
  if (!text) return;
  state.lastLang = detectLang(text);
  state.messages.push({ id: `t-${Date.now()}`, role: "user", text, partial: false, via: "text" });
  setFace("think");
  render();
  try {
    await ensureConnected(false);
    client.sendText(text);
  } catch (err) {
    connectFailed(err);
  }
}

async function newChat() {
  if (client) { try { await client.close(); } catch { /* ignored */ } client = null; }
  state.messages = [];
  state.listening = false;
  state.speaking = false;
  state.conn = "idle";
  setFace("hello");
  document.body.classList.remove("menu-open");
  render();
}

function bindUi() {
  document.addEventListener("click", (e) => {
    const target = /** @type {HTMLElement} */ (e.target);
    const ask = target.closest("[data-ask]");
    if (ask) { document.body.classList.remove("menu-open"); void sendText(/** @type {HTMLElement} */ (ask).dataset.ask || ""); return; }
    const toggle = target.closest("[data-toggle]");
    if (toggle) {
      const [id, idx] = (/** @type {HTMLElement} */ (toggle).dataset.toggle || "").split(":");
      const m = state.messages.find((x) => x.id === id);
      if (m) { m.open = m.open || new Set(); m.open.has(+idx) ? m.open.delete(+idx) : m.open.add(+idx); renderThread(); }
      return;
    }
    const copy = target.closest("[data-copy]");
    if (copy) {
      const m = state.messages.find((x) => x.id === /** @type {HTMLElement} */ (copy).dataset.copy);
      if (m) void navigator.clipboard?.writeText(m.text).then(() => toast(t().copied));
      return;
    }
    if (target.closest(".js-mic, .js-mic-small")) { void onMic(); return; }
    if (document.body.classList.contains("menu-open") && !target.closest(".side, #menu-btn")) document.body.classList.remove("menu-open");
  });
  $("#menu-btn").addEventListener("click", () => document.body.classList.toggle("menu-open"));
  $("#newchat").addEventListener("click", () => void newChat());
  $$("#lang-seg button").forEach((b) => b.addEventListener("click", () => { state.langSel = b.dataset.lang || "auto"; render(); }));
  $("#tts-btn").addEventListener("click", () => {
    state.tts = !state.tts;
    $("#tts-toggle").classList.toggle("on", state.tts);
    $("#tts-btn").setAttribute("aria-pressed", String(state.tts));
    client?.setOutputMuted(!state.tts);
  });
  const input = /** @type {HTMLInputElement} */ ($("#input"));
  const send = /** @type {HTMLButtonElement} */ ($("#send"));
  input.addEventListener("input", () => { send.disabled = !input.value.trim(); });
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    send.disabled = true;
    void sendText(text);
  });
  document.addEventListener("keydown", (e) => {
    const tag = /** @type {HTMLElement} */ (e.target).tagName;
    if (e.code === "Space" && !["INPUT", "TEXTAREA", "BUTTON", "A"].includes(tag)) { e.preventDefault(); void onMic(); }
  });
  $("#pass-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const passcode = /** @type {HTMLInputElement} */ ($("#pass-input")).value;
    const r = await fetch("api/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ passcode }) });
    if (r.ok) /** @type {HTMLDialogElement} */ ($("#pass-dialog")).close();
    else toast(t().passBad);
  });
}

async function init() {
  bindUi();
  // 치토 이미지가 아직 없으면(레포에 넣지 않음 — scripts/prepare_assets.py) 깨진 그림 대신 빈칸으로 둔다
  document.addEventListener("error", (e) => {
    const el = /** @type {HTMLElement} */ (e.target);
    if (el.tagName === "IMG") el.style.visibility = "hidden";
  }, true);
  if (!MOCK && !(/** @type {any} */ (globalThis).OpenAIAgentsRealtime)) state.sdkMissing = true;
  render();
  if (MOCK) {
    const fixtures = await loadFixtures();
    if (MOCK === "listen") fixture = { ...fixtures.answer, via: "voice", stopAfterListening: true };
    else fixture = fixtures[MOCK] || null;
    if (!fixture) return;
    if (fixture.via === "voice") await onMic();
    else await sendText(fixture.question);
    return;
  }
  try {
    config = { ...config, ...(await (await fetch("api/config")).json()) };
    if (config.needPasscode && !config.authed) /** @type {HTMLDialogElement} */ ($("#pass-dialog")).showModal();
  } catch { /* 설정 없이도 화면은 연다 */ }
}

void init();
