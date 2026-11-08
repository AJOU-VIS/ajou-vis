"""치토 목소리 설정 — prompts/persona_ko.md 목소리(TTS) 블록을 읽어 TTS 옵션으로 바꾼다.

목소리 설정의 원본은 페르소나 파일 하나다. Colab 노트북(7번 셀)과 Mac 실행 스크립트
(speech-to-speech/run_local_rag.sh)가 모두 이 모듈로 같은 값을 읽는다.

블록에서 읽는 줄 (줄 앞 이름을 바꾸면 못 읽으니 그대로 둔다):
  - 방식: ...            "복제"가 들어가면 기준 음성 복제(clone), 아니면 화자 지정(custom)
  - 기준 음성: <경로> ...  clone일 때. 레포 루트 기준 경로 (첫 단어만 읽음)
  - 기준 음성 문장: ...    clone일 때. 기준 음성에서 말한 문장
  - 화자: <이름>           custom일 때 (예: Sohee)
  - 말투 지시문: ...       "없음"이면 사용 안 함
  - 문장 사이 무음: 0.4초

명령줄에서 쓰기 (Mac 실행 스크립트용, 한 줄에 인자 하나씩 출력):
  python server/voice_config.py --args
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PERSONA_PATH = REPO_DIR / "prompts" / "persona_ko.md"
BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"   # 기준 음성 복제용 (CustomVoice 모델은 복제 불가)

_BLOCK = re.compile(r"<!--\s*TTS:BEGIN\s*-->(.*?)<!--\s*TTS:END\s*-->", re.DOTALL)


@dataclass
class VoiceConfig:
    mode: str                     # "clone" 또는 "custom"
    ref_audio: Path | None = None
    ref_text: str = ""
    speaker: str = ""
    instruct: str = ""
    sentence_pause_s: float = 0.0

    def tts_args(self, include_pause: bool = True) -> list[str]:
        """speech-to-speech Qwen3-TTS 옵션. 문장 사이 무음은 포크에 옵션이 있을 때만 넘기려면 빼고 받는다."""
        if self.mode == "clone":
            args = ["--qwen3_tts_model_name", BASE_MODEL,
                    "--qwen3_tts_ref_audio", str(self.ref_audio), "--qwen3_tts_ref_text", self.ref_text]
        else:
            args = ["--qwen3_tts_speaker", self.speaker]
            if self.instruct:
                args += ["--qwen3_tts_instruct", self.instruct]
        if include_pause and self.sentence_pause_s:
            args += ["--qwen3_tts_sentence_pause_s", f"{self.sentence_pause_s:g}"]
        return args


def _field(block: str, name: str) -> str | None:
    m = re.search(rf"(?m)^-\s*{re.escape(name)}\s*:\s*(.+)$", block)
    return m.group(1).strip() if m else None


def load(path: Path = PERSONA_PATH, repo_dir: Path = REPO_DIR) -> VoiceConfig:
    """페르소나 파일의 목소리 블록을 읽는다. 필요한 줄이 없으면 어느 줄인지 알려주며 실패한다."""
    m = _BLOCK.search(path.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{path}에 목소리 블록(<!-- TTS:BEGIN --> ~ <!-- TTS:END -->)이 없음")
    block = m.group(1)

    def need(name: str) -> str:
        value = _field(block, name)
        if not value:
            raise ValueError(f"{path.name} 목소리 블록에 '- {name}:' 줄이 없음")
        return value

    instruct = _field(block, "말투 지시문") or ""
    if instruct.startswith("없음"):
        instruct = ""
    pause = re.match(r"([\d.]+)\s*초", _field(block, "문장 사이 무음") or "")
    config = VoiceConfig(mode="clone" if "복제" in need("방식") else "custom",
                         instruct=instruct, sentence_pause_s=float(pause.group(1)) if pause else 0.0)

    if config.mode == "clone":
        config.ref_audio = repo_dir / need("기준 음성").split()[0]
        config.ref_text = need("기준 음성 문장")
        if not config.ref_audio.exists():
            raise ValueError(f"기준 음성 파일이 없음: {config.ref_audio}")
    else:
        config.speaker = need("화자").split()[0]
    return config


if __name__ == "__main__":
    voice = load()
    if "--args" in sys.argv:
        print("\n".join(voice.tts_args()))
    else:
        print(voice)
