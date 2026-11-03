"""치토 표정 이미지를 웹 화면용(480px)으로 만든다 — 원본 PNG는 팀 Drive '치토 PNG' 폴더 (레포에는 넣지 않음).

실행:  python web/scripts/prepare_assets.py "<치토 PNG 폴더>"
결과:  web/static/assets/chito/chito_*.png (.gitignore)

원본은 파일 이름 앞 번호(예: "29.")로 찾는다. Drive에 올리면서 이름 뒤쪽이 바뀌거나
(예: "29.인사 (1).png") 폴더가 한 겹 더 생겨도, 한글 자모가 나뉘어 저장돼도(NFD) 찾는다.
없는 표정은 건너뛰고 끝에 알려 준다 — 화면은 그 표정만 이미지 없이 뜬다.
"""
import re
import sys
import unicodedata
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


def find(files, filename):
    """이름이 같은 파일, 없으면 앞 번호가 같은 PNG 하나."""
    want = unicodedata.normalize("NFC", filename)
    for f in files:
        if unicodedata.normalize("NFC", f.name) == want:
            return f
    number = filename.split(".", 1)[0]
    same_number = [f for f in files if re.match(rf"{number}\.", unicodedata.normalize("NFC", f.name))]
    return same_number[0] if len(same_number) == 1 else None


src = Path(sys.argv[1])
if not src.is_dir():
    sys.exit(f"폴더가 없습니다: {src}")
files = sorted(p for p in src.rglob("*") if p.suffix.lower() == ".png")
if not files:
    sys.exit(f"PNG가 없습니다: {src}")

dst = Path(__file__).resolve().parents[1] / "static" / "assets" / "chito"
dst.mkdir(parents=True, exist_ok=True)
missing = []
for name, filename in FACES.items():
    path = find(files, filename)
    if path is None:
        missing.append(filename)
        continue
    im = Image.open(path).convert("RGBA")
    im = im.crop(im.getbbox())
    w, h = im.size
    side = max(w, h)
    pad = int(side * 0.06)
    canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((side + 2 * pad - w) // 2, (side + 2 * pad - h) // 2))
    canvas.thumbnail((480, 480), Image.LANCZOS)
    canvas.save(dst / f"{name}.png", optimize=True)
    print(name, "←", path.relative_to(src))

if missing:
    print(f"\n못 찾은 원본 {len(missing)}개 (이 표정은 이미지 없이 뜬다): {', '.join(missing)}")
    print("폴더에 있는 PNG:", ", ".join(f.name for f in files[:40]))
