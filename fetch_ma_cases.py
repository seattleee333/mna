"""최근 5년 상장사 '타법인 주식 취득' 사례 목록 → ma_cases.json  (AI 매칭 결과의 '업계 M&A 사례 보기'용)
- 대상 공시: ma_cache.json 의 acq(타법인주식및출자증권취득결정) 공시
- 1순위: 상세 API otcprStkInvscrInhDecsn (회사·연도 단위) → 대상회사·주요사업·취득금액·지분율·목적·거래상대방
- 2순위: 상세 API에 없는 건(거래소 접수 등)은 공시 원문에서 대상회사·금액을 읽는다 (fetch_deals 의 파서 재사용)
환경변수: DART_API_KEY, MAX_DOCS(기본 2500), BUDGET_MIN(기본 100)
"""
import os, json, time, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import fetch_profiles as fp
import fetch_deals as fd

MA = "ma_cache.json"
OUT = "ma_cases.json"
LOG = "ma_cases_log.txt"
YEARS = 5
MAX_DOCS = int(os.environ.get("MAX_DOCS", "2500"))
BUDGET = int(os.environ.get("BUDGET_MIN", "100")) * 60
START = time.time()
_lock = threading.Lock()
_n = {"api": 0, "doc": 0}
KEYS_LOGGED = [0]


def log(m):
    fp.log(m)


def oku(v):
    """원 → 억원(소수 1자리)"""
    n = fd.parse_amount(v)
    return round(n / 1e8, 1) if n else None


def clip(v, n):
    v = fd.clean(v)
    return v[:n] if v else None


def main():
    if not fp.API_KEY:
        log("DART_API_KEY 없음"); return
    ma = json.load(open(MA, encoding="utf-8"))
    since = (dt.date.today().replace(year=dt.date.today().year - YEARS)).strftime("%Y%m%d")
    acq = [f for f in ma["filings"].values() if f["kind"] == "acq" and f["date"] >= since]
    log(f"취득 공시 {len(acq)}건")
    names = {f["corp_code"]: (f["corp_name"], f["stock_code"]) for f in acq}
    pairs = sorted({(f["corp_code"], f["date"][:4]) for f in acq})
    cases, covered = [], set()

    def api_pair(p):
        cc, y = p
        if time.time() - START > BUDGET:
            return
        d = fp.call("otcprStkInvscrInhDecsn.json", {"corp_code": cc, "bgn_de": f"{y}0101", "end_de": f"{y}1231"})
        with _lock:
            _n["api"] += 1
        if not d or d.get("status") != "000":
            return
        for r in d.get("list", []):
            with _lock:
                if KEYS_LOGGED[0] < 2:
                    KEYS_LOGGED[0] += 1
                    log("API 응답 키: " + ",".join(sorted(r.keys())))
                covered.add(r.get("rcept_no"))
                cases.append({
                    "d": (r.get("rcept_no") or "")[:8], "b": names[cc][0], "bc": names[cc][1],
                    "t": clip(r.get("iscmp_cmpnm"), 60), "tb": clip(r.get("iscmp_main_bsn"), 120),
                    "a": oku(r.get("inhdtl_inhprc")), "s": clip(r.get("atinh_eqrt"), 12),
                    "p": clip(r.get("inh_pp"), 160), "cp": clip(r.get("dlptn_cmpnm"), 60),
                    "n": clip(r.get("iscmp_nation"), 12), "r": r.get("rcept_no"), "src": "api"})
        time.sleep(0.05)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(api_pair, pairs))
    log(f"API 호출 {_n['api']}회 → 사례 {len(cases)}건")

    rest = [f for f in acq if f["rcept_no"] not in covered][:MAX_DOCS]
    log(f"상세 API에 없는 공시 {len([f for f in acq if f['rcept_no'] not in covered])}건 중 원문 확인 {len(rest)}건")

    def doc_one(f):
        if time.time() - START > BUDGET:
            return
        html = fd.fetch_raw_document(f["rcept_no"])
        with _lock:
            _n["doc"] += 1
        if not html:
            return
        x = fd.extract_from_raw_doc(html, f["corp_name"], "양수")
        if not x:
            return
        with _lock:
            cases.append({"d": f["date"], "b": f["corp_name"], "bc": f["stock_code"], "t": clip(x["target"], 60), "tb": None,
                          "a": oku(x["amount"]), "s": None, "p": None, "cp": clip(x.get("seller"), 60), "n": None,
                          "r": f["rcept_no"], "src": "doc"})
        time.sleep(0.05)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(doc_one, rest))
    log(f"원문 확인 {_n['doc']}건 → 총 사례 {len(cases)}건")

    seen, out = set(), []
    for c in sorted(cases, key=lambda x: x["d"], reverse=True):
        k = (c["r"], c["t"])
        if k in seen or not c["t"]:
            continue
        seen.add(k); out.append(c)
    json.dump({"updated": dt.date.today().isoformat(), "since": since, "cases": out},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"저장 {OUT}: {len(out)}건 ({os.path.getsize(OUT) // 1024}KB)")
    open(LOG, "w", encoding="utf-8").write("\n".join(fp._logs))


if __name__ == "__main__":
    main()
