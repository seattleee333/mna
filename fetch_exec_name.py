"""상장사 임원현황(사업보고서)에서 특정 이름의 임원을 찾는다.

- 자료: DART 임원현황(exctvSttus). 최근 사업연도 사업보고서, 없으면 직전 연도.
- 결과: exec_name_<이름>.json (이름이 일치한 사람만 저장)
"""
import os
import re
import json
import time
import datetime as dt
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests

from fetch_peers import load_corp_map

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
NAME = (os.environ.get("EXEC_NAME") or "김동환").strip()
YEARS = [dt.date.today().year - 1, dt.date.today().year - 2]
WORKERS = 5
OUT = f"exec_name_{NAME}.json"

_lock = threading.Lock()
found = []
status = Counter()


def fetch_one(stock, corp_code, name):
    for year in YEARS:
        last = None
        for attempt in range(4):
            try:
                r = requests.get(BASE + "exctvSttus.json", params={
                    "crtfc_key": API_KEY, "corp_code": corp_code, "bsns_year": str(year), "reprt_code": "11011"}, timeout=30)
                j = r.json()
                st = j.get("status")
                if st == "020":
                    time.sleep(5 * (attempt + 1))
                    last = st
                    continue
                break
            except Exception as e:
                last = type(e).__name__
                time.sleep(1 + attempt)
                j, st = None, None
        else:
            with _lock:
                status["error:" + str(last)] += 1
            return
        with _lock:
            status[st] += 1
        if st == "013":      # 데이터 없음 → 직전 연도 시도
            continue
        if st != "000":
            return
        got = []
        for it in j.get("list") or []:
            if re.sub(r"\s+", "", it.get("nm") or "") == NAME:
                got.append({
                    "company": it.get("corp_name") or name, "stock": stock, "cls": it.get("corp_cls"),
                    "nm": it.get("nm"), "ofcps": (it.get("ofcps") or "").strip(),
                    "registered": (it.get("rgist_exctv_at") or "").strip(),
                    "job": (it.get("chrg_job") or "").strip(), "birth": (it.get("birth_ym") or "").strip(),
                    "sex": (it.get("sexdstn") or "").strip(), "career": (it.get("main_career") or "").strip()[:200],
                    "tenure_end": (it.get("tenure_end_on") or "").strip(), "year": year, "rcept": it.get("rcept_no") or "",
                })
        with _lock:
            found.extend(got)
        return


def main():
    if not API_KEY:
        print("DART_API_KEY가 없어 수집하지 않습니다.")
        return
    corp_map = load_corp_map()
    todo = [(s, c, n) for s, (c, n) in corp_map.items()]
    print(f"상장사 {len(todo)}곳, 찾는 이름 {NAME}")
    t0 = time.time()
    done = [0]

    def work(a):
        fetch_one(*a)
        done[0] += 1
        if done[0] % 300 == 0:
            print(f"  {done[0]}/{len(todo)} ({time.time() - t0:.0f}초)", flush=True)
        time.sleep(0.05)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))
    found.sort(key=lambda x: (x["company"], x["ofcps"]))
    res = {"name": NAME, "years": YEARS, "status": dict(status), "count": len(found), "list": found,
           "updated": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y-%m-%d")}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"일치 {len(found)}명, 상태 {dict(status)}, 소요 {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
