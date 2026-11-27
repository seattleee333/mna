"""전 상장사 피어 데이터(TTM 손익 + 최근 분기말 재무상태 + 주식수 + 6개월 평균 주가) → peer_universe.json

피어그룹 배수법 화면(peer.html)에서 아무 상장사나 비교기업으로 고를 수 있게 하는 데이터.
- TTM = 최근 사업보고서(12개월) + 최근 분기·반기 누적 − 전년 같은 기간 누적
- 재무상태표는 가장 최근 보고서 기준 (연결 우선, 없으면 별도)
- 주식수 = 보통주 발행주식수 − 자기주식 (자기주식 제외 유통주식)
- 주가 = 직전 거래일까지 최근 6개월(182일) 종가 평균 (네이버 금융 일봉)
- 보고서가 바뀐 회사만 다시 받는다(호출 한도 때문에 한 번에 BUDGET 회까지, 남으면 다음 실행에서 이어서)
단위: 백만원(금액), 주(주식수), 원(주가)
"""
import json
import os
import re
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import threading

import requests

from fetch_peers import load_corp_map

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
OUT = "peer_universe.json"
BUDGET = int(os.environ.get("PEER_BUDGET", "9000"))
# 실행 시간 한도(분): 넘으면 새 호출을 멈추고 지금까지 받은 것을 저장한다
DEADLINE = time.time() + 60 * int(os.environ.get("PEER_MINUTES", "120"))
WORKERS = 4
UA = {"User-Agent": "Mozilla/5.0"}
KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(KST).date()

lock = threading.Lock()
calls = [0]
log = []


def api(path, **p):
    with lock:
        if calls[0] >= BUDGET or time.time() > DEADLINE:
            raise RuntimeError("budget")
        calls[0] += 1
    p["crtfc_key"] = API_KEY
    for a in range(4):
        try:
            j = requests.get(BASE + path, params=p, timeout=40).json()
            if j.get("status") == "020":
                time.sleep(10 * (a + 1)); continue
            return j
        except Exception:
            time.sleep(2 + a)
    return {}


def num(s):
    if s in (None, "", "-"):
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


# ── 1) 정기보고서 목록: 회사별 최신 사업보고서 / 최근 분기·반기 ──
def report_index():
    rep = {}  # corp_code -> list of (period 'YYYY.MM', kind, rcept_no, rcept_dt)
    start = dt.date(TODAY.year - 1, 1, 1)
    s = start
    while s <= TODAY:
        e = min(s + dt.timedelta(days=88), TODAY)
        page = 1
        while True:
            j = api("list.json", bgn_de=s.strftime("%Y%m%d"), end_de=e.strftime("%Y%m%d"), pblntf_ty="A",
                    page_no=page, page_count=100)
            for x in j.get("list") or []:
                if x.get("corp_cls") not in ("Y", "K", "N"):
                    continue
                m = re.match(r"^(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)", x.get("report_nm", "").replace("[기재정정]", "").strip())
                if not m:
                    continue
                rep.setdefault(x["corp_code"], []).append((f"{m.group(2)}.{m.group(3)}", m.group(1), x["rcept_no"], x["rcept_dt"]))
            tp = int(j.get("total_page") or 1)
            if page >= tp:
                break
            page += 1
        s = e + dt.timedelta(days=1)
    return rep


def plan(reports):
    """최신 사업보고서(FY), 그 이후 최신 분기·반기(L), 전년 같은 기간(P)과 reprt_code"""
    by = {}
    for per, kind, rc, rd in reports:
        if per not in by or rc > by[per][2]:  # 정정보고서는 접수번호가 더 큼 → 최신 것 사용
            by[per] = (per, kind, rc, rd)
    fys = sorted([v for v in by.values() if v[1] == "사업보고서"], key=lambda v: v[0])
    if not fys:
        return None
    fy = fys[-1]
    fy_m = int(fy[0][5:])
    later = sorted([v for v in by.values() if v[1] != "사업보고서" and v[0] > fy[0]], key=lambda v: v[0])
    out = {"fy": fy, "fy_m": fy_m}
    if later:
        L = later[-1]
        y, m = int(L[0][:4]), int(L[0][5:])
        months = (y * 12 + m) - (int(fy[0][:4]) * 12 + fy_m)  # FY말 이후 경과 개월 3/6/9
        code = {3: "11013", 6: "11012", 9: "11014"}.get(months)
        if code:
            out["L"] = L
            out["code"] = code
            pkey = f"{y - 1}.{m:02d}"
            out["P"] = by.get(pkey)
    return out


# ── 2) 재무제표 ──
REV_ID = ("ifrs-full_Revenue", "ifrs_Revenue")
OP_ID = ("dart_OperatingIncomeLoss",)
NI_OWN = ("ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs_ProfitLossAttributableToOwnersOfParent")
NI_ALL = ("ifrs-full_ProfitLoss", "ifrs_ProfitLoss")
DA_RE = re.compile(r"상각")
DA_NOT = re.compile(r"손상|처분|환입|대손|평가|폐기|외화|이연|상각후|충당|정부보조금|할인발행|할증|사채|전환권|합계|기타")
DEBT_RE = re.compile(r"차입금|사채|유동성장기부채")
DEBT_NOT = re.compile(r"리스|이자|할인|할증|조정|충당|미지급|보증|계약|상환할증|전환권|신주인수권|파생|부채합계|차입부채합계|매입채무")


def fin(corp, year, code, fs_pref):
    order = [fs_pref] if fs_pref else ["CFS", "OFS"]
    if fs_pref:
        order.append("OFS" if fs_pref == "CFS" else "CFS")
    for fs in order:
        j = api("fnlttSinglAcntAll.json", corp_code=corp, bsns_year=year, reprt_code=code, fs_div=fs)
        if j.get("status") == "000" and j.get("list"):
            return j["list"], fs
        if fs_pref:  # 선호 구분이 이미 있으면 한 번만 더 시도
            continue
    return None, None


def pick(rows, ids, names=None, sj=("IS", "CIS"), cum=True):
    for r in rows:
        if r.get("sj_div") in sj and r.get("account_id") in ids and r.get("account_detail") in (None, "-", ""):
            v = num(r.get("thstrm_add_amount")) if cum else None
            return v if v is not None else num(r.get("thstrm_amount"))
    if names:
        for r in rows:
            nm = re.sub(r"\s+", "", r.get("account_nm") or "")
            if r.get("sj_div") in sj and nm in names and r.get("account_detail") in (None, "-", ""):
                v = num(r.get("thstrm_add_amount")) if cum else None
                return v if v is not None else num(r.get("thstrm_amount"))
    return None


def flows(rows):
    """손익(누적) + 현금흐름표 상각비"""
    rev = pick(rows, REV_ID, {"매출액", "수익(매출액)", "영업수익", "매출", "매출및지분법손익"})
    op = pick(rows, OP_ID, {"영업이익", "영업이익(손실)", "영업손익"})
    ni = pick(rows, NI_OWN)
    ni_all = pick(rows, NI_ALL, {"당기순이익", "당기순이익(손실)", "반기순이익", "분기순이익"})
    da, seen = 0.0, set()
    for r in rows:
        nm = re.sub(r"\s+", "", r.get("account_nm") or "")
        if r.get("sj_div") == "CF" and DA_RE.search(nm) and not DA_NOT.search(nm) and nm not in seen and r.get("account_detail") in (None, "-", ""):
            v = num(r.get("thstrm_amount"))
            if v is not None:
                da += abs(v); seen.add(nm)
    return {"rev": rev, "op": op, "ni": ni if ni is not None else ni_all, "ni_own": ni is not None, "da": da if seen else None, "da_items": sorted(seen)}


def stocks(rows):
    bs = [r for r in rows if r.get("sj_div") == "BS" and r.get("account_detail") in (None, "-", "")]

    def g(ids, names=()):
        for r in bs:
            if r.get("account_id") in ids:
                return num(r.get("thstrm_amount"))
        for r in bs:
            if re.sub(r"\s+", "", r.get("account_nm") or "") in names:
                return num(r.get("thstrm_amount"))
        return None
    cash = g(("ifrs-full_CashAndCashEquivalents",), ("현금및현금성자산",)) or 0
    stf = 0.0
    for r in bs:
        nm = re.sub(r"\s+", "", r.get("account_nm") or "")
        if nm in ("단기금융상품", "단기예금", "단기금융기관예치금"):
            stf += num(r.get("thstrm_amount")) or 0
    debt, items = 0.0, []
    for r in bs:
        nm = re.sub(r"\s+", "", r.get("account_nm") or "")
        if DEBT_RE.search(nm) and not DEBT_NOT.search(nm):
            v = num(r.get("thstrm_amount"))
            if v:
                debt += v; items.append(nm)
    lease = 0.0
    for r in bs:
        nm = re.sub(r"\s+", "", r.get("account_nm") or "")
        if "리스부채" in nm and "합계" not in nm:
            lease += num(r.get("thstrm_amount")) or 0
    return {"cash": cash, "stf": stf, "debt": debt, "debt_items": items, "lease": lease,
            "assets": g(("ifrs-full_Assets",), ("자산총계",)), "liab": g(("ifrs-full_Liabilities",), ("부채총계",)),
            "eq": g(("ifrs-full_Equity",), ("자본총계",)), "nci": g(("ifrs-full_NoncontrollingInterests",), ("비지배지분",))}


def shares(corp, year, code):
    j = api("stockTotqySttus.json", corp_code=corp, bsns_year=year, reprt_code=code)
    for r in j.get("list") or []:
        if "보통" in (r.get("se") or ""):
            iss, tre = num(r.get("istc_totqy")), num(r.get("tesstk_co")) or 0
            if iss:
                return {"iss": iss, "tre": tre, "out": iss - tre}
    return None


def price(sc):
    try:
        r = requests.get("https://fchart.stock.naver.com/sise.nhn", params={"symbol": sc, "timeframe": "day", "count": 140, "requestType": 0},
                         headers=UA, timeout=20)
        rows = [x.split("|") for x in re.findall(r'data="([^"]+)"', r.text)]
        rows = [(x[0], float(x[4])) for x in rows if len(x) > 4 and x[4] not in ("", "0")]
        frm = (TODAY - dt.timedelta(days=182)).strftime("%Y%m%d")
        to = TODAY.strftime("%Y%m%d")
        w = [p for d_, p in rows if frm <= d_ < to]
        if not w:
            return None
        return {"avg": round(sum(w) / len(w), 1), "n": len(w), "last": rows[-1][1], "last_d": rows[-1][0],
                "from": min(d_ for d_, _ in rows if d_ >= frm), "to": max(d_ for d_, _ in rows if d_ < to)}
    except Exception:
        return None


def m(v):  # 원 → 백만원
    return None if v is None else round(v / 1e6, 1)


def build(item, prev):
    sc, corp, nm, mk, ic, pl = item
    fy, L, P, code = pl["fy"], pl.get("L"), pl.get("P"), pl.get("code")
    basis = [fy[2], L[2] if L else "", P[2] if P else ""]
    e = dict(prev) if prev else {}
    if not prev or prev.get("basis") != basis:
        fs_pref = (prev or {}).get("fs")
        fyr, fs = fin(corp, fy[0][:4], "11011", fs_pref)
        if not fyr:
            return prev
        a = flows(fyr)
        ttm = dict(a)
        bsrows, period, ttm_note = fyr, fy[0], "사업보고서 12개월"
        if L and P:
            lr, _ = fin(corp, L[0][:4], code, fs)
            pr, _ = fin(corp, P[0][:4], code, fs)
            if lr and pr:
                b, c = flows(lr), flows(pr)
                for k in ("rev", "op", "ni", "da"):
                    ttm[k] = None if None in (a[k], b[k], c[k]) else a[k] + b[k] - c[k]
                ttm["ni_own"] = a["ni_own"] and b["ni_own"] and c["ni_own"]
                bsrows, period, ttm_note = lr, L[0], f"{fy[0]} 사업 + {L[0]} 누적 − {P[0]} 누적"
        elif L:
            lr, _ = fin(corp, L[0][:4], code, fs)
            if lr:
                bsrows, period = lr, L[0]
        st = stocks(bsrows)
        sh = shares(corp, period[:4], code if period != fy[0] else "11011")
        e = {"c": sc, "n": nm, "m": mk, "ic": ic, "fs": fs, "per": period, "fy": fy[0], "basis": basis, "note": ttm_note,
             "rcept": {"fy": fy[2], "l": L[2] if L else "", "p": P[2] if P else ""},
             "t": [m(ttm["rev"]), m(ttm["op"]), m(ttm["da"]), m(ttm["ni"])], "own": bool(ttm.get("ni_own")),
             "b": [m(st["cash"]), m(st["stf"]), m(st["debt"]), m(st["lease"]), m(st["assets"]), m(st["liab"]), m(st["eq"]), m(st["nci"])],
             "di": st["debt_items"][:6], "ai": a["da_items"][:6],
             "s": [sh["iss"], sh["tre"], sh["out"]] if sh else None}
    px = price(sc) if time.time() < DEADLINE else None
    if px:
        e["px"] = px
    return e


def main():
    if not API_KEY:
        print("DART_API_KEY 없음"); return
    old = {}
    if os.path.exists(OUT):
        try:
            old = {x["c"]: x for x in json.load(open(OUT, encoding="utf-8"))["c"]}
        except Exception:
            old = {}
    idx = {x["c"]: x for x in json.load(open("match_index.json", encoding="utf-8"))["c"]}
    cm = load_corp_map()
    reps = report_index()
    print("정기보고서 목록 회사 수", len(reps), "호출", calls[0], flush=True)
    todo = []
    for sc, (corp, nm) in cm.items():
        if corp not in reps:
            continue
        pl = plan(reps[corp])
        if not pl:
            continue
        x = idx.get(sc, {})
        todo.append((sc, corp, x.get("n") or nm, x.get("m") or "", x.get("ic") or "", pl))
    # 새로 받아야 하는 회사부터
    todo.sort(key=lambda t: (t[0] in old and old[t[0]].get("basis") == [t[5]["fy"][2], (t[5].get("L") or ("", "", ""))[2], (t[5].get("P") or ("", "", ""))[2]], t[0]))
    res = dict(old)
    done = [0]

    def run(t):
        try:
            e = build(t, old.get(t[0]))
        except RuntimeError:
            e = old.get(t[0])
            if e is not None and time.time() < DEADLINE:
                p = price(t[0])
                if p:
                    e = dict(e); e["px"] = p
        except Exception as ex:
            with lock:
                log.append(f"{t[2]} 오류 {type(ex).__name__}")
            e = old.get(t[0])
        if e:
            with lock:
                res[t[0]] = e
                done[0] += 1
                if done[0] % 200 == 0:
                    print(f"  {done[0]}/{len(todo)} 호출 {calls[0]}", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(run, todo))
    live = {t[0] for t in todo}
    rows = [v for k, v in res.items() if k in live and v.get("t")]
    rows.sort(key=lambda v: v["c"])
    pending = sum(1 for t in todo if not res.get(t[0]) or res[t[0]].get("basis") != [t[5]["fy"][2], (t[5].get("L") or ("", "", ""))[2], (t[5].get("P") or ("", "", ""))[2]])
    json.dump({"updated": TODAY.isoformat(), "unit": "백만원", "n": len(rows), "pending": pending,
               "c": rows}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("완료", len(rows), "남은 회사", pending, "호출", calls[0])
    print("\n".join(log[:30]))


if __name__ == "__main__":
    main()
