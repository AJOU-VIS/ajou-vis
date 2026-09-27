"""
AJOU-VIS 캠퍼스 시설 안내 크롤러
============================================
대상: www.ajou.ac.kr 캠퍼스 생활 안내 페이지들
      - 편의시설(facility.do): 편의점/카페/식당/서점 등
      - 체육시설(sports.do)
      - 학교버스(bus01.do)
목표: 각 페이지 안의 표(테이블) 내용을 그대로 JSON으로 저장한다.

동작 방식
---------
이 페이지들은 (확인 결과) 학칙 규정집이나 캘린더와 달리 JS 렌더링 없이
서버가 완성된 HTML을 바로 내려주는 정적 페이지라서, Selenium 없이
requests + BeautifulSoup만으로 충분하다.

페이지마다 표의 정확한 열 구성(칸 이름)이 다를 수 있어서, 표 구조를
미리 가정하지 않고 "표 안의 모든 행/칸을 그대로" 뽑아내는 범용 방식으로
파싱한다. 첫 행이 헤더(th)로 보이면 그 이름을 칸 이름으로 쓰고,
아니면 그냥 칸1/칸2/... 로 이름 붙인다.

실행 방법
---------
pip install requests beautifulsoup4
python campus_facility_crawler.py
결과는 output/campus_facilities.json 에 저장됨

주의
----
이 대화 환경은 네트워크 정책상 ajou.ac.kr에 실제 접속해 검증하지 못했다.
표 구조가 예상과 다르면 output/_debug_html/ 안의 원본 HTML을 보고
find_tables()나 parse_table() 로직을 조정해야 할 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# 크롤링 대상 페이지들. 나중에 더 추가하고 싶으면 여기에 한 줄씩 추가.
TARGET_PAGES = [
    {"name": "편의시설", "url": "https://www.ajou.ac.kr/kr/life/facility.do"},
    {"name": "체육시설", "url": "https://www.ajou.ac.kr/kr/life/sports.do"},
    {"name": "학교버스", "url": "https://www.ajou.ac.kr/kr/life/bus01.do"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    response.encoding = response.apparent_encoding  # 한글 깨짐 방지
    return response.text


def get_row_cells(row) -> list[str]:
    """행 하나에서 칸 텍스트 목록을 뽑는다. colspan(칸 병합)이 있으면
    그 텍스트를 병합된 칸 수만큼 반복해서 넣어, 나중에 헤더와 위치가
    어긋나지 않게 한다. (예: "24시간 운영"이 4칸을 합친 셀이면
    ["24시간 운영", "24시간 운영", "24시간 운영", "24시간 운영"]으로 처리)"""
    cells = []
    for cell in row.find_all(["td", "th"]):
        text = cell.get_text(" ", strip=True)
        colspan = int(cell.get("colspan", 1) or 1)
        cells.extend([text] * colspan)
    return cells


def parse_table(table) -> list[dict]:
    """table 태그 하나를 [{칸이름: 값, ...}, ...] 형태로 바꾼다."""
    rows = table.find_all("tr")
    if not rows:
        return []

    # 첫 행에 th가 있으면 그걸 칸 이름(헤더)으로 쓰고, 없으면 칸1/칸2/...로 번호 매김
    header_cells = rows[0].find_all("th")
    if header_cells:
        headers = get_row_cells(rows[0])
        data_rows = rows[1:]
    else:
        headers = [f"칸{i + 1}" for i in range(len(get_row_cells(rows[0])))]
        data_rows = rows

    parsed = []
    for row in data_rows:
        cells = get_row_cells(row)
        if not cells:
            continue
        # 칸 개수가 헤더보다 적으면(rowspan 등) 있는 만큼만 매칭
        entry = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        parsed.append(entry)

    return parsed


def find_tables(soup: BeautifulSoup) -> list:
    """페이지 본문 영역의 표들을 찾는다. 특정 클래스명에 의존하지 않고
    페이지 안의 모든 table 태그를 대상으로 한다 (필요하면 나중에
    본문 영역만 좁히도록 조정 가능)."""
    return soup.find_all("table")


def crawl_page(name: str, url: str) -> dict:
    print(f"[크롤링 시작] {name} ({url})")
    html = fetch_html(url)

    # 디버깅용 원본 저장
    debug_dir = Path("output/_debug_html")
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe_name = name.replace("/", "_")
    with open(debug_dir / f"facility_{safe_name}.html", "w", encoding="utf-8") as f:
        f.write(html)

    soup = BeautifulSoup(html, "html.parser")
    tables = find_tables(soup)

    if not tables:
        print("  !! 경고: table을 찾지 못함. 페이지가 카드/리스트 형태일 수 있음. "
              "_debug_html 폴더 확인 필요")
        return {"page_name": name, "url": url, "tables": []}

    parsed_tables = [parse_table(t) for t in tables]
    total_rows = sum(len(t) for t in parsed_tables)
    print(f"  -> 표 {len(tables)}개, 총 {total_rows}행 추출")

    return {"page_name": name, "url": url, "tables": parsed_tables}


def main():
    results = []
    for page in TARGET_PAGES:
        try:
            result = crawl_page(page["name"], page["url"])
        except Exception as e:
            print(f"  !! 실패: {page['name']} - {e}")
            continue
        results.append(result)

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "campus_facilities.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[전체 완료] {out_path} 저장")


if __name__ == "__main__":
    main()
