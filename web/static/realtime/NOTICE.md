# 출처

이 폴더의 파일은 [AJOU-VIS/speech-to-speech](https://github.com/AJOU-VIS/speech-to-speech) 포크(원본: huggingface/speech-to-speech, Apache License 2.0)의 `demo/`에서 **수정 없이** 복사했다 (포크 커밋 `9dd182d`, 2026-11-03).

| 파일 | 원본 경로 |
|---|---|
| `s2s-realtime-client.js` | `demo/s2s-realtime-client.js` |
| `ws/codec.js`, `ws/orb-visualizer.js`, `ws/user-audio-recorder.js` | `demo/ws/` |
| `worklets/mic-capture.js`, `worklets/audio-playback.js` | `demo/worklets/` |

치토 화면에 필요한 기능(텍스트 질문, 끊기, 답 소리 끄기)은 이 파일들을 고치지 않고 `../chito-client.js`에서 상속으로 더했다. 원본을 다시 가져올 때는 이 폴더를 통째로 바꾸면 된다.
