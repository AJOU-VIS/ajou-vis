"""
AJOU-VIS 규정집 크롤러
============================================
대상 사이트: rules.ajou.ac.kr (아주대학교 규정정보)
목표: 규정 상세 페이지에서 "제O조(제목)" 단위로 조항을 분리해
     RAG 파이프라인에 바로 넣을 수 있는 JSON으로 저장한다.

동작 방식
---------
페이지 로드 시 목차가 먼저 뜨고 실제 조문 본문은 비동기로 채워지며,
같은 조항 헤더가 목차에 2~3회 중복 렌더링된다. 이 문제를 피하기 위해
조문 전용 앵커 id(예: id="jo003200")를 가진 요소만 골라 본문을 추출한다.
또한 일부 headless(창 없는) 브라우저 환경에서 콘텐츠가 다르게 내려오는
경우가 있어, 자동화 브라우저로 감지되지 않도록 대응 옵션을 적용했다.

실행 방법
---------
1. 터미널에서 가상환경 활성화 후 프로젝트 폴더로 이동
2. Chrome이 설치되어 있어야 함 (Selenium 4.6+ 는 드라이버 자동 관리)
3. pip install selenium beautifulsoup4
4. python rules_crawler.py
5. 결과는 output/ 폴더에 규정별 JSON 파일로 저장됨

검증 현황
----
학칙(594)·장학금 지급규칙(288)·외국인학생 지원규칙(293) 3개 규정,
총 111개 조항을 로컬에서 실행해 정상 추출 확인함 (headless 모드 포함).
새 규정을 TARGET_RULES에 추가할 때는 해당 상세 페이지의 조문이
같은 id="jo..." 구조로 렌더링되는지 먼저 확인할 것.
"""

import json
import re
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from bs4 import BeautifulSoup


# ── 1. 크롤링 대상 규정 목록 ──────────────────────────────────────────
# rules.ajou.ac.kr 규정 목록에서 확인한 detail 페이지 ID.
# 나중에 더 추가하고 싶은 규정이 있으면 여기에 한 줄씩 추가하면 됨.
TARGET_RULES = [
    {"name": "아주대학교 학칙", "rule_id": 594},
    {"name": "장학금 지급규칙", "rule_id": 288},
    {"name": "외국인학생 지원 및 관리에 관한 규칙", "rule_id": 293},
]

BASE_URL = "https://rules.ajou.ac.kr/IRS/rule/detail/{rule_id}"

# 조 번호 패턴: "제1조(목적)", "제7조의2(평생학습중심대학추진본부)" 같은 형태를 모두 잡는다.
ARTICLE_PATTERN = re.compile(r"(제\d+조(?:의\d+)?\([^)]+\))")


def fetch_rendered_html(url: str, min_wait_seconds: int = 8, max_wait_seconds: int = 30) -> str:
    """Selenium으로 페이지를 열고, 본문(조문)이 실제로 다 채워질 때까지 기다린 뒤
    최종 렌더링된 HTML을 문자열로 반환한다.

    목차가 먼저 뜨고 실제 조문 본문은 조금 늦게(비동기로) 채워지는 사이트라서,
    "길이가 안 변한다"는 판단을 성급하게 내리지 않도록
    - 최소 min_wait_seconds초는 무조건 기다리고
    - 그 이후에도 '3번 연속으로' 길이가 같아야만 로딩 완료로 간주한다.
    """
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # 일부 사이트가 자동화 브라우저를 감지해서 다른 화면을 주는 경우가 있어서,
    # 그런 감지를 최대한 피하도록 몇 가지 옵션을 추가한다.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    # navigator.webdriver 값을 숨겨서 "자동화 브라우저"로 감지되는 걸 최대한 피한다.
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    try:
        driver.get(url)

        # 1차: "제1조" 텍스트가 최초로 나타날 때까지 대기 (목차만 먼저 뜨는 경우가 많음)
        WebDriverWait(driver, max_wait_seconds).until(
            lambda d: "제1조" in d.page_source or "제 1 조" in d.page_source
        )

        # 2차: 최소 대기시간을 보장하면서, 길이가 3번 연속 같을 때만 "완료"로 판단.
        start = time.time()
        stable_count = 0
        prev_len = -1
        while time.time() - start < max_wait_seconds:
            cur_len = len(driver.page_source)
            if cur_len == prev_len:
                stable_count += 1
            else:
                stable_count = 0
            prev_len = cur_len

            elapsed = time.time() - start
            if elapsed >= min_wait_seconds and stable_count >= 3:
                break
            time.sleep(1)

        return driver.page_source
    finally:
        driver.quit()


def extract_meta(full_page_text: str, rule_name: str) -> dict:
    """규정명, 시행일 등 상단 메타 정보를 최대한 뽑아본다.
    시행일은 조문 본문(id="jo...")이 아니라 페이지 상단 제목 옆에 별도로
    있어서, real_text가 아니라 페이지 전체 텍스트에서 찾아야 한다.
    "[시행 2026-07-24]"처럼 대괄호로 감싸진 경우도, "시행 2024-11-04"처럼
    감싸지지 않은 경우도 있어서 대괄호 유무와 구분자(. 또는 -)를 모두
    허용하도록 패턴을 넉넉하게 잡는다."""
    match = re.search(r"시행\s*(\d{4}[.\-]\d{1,2}[.\-]\d{1,2})", full_page_text)
    effective_date = match.group(1) if match else None
    return {"rule_name": rule_name, "effective_date": effective_date}


def find_real_content_text(soup: BeautifulSoup) -> str:
    """실제 조문 본문에는 각 조항마다 고유한 앵커 id(예: id="jo003200")가
    붙어있다. 목차(TOC)는 그 id를 '가리키기만' 하는 링크(<a href="#jo003200">)일
    뿐, 자기 자신은 id를 갖지 않는다. 그래서 id="jo..." 를 가진 태그만
    찾으면 목차 중복 문제를 아예 피해서 진짜 본문만 뽑아낼 수 있다.
    """
    jo_tags = soup.find_all(id=re.compile(r"^jo\d+"))
    if not jo_tags:
        print("  !! 경고: id='jo...' 형태의 조항 앵커를 찾지 못함 -> "
              "사이트 구조가 예상과 다를 수 있음. _debug_html 파일 확인 필요")
        return soup.get_text("\n", strip=True)

    print(f"  (참고) id='jo...' 앵커 {len(jo_tags)}개 발견")

    # 각 앵커 태그부터 "다음 앵커 태그 직전"까지의 텍스트를 모아 본문을 구성한다.
    # 앵커가 조문 텍스트를 직접 감싸고 있을 수도, 그냥 빈 마커일 수도 있어서
    # 두 경우 모두 대응하기 위해 해당 태그 자신의 텍스트 + 이후 형제 요소들의
    # 텍스트를 다음 앵커가 나올 때까지 이어붙인다.
    parts = []
    for tag in jo_tags:
        parts.append(tag.get_text(" ", strip=True))
        for sib in tag.find_next_siblings():
            if sib.find(id=re.compile(r"^jo\d+")) or (sib.get("id") or "").startswith("jo"):
                break
            parts.append(sib.get_text(" ", strip=True))
    return "\n".join(p for p in parts if p)


def cut_before_addenda(text: str) -> str:
    """'부칙' 섹션부터는 본칙 조항이 아니므로, 조항 분할 전에 잘라낸다.
    부칙 안에도 '제1조(시행일)' 같은 패턴이 또 나와서 분할을 망칠 수 있음."""
    match = re.search(r"\n\s*부\s*칙\s*\n", text)
    if match:
        return text[: match.start()]
    return text


def split_into_articles(full_text: str) -> list[dict]:
    """조문 전체 텍스트를 "제O조(제목)" 단위로 분리한다.
    각 청크가 곧 RAG에 넣을 하나의 문서(조항)가 된다."""
    matches = list(ARTICLE_PATTERN.finditer(full_text))
    articles = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        chunk = full_text[start:end].strip()

        header = m.group(1)
        # "제32조(휴학)" -> 조번호 "제32조", 제목 "휴학"
        header_match = re.match(r"(제\d+조(?:의\d+)?)\(([^)]+)\)", header)
        article_no = header_match.group(1) if header_match else None
        article_title = header_match.group(2) if header_match else None

        articles.append({
            "article_no": article_no,
            "article_title": article_title,
            "text": chunk,
        })
    return articles


def crawl_rule(name: str, rule_id: int) -> dict:
    url = BASE_URL.format(rule_id=rule_id)
    print(f"[크롤링 시작] {name} ({url})")

    html = fetch_rendered_html(url)
    soup = BeautifulSoup(html, "html.parser")

    # 진단용: "제1조"가 페이지에 몇 번 등장했는지 세어본다.
    # 1번이면 목차만 로드되고 실제 본문은 아직 안 들어왔을 가능성이 높다.
    occurrence = html.count("제1조")
    if occurrence < 2:
        print(f"  !! 경고: '제1조'가 페이지에 {occurrence}번만 나타남 -> "
              f"본문이 아직 로드되지 않았을 수 있음. output/_debug_html/{rule_id}.html 확인 필요")

    # 디버깅용으로 렌더링된 HTML 원본을 같이 저장해둔다.
    # 혹시 또 이상하게 나오면 이 파일을 보면서 구조를 다시 확인하면 된다.
    debug_dir = Path("output/_debug_html")
    debug_dir.mkdir(parents=True, exist_ok=True)
    with open(debug_dir / f"{rule_id}.html", "w", encoding="utf-8") as f:
        f.write(html)

    real_text = find_real_content_text(soup)
    real_text = cut_before_addenda(real_text)

    # 시행일은 조문 본문이 아니라 페이지 전체(제목 영역)에서 찾아야 하므로
    # real_text가 아니라 soup 전체 텍스트를 넘긴다.
    meta = extract_meta(soup.get_text("\n", strip=True), name)
    articles = split_into_articles(real_text)

    print(f"  -> 조항 {len(articles)}개 추출")
    return {
        "rule_name": name,
        "rule_id": rule_id,
        "url": url,
        "effective_date": meta["effective_date"],
        "article_count": len(articles),
        "articles": articles,
    }


def main():
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    for rule in TARGET_RULES:
        try:
            result = crawl_rule(rule["name"], rule["rule_id"])
        except Exception as e:
            print(f"  !! 실패: {rule['name']} - {e}")
            continue

        out_path = out_dir / f"{rule['rule_id']}_{rule['name']}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  저장 완료: {out_path}\n")


if __name__ == "__main__":
    main()
