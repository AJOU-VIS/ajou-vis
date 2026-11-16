"""시설 안내 페이지의 표 파서 (rowspan·colspan 처리, 표 제목 수집).

왜 필요한가
-----------
기존 파서는 colspan(가로 병합)만 처리하고 rowspan(세로 병합)은 처리하지 않아서, 앞 칸이 세로로 병합된
행은 칸이 하나씩 왼쪽으로 밀려 엉뚱한 열 이름에 값이 들어갔다
(예: 학교버스 표의 "구분" 칸에 출발시각이 들어감, 체육시설 표의 "층별" 칸에 종목이 들어감).
또 시설 이름은 표 안이 아니라 표 위의 제목에 있는데 수집하지 않아서, 체육시설 안내 조각에 시설 이름이 없었다.

동작
----
- expand_table: 병합된 칸을 반복해서 채워 행마다 칸 수가 같은 격자로 펼친다.
- parse_table: 격자를 [{열 이름: 값}] 으로 바꾼다. 첫 행에 th가 있으면 열 이름으로 쓴다.
- table_title: 표의 caption, 없으면 표 바로 앞의 제목 태그(h1~h6) 텍스트. 페이지 이름과 같으면 비운다.
- parse_page_tables: (표 목록, 표 제목 목록)을 돌려준다. 두 목록의 길이는 같다.
- requests·selenium 없이 beautifulsoup4만 있으면 동작한다 (시험: test_facility_tables.py).
"""
import re

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def _text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _span(cell, name):
    try:
        return max(int(cell.get(name) or 1), 1)
    except ValueError:
        return 1


def expand_table(table):
    """표를 병합 없는 격자(행마다 칸 수가 같은 목록의 목록)로 펼친다."""
    grid, pending = [], {}                       # pending: 열 번호 -> [아래로 더 이어질 행 수, 텍스트]
    for tr in table.find_all("tr"):
        cells = [c for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr]   # 중첩 표의 칸은 제외
        row, col, ci = [], 0, 0
        while True:
            if col in pending:                    # 위 행에서 세로로 병합돼 내려온 칸
                left, text = pending[col]
                row.append(text)
                if left > 1:
                    pending[col] = [left - 1, text]
                else:
                    del pending[col]
                col += 1
            elif ci < len(cells):
                cell = cells[ci]
                ci += 1
                text = _text(cell)
                rs, cs = _span(cell, "rowspan"), _span(cell, "colspan")
                for _ in range(cs):
                    row.append(text)
                    if rs > 1:
                        pending[col] = [rs - 1, text]
                    col += 1
            elif any(c > col for c in pending):   # 뒤쪽 열에 이어지는 병합 칸이 있으면 사이를 빈 칸으로 메운다
                row.append("")
                col += 1
            else:
                break
        grid.append(row)
    return grid


def _unique(names):
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else "%s(%d)" % (n, seen[n]))
    return out


def parse_table(table):
    """table 태그 하나를 [{열 이름: 값, ...}, ...] 로 바꾼다."""
    grid = expand_table(table)
    if not grid:
        return []
    first_tr = table.find("tr")
    if first_tr is not None and first_tr.find("th"):
        headers, data = _unique(grid[0]), grid[1:]
    else:
        headers, data = ["칸%d" % (i + 1) for i in range(len(grid[0]))], grid
    rows = []
    for row in data:
        if not any(row):
            continue
        rows.append({h: row[i] for i, h in enumerate(headers) if i < len(row)})
    return rows


def table_title(table, page_name=""):
    """표 제목: caption → 표 바로 앞의 제목 태그. 페이지 이름과 같으면 비운다."""
    cap = table.find("caption")
    if cap is not None and _text(cap):
        return _text(cap)
    head = table.find_previous(HEADING_TAGS)
    title = _text(head) if head is not None else ""
    return "" if title == page_name else title


def parse_page_tables(soup, page_name=""):
    """페이지의 모든 표를 (표 목록, 표 제목 목록)으로 돌려준다."""
    tables = soup.find_all("table")
    return [parse_table(t) for t in tables], [table_title(t, page_name) for t in tables]
