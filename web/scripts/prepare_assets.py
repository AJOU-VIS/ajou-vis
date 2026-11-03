"""치토 표정 이미지를 웹 화면용(480px)으로 만든다 — 원본 PNG는 팀 Drive '치토 PNG' 폴더 (레포에는 넣지 않음).

실행:  python web/scripts/prepare_assets.py "<치토 PNG 폴더>"
결과:  web/static/assets/chito/chito_*.png (.gitignore)
"""
import sys
from pathlib import Path

from PIL import Image

# 화면 상태 → 원본 파일 (설계 보드 '상황별 치토 표정')
FACES = {
    "chito_idle": "2.메인 캐릭터 기본형.png",
    "chito_hello": "29.인사.png",
    "chito_listen": "10.궁금.png",
    "chito_think": "22.독서.png",
    "chito_answer": "16.안내.png",
    "chito_sorry": "27.미안해(사과).png",
    "chito_noscope": "15.금지.png",
    "chito_crisis": "7.애.png",
    "chito_error": "11.놀람.png",
}

src = Path(sys.argv[1])
dst = Path(__file__).resolve().parents[1] / "static" / "assets" / "chito"
dst.mkdir(parents=True, exist_ok=True)
for name, filename in FACES.items():
    im = Image.open(src / filename).convert("RGBA")
    im = im.crop(im.getbbox())
    w, h = im.size
    side = max(w, h)
    pad = int(side * 0.06)
    canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((side + 2 * pad - w) // 2, (side + 2 * pad - h) // 2))
    canvas.thumbnail((480, 480), Image.LANCZOS)
    canvas.save(dst / f"{name}.png", optimize=True)
    print(name, "←", filename)
