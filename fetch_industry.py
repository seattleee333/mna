"""특정 업종(예: 배전반 및 전기 자동제어반 제조업)의 최근 5년 M&A 사례를 OpenDART에서 직접 모은다.

사례 3종류
 1) 타법인 지분 취득  — 누가 이 업종 회사의 지분을 샀나 (취득결정 공시 + 상세 API)
 2) 최대주주 변경     — 이 업종 상장사의 최대주주 변동 이력 (hyslrChgSttus)
 3) 유상증자          — 이 업종 상장사의 유상증자 결정 (piicDecsn)
회사의 업종은 DART 기업개황(company.json)의 업종코드(KSIC)로 판단한다.
각 회사에 대해 거래 전년도 재무(매출·영업이익·자산·부채·자본)를 fnlttSinglAcnt로 붙인다.
결과: industry_deals.json (+ 캐시 industry_cache.json, 로그 industry_log.txt)
"""
import os
import re
import io
import json
import time
import zipfile
import threading
import datetime as dt
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET

import requests

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
OUT = "industry_deals.json"
CACHE = "industry_cache.json"
LOG = "industry_log.txt"
MA_CACHE = "ma_cache.json"
START = time.time()
BUDGET = 150 * 60
WORKERS = 5
SEEDS = ["광명전기", "지투파워", "이에스아이"]            # 업종코드 확인용 대표 회사
FORCE_CODES = [c for c in os.environ.get("INDUTY_CODES", "").split(",") if c.strip()]
KEYWORD_RE = re.compile(r"배전반|자동제어반|수배전|분전반|배전|제어반")
EVENT_RE = re.compile(r"최대주주|주식양수도|유상증자|제3자배정|합병|분할|영업양수|영업양도|경영권|지분양수|지분양도")
TODAY = dt.date.today()
SINCE = dt.date(TODAY.year - 5, TODAY.month, TODAY.day).strftime("%Y%m%d")

_lock = threading.Lock()
_logs = []
_quota = False


def log(m):
    print(m, flush=True)
    _logs.append(str(m))


def call(name, params, tries=3, raw=False):
    global _quota
    p = dict(params, crtfc_key=API_KEY)
    for i in range(tries):
        if _quota:
            break
        try:
            r = requests.get(BASE + name, params=p, timeout=40)
            r.raise_for_status()
            if raw:
                return r.content
            d = r.json()
            if d.get("status") == "020":
                _quota = True
                log("DART 요청 한도 초과 - 중단")
            return d
        except (requests.RequestException, ValueError):
            time.sleep(1.5 * (i + 1))
    return None if raw else {"status": "999", "message": "요청 실패"}


def num(v):
    try:
        n = int(float(str(v).replace(",", "").strip()))
        return n
    except (ValueError, TypeError):
        return None


def clean(v):
    s = re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""
    return None if s in ("", "-") else s


def norm(name):
    s = re.sub(r"\(주\)|㈜|주식회사|\s", "", name or "")
    return s


def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            pass
    return {"company": {}, "acq": {}, "fin": {}}


def save_cache(c):
    with _lock:
        json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def pmap(fn, items):
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return list(ex.map(fn, items))


# ── 회사 목록 / 업종 ─────────────────────────────────────────
def corp_list():
    raw = call("corpCode.xml", {}, raw=True)
    z = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(z.read(z.namelist()[0]))
    out = []
    for e in root.iter("list"):
        out.append({"corp_code": e.findtext("corp_code"), "name": (e.findtext("corp_name") or "").strip(),
                    "stock": (e.findtext("stock_code") or "").strip()})
    return out


def company_info(cache, cc):
    c = cache["company"].get(cc)
    if c is not None:
        return c
    if time.time() - START > BUDGET:
        return None
    d = call("company.json", {"corp_code": cc})
    if d.get("status") == "000":
        c = {"name": d.get("corp_name"), "induty": d.get("induty_code") or "", "stock": d.get("stock_code") or "",
             "cls": d.get("corp_cls")}
    elif d.get("status") in ("013", "100"):
        c = {"name": None, "induty": "", "stock": "", "cls": ""}
    else:
        return None
    with _lock:
        cache["company"][cc] = c
    return c


# ── 상세 API ────────────────────────────────────────────────
def detail_rows(endpoint, cc, year, extra=None):
    p = {"corp_code": cc, "bgn_de": f"{year}0101", "end_de": f"{year}1231"}
    d = call(endpoint + ".json", p)
    if d and d.get("status") == "000":
        return d.get("list", [])
    return []


ACC = [("rev", ("매출액", "수익(매출액)", "영업수익")), ("op", ("영업이익", "영업이익(손실)")),
       ("asset", ("자산총계",)), ("debt", ("부채총계",)), ("equity", ("자본총계",))]


def fin(cache, cc, year):
    """거래 전년도(year) 재무. 연결 우선, 없으면 개별. 단위 원."""
    key = f"{cc}|{year}"
    if key in cache["fin"]:
        return cache["fin"][key]
    d = call("fnlttSinglAcnt.json", {"corp_code": cc, "bsns_year": str(year), "reprt_code": "11011"})
    res = None
    if d and d.get("status") == "000":
        rows = d.get("list", [])
        for fsd in ("CFS", "OFS"):
            sub = [r for r in rows if r.get("fs_div") == fsd]
            if not sub:
                continue
            res = {"year": year, "fs": "연결" if fsd == "CFS" else "별도"}
            for k, names in ACC:
                for r in sub:
                    if r.get("account_nm") in names and r.get("sj_div") in ("IS", "CIS", "BS"):
                        res[k] = num(r.get("thstrm_amount"))
                        break
            break
    elif d and d.get("status") == "013":
        res = {"year": year, "none": True}
    else:
        return res
    with _lock:
        cache["fin"][key] = res
    return res


def main():
    cache = load_cache()
    corps = corp_list()
    by_name = defaultdict(list)
    for c in corps:
        by_name[norm(c["name"])].append(c)
    log(f"기업 목록 {len(corps)}개")

    # 1) 상장사 업종코드 수집
    listed = [c for c in corps if c["stock"]]
    log(f"상장사 {len(listed)}개 업종코드 조회")
    pmap(lambda c: company_info(cache, c["corp_code"]), listed)
    save_cache(cache)

    # 2) 대표 회사의 업종코드로 대상 업종 확정
    codes = set(FORCE_CODES)
    for s in SEEDS:
        for c in by_name.get(norm(s), []):
            info = company_info(cache, c["corp_code"])
            log(f"[대표회사] {s} corp={c['corp_code']} stock={c['stock']} 업종코드={info and info['induty']}")
            if info and info["induty"] and not FORCE_CODES and s != "지투파워" and s != "이에스아이":
                codes.add(info["induty"])
    if not codes:
        for s in SEEDS:
            for c in by_name.get(norm(s), []):
                info = company_info(cache, c["corp_code"])
                if info and info["induty"]:
                    codes.add(info["induty"])
    log(f"대상 업종코드: {sorted(codes)}")
    for cd in sorted(codes):
        names = [v["name"] for v in cache["company"].values() if v["induty"] == cd and v["name"]]
        log(f"  코드 {cd} 상장사 {len(names)}곳: {', '.join(names[:60])}")

    def in_ind(info):
        return bool(info and info["induty"] in codes)

    ind_corps = {cc: v for cc, v in cache["company"].items() if in_ind(v)}   # 대상 업종 회사 (corp_code → info)
    log(f"대상 업종 회사 {len(ind_corps)}곳")

    # 3) 타법인 지분 취득 — 취득결정 공시 전체의 상세 행에서 대상회사가 이 업종인 것
    ma = json.load(open(MA_CACHE, encoding="utf-8"))
    acq_f = [f for f in ma["filings"].values() if f["kind"] == "acq"]
    pairs = sorted({(f["corp_code"], f["date"][:4]) for f in acq_f})
    log(f"취득공시 {len(acq_f)}건 / 상세조회 {len(pairs)}회")

    def get_acq(p):
        k = f"{p[0]}|{p[1]}"
        if k in cache["acq"]:
            return
        if time.time() - START > BUDGET:
            return
        rows = detail_rows("otcprStkInvscrInhDecsn", p[0], p[1])
        slim = []
        for r in rows:
            slim.append({k2: r.get(k2) for k2 in (
                "rcept_no", "corp_code", "corp_name", "iscmp_cmpnm", "iscmp_nation", "iscmp_rp", "iscmp_cpt",
                "iscmp_mbsn", "inhdtl_stkcnt", "inhdtl_inhprc", "inhdtl_tast", "atinh_owshares", "atinh_eqrt", "inh_pp",
                "inh_prd", "dlptn_cmpnm", "dlptn_mbsn", "dlptn_rl_cmpn", "inh_bd")})
        with _lock:
            cache["acq"][k] = slim

    pmap(get_acq, pairs)
    save_cache(cache)

    # 대상회사 이름 → corp_code (유일하게 매칭될 때만) → 업종 확인
    tgt_names = set()
    for rows in cache["acq"].values():
        for r in rows:
            n = clean(r.get("iscmp_cmpnm"))
            if n:
                tgt_names.add(n)
    log(f"취득 대상회사(이름) {len(tgt_names)}곳")
    name_cc = {}
    for n in tgt_names:
        cands = by_name.get(norm(n), [])
        if len(cands) == 1:
            name_cc[n] = cands[0]["corp_code"]
        elif len(cands) > 1:   # 상장사 우선
            ls = [c for c in cands if c["stock"]]
            if len(ls) == 1:
                name_cc[n] = ls[0]["corp_code"]
    log(f"  이름으로 corp_code 확인 {len(name_cc)}곳 → 업종 조회")
    pmap(lambda n: company_info(cache, name_cc[n]), list(name_cc))
    save_cache(cache)

    deals = []
    seen_acq = set()
    for rows in cache["acq"].values():
        for r in rows:
            n = clean(r.get("iscmp_cmpnm"))
            if not n or r["rcept_no"] in seen_acq:
                continue
            cc = name_cc.get(n)
            info = cache["company"].get(cc) if cc else None
            blob = " ".join(str(v) for v in r.values() if v)
            hit_ind = in_ind(info)
            hit_kw = bool(KEYWORD_RE.search(blob))
            if not (hit_ind or hit_kw):
                continue
            if r["rcept_no"][:8] < SINCE:
                continue
            seen_acq.add(r["rcept_no"])
            deals.append({
                "type": "타법인 지분 취득", "date": r["rcept_no"][:8], "rcept_no": r["rcept_no"],
                "target": n, "target_cc": cc, "target_induty": info["induty"] if info else None,
                "match": "업종코드" if hit_ind else "키워드",
                "buyer": clean(r.get("corp_name")), "buyer_cc": r.get("corp_code"),
                "counterparty": clean(r.get("dlptn_cmpnm")), "amount": num(r.get("inhdtl_inhprc")),
                "shares": num(r.get("inhdtl_stkcnt")), "stake_after": clean(r.get("atinh_eqrt")),
                "purpose": clean(r.get("inh_pp")), "nation": clean(r.get("iscmp_nation"))})
    log(f"타법인 취득 사례 {len(deals)}건")

    # 4) 대상 업종 상장사의 최대주주 변경 / 유상증자 / 주요 공시
    events_filings = {}

    def per_corp(cc):
        out = {"hyslr": [], "piic": [], "filings": []}
        for y in range(TODAY.year - 5, TODAY.year + 1):
            d = call("hyslrChgSttus.json", {"corp_code": cc, "bsns_year": str(y), "reprt_code": "11011"})
            if d and d.get("status") == "000":
                out["hyslr"] += d.get("list", [])
            for r in detail_rows("piicDecsn", cc, y):
                out["piic"].append(r)
        page = 1
        while True:
            d = call("list.json", {"corp_code": cc, "bgn_de": SINCE, "end_de": TODAY.strftime("%Y%m%d"),
                                   "page_no": page, "page_count": 100})
            if not d or d.get("status") != "000":
                break
            for it in d.get("list", []):
                if EVENT_RE.search(it.get("report_nm", "")):
                    out["filings"].append({"rcept_no": it["rcept_no"], "date": it["rcept_dt"],
                                           "report_nm": it["report_nm"].strip()})
            if page >= int(d.get("total_page", 1)):
                break
            page += 1
        return cc, out

    listed_ind = [cc for cc, v in ind_corps.items() if v.get("stock")]
    log(f"대상 업종 상장사 {len(listed_ind)}곳 이벤트 조회")
    for cc, out in pmap(per_corp, listed_ind):
        events_filings[cc] = out

    for cc, out in events_filings.items():
        nm = ind_corps[cc]["name"]
        seen = set()
        for r in out["hyslr"]:
            on = (r.get("change_on") or "").replace(".", "").replace("-", "").strip()
            holder = clean(r.get("mxmm_shrholdr_nm"))
            key = (on, holder)
            if not on or key in seen or on < SINCE[:6]:
                continue
            seen.add(key)
            deals.append({"type": "최대주주 변경", "date": on, "rcept_no": r.get("rcept_no"), "target": nm,
                          "target_cc": cc, "target_induty": ind_corps[cc]["induty"], "buyer": holder,
                          "amount": None, "stake_after": clean(r.get("qota_rt")),
                          "purpose": clean(r.get("change_cause"))})
        seen = set()
        for r in out["piic"]:
            if r["rcept_no"] in seen or r["rcept_no"][:8] < SINCE:
                continue
            seen.add(r["rcept_no"])
            tot = sum(num(r.get(k)) or 0 for k in ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"))
            deals.append({"type": "유상증자", "date": r["rcept_no"][:8], "rcept_no": r["rcept_no"], "target": nm,
                          "target_cc": cc, "target_induty": ind_corps[cc]["induty"],
                          "buyer": None, "amount": tot or None, "shares": num(r.get("nstk_ostk_cnt")),
                          "purpose": clean(r.get("ic_mthn"))})
    log(f"전체 사례 {len(deals)}건")

    # 5) 대상회사 거래 전년도 재무
    need = sorted({(d["target_cc"], int(d["date"][:4]) - 1) for d in deals if d.get("target_cc")})
    log(f"재무 조회 {len(need)}건")
    pmap(lambda p: fin(cache, p[0], p[1]), need)
    save_cache(cache)
    for d in deals:
        d["fin"] = cache["fin"].get(f"{d['target_cc']}|{int(d['date'][:4]) - 1}") if d.get("target_cc") else None
    deals.sort(key=lambda x: x["date"], reverse=True)
    latest = {}
    for cc in ind_corps:
        for y in range(TODAY.year - 6, TODAY.year):
            latest[f"{cc}|{y}"] = fin(cache, cc, y)
    save_cache(cache)

    out = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "since": SINCE, "induty_codes": sorted(codes),
           "companies": [{"corp_code": cc, "name": v["name"], "induty": v["induty"], "stock": v["stock"]}
                         for cc, v in ind_corps.items()],
           "deals": deals, "fin_by_year": latest,
           "filings": {ind_corps[cc]["name"]: o["filings"] for cc, o in events_filings.items()}}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    try:
        main()
    finally:
        open(LOG, "w", encoding="utf-8").write("\n".join(_logs))
