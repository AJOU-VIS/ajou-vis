"""실시간 좌석 정보 조회 (프롬프트 계약 ②와 동일한 형식으로 반환).

좌석은 분 단위로 바뀌는 데이터라 벡터DB(ChromaRetriever)에 넣지 않고,
질문이 들어올 때마다 도서관 API를 직접 호출해 최신 값을 가져온다.
rag.format_context()와 같은 "[출처: ...] 내용" 형식 문자열을 반환해서,
app.py가 규정 검색 결과와 동일한 방식으로 다룰 수 있게 한다.

행사 일정·캠퍼스 시설은 (분·시간 단위로 바뀌지 않아) 이 모듈 대상이 아니다 —
embed_corpus.py를 통해 규정과 같은 벡터DB에 포함되어 ChromaRetriever로 검색된다.
"""
from __future__ import annotations

import requests

API_URL = "https://library.ajou.ac.kr/pyxis-api/1/seat-rooms"
API_PARAMS = {"smufMethodCode": "PC", "branchGroupId": 1}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
SOURCE_NAME = "아주대학교 중앙도서관 좌석현황"


def _find_rooms(payload) -> list[dict]:
    """library_seats_crawler.py와 동일한 재귀 탐색: 'seats' 필드를 가진
    딕셔너리들의 리스트를 응답 어디에 있든 찾아낸다."""
    def looks_like_room_list(node) -> bool:
        return (
            isinstance(node, list) and len(node) > 0
            and isinstance(node[0], dict) and "seats" in node[0]
        )

    def search(node):
        if looks_like_room_list(node):
            return node
        if isinstance(node, dict):
            for v in node.values():
                found = search(v)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = search(item)
                if found is not None:
                    return found
        return None

    return search(payload) or []


def fetch_seat_status(timeout: float = 5.0) -> list[dict]:
    """도서관 좌석 API를 호출해 방 목록을 반환한다.
    음성 응답 지연에 영향을 주므로 timeout을 짧게 둔다 — 실패하면 빈 리스트,
    호출한 쪽(format_seat_context)이 이를 '정보 없음'으로 처리한다."""
    response = requests.get(API_URL, params=API_PARAMS, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return _find_rooms(response.json())


def format_seat_context() -> str:
    """rag.format_context()와 동일한 형식의 문자열로 좌석 현황을 반환한다.
    API 호출 실패 시 빈 문자열을 반환 — gate.passes()가 빈 컨텍스트를
    '근거 없음'으로 처리해 자동으로 보류 응답으로 이어지게 한다."""
    try:
        rooms = fetch_seat_status()
    except Exception:
        return ""

    lines = []
    for room in rooms:
        seats = room.get("seats", {})
        name = room.get("name", "열람실")
        available = seats.get("available")
        total = seats.get("total")
        if available is None or total is None:
            continue
        lines.append(f"[출처: {SOURCE_NAME}] {name} 잔여석 {available}/{total}석")

    return "\n".join(lines)
