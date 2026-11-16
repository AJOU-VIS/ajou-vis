"""facility_tables / facility_records 시험 (네트워크·selenium·requests 불필요).
실행: python3 corpus/scripts/test_facility_tables.py   (beautifulsoup4 필요)"""
import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facility_records import load_facility_file
from facility_tables import parse_page_tables, parse_table

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(("통과 " if cond else "실패 ") + name)


def tables_of(html, page_name=""):
    return parse_page_tables(BeautifulSoup(html, "html.parser"), page_name)


# ── 1) 체육시설 표처럼 앞 칸이 세로 병합된 표 (층별·요일·시간·요금이 여러 종목에 걸침) ──
SPORTS = """<table>
<tr><th>층별</th><th>종목</th><th>요일</th><th>시간</th><th>이용 요금</th></tr>
<tr><td rowspan="3">1층</td><td>농구</td><td rowspan="3">월 ~ 금</td><td rowspan="3">09:00 ~ 18:00</td><td rowspan="3">무료</td></tr>
<tr><td>배구</td></tr>
<tr><td>배드민턴</td></tr>
</table>"""
rows = tables_of(SPORTS)[0][0]
check("세로 병합된 표가 3행으로 읽힌다", len(rows) == 3)
check("배구 행에도 층별·요일·시간·요금이 채워진다",
      rows[1] == {"층별": "1층", "종목": "배구", "요일": "월 ~ 금", "시간": "09:00 ~ 18:00", "이용 요금": "무료"})
check("종목 이름이 '종목' 열에 그대로 있다(층별 열로 밀리지 않음)", [r["종목"] for r in rows] == ["농구", "배구", "배드민턴"])

# ── 2) 학교버스 표: "구분"(수원역)과 출발·도착 장소가 세로 병합 ──
BUS = """<table>
<tr><th>구분</th><th>출발시각</th><th>출발장소</th><th>도착장소</th></tr>
<tr><td rowspan="3">수원역</td><td>08:15</td><td rowspan="3">수원역 9번/10번 출구 중간지점</td><td rowspan="3">율곡관 입구 → 원천관 입구</td></tr>
<tr><td>09:50</td></tr>
<tr><td>11:20</td></tr>
<tr><td rowspan="2">광교 중앙역</td><td>08:30</td><td rowspan="2">광교중앙역 1번 출구</td><td rowspan="2">율곡관 건물 도로변</td></tr>
<tr><td>10:00</td></tr>
</table>"""
bus = tables_of(BUS)[0][0]
check("버스 표가 5행으로 읽힌다", len(bus) == 5)
check("09:50 행의 구분은 수원역이고 출발시각은 09:50이다(시각이 구분 칸으로 밀리지 않음)",
      bus[1]["구분"] == "수원역" and bus[1]["출발시각"] == "09:50")
check("11:20 행에도 출발장소·도착장소가 채워진다", bus[2]["출발장소"].startswith("수원역 9번") and bus[2]["도착장소"].startswith("율곡관"))
check("광교 중앙역 두 행이 모두 구분·장소를 갖는다", bus[3]["구분"] == bus[4]["구분"] == "광교 중앙역" and bus[4]["출발장소"] == "광교중앙역 1번 출구")

# ── 3) colspan, 열 이름 중복, 병합 칸 뒤쪽이 비는 경우 ──
rows = parse_table(BeautifulSoup("""<table><tr><th>이름</th><th>시간</th><th>비고</th><th>전화</th></tr>
<tr><td>카페</td><td colspan="2">24시간 운영</td><td>1234</td></tr></table>""", "html.parser").table)
check("colspan 칸은 병합된 칸 수만큼 반복된다", rows[0] == {"이름": "카페", "시간": "24시간 운영", "비고": "24시간 운영", "전화": "1234"})
rows = parse_table(BeautifulSoup("<table><tr><th>요금</th><th>요금</th></tr><tr><td>1</td><td>2</td></tr></table>", "html.parser").table)
check("열 이름이 겹치면 번호를 붙여 값이 덮이지 않는다", rows == [{"요금": "1", "요금(2)": "2"}])
rows = parse_table(BeautifulSoup("""<table><tr><th>a</th><th>b</th><th>c</th></tr>
<tr><td>A</td><td>B</td><td rowspan="2">C</td></tr><tr><td>X</td></tr></table>""", "html.parser").table)
check("병합 칸이 뒤쪽 열에 있고 앞쪽 칸이 모자라면 사이를 빈 칸으로 메운다", rows[1] == {"a": "X", "b": "", "c": "C"})

# ── 4) 표 제목 ──
PAGE = """<h1>아주대학교</h1><h2>체육시설</h2><table><tr><th>시간</th></tr><tr><td>1</td></tr></table>
<h3>헬스장</h3><table><tr><th>시간</th></tr><tr><td>07:00</td></tr></table>
<h3>GX</h3><table><tr><th>시간</th></tr><tr><td>월~금</td></tr></table>
<table><tr><th>요금</th></tr><tr><td>5만원</td></tr></table>
<table><caption>대관료 안내</caption><tr><th>구분</th></tr><tr><td>x</td></tr></table>"""
tabs, titles = tables_of(PAGE, "체육시설")
check("표 목록과 제목 목록의 길이가 같다", len(tabs) == len(titles) == 5)
check("제목이 페이지 이름과 같으면 비운다", titles[0] == "")
check("표 바로 앞의 제목이 표 제목이 된다", titles[1] == "헬스장" and titles[2] == "GX")
check("제목이 없는 두 번째 표는 같은 구역의 제목을 따른다", titles[3] == "GX")
check("caption이 있으면 caption이 제목이다", titles[4] == "대관료 안내")

# ── 5) 시설 레코드 만들기 ──
FAC = [
    {"page_name": "편의시설", "url": "u1", "tables": [[
        {"구분": "위치", "CU성호관점": "성호관 1층", "CU다산관점": "다산관 지하"},
        {"구분": "운영시간", "CU성호관점": "24시간", "CU다산관점": "09:00 ~ 18:00"}]]},
    {"page_name": "체육시설", "url": "u2", "tables": [[
        {"시간": "07:00 ~ 22:00", "요금 (1개월)": "학생 20,000원", "준비물": "운동복", "비고": ""}]], "table_titles": ["헬스장"]},
    {"page_name": "학교버스", "url": "u3", "tables": [[
        {"구분": "수원역", "출발시각": "08:15", "출발장소": "수원역 9번/10번 출구", "도착장소": "율곡관 입구"},
        {"구분": "수원역", "출발시각": "09:50", "출발장소": "수원역 9번/10번 출구", "도착장소": "율곡관 입구"}]], "table_titles": ["등교"]},
]
recs = load_facility_file(FAC)
by_title = {}
for r in recs:
    by_title.setdefault(r["article_title"], []).append(r)
check("편의시설은 업체별로 묶인다(업체 하나에 청크 하나)", "CU성호관점" in by_title and len(by_title["CU성호관점"]) == 1)
check("묶인 청크에 위치와 운영시간이 함께 들어간다", all(x in by_title["CU성호관점"][0]["text"] for x in ("위치: 성호관 1층", "운영시간: 24시간")))
gym = by_title.get("헬스장", [{}])[0].get("text", "")
check("체육시설 문장 앞에 시설 이름(표 제목)이 붙는다", gym.startswith("체육시설 헬스장 - 시간: 07:00 ~ 22:00"))
check("빈 값(비고)은 문장에 넣지 않는다", "비고" not in gym)
bus_recs = by_title.get("등교", [])
check("학교버스는 행 단위 문장이 된다(2행 = 2개)", len(bus_recs) == 2)
check("학교버스 문장에 구분·출발시각이 함께 들어간다", "구분: 수원역, 출발시각: 09:50" in bus_recs[1]["text"] and bus_recs[1]["text"].startswith("학교버스 등교 - "))
check("학교버스가 열 이름(출발시각 등)을 업체처럼 묶은 청크가 없다", not any(t in by_title for t in ("출발시각", "출발장소", "도착장소")))
old = load_facility_file([{"page_name": "체육시설", "url": "u", "tables": [[{"시간": "07:00"}]]}])
check("table_titles가 없는 옛 JSON도 처리한다", old[0]["text"] == "체육시설 - 시간: 07:00" and old[0]["article_title"] == "체육시설")
check("레코드에 임베딩이 읽는 필드가 모두 있다",
      all({"rule_name", "rule_id", "url", "effective_date", "article_no", "article_title", "text"} <= set(r) for r in recs))

# ── 6) 병합 머리글로 갈라진 '(2)' 열 처리 ──
DUP = [
    {"page_name": "편의시설", "url": "u4", "tables": [[
        {"구분": "위치", "올리브 홀딩스": "중앙도서관 1층", "올리브 홀딩스(2)": "제1학생회관 1층"},
        {"구분": "운영시간", "올리브 홀딩스": "08:00 ~ 18:00", "올리브 홀딩스(2)": "09:00 ~ 17:00"}]]},
    {"page_name": "편의시설", "url": "u5", "tables": [[
        {"구분": "운영시간", "A점": "10시", "A점(2)": "11시"}]]},
    {"page_name": "체육시설", "url": "u6", "tables": [[
        {"시간": "월 ~ 토", "시간(2)": "07:00 ~ 22:00", "요금 (1개월)": "20,000원",
         "양식 다운로드": "체육관 사용 허가 신청서", "양식 다운로드(2)": "다운로드 다운로드"},
        {"이용 요금": "대관료", "이용 요금(2)": "150,000원/1시간"}]], "table_titles": ["체육관"]},
]
drecs = load_facility_file(DUP)
titles = [r["article_title"] for r in drecs]
check("같은 업체 이름은 위치로 구분한다(중앙도서관)", "올리브 홀딩스 (중앙도서관 1층)" in titles)
check("같은 업체 이름은 위치로 구분한다(제1학생회관)", "올리브 홀딩스 (제1학생회관 1층)" in titles)
check("제목에 (2)가 남지 않는다", not any("(2)" in x for x in titles if x.startswith("올리브")))
lib = next(r for r in drecs if r["article_title"] == "올리브 홀딩스 (중앙도서관 1층)")["text"]
check("운영시간이 다른 매장 것과 섞이지 않는다", "08:00 ~ 18:00" in lib and "09:00 ~ 17:00" not in lib)
check("위치 행이 없으면 이름을 그대로 둔다", "A점" in titles and "A점(2)" in titles)
gym = [r["text"] for r in drecs if r["rule_id"] == "체육시설"]
check("시간과 시간(2)를 한 항목으로 합친다", "시간: 월 ~ 토 07:00 ~ 22:00" in gym[0] and "시간(2)" not in gym[0])
check("'요금 (1개월)' 같은 이름은 그대로 둔다", "요금 (1개월): 20,000원" in gym[0])
check("링크 글자만 있는 칸은 뺀다", "다운로드 다운로드" not in gym[0] and "양식 다운로드: 체육관 사용 허가 신청서" in gym[0])
check("이용 요금을 합친다", "이용 요금: 대관료 150,000원/1시간" in gym[1])

bad = [n for n, ok in checks if not ok]
print("\n전체 %d개 점검 %s" % (len(checks), "통과" if not bad else "중 실패 %d개" % len(bad)))
sys.exit(1 if bad else 0)
