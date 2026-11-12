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
- 페이지에는 부칙 뒤(또는 앞)에 개정 조문 목록 같은 "제42조(…)" 줄이 더 붙어 있다. 부칙 항목은 제1조 부근의
  작은 번호에서 시작해 조금씩 늘어나는 번호이므로, 번호가 크게 뛰거나 늘지 않으면 거기서 멈춰 그 뒤 조문이
  부칙으로 섞이지 않게 한다. (삭제된 조가 있으면 번호가 건너뛸 수 있어 MAX_GAP까지는 허용한다.)
- selenium 없이 텍스트만으로 동작한다 (시험: test_addenda_parser.py).
"""
import re

# 헤더: "부 칙 <기획팀-2271호 : 2025.1.31.>", "부 칙<기획팀-469호 : 2024.4.26.>", "기획팀–706호"(긴 하이픈) 모두 허용
ADDENDA_HEADER = re.compile(
    r"부\s*칙\s*<\s*([^<>:：]+?)\s*[:：]\s*(\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?)\s*>")
# 항목: 줄 맨 앞의 "제6조(제목)". 줄바꿈이 사라진 텍스트에는 아래 ITEM_ANY를 대신 쓴다.
ITEM_LINE = re.compile(r"(?m)^[ \t]*(제\d+조(?:의\d+)?)\(([^)\n]+)\)")
ITEM_ANY = re.compile(r"(?<![가-힣0-9])(제\d+조(?:의\d+)?)\(([^)\n]+)\)")

DEFAULT_KEYWORDS = ("졸업학점", "학사경고", "성적", "학점", "수강신청", "졸업요건", "조기졸업", "학사과정",
                    "제45조", "제46조", "제47조", "제50조", "제51조")   # 학점인정·성적·학사경고·졸업요건·조기졸업 조문을 가리키는 부칙
FIRST_MAX = 3      # 부칙 첫 항목은 제1조(시행일) 부근이다
MAX_GAP = 3        # 다음 항목 번호는 앞 번호보다 크고 이 값 이하로만 건너뛴다
MAX_CHARS = 1500   # 마지막 부칙 뒤에 페이지 바닥글이 붙어도 한 항목이 너무 길어지지 않게


def _squash(s):
    return re.sub(r"\s+", "", s)


def _number(label):
    """'제6조' -> (6, 0), '제44조의2' -> (44, 2)"""
    m = re.match(r"제(\d+)조(?:의(\d+))?", label)
    return int(m.group(1)), int(m.group(2) or 0)


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
        valid, prev = [], 0                       # 부칙 항목은 작은 번호에서 시작해 조금씩 늘어난다
        for m in items:
            no, sub_no = _number(m.group(1))
            ok = sub_no == 0 and ((not valid and no <= FIRST_MAX) or (valid and prev < no <= prev + MAX_GAP))
            if not ok:                            # 번호가 크게 뛰거나 늘지 않으면 부칙이 아닌 조문(개정 조문 목록 등)
                break
            valid.append(m)
            prev = no
        tail_end = items[len(valid)].start() if len(valid) < len(items) else len(body)
        for j, m in enumerate(valid):
            e = valid[j + 1].start() if j + 1 < len(valid) else tail_end   # 마지막 항목은 끊긴 지점까지만
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
