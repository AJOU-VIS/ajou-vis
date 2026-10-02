"""
AJOU-VIS 캘린더(행사 일정) 크롤러
============================================
대상: www.ajou.ac.kr 캘린더 "주간 리스트" 화면 (notice-calendar.do?mode=wList)
목표: 날짜별 학사/행사 일정을 (날짜, 구분, 내용, 기간) 단위로 저장한다.

동작 방식
---------
학칙 크롤러(rules_crawler.py)와 마찬가지로, 이 페이지도 처음엔 껍데기만
로드되고 실제 일정 표는 JS로 나중에 채워진다. 그래서 Selenium으로
"실제 표가 채워질 때까지" 기다린 뒤 최종 HTML을 가져온다.

날짜 하나의 URL(mode=wList&date=YYYY-MM-DD)을 열면 그 날짜가 포함된
한 주(또는 그 근방 기간)의 일정이 나온다. 실제 구조를 열어보니 표(table)가
아니라, 하루당 하나씩(div.b-cal-content-box) 블록이 나뉘어 있고 그 안에
날짜와 그날의 일정 목록(ul.b-cal-undergrad > li)이 들어있는 형태였다.

여러 주를 이어서 가져오기 위해, 사이트의 "다음" 버튼을 따라가는 대신
우리가 직접 7일 간격으로 날짜를 만들어서 순서대로 조회한다. 실제로
"다음" 버튼이 가리키는 날짜와 화면에 표시된 기간 사이에 며칠씩 비는
구간이 생기는 걸 확인했기 때문이다 (자세한 이유는 crawl_events() 참고).

실행 방법
---------
pip install selenium beautifulsoup4
python event_calendar_crawler.py
결과는 output/events.json 에 저장됨

주의
----
이 대화 환경은 네트워크 정책상 ajou.ac.kr에 실제 접속해 검증하지 못했다.
표의 실제 HTML 구조(태그/클래스명)는 이전 학칙 크롤러 디버깅 때와 마찬가지로
로컬에서 돌려보면서 다를 경우 debug 폴더의 HTML을 보고 맞춰야 할 수 있다.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

BASE_URL = "https://www.ajou.ac.kr/kr/ajou/notice-calendar.do"

# 크롤링을 시작할 날짜 (이 날짜가 포함된 주부터 시작해서 "다음" 버튼을 따라감)
START_DATE = "2026-09-27"
# 몇 구간(주)까지 이어서 가져올지. 너무 크게 잡으면 오래 걸리고 서버에 부담을 주니
# 처음엔 작게(4주 정도) 테스트해보고 필요하면 늘리는 걸 추천.
MAX_PERIODS = 4

DATE_ROW_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\([월화수목금토일]\)$")


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # 규정 크롤러 때와 동일하게, 자동화 브라우저로 감지되는 걸 최대한 피한다.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def fetch_rendered_html(driver: webdriver.Chrome, date: str,
                         min_wait_seconds: int = 6, max_wait_seconds: int = 25) -> str:
    """지정한 날짜의 주간 리스트 페이지를 열고, 실제 일정 표가 채워질 때까지
    기다린 뒤 최종 HTML을 반환한다."""
    url = f"{BASE_URL}?mode=wList&date={date}&srCategoryId="
    driver.get(url)

    start = time.time()
    stable_count, prev_len = 0, -1
    while time.time() - start < max_wait_seconds:
        source = driver.page_source
        # 날짜 형식("2026-07-19(일)")이 실제로 나타났는지가 표가 로드됐다는 신호
        has_date_row = bool(re.search(r"\d{4}-\d{2}-\d{2}\([월화수목금토일]\)", source))
        cur_len = len(source)
        stable_count = stable_count + 1 if cur_len == prev_len else 0
        prev_len = cur_len

        elapsed = time.time() - start
        if has_date_row and elapsed >= min_wait_seconds and stable_count >= 3:
            break
        time.sleep(1)

    return driver.page_source


def find_day_containers(soup: BeautifulSoup):
    """board-wrap 안에서 '하루 단위' 블록들을 찾는다.
    구조: div.b-cal-content-box 하나가 하루치를 담고 있고,
    그 안에 날짜(p.b-cal-date > span)와 그날의 일정 목록(ul.b-cal-undergrad)이 있다."""
    board_wrap = soup.find(class_="board-wrap")
    if board_wrap is None:
        return []
    return board_wrap.select("div.b-cal-content-box")


def parse_events_from_day(day_container) -> list[dict]:
    """하루 블록 하나에서 그날의 일정들을 뽑아낸다.
    날짜는 블록 상단의 p.b-cal-date > span 에서, 각 일정은
    ul.b-cal-undergrad 안의 li 하나하나에서 카테고리·내용·기간을 가져온다."""
    date_span = day_container.select_one("p.b-cal-date > span")
    if date_span is None:
        return []
    date_text = date_span.get_text(strip=True)

    events = []
    for li in day_container.select("ul.b-cal-undergrad li"):
        category_span = li.select_one("span.b-cate")
        period_span = li.select_one("span.b-date")
        link = li.find("a")

        category = category_span.get_text(strip=True).strip("[]") if category_span else None
        period = period_span.get_text(strip=True) if period_span else None
        content = link.get_text(strip=True) if link else None

        if content is None:
            continue  # 내용이 없는 항목은 건너뜀

        events.append({
            "date": date_text,
            "category": category,
            "content": content,
            "period": period,
        })

    return events


def crawl_events() -> list[dict]:
    """사이트의 '다음' 버튼을 믿고 따라가면, 실제로 화면에 보여준 기간(예: 7일)과
    버튼이 가리키는 다음 시작일 사이에 며칠씩 비는 구간(gap)이 생기는 걸
    확인했다 (예: 09-27~10-03을 보여주고 '다음'은 10-10을 가리킴 -> 10-04~10-09 누락).
    그래서 사이트 버튼을 따라가지 않고, 우리가 직접 7일 간격으로 날짜를
    만들어서 순서대로 조회하는 방식으로 안전하게 처리한다."""
    driver = build_driver()
    all_events = []

    try:
        start = datetime.strptime(START_DATE, "%Y-%m-%d")
        for i in range(MAX_PERIODS):
            current_date = (start + timedelta(days=7 * i)).strftime("%Y-%m-%d")

            print(f"[{i + 1}/{MAX_PERIODS}] {current_date} 기준 구간 조회 중...")
            html = fetch_rendered_html(driver, current_date)
            soup = BeautifulSoup(html, "html.parser")

            # 디버깅용 HTML 저장 (구조가 예상과 다를 때 확인용)
            debug_dir = Path("output/_debug_html")
            debug_dir.mkdir(parents=True, exist_ok=True)
            with open(debug_dir / f"calendar_{current_date}.html", "w", encoding="utf-8") as f:
                f.write(html)

            day_containers = find_day_containers(soup)
            if not day_containers:
                print("  !! 경고: 일정 블록을 찾지 못함. _debug_html 폴더 확인 필요")
                continue  # 이 구간만 건너뛰고 다음 구간은 계속 시도

            events = []
            for day_container in day_containers:
                events.extend(parse_events_from_day(day_container))
            print(f"  -> {len(events)}개 일정 추출")
            all_events.extend(events)
    finally:
        driver.quit()

    return all_events


def main():
    events = crawl_events()

    # 같은 일정이 기간 내 매일 반복 표시되므로, (구분, 내용, 기간)이 같으면
    # 같은 일정으로 보고 하나만 남긴다. 날짜(date)는 "오늘 기준 조회 시작일"일
    # 뿐 실제 시작일이 아닐 수 있어 최종 결과에서는 제외하고, period가
    # 시작~종료를 이미 다 담고 있으므로 그걸 기준으로 삼는다.
    unique = {}
    for e in events:
        key = (e["category"], e["content"], e["period"])
        if key not in unique:
            unique[key] = {
                "category": e["category"],
                "content": e["content"],
                "period": e["period"],
            }
    result = list(unique.values())

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "events.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[전체 완료] 총 {len(result)}개 일정(중복 제거 후) 저장 -> {out_path}")


if __name__ == "__main__":
    main()
