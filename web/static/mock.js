// @ts-check
/**
 * 화면 확인용 가짜 연결 (?mock=answer|contact|sorry|noscope|crisis|en|greet|listen) — 서버·비용 없음.
 * ChitoClient와 같은 이벤트를 같은 순서로 낸다. 대화 데이터는 mock/fixtures.json
 * (11/3 마지막 스모크의 실제 답 + 같은 질문의 실제 검색 결과, scripts/make_mock_fixtures.py).
 */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** @param {string} text @param {number} n */
function pieces(text, n) {
  const size = Math.ceil(text.length / n);
  return Array.from({ length: n }, (_, i) => text.slice(0, size * (i + 1)));
}

export async function loadFixtures() {
  const r = await fetch("mock/fixtures.json");
  return r.json();
}

export class MockClient extends EventTarget {
  /** @param {any} fixture */
  constructor(fixture) {
    super();
    this.fixture = fixture;
    this.status = "idle";
    this._muted = true;
    this._speaking = false;
    this._levelTimer = 0;
  }

  /** @param {string} type @param {any} [detail] */
  _emit(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }

  /** @param {string} s */
  _setStatus(s) { this.status = s; this._emit("status", { status: s }); }

  async connect() {
    this._setStatus("connecting");
    await sleep(120);
    this._setStatus("connected");
  }

  async close() { this._levels(false); this._setStatus("closed"); }

  /** @param {boolean} m */
  setMuted(m) {
    this._muted = m;
    if (!m && this.fixture?.via === "voice") void this._voiceTurn();
  }

  setOutputMuted() {}
  interrupt() { this._speaking = false; }
  get isSpeaking() { return this._speaking; }

  /** @param {string} _text */
  sendText(_text) { void this._answer(); }

  /** @param {boolean} on */
  _levels(on) {
    clearInterval(this._levelTimer);
    const root = document.documentElement;
    if (!on) { for (let i = 0; i < 5; i += 1) root.style.removeProperty(`--bar${i}`); return; }
    this._levelTimer = window.setInterval(() => {
      for (let i = 0; i < 5; i += 1) root.style.setProperty(`--bar${i}`, (0.25 + Math.random() * 0.75).toFixed(2));
    }, 120);
  }

  async _voiceTurn() {
    const f = this.fixture;
    this._emit("user-turn-started", { itemId: "u1" });
    this._setStatus("user-speaking");
    this._levels(true);
    for (const text of pieces(f.question, 3)) {
      await sleep(180);
      this._emit("transcript", { role: "user", text, partial: true, itemId: "u1" });
    }
    if (f.stopAfterListening) return;
    await sleep(150);
    this._emit("user-turn-stopped", { itemId: "u1" });
    this._emit("transcript", { role: "user", text: f.question, partial: false, itemId: "u1" });
    this._setStatus("processing");
    this._levels(false);
    await this._answer();
  }

  async _answer() {
    const f = this.fixture;
    await sleep(300);
    this._speaking = true;
    this._setStatus("ai-speaking");
    this._levels(true);
    for (const text of pieces(f.answer, 4)) {
      await sleep(160);
      this._emit("transcript", { role: "assistant", text, partial: true, responseId: "r1" });
    }
    this._emit("transcript", { role: "assistant", text: f.answer, partial: false, responseId: "r1" });
    await sleep(120);
    this._speaking = false;
    this._levels(false);
    this._setStatus("connected");
    this._emit("response-finished", { responseId: "r1", status: "completed", audible: true, transcript: f.answer });
  }
}
