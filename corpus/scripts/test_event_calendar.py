"""event_calendar_crawler 의 순수 로직(시작 날짜, 중복 제거, 병합) 점검. 학교 사이트에는 접속하지 않는다.
실행: python corpus/scripts/test_event_calendar.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import event_calendar_crawler as c

fails = 0
total = 0
def check(name, cond):
    global fails, total
    total += 1
    print(("통과 " if cond else "실패 ") + name)
    fails += 0 if cond else 1

mid = {"category": "학사", "content": "2학기 중간시험", "period": "10-20 ~ 10-26"}
fin = {"category": "학사", "content": "2학기 기말시험", "period": "12-08 ~ 12-14"}

# 1. 시작 날짜: 한국 시간 오늘에서 7일 전
now = datetime(2026, 11, 18, 5, 0, tzinfo=c.KST)
check("시작 날짜는 오늘(한국 시간) 7일 전", c.default_start_date(now) == "2026-11-11")

# 2. 중복 제거: (구분, 내용, 기간) 같으면 하나, date 필드는 버린다
d = c.dedupe([{**mid, "date": "2026-10-20(화)"}, {**mid, "date": "2026-10-21(수)"}])
check("같은 일정은 하나만 남는다", len(d) == 1)
check("결과에 date 필드가 없다", "date" not in d[0])

# 3. 병합: 지난 일정은 남고 새 일정이 더해진다
m = c.merge_events([mid], [fin])
check("지난 일정(중간시험)이 남는다", mid in m)
check("새 일정(기말시험)이 더해진다", fin in m)
check("기존 순서 유지, 새 항목은 뒤에", m == [mid, fin])

# 4. 병합: 겹치는 일정은 중복되지 않는다
m = c.merge_events([mid, fin], [fin, mid])
check("겹치는 일정은 중복되지 않는다", len(m) == 2)

# 5. 병합: 기간이 바뀐 일정은 새 항목으로 더해진다 (공지 변경 반영, 옛 값도 남음)
fin2 = {**fin, "period": "12-09 ~ 12-15"}
m = c.merge_events([fin], [fin2])
check("기간이 바뀐 일정은 둘 다 남는다", len(m) == 2 and fin2 in m)

# 6. 병합: 기존 파일이 비어 있어도 동작
check("기존이 비어 있어도 병합된다", c.merge_events([], [mid]) == [mid])

# 7. 가져온 일정이 0개면 기존 파일을 덮어쓰지 않고 실패로 끝난다 (접속 차단·구조 변경 대비)
import json, tempfile
tmp = Path(tempfile.mkdtemp()) / "events.json"
tmp.write_text(json.dumps([mid]), encoding="utf-8")
orig = c.crawl_events
c.crawl_events = lambda start, periods: []
try:
    c.main(["--out", str(tmp), "--weeks", "1"])
    exited = False
except SystemExit as e:
    exited = e.code == 1
c.crawl_events = orig
check("0개면 실패 종료(코드 1)", exited)
check("0개면 기존 파일 그대로", json.loads(tmp.read_text(encoding="utf-8")) == [mid])

# 8. 정상 실행: 기존 일정에 새 일정이 더해져 저장된다
c.crawl_events = lambda start, periods: [{**fin, "date": "2026-12-08(화)"}]
c.main(["--out", str(tmp), "--weeks", "1"])
c.crawl_events = orig
saved = json.loads(tmp.read_text(encoding="utf-8"))
check("저장 결과에 기존+새 일정이 모두 있다", saved == [mid, fin])

print("\n전체 %d개 점검 %s" % (total, "통과" if not fails else "중 %d개 실패" % fails))
sys.exit(1 if fails else 0)
