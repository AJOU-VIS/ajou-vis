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

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

BASE_URL = "https://www.ajou.ac.kr/kr/ajou/notice-calendar.do"

# 기본값: 오늘(한국 시간) 기준 1주 전 주부터 20주(약 5개월)를 가져온다.
# 실행할 때 --start, --weeks 로 바꿀 수 있다. (자동 갱신은 GitHub Actions가 매일 실행)
DEFAULT_WEEKS = 20
LOOKBACK_DAYS = 7          # 지금 진행 중인 긴 일정(예: 시작이 지난주)을 놓치지 않으려고 하루 7일 전부터
KST = timezone(timedelta(hours=9))
DEFAULT_OUT = Path("output/events.json")

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


def default_start_date(now: datetime | None = None) -> str:
    """오늘(한국 시간)에서 LOOKBACK_DAYS 전 날짜를 YYYY-MM-DD로 돌려준다."""
    now = now or datetime.now(KST)
    return (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")


def event_key(e: dict) -> tuple:
    return (e.get("category"), e.get("content"), e.get("period"))


def dedupe(events: list[dict]) -> list[dict]:
    """(구분, 내용, 기간)이 같으면 같은 일정으로 보고 하나만 남긴다 (날짜 필드는 버림)."""
    unique = {}
    for e in events:
        k = event_key(e)
        if k not in unique:
            unique[k] = {"category": e.get("category"), "content": e.get("content"),
                         "period": e.get("period")}
    return list(unique.values())


def merge_events(old: list[dict], new: list[dict]) -> list[dict]:
    """기존 파일의 일정을 지우지 않고 새 일정을 더한다.
    학교 페이지는 조회한 기간의 일정만 보여 주므로, 지난 일정(예: 중간시험)은 다음 갱신 때 사라진다.
    평가 문항·시연에서 '이번 학기 중간시험 언제였지?' 같은 질문이 계속 맞도록 지난 일정은 남긴다.
    같은 (구분, 내용, 기간)은 하나로 합친다. 기존 순서를 유지하고 새 항목은 뒤에 붙인다."""
    return dedupe(list(old) + list(new))


def crawl_events(start_date: str, periods: int) -> list[dict]:
    """사이트의 '다음' 버튼을 믿고 따라가면, 실제로 화면에 보여준 기간(예: 7일)과
    버튼이 가리키는 다음 시작일 사이에 며칠씩 비는 구간(gap)이 생기는 걸
    확인했다 (예: 09-27~10-03을 보여주고 '다음'은 10-10을 가리킴 -> 10-04~10-09 누락).
    그래서 사이트 버튼을 따라가지 않고, 우리가 직접 7일 간격으로 날짜를
    만들어서 순서대로 조회하는 방식으로 안전하게 처리한다."""
    driver = build_driver()
    all_events = []

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        for i in range(periods):
            current_date = (start + timedelta(days=7 * i)).strftime("%Y-%m-%d")

            print(f"[{i + 1}/{periods}] {current_date} 기준 구간 조회 중...")
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="아주대 학사일정(캘린더) 크롤러")
    ap.add_argument("--start", default="", help="조회 시작 날짜 YYYY-MM-DD (기본: 오늘 7일 전, 한국 시간)")
    ap.add_argument("--weeks", type=int, default=DEFAULT_WEEKS, help="가져올 주 수 (기본 %d)" % DEFAULT_WEEKS)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="저장 경로 (기본 output/events.json)")
    ap.add_argument("--no-merge", action="store_true",
                    help="기존 파일을 무시하고 새로 가져온 일정만 저장 (기본은 기존 일정에 더함)")
    args = ap.parse_args(argv)

    start_date = args.start or default_start_date()
    events = crawl_events(start_date, args.weeks)

    # 같은 일정이 기간 내 매일 반복 표시되므로, (구분, 내용, 기간)이 같으면 하나만 남긴다.
    new = dedupe(events)
    if not new:
        # 접속이 막혔거나 페이지 구조가 바뀐 경우. 기존 파일을 빈 값으로 덮어쓰지 않는다.
        print("\n[실패] 일정을 하나도 가져오지 못했습니다. 기존 파일은 그대로 둡니다.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    old = []
    if out_path.exists() and not args.no_merge:
        old = json.loads(out_path.read_text(encoding="utf-8"))
    result = new if args.no_merge else merge_events(old, new)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n[전체 완료] 새로 가져온 일정 {len(new)}개, 기존 {len(old)}개 -> "
          f"저장 {len(result)}개 -> {out_path}")


if __name__ == "__main__":
    main()
