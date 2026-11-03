"""코스피·코스닥 상장사 대표이사 보수 상위 순위 (사업보고서 '개인별 보수지급금액(5억원 이상 상위 5인)').

- 대상: 상장사 전체(종목코드 있는 법인), 최근 사업연도 사업보고서
- 자료: 공시된 보수총액(급여·상여·퇴직소득 등 포함, 주식매수선택권 행사이익 등은 회사별로 다름)
- 결과: exec_pay_<연도>.json 에 순위표만 저장한다(회사별 원자료는 저장하지 않음).
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

from fetch_peers import load_corp_map, parse_amt

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
YEAR = int(os.environ.get("PAY_YEAR") or (dt.date.today().year - 1))
TOP = 50
WORKERS = 5
DEBUG_FILE = "exec_pay_debug.txt"
OUT = f"exec_pay_{YEAR}.json"

RE_CEO = re.compile(r"대표|CEO", re.I)
RE_TOP = re.compile(r"대표|CEO|회장|(?<!부)사장", re.I)

_lock = threading.Lock()
rows = []            # 5억원 이상 보수를 받은 모든 사람 (메모리에서만 사용)
status = Counter()
sample_keys = []


def fetch_one(stock, corp_code, name):
    last = None
    for attempt in range(4):
        try:
            r = requests.get(BASE + "indvdlByPay.json", params={
                "crtfc_key": API_KEY, "corp_code": corp_code, "bsns_year": str(YEAR), "reprt_code": "11011"}, timeout=30)
            j = r.json()
            st = j.get("status")
            if st == "020":          # 요청 제한 초과: 잠시 쉬고 다시
                time.sleep(5 * (attempt + 1))
                last = st
                continue
            with _lock:
                status[st] += 1
            if st != "000":
                return
            got = []
            for it in j.get("list") or []:
                pay = parse_amt(it.get("mendng_totamt"))
                if pay is None:
                    continue
                excl = parse_amt(it.get("mendng_totamt_ct_incls_mendng"))
                got.append({
                    "nm": (it.get("nm") or "").strip(), "pos": (it.get("ofcps") or "").strip(),
                    "pay": pay, "excl": excl, "cls": (it.get("corp_cls") or "").strip(),
                    "co": (it.get("corp_name") or name), "stock": stock, "rcept": it.get("rcept_no") or "",
                })
            with _lock:
                if got and not sample_keys:
                    sample_keys.extend(sorted((j.get("list") or [{}])[0].keys()))
                rows.extend(got)
            return
        except Exception as e:
            last = type(e).__name__
            time.sleep(1 + attempt)
    with _lock:
        status["error:" + str(last)] += 1


def market_of(cls):
    return {"Y": "KOSPI", "K": "KOSDAQ"}.get(cls)


def rank(items, market, regex):
    pick = [x for x in items if market_of(x["cls"]) == market and regex.search(x["pos"])]
    pick.sort(key=lambda x: -x["pay"])
    out = []
    for i, x in enumerate(pick[:TOP], 1):
        out.append({
            "rank": i, "name": x["nm"], "company": x["co"], "stock": x["stock"], "pos": x["pos"],
            "pay_eok": round(x["pay"] / 1e8, 1),
            "excl_eok": round(x["excl"] / 1e8, 1) if x.get("excl") else None,
            "rcept": x["rcept"],
        })
    return out, len(pick)


def main():
    if not API_KEY:
        print("DART_API_KEY가 없어 수집하지 않습니다.")
        return
    corp_map = load_corp_map()
    todo = [(s, c, n) for s, (c, n) in corp_map.items()]
    print(f"상장사 {len(todo)}곳, 사업연도 {YEAR}")
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

    res = {"year": YEAR, "updated": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y-%m-%d"),
           "note": "사업보고서 '개인별 보수지급금액(5억원 이상 상위 5인)' 기준. 보수총액에는 급여·상여·퇴직소득 등이 들어 있어 한 해 연봉과 다를 수 있음."}
    counts = {}
    for mk in ("KOSPI", "KOSDAQ"):
        res[mk.lower()], counts[mk] = rank(rows, mk, RE_CEO)
        res[mk.lower() + "_top"], counts[mk + "_top"] = rank(rows, mk, RE_TOP)
    res["counts"] = counts
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    pos = Counter(x["pos"] for x in rows if market_of(x["cls"]))
    with open(DEBUG_FILE, "w", encoding="utf-8") as f:
        f.write(f"year {YEAR}\n상장사 {len(todo)}\n상태 {dict(status)}\n5억원 이상 인원 {len(rows)}\n")
        f.write(f"cls {dict(Counter(x['cls'] for x in rows))}\n필드 {sample_keys}\n대표 순위 대상 {counts}\n")
        f.write("직위 상위 40: " + json.dumps(pos.most_common(40), ensure_ascii=False) + "\n")
        f.write(f"소요 {time.time() - t0:.0f}초\n")
    print(open(DEBUG_FILE, encoding="utf-8").read())


if __name__ == "__main__":
    main()
