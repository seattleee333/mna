"""최근 5년 M&A 통계 — 전부 DART 공시(OpenDART API)에서 직접 집계한다. (기사·추정 사용 안 함)

1) 가장 M&A를 활발하게 한 기업: list.json(공시 목록)에서
   '타법인주식및출자증권취득결정' 공시를 회사별로 센다. (정정공시·종속회사 공시 제외)
2) 가장 비싸게 매각한 딜: '타법인주식및출자증권처분결정'·'영업양도결정' 공시의 처분(양도)금액.
   - 금융위 접수 주요사항보고서는 상세 API(otcprStkInvscrTrfDecsn, bsnTrfDecsn)로,
   - 거래소 접수 공시는 공시 원문(document.xml)을 읽어서 금액·상대방을 추출한다.
결과: ma_stats.json  (이어하기용 캐시: ma_cache.json, 진단 로그: ma_stats_log.txt)
"""
import os
import re
import io
import json
import time
import zipfile
import calendar
import html as htmllib
import threading
import datetime as dt
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor

import requests

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
OUT = "ma_stats.json"
CACHE = "ma_cache.json"
LOG = "ma_stats_log.txt"
YEARS = 5
BUDGET = 110 * 60          # 전체 실행 시간 예산(초)
START = time.time()
WORKERS = 4
PARSER_VERSION = 1
USE_DOC = os.environ.get("MA_USE_DOC") == "1"   # 원문 파서 검증 전에는 순위에 쓰지 않는다(로그 점검만)

LIST_TYPES = ["B001", "I001"]   # 주요사항보고서(금융위), 수시공시(거래소)

_log_lines = []
_lock = threading.Lock()
_quota_hit = False
_doc_errors = 0


def log(msg):
    print(msg, flush=True)
    _log_lines.append(msg)


def call(name, params, tries=3, raw=False):
    p = dict(params, crtfc_key=API_KEY)
    for i in range(tries):
        try:
            r = requests.get(BASE + name, params=p, timeout=40)
            r.raise_for_status()
            return r.content if raw else r.json()
        except (requests.RequestException, ValueError):
            time.sleep(1.5 * (i + 1))
    return None if raw else {"status": "999", "message": "요청 실패"}


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


# ───────────────────────── 1) 공시 목록 스캔 (이어하기 + 병렬) ─────────────────────────
def scan_window(bgn, end, ty):
    """한 달·한 유형의 공시 목록을 전부 읽어 해당 공시만 반환. 실패/중단이면 None."""
    global _quota_hit
    found, page, pages = [], 1, 0
    while True:
        if _quota_hit or time.time() - START > BUDGET:
            return None
        d = call("list.json", {"bgn_de": bgn, "end_de": end, "pblntf_detail_ty": ty,
                               "page_no": page, "page_count": 100})
        pages += 1
        st = d.get("status")
        if st == "013":
            break
        if st == "020":
            _quota_hit = True
            log("DART 요청 한도 초과 - 이번 실행은 여기서 중단(내일 이어서 진행)")
            return None
        if st != "000":
            log(f"  list 오류 {bgn} {ty} p{page}: {st} {d.get('message')}")
            return None
        for it in d.get("list", []):
            kind = classify(it.get("report_nm", ""))
            if kind:
                found.append({
                    "kind": kind, "corp_code": it.get("corp_code"), "corp_name": it.get("corp_name"),
                    "stock_code": (it.get("stock_code") or "").strip(), "rcept_no": it["rcept_no"],
                    "date": it.get("rcept_dt"), "report_nm": it.get("report_nm")})
        if page >= int(d.get("total_page", 1)):
            break
        page += 1
        time.sleep(0.05)
    return found, pages


def scan_filings(cache):
    done = cache.setdefault("done", {})
    filings = cache.setdefault("filings", {})
    tasks = []
    for bgn, end in months(YEARS):
        for ty in LIST_TYPES:
            key = f"{bgn[:6]}|{ty}"
            if done.get(key, "") >= end:      # 이미 끝까지 읽은 구간
                continue
            tasks.append((key, bgn, end, ty))
    log(f"목록 스캔 대상 {len(tasks)}구간 (이미 완료 {len(done)}구간)")
    complete = True
    n = 0

    def work(t):
        key, bgn, end, ty = t
        return t, scan_window(bgn, end, ty)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for t, res in ex.map(work, tasks):
            key, bgn, end, ty = t
            if res is None:
                complete = False
                continue
            found, pages = res
            with _lock:
                for f in found:
                    filings[f["rcept_no"]] = f
                done[key] = end
            n += 1
            log(f"  {key} 완료: 공시 {len(found)}건 (페이지 {pages}), 누적 {len(filings)}건")
            if n % 6 == 0:
                save_cache(cache)
    save_cache(cache)
    return complete


def save_cache(cache):
    with _lock:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


# ───────────────────────── 2) 상세 조회 ─────────────────────────
def amount(v):
    try:
        n = int(float(str(v).replace(",", "").strip()))
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def clean(v):
    s = re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""
    return None if s in ("", "-") else s


def detail_rows(endpoint, corp_code, year):
    d = call(endpoint + ".json", {"corp_code": corp_code, "bgn_de": f"{year}0101", "end_de": f"{year}1231"})
    if d and d.get("status") == "000":
        return d.get("list", [])
    return []


NUM_RE = re.compile(r"^[\(\)\d,\.\s주]*?(\d[\d,]{3,})\s*$")


def doc_tokens(rcept_no):
    """공시 원문(zip/xml)을 받아 텍스트 조각 목록으로 만든다."""
    raw = call("document.xml", {"rcept_no": rcept_no}, raw=True)
    if not raw:
        return None
    if raw[:5] == b"<?xml":      # zip이 아니라 오류 응답(예: 800 시스템 점검)
        global _doc_errors
        _doc_errors += 1
        if _doc_errors <= 3:
            log("원문 조회 오류 응답: " + raw[:300].decode("utf-8", "replace"))
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        name = z.namelist()[0]
        data = z.read(name)
    except Exception:
        return None
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    text = re.sub(r"<[^>]+>", "\n", text)
    text = htmllib.unescape(text).replace("\xa0", " ")
    return [t.strip() for t in text.split("\n") if t.strip()]


def after(tokens, label, start=0, span=6, want_num=False):
    """label을 포함한 조각 뒤쪽에서 값 조각을 찾는다."""
    for i in range(start, len(tokens)):
        if label in tokens[i].replace(" ", ""):
            for j in range(i + 1, min(i + 1 + span, len(tokens))):
                tk = tokens[j]
                if want_num:
                    m = NUM_RE.match(tk)
                    if m:
                        return int(m.group(1).replace(",", "")), i
                else:
                    if tk and tk not in ("-",) and not re.match(r"^\d+\.\s", tk):
                        return tk, i
    return None, start


def strip_country(s):
    return re.sub(r"\s*\((대한민국|한국|[가-힣A-Za-z ]{2,12})\)\s*$", "", s).strip() if s else s


def parse_doc(kind, tokens):
    if kind == "disp":
        amt, _ = after(tokens, "처분금액", want_num=True)
        _, i0 = after(tokens, "발행회사")
        tgt, _ = after(tokens, "회사명", start=i0)
        _, i1 = after(tokens, "거래상대방")
        buyer, _ = after(tokens, "회사명", start=i1) if i1 else (None, 0)
    elif kind == "biz_out":
        amt, _ = after(tokens, "양도금액", want_num=True)
        tgt, _ = after(tokens, "양도영업")
        _, i1 = after(tokens, "양수인")
        buyer, _ = after(tokens, "회사명", start=i1) if i1 else (None, 0)
    else:  # acq
        amt, _ = after(tokens, "취득금액", want_num=True)
        _, i0 = after(tokens, "발행회사")
        tgt, _ = after(tokens, "회사명", start=i0)
        buyer = None
    return {"v": PARSER_VERSION, "amount": amt, "target": strip_country(clean(tgt)) if tgt else None,
            "buyer": strip_country(clean(buyer)) if buyer else None}


_sample_logged = set()


def doc_info(cache, f):
    docs = cache.setdefault("docs", {})
    rno = f["rcept_no"]
    cur = docs.get(rno)
    if cur and cur.get("v") == PARSER_VERSION:
        return cur
    if _doc_errors >= 8:        # 점검 중 등으로 계속 실패하면 더 호출하지 않는다
        return {}
    tokens = doc_tokens(rno)
    time.sleep(0.1)
    if tokens is None:
        return {}
    info = parse_doc(f["kind"], tokens)
    docs[rno] = info
    if f["kind"] not in _sample_logged:     # 파서 점검용으로 종류별 첫 문서의 조각을 로그에 남긴다
        _sample_logged.add(f["kind"])
        log(f"[샘플 {f['kind']}] {f['corp_name']} {rno} → {info}")
        log("   조각: " + " | ".join(tokens[:160]))
    return info


# ───────────────────────── main ─────────────────────────
def main():
    if not API_KEY:
        print("DART_API_KEY가 없어 ma_stats.json을 갱신하지 않습니다.")
        return
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    complete = scan_filings(cache)
    filings = cache.get("filings", {})
    if not filings:
        print("수집된 공시가 없어 종료")
        return
    today = dt.date.today()
    since = today.replace(year=today.year - YEARS).strftime("%Y%m%d")
    rows = [f for f in filings.values() if f["date"] >= since]

    # ---- 1) 가장 활발한 인수 기업 ----
    acq = [f for f in rows if f["kind"] == "acq"]
    cnt = Counter(f["corp_code"] for f in acq)
    names = {f["corp_code"]: (f["corp_name"], f["stock_code"]) for f in acq}
    by_year = defaultdict(Counter)
    for f in acq:
        by_year[f["corp_code"]][f["date"][:4]] += 1
    order = sorted(cnt.items(), key=lambda x: (-x[1], names[x[0]][0]))[:50]
    ranking = [{"corp_code": c, "corp_name": names[c][0], "stock_code": names[c][1], "count": n,
                "by_year": dict(sorted(by_year[c].items()))} for c, n in order]
    top10 = ranking[:10]
    for r in top10:
        targets = {}
        mine = [f for f in acq if f["corp_code"] == r["corp_code"]]
        api_seen = set()
        for y in sorted({f["date"][:4] for f in mine}):
            for row in detail_rows("otcprStkInvscrInhDecsn", r["corp_code"], y):
                tgt, amt = clean(row.get("iscmp_cmpnm")), amount(row.get("inhdtl_inhprc"))
                api_seen.add(row.get("rcept_no"))
                if tgt and amt and row.get("rcept_no", "")[:8] >= since:
                    targets[tgt] = max(targets.get(tgt, 0), amt)
            time.sleep(0.1)
        r["recent"] = [{"date": f["date"], "rcept_no": f["rcept_no"]}
                       for f in sorted(mine, key=lambda x: x["date"], reverse=True)[:3]]
        for f in (mine if USE_DOC else []):      # 상세 API에 없는(거래소 접수) 건은 공시 원문에서 읽는다
            if f["rcept_no"] in api_seen:
                continue
            info = doc_info(cache, f)
            if info.get("target") and info.get("amount"):
                targets[info["target"]] = max(targets.get(info["target"], 0), info["amount"])
        r["top_targets"] = [{"name": k, "amount": v} for k, v in sorted(targets.items(), key=lambda x: -x[1])[:3]]
        log(f"  [{r['corp_name']}] {r['count']}건, 주요 대상 {len(r['top_targets'])}건")
    save_cache(cache)

    # ---- 2) 가장 비싸게 매각한 딜 ----
    sells = [f for f in rows if f["kind"] in ("disp", "biz_out")]
    sellers = defaultdict(set)   # (corp_code, kind) -> {연도}
    for f in sells:
        sellers[(f["corp_code"], f["kind"])].add(f["date"][:4])
    meta = {f["corp_code"]: (f["corp_name"], f["stock_code"]) for f in sells}
    deals = {}
    api_rnos = set()
    for (corp_code, kind), years in sellers.items():
        endpoint = "otcprStkInvscrTrfDecsn" if kind == "disp" else "bsnTrfDecsn"
        for y in sorted(years):
            if time.time() - START > BUDGET + 20 * 60:
                log("시간 예산 초과 - 처분 상세 조회 중단")
                complete = False
                break
            for row in detail_rows(endpoint, corp_code, y):
                rno = row.get("rcept_no", "")
                if rno[:8] < since:
                    continue
                api_rnos.add(rno)
                if kind == "disp":
                    amt, target, buyer = amount(row.get("trfdtl_trfprc")), clean(row.get("iscmp_cmpnm")), clean(row.get("dlptn_cmpnm"))
                    extra = {"stake_after": clean(row.get("attrf_eqrt")), "type": "타법인 지분 매각"}
                else:
                    amt, target, buyer = amount(row.get("trf_prc")), clean(row.get("trf_bsn")), clean(row.get("dlptn_cmpnm"))
                    extra = {"stake_after": None, "type": "사업(영업) 양도"}
                if not amt:
                    continue
                deals[rno] = {"corp_code": corp_code, "corp_name": meta[corp_code][0], "stock_code": meta[corp_code][1],
                              "rcept_no": rno, "date": rno[:8], "target": target, "buyer": buyer, "amount": amt, **extra}
            time.sleep(0.1)
    n_api = len(deals)
    n_doc = 0
    for f in (sells if USE_DOC else []):     # 상세 API에 없는(거래소 접수) 건은 공시 원문에서 읽는다
        if f["rcept_no"] in deals:
            continue
        if time.time() - START > BUDGET + 40 * 60:
            log("시간 예산 초과 - 원문 조회 중단")
            complete = False
            break
        info = doc_info(cache, f)
        n_doc += 1
        if info.get("amount"):
            deals[f["rcept_no"]] = {
                "corp_code": f["corp_code"], "corp_name": f["corp_name"], "stock_code": f["stock_code"],
                "rcept_no": f["rcept_no"], "date": f["rcept_no"][:8], "target": info.get("target"),
                "buyer": info.get("buyer"), "amount": info["amount"], "stake_after": None,
                "type": "타법인 지분 매각" if f["kind"] == "disp" else "사업(영업) 양도"}
    save_cache(cache)
    if not USE_DOC:     # 원문 서비스 상태·구조 점검용 샘플만 로그에 남긴다
        for kind in ("disp", "biz_out", "acq"):
            for f in sorted([x for x in rows if x["kind"] == kind], key=lambda x: x["date"], reverse=True)[:1]:
                doc_info(cache, f)
    uniq = {}
    for d in deals.values():      # 같은 딜의 중복(정정 등) 제거
        k = (d["corp_code"], d["target"], d["amount"])
        if k not in uniq:
            uniq[k] = d
    expensive = sorted(uniq.values(), key=lambda x: -x["amount"])[:50]
    log(f"매각 후보 {len(sells)}건 → 상세 API로 금액 확인 {n_api}건 + 원문 조회 {n_doc}건, 금액 확인 딜 {len(uniq)}건")

    out = {
        "doc_used": USE_DOC,
        "updated": today.strftime("%Y%m%d"), "since": since, "complete": complete,
        "totals": {"acq_filings": len(acq), "disp_filings": sum(1 for f in rows if f["kind"] == "disp"),
                   "biz_out_filings": sum(1 for f in rows if f["kind"] == "biz_out")},
        "active": {"top10": top10, "next": [{k: v for k, v in r.items() if k != "top_targets"} for r in ranking[10:50]]},
        "expensive": expensive,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log(f"ma_stats.json 저장 완료 (complete={complete})")


if __name__ == "__main__":
    try:
        main()
    finally:
        with open(LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(_log_lines[-400:]))
