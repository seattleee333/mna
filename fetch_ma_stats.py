"""최근 5년 M&A 통계 — 전부 DART 공시(OpenDART API)에서 직접 집계한다. (기사·추정 사용 안 함)

1) 가장 M&A를 활발하게 한 기업: list.json(공시 목록)에서
   '타법인주식및출자증권취득결정' 공시를 회사별로 센다. (정정공시·종속회사 공시 제외)
2) 가장 비싸게 매각한 딜: 처분 공시를 낸 회사의 상세 API
   (otcprStkInvscrTrfDecsn 타법인 주식 처분, bsnTrfDecsn 영업양도)에서 처분금액이 큰 순으로 정렬.
결과: ma_stats.json
"""
import os
import re
import json
import time
import calendar
import datetime as dt
from collections import defaultdict, Counter

import requests

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
OUT = "ma_stats.json"
YEARS = 5
BUDGET = 100 * 60          # 전체 실행 시간 예산(초)
START = time.time()

LIST_TYPES = ["B001", "I001"]   # 주요사항보고서(금융위), 수시공시(거래소)


def call(name, params, tries=3):
    p = dict(params, crtfc_key=API_KEY)
    for i in range(tries):
        try:
            r = requests.get(BASE + name, params=p, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            time.sleep(1.5 * (i + 1))
    return {"status": "999", "message": "요청 실패"}


def months(n_years):
    today = dt.date.today()
    y, m = today.year - n_years, today.month
    cur = dt.date(y, m, 1)
    while cur <= today:
        last = calendar.monthrange(cur.year, cur.month)[1]
        yield cur.strftime("%Y%m%d"), min(dt.date(cur.year, cur.month, last), today).strftime("%Y%m%d")
        cur = dt.date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def classify(report_nm):
    t = re.sub(r"\s+", "", report_nm)
    if any(x in t for x in ("종속회사", "자회사")):
        return None
    if "정정" in t:        # [기재정정], [첨부정정] 등 원 공시와 중복
        return None
    if "타법인주식및출자증권취득결정" in t:
        return "acq"
    if "타법인주식및출자증권처분결정" in t:
        return "disp"
    if "영업양도결정" in t:
        return "biz_out"
    return None


def scan_filings():
    found = {}   # rcept_no -> row
    pages_called = 0
    for bgn, end in months(YEARS):
        for ty in LIST_TYPES:
            page = 1
            while True:
                if time.time() - START > BUDGET:
                    print("시간 예산 초과 - 공시 목록 수집 중단")
                    return found, False
                d = call("list.json", {"bgn_de": bgn, "end_de": end, "pblntf_detail_ty": ty,
                                       "page_no": page, "page_count": 100})
                pages_called += 1
                st = d.get("status")
                if st == "013":
                    break
                if st == "020":
                    print("DART 요청 한도 초과 - 중단")
                    return found, False
                if st != "000":
                    print(f"  list 오류 {bgn} {ty} p{page}: {st} {d.get('message')}")
                    break
                for it in d.get("list", []):
                    kind = classify(it.get("report_nm", ""))
                    if kind:
                        found[it["rcept_no"]] = {
                            "kind": kind, "corp_code": it.get("corp_code"), "corp_name": it.get("corp_name"),
                            "stock_code": (it.get("stock_code") or "").strip(), "rcept_no": it["rcept_no"],
                            "date": it.get("rcept_dt"), "report_nm": it.get("report_nm"),
                        }
                if page >= int(d.get("total_page", 1)):
                    break
                page += 1
                time.sleep(0.12)
        print(f"  {bgn[:6]} 완료 (누적 해당 공시 {len(found)}건, 호출 {pages_called}회)", flush=True)
    return found, True


def amount(v):
    try:
        n = int(float(str(v).replace(",", "").strip()))
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def clean(v):
    s = (str(v).strip() if v is not None else "")
    return None if s in ("", "-") else s


def detail_rows(endpoint, corp_code, year):
    d = call(endpoint + ".json", {"corp_code": corp_code, "bgn_de": f"{year}0101", "end_de": f"{year}1231"})
    if d.get("status") == "000":
        return d.get("list", [])
    return []


def main():
    if not API_KEY:
        print("DART_API_KEY가 없어 ma_stats.json을 갱신하지 않습니다.")
        return
    filings, complete = scan_filings()
    if not filings:
        print("수집된 공시가 없어 종료")
        return
    today = dt.date.today()
    since = (today.replace(year=today.year - YEARS)).strftime("%Y%m%d")
    rows = [f for f in filings.values() if f["date"] >= since]

    # ---- 1) 가장 활발한 인수 기업 ----
    acq = [f for f in rows if f["kind"] == "acq"]
    cnt = Counter(f["corp_code"] for f in acq)
    names = {f["corp_code"]: (f["corp_name"], f["stock_code"]) for f in acq}
    by_year = defaultdict(Counter)
    for f in acq:
        by_year[f["corp_code"]][f["date"][:4]] += 1
    ranking = []
    for corp_code, n in cnt.most_common(30):
        ranking.append({"corp_code": corp_code, "corp_name": names[corp_code][0], "stock_code": names[corp_code][1],
                        "count": n, "by_year": dict(sorted(by_year[corp_code].items()))})
    top10 = ranking[:10]
    # 상위 10개 기업의 주요 취득 대상(상세 API에서 확인되는 건, 금액 큰 순)
    for r in top10:
        targets = {}
        for y in sorted({f["date"][:4] for f in acq if f["corp_code"] == r["corp_code"]}):
            for row in detail_rows("otcprStkInvscrInhDecsn", r["corp_code"], y):
                tgt, amt = clean(row.get("iscmp_cmpnm")), amount(row.get("inhdtl_inhprc"))
                if tgt and amt and row.get("rcept_no", "")[:8] >= since:
                    targets[tgt] = max(targets.get(tgt, 0), amt)
            time.sleep(0.1)
        r["top_targets"] = [{"name": k, "amount": v} for k, v in sorted(targets.items(), key=lambda x: -x[1])[:3]]
        print(f"  [{r['corp_name']}] {r['count']}건, 주요 대상 {len(r['top_targets'])}건")

    # ---- 2) 가장 비싸게 매각한 딜 ----
    sellers = defaultdict(set)   # (corp_code, kind) -> {연도}
    meta = {}
    for f in rows:
        if f["kind"] in ("disp", "biz_out"):
            sellers[(f["corp_code"], f["kind"])].add(f["date"][:4])
            meta[f["corp_code"]] = (f["corp_name"], f["stock_code"])
    deals = {}
    n_calls = 0
    for (corp_code, kind), years in sellers.items():
        endpoint = "otcprStkInvscrTrfDecsn" if kind == "disp" else "bsnTrfDecsn"
        for y in sorted(years):
            if time.time() - START > BUDGET + 25 * 60:
                print("시간 예산 초과 - 처분 상세 조회 중단")
                complete = False
                break
            for row in detail_rows(endpoint, corp_code, y):
                rno = row.get("rcept_no", "")
                if rno[:8] < since:
                    continue
                if kind == "disp":
                    amt, target, buyer = amount(row.get("trfdtl_trfprc")), clean(row.get("iscmp_cmpnm")), clean(row.get("dlptn_cmpnm"))
                    extra = {"stake_after": clean(row.get("attrf_eqrt")), "type": "타법인 지분 매각"}
                else:
                    amt, target, buyer = amount(row.get("trf_prc")), clean(row.get("trf_bsn")), clean(row.get("dlptn_cmpnm"))
                    extra = {"stake_after": None, "type": "사업(영업) 양도"}
                if not amt:
                    continue
                key = (corp_code, target, amt)
                if key in deals:
                    continue
                deals[key] = {"corp_code": corp_code, "corp_name": meta[corp_code][0], "stock_code": meta[corp_code][1],
                              "rcept_no": rno, "date": rno[:8], "target": target, "buyer": buyer, "amount": amt, **extra}
            n_calls += 1
            time.sleep(0.1)
    expensive = sorted(deals.values(), key=lambda x: -x["amount"])[:20]
    print(f"처분 상세 조회 {n_calls}회, 후보 딜 {len(deals)}건")

    out = {
        "updated": dt.date.today().strftime("%Y%m%d"), "since": since, "complete": complete,
        "totals": {"acq_filings": len(acq), "disp_filings": sum(1 for f in rows if f["kind"] == "disp"),
                   "biz_out_filings": sum(1 for f in rows if f["kind"] == "biz_out")},
        "active": {"top10": top10, "next": [{k: v for k, v in r.items() if k != "top_targets"} for r in ranking[10:30]]},
        "expensive": expensive,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("ma_stats.json 저장 완료")


if __name__ == "__main__":
    main()
