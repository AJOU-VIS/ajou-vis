// @ts-check
/**
 * 치토 실시간 연결 — speech-to-speech demo의 S2sRealtimeClient(웹소켓 경로)를 그대로 쓰고,
 * 화면에 필요한 세 가지만 더한다: 텍스트 질문, 말하는 중 끊기, 답 소리 끄기.
 * 원본 파일은 realtime/ 아래에 수정 없이 복사해 두었다 (realtime/NOTICE.md).
 */
import { S2sRealtimeClient } from "./realtime/s2s-realtime-client.js";

export class ChitoClient extends S2sRealtimeClient {
  /** @param {any} options */
  constructor(options) {
    super(options);
    this._outputMuted = false;
    this._outputConnected = true;
  }

  async connect() {
    await super.connect();
    this.setOutputMuted(this._outputMuted);
  }

  /** 텍스트 질문 — SDK sendMessage가 conversation.item.create + response.create를 보낸다. @param {string} text */
  sendText(text) {
    if (!this._session) throw new Error("not connected");
    this._responseRequested = true;
    this._session.sendMessage(text);
  }

  /** 치토가 말하는 중에 끊고 바로 말하기 */
  interrupt() {
    try { this._session?.interrupt(); } catch { /* 이미 끝난 응답 */ }
    this._clearPlayback();
  }

  /** 답 소리 끄기·켜기 (글자는 계속 온다) @param {boolean} muted */
  setOutputMuted(muted) {
    this._outputMuted = muted;
    const out = this._outAnalyser;
    const ctx = this._ctx;
    if (!out || !ctx) return;
    if (muted && this._outputConnected) {
      out.disconnect(ctx.destination);
      this._outputConnected = false;
    } else if (!muted && !this._outputConnected) {
      out.connect(ctx.destination);
      this._outputConnected = true;
    }
  }

  get isSpeaking() { return Boolean(this._aiSpeaking); }
}
