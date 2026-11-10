"""AI 매칭 '인수 여력' 점수용 재무 수집 → cash_cache.json
상장사 전체의 최근 사업연도 전체 재무제표(fnlttSinglAcntAll, 연결 우선 → 없으면 별도)에서
현금성 자산(현금·단기금융상품), 영업현금흐름, EBITDA(영업이익+감가상각), 차입금을 억원 단위로 저장한다.
이미 받은 회사는 건너뛰므로 여러 번 나눠 돌려도 된다. 공시(공개) 재무만 저장한다.
"""
import os
import re
import json
import time
import datetime as dt
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from fetch_peers import API_KEY, load_corp_map, fetch_fin, extract_metrics, parse_amt, norm_nm

OUT = "cash_cache.json"
YEAR = int(os.environ.get("CASH_YEAR") or (dt.date.today().year - 1))
WORKERS = 5
BUDGET = 80 * 60
EOK = 1e8
_lock = threading.Lock()
status = Counter()


def ocf_of(rows):
    for r in rows:
        if (r.get("sj_div") or "") != "CF":
            continue
        aid = (r.get("account_id") or "").strip()
        nm = norm_nm(r.get("account_nm"))
        if aid == "ifrs-full_CashFlowsFromUsedInOperatingActivities" or nm.startswith("영업활동") and "현금흐름" in nm and "이자" not in nm:
            v = parse_amt(r.get("thstrm_amount"))
            if v is not None:
                return v
    return None


def r1(v):
    return None if v is None else round(v / EOK, 1)


def main():
    if not API_KEY:
        print("DART_API_KEY가 없어 수집하지 않습니다.")
        return
    try:
        cache = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        cache = {"year": YEAR, "c": {}}
    if cache.get("year") != YEAR:
        cache = {"year": YEAR, "c": {}}
    cm = load_corp_map()
    todo = [(s, c) for s, (c, _) in cm.items() if s not in cache["c"]]
    print(f"사업연도 {YEAR}, 상장사 {len(cm)}곳 중 남은 {len(todo)}곳")
    t0 = time.time()
    done = [0]

    def work(a):
        stock, corp = a
        if time.time() - t0 > BUDGET:
            return
        rows, fs = fetch_fin(corp, YEAR)
        with _lock:
            done[0] += 1
            if done[0] % 300 == 0:
                print(f"  {done[0]}/{len(todo)} ({time.time() - t0:.0f}초)", flush=True)
        if not rows:
            with _lock:
                status["없음"] += 1
                cache["c"][stock] = None
            return
        m = extract_metrics(rows)
        ebitda = (m["op"] + (m["da"] or 0)) if m["op"] is not None else None
        rec = [r1(m["cash"]), r1(ocf_of(rows)), r1(ebitda), r1(m["debt"]), fs]
        with _lock:
            status["ok"] += 1
            cache["c"][stock] = rec
        time.sleep(0.05)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))
    cache["updated"] = dt.date.today().isoformat()
    json.dump(cache, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    have = sum(1 for v in cache["c"].values() if v)
    print(f"이번 실행 {dict(status)}, 누적 재무 확보 {have}곳 / 기록 {len(cache['c'])}곳, 소요 {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
