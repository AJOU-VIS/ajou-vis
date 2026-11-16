"""규정 조항이 여러 조각으로 쪼개질 때, 조각마다 규정명·조문 번호·제목을 앞에 붙인다.

문제: 조문이 450자 넘게 쪼개지면 두 번째 조각부터는 '제47조(학사경고, 유급)' 같은 머리말이 없다.
그러면 같은 조문의 뒷부분("2. 약학과 …")이 앞부분(1.75 미만)보다 먼저 검색되거나(X4),
정답이 든 앞 조각 대신 뒷 조각만 걸린다(B3). 머리말을 붙이면 어느 규정·조문의 조각인지가 임베딩에 반영된다.
조항 번호가 없는 레코드(학사 안내 페이지·행사·시설)는 이미 제목 경로나 이름이 붙어 있어 건드리지 않는다.
"""


def with_context(article: dict, piece: str) -> str:
    article_no = (article.get("article_no") or "").strip()
    if not article_no:
        return piece
    rule_name = (article.get("rule_name") or "").strip()
    title = (article.get("article_title") or "").strip()
    header = "%s(%s)" % (article_no, title) if title else article_no
    if piece.lstrip().startswith(article_no):
        prefix = rule_name                      # 조각이 이미 조문 머리말로 시작하면 규정명만 붙인다
    else:
        prefix = ("%s %s" % (rule_name, header)).strip()
    return ("%s %s" % (prefix, piece.lstrip())).strip() if prefix else piece
