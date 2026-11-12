"""학칙 부칙(경과 조치) 파서.

왜 필요한가
-----------
학칙 본문(제50조)은 현행 기준만 적고, 학번별 예외는 부칙의 경과 조치에 있다.
예) 부칙 <기획팀-2271호 : 2025.1.31.> 제6조 — 소프트웨어학과 졸업학점 변경은 2025학년도
    신입학생부터 적용하고 2024학년도 이전 입학생은 개정 이전의 규칙(140학점)을 적용한다.
rules_crawler.py는 부칙을 조항 분할 전에 잘라내고 있어서 이런 예외가 코퍼스에 없었다.

동작
----
- "부 칙 <기획팀-2271호 : 2025.1.31.>" 헤더로 부칙을 나누고, 안의 "제N조(제목)" 항목을 하나씩 뽑는다.
- 학생에게 적용되는 내용(졸업학점·학사경고·성적·학점·수강신청 등)이 있는 항목만 남긴다.
  대학원 학과 신설 같은 항목까지 넣으면 검색에 잡음이 늘어난다.
- 결과는 rules_crawler의 조항과 같은 형식(article_no, article_title, text)이라 embed_corpus.py를 고칠 필요가 없다.
- selenium 없이 텍스트만으로 동작한다 (시험: test_addenda_parser.py).
"""
import re

# 헤더: "부 칙 <기획팀-2271호 : 2025.1.31.>", "부 칙<기획팀-469호 : 2024.4.26.>", "기획팀–706호"(긴 하이픈) 모두 허용
ADDENDA_HEADER = re.compile(
    r"부\s*칙\s*<\s*([^<>:：]+?)\s*[:：]\s*(\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?)\s*>")
# 항목: 줄 맨 앞의 "제6조(제목)". 줄바꿈이 사라진 텍스트에는 아래 ITEM_ANY를 대신 쓴다.
ITEM_LINE = re.compile(r"(?m)^[ \t]*(제\d+조(?:의\d+)?)\(([^)\n]+)\)")
ITEM_ANY = re.compile(r"(?<![가-힣0-9])(제\d+조(?:의\d+)?)\(([^)\n]+)\)")

DEFAULT_KEYWORDS = ("졸업학점", "학사경고", "성적", "학점", "수강신청", "졸업요건", "조기졸업", "학사과정")
MAX_CHARS = 1500   # 마지막 부칙 뒤에 페이지 바닥글이 붙어도 한 항목이 너무 길어지지 않게


def _squash(s):
    return re.sub(r"\s+", "", s)


def parse_addenda(page_text, keywords=DEFAULT_KEYWORDS, max_chars=MAX_CHARS):
    """(항목 목록, 키워드가 없어 제외한 개수)를 돌려준다."""
    heads = list(ADDENDA_HEADER.finditer(page_text))
    found, dropped = {}, 0
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(page_text)
        body = page_text[h.end():end]
        doc_no, date = _squash(h.group(1)), _squash(h.group(2))
        items = list(ITEM_LINE.finditer(body))
        if len(items) <= 1:                       # 줄바꿈이 없는 텍스트면 위치 기준을 느슨하게
            loose = list(ITEM_ANY.finditer(body))
            if len(loose) > len(items):
                items = loose
        for j, m in enumerate(items):
            e = items[j + 1].start() if j + 1 < len(items) else len(body)
            text = body[m.start():e].strip()[:max_chars]
            title = m.group(2).strip()
            if not any(k in title + text for k in keywords):
                dropped += 1
                continue
            article_no = "부칙(%s, %s) %s" % (date, doc_no, m.group(1))
            rec = {"article_no": article_no, "article_title": title,
                   "text": "부칙 <%s : %s> %s" % (doc_no, date, text)}
            old = found.get(article_no)           # 같은 부칙이 페이지에 두 번 나오면 긴 쪽만 남긴다
            if old is None or len(rec["text"]) > len(old["text"]):
                found[article_no] = rec
    return list(found.values()), dropped
