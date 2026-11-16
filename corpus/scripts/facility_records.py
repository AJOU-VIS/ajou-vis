"""시설 JSON(campus_facility_crawler 결과)을 임베딩용 공통 레코드로 바꾼다 (embed_corpus.py에서 분리).

두 가지 표를 다르게 다룬다.
- 편의시설류: "구분"(위치/운영시간 등)을 행으로, 업체명(CU성호관점 등)을 칸으로 나열한 표. 행 그대로 한 문장으로
  합치면 "CU" 같은 업체명이 다른 업체 이름들 틈에 묻혀 검색에서 밀려서(실측 확인됨), 업체 하나당 청크 하나로 다시 묶는다.
- 그 밖(체육시설, 학교버스 등): 행 하나가 곧 한 항목이라 행 단위 문장으로 만든다. 표 제목(시설 이름)이 있으면
  문장 앞에 붙인다. 학교버스 표에도 "구분" 칸이 있는데, 편의시설처럼 묶으면 "출발시각"이 업체 이름처럼 취급돼
  엉뚱한 청크가 만들어지므로, 업체별 묶기는 ENTITY_PAGES에 적힌 페이지에만 쓴다.
"""

import re

ENTITY_PAGES = ("편의시설",)
_DUP = re.compile(r"^(.*?)\s*\((\d+)\)$")        # '올리브 홀딩스(2)', '시간(2)'
_LINK_ONLY = re.compile(r"^(다운로드\s*)+$")        # '다운로드 다운로드'처럼 링크 글자만 있는 칸


def _base(key, keys):
    """'이름(2)'는 같은 표에 '이름'이 있을 때만 '이름'으로 본다. 아니면 그대로(예: '요금 (1개월)')."""
    m = _DUP.match(key)
    return m.group(1) if m and m.group(1) in keys else key


def _entity_labels(table):
    """같은 업체 이름이 여러 칸이면 '위치' 행으로 구분한다: '올리브 홀딩스 (중앙도서관 1층)'.
    위치 행이 없으면 이름을 그대로 둔다."""
    keys = [k for k in table[0] if k != "구분"]
    names = set(keys)
    groups = {}
    for k in keys:
        groups.setdefault(_base(k, names), []).append(k)
    place = next((r for r in table if "위치" in r.get("구분", "")), None)
    labels = {}
    for base, members in groups.items():
        if len(members) < 2 or place is None:
            continue
        for k in members:
            where = str(place.get(k, "")).strip()
            if where:
                labels[k] = "%s (%s)" % (base, where)
    return labels, {k: _base(k, names) for k in keys}


def _merge_duplicate_columns(row):
    """병합 머리글이 두 칸으로 갈라진 것('시간', '시간(2)')을 한 항목으로 합친다. 링크 글자만 있는 칸은 뺀다."""
    names = set(row)
    merged = {}
    for k, v in row.items():
        v = str(v).strip()
        if not v or _LINK_ONLY.match(v):
            continue
        merged.setdefault(_base(k, names), []).append(v)
    return [(k, " ".join(vs)) for k, vs in merged.items()]


def _record(page, title, text):
    return {
        "rule_name": "아주대학교 %s" % page["page_name"],
        "rule_id": page["page_name"],
        "url": page["url"],
        "effective_date": None,
        "article_no": None,
        "article_title": title,
        "text": text,
    }


def load_facility_file(data):
    records = []
    for page in data:
        page_name = page["page_name"]
        titles = page.get("table_titles") or []          # 옛 JSON에는 없을 수 있다
        for ti, table in enumerate(page.get("tables", [])):
            if not table:
                continue
            title = titles[ti] if ti < len(titles) else ""
            if page_name in ENTITY_PAGES and "구분" in table[0]:
                entities = {}                            # {업체명: ["위치: ...", "운영시간: ...", ...]}
                labels, _ = _entity_labels(table)
                for row in table:
                    label = row.get("구분", "")
                    for key, value in row.items():
                        if key == "구분":
                            continue
                        entities.setdefault(labels.get(key, key), []).append("%s: %s" % (label, value) if label else str(value))
                for entity_name, parts in entities.items():
                    kind = page_name + (" · " + title if title else "")   # 예: '편의시설 · 교내 편의점에 관한 내용'
                    records.append(_record(page, entity_name, "%s (%s) - %s" % (entity_name, kind, ", ".join(parts))))
            else:
                head = page_name + (" " + title if title else "")
                for row in table:
                    items = _merge_duplicate_columns(row)
                    if not items:
                        continue
                    sentence = ", ".join("%s: %s" % (k, v) for k, v in items)
                    records.append(_record(page, title or page_name, "%s - %s" % (head, sentence)))
    return records
