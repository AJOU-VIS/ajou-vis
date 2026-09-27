"""
AJOU-VIS 도서관 좌석 현황 크롤러
============================================
대상: 아주대 중앙도서관 좌석 현황 API (pyxis-api)
목표: 열람실별 잔여석/전체석 현황을 JSON으로 저장한다.

동작 방식
---------
도서관 홈페이지(library.ajou.ac.kr) 좌석현황 위젯이 내부적으로 호출하는
API를 브라우저 개발자도구(Network 탭)로 직접 확인해 찾아낸 엔드포인트다.
로그인 없이 접근 가능하며, 화면을 렌더링할 필요가 없어 Selenium 없이
requests만으로 충분하다.

다른 크롤러(rules_crawler.py)와의 차이점
---------
학칙·규정은 자주 안 바뀌는 "정적" 정보라 한 번 크롤링해두면 오래 쓸 수
있지만, 좌석 현황은 실시간으로 계속 바뀌는 정보다. 그래서:
- 결과 JSON에 "조회 시각(fetched_at)"을 반드시 남긴다
- 벡터DB에 넣어 의미 기반 검색을 할 대상이 아니라, RAG 서버가 질문 시점에
  직접 조회해서 최신 숫자를 answer에 넣는 방식이 더 적합할 수 있다
  (이 부분은 서버 설계 논의가 필요 — docs 참고)
- 나중에 자동 갱신(예: GitHub Actions 주기 실행)을 붙이기 좋도록
  한 번 실행하면 끝나는 단순한 구조로 만들었다

실행 방법
---------
pip install requests
python library_seats_crawler.py
결과는 output/library_seats.json 에 저장됨
"""

from __future__ import annotations  # Python 3.9에서도 dict | list 같은 표기 쓰기 위함

import json
from datetime import datetime
from pathlib import Path

import requests

API_URL = "https://library.ajou.ac.kr/pyxis-api/1/seat-rooms"
API_PARAMS = {"smufMethodCode": "PC", "branchGroupId": 1}

# 일반 브라우저처럼 보이도록 최소한의 헤더만 지정 (API가 기본 요청도 잘 받아주지만,
# 혹시 몰라 User-Agent 정도는 넣어둔다)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def fetch_seat_status() -> dict | list:
    """도서관 좌석 현황 API를 호출해서 원본 응답(JSON)을 그대로 반환한다.
    최상위가 배열인지, {"rooms": [...]} 처럼 감싸져 있는지는
    extract_rooms()에서 알아서 처리한다."""
    response = requests.get(API_URL, params=API_PARAMS, headers=HEADERS, timeout=10)
    response.raise_for_status()  # 200이 아니면 여기서 바로 에러 발생 (로그인 필요 등)
    return response.json()


def extract_rooms(payload: dict | list) -> list[dict]:
    """API 응답 어딘가에 있는 '방(room) 목록'을 재귀적으로 찾아낸다.
    응답이 몇 겹으로 감싸져 있는지 몰라도, "seats" 필드를 가진 딕셔너리들의
    리스트를 발견하면 그게 방 목록이라고 판단한다 (화면에서 확인한 실제
    구조: 각 방 항목에 반드시 "seats": {...} 가 있음)."""

    def looks_like_room_list(node) -> bool:
        return (
            isinstance(node, list)
            and len(node) > 0
            and isinstance(node[0], dict)
            and "seats" in node[0]
        )

    def search(node):
        if looks_like_room_list(node):
            return node
        if isinstance(node, dict):
            for value in node.values():
                found = search(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = search(item)
                if found is not None:
                    return found
        return None

    result = search(payload)
    if result is not None:
        return result

    # 여기까지 왔으면 못 찾은 것 -> 사람이 보고 바로 알 수 있게 구조를 남긴다
    preview = json.dumps(payload, ensure_ascii=False, indent=2)[:1000]
    raise ValueError(
        "응답에서 'seats' 필드를 가진 방 목록을 찾지 못했습니다.\n"
        "아래 응답 미리보기를 보고 방 목록이 실제로 어디 있는지 확인하세요:\n"
        f"{preview}"
    )


def normalize(rooms: list[dict]) -> dict:
    """API 원본 응답에서 우리한테 필요한 필드만 뽑아 정리한다.
    나중에 API 응답 구조가 조금 바뀌어도 이 함수만 손보면 되도록
    변환 로직을 한곳에 모아둔다."""
    normalized_rooms = []
    for room in rooms:
        seats = room.get("seats", {})
        normalized_rooms.append({
            "room_id": room.get("id"),
            "room_name": room.get("name"),
            "floor": room.get("floor"),
            "total": seats.get("total"),
            "occupied": seats.get("occupied"),
            "available": seats.get("available"),
            "unavailable": seats.get("unavailable"),
            "waiting": seats.get("waiting"),
        })

    return {
        "source": "아주대학교 중앙도서관 좌석현황",
        "url": "https://library.ajou.ac.kr/",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "rooms": normalized_rooms,
    }


def main():
    print("[조회 시작] 도서관 좌석 현황 API")
    raw_payload = fetch_seat_status()
    rooms = extract_rooms(raw_payload)
    result = normalize(rooms)

    print(f"[조회 완료] 열람실 {len(result['rooms'])}개")
    for room in result["rooms"]:
        print(f"  - {room['room_name']}: 잔여석 {room['available']}/{room['total']}")

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "library_seats.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[저장 완료] {out_path}")


if __name__ == "__main__":
    main()
