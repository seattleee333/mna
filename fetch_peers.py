"""업종별 피어(비교 상장사)의 EV/EBITDA·PER 배수를 계산해 peers.json을 만든다.

- 업종 분류·피어 후보: peers_seed.json (AI가 제안한 초안, 사람이 검토)
- 재무 데이터: DART 오픈API 전체 재무제표(fnlttSinglAcntAll) — 영업이익, 감가상각비, 차입금, 현금, 순이익
- 시가총액: 네이버 증권(공개 페이지/모바일 API)
- 결과: 업종별 EV/EBITDA·PER의 25%/중앙값/75% 분위수 (보수/기본/낙관 시나리오에 대응)
"""
import io
import os
import re
import json
import time
import zipfile
import datetime as dt
import statistics
import xml.etree.ElementTree as ET

import requests

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
SEED = "peers_seed.json"
OUT = "peers.json"
DEBUG = []
START = time.time()
BUDGET = 28 * 60  # XBRL 조회에 쓸 수 있는 총 시간(초)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

DEBT_NAMES = {"단기차입금", "장기차입금", "유동성장기차입금", "유동성장기부채", "유동성사채", "사채",
              "차입금", "단기사채", "리스부채", "유동리스부채", "비유동리스부채", "유동성리스부채",
              "장기사채", "전환사채", "신주인수권부사채", "유동성전환사채"}
CASH_NAMES = {"현금및현금성자산", "현금 및 현금성자산", "단기금융상품", "단기금융자산", "단기투자자산",
              "단기예금", "단기금융기관예치금", "당기손익-공정가치측정금융자산(유동)"}
NCI_NAMES = {"비지배지분"}


def parse_amt(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_corp_map():
    """종목코드 -> (corp_code, DART 법인명)"""
    r = requests.get(BASE + "corpCode.xml", params={"crtfc_key": API_KEY}, timeout=60)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(zf.read(zf.namelist()[0]))
    m = {}
    for it in root.findall("list"):
        sc = (it.findtext("stock_code") or "").strip()
        if sc:
            m[sc] = ((it.findtext("corp_code") or "").strip(), (it.findtext("corp_name") or "").strip())
    return m


def fetch_fin(corp_code, year):
    for fs_div in ("CFS", "OFS"):
        try:
            r = requests.get(BASE + "fnlttSinglAcntAll.json", params={
                "crtfc_key": API_KEY, "corp_code": corp_code, "bsns_year": str(year),
                "reprt_code": "11011", "fs_div": fs_div}, timeout=30)
            j = r.json()
        except Exception:
            continue
        if j.get("status") == "000" and j.get("list"):
            return j["list"], fs_div
        time.sleep(0.15)
    return None, None


def norm_nm(nm):
    """계정명 정규화: 공백·로마숫자·번호 접두어 제거"""
    nm = re.sub(r"\s+", "", nm or "")
    return re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX0-9]+[\.\)]", "", nm)


def extract_metrics(rows):
    op = None
    da_cf = 0.0
    da_found = False
    da_is = 0.0   # 손익계산서/주석에 따로 나온 감가상각비(대체)
    da_is_found = False
    cash = debt = nci = 0.0
    ni = None
    gp = sga = None
    for r in rows:
        raw = (r.get("account_nm") or "").strip()
        nm = norm_nm(raw)
        aid = (r.get("account_id") or "").strip()
        sj = (r.get("sj_div") or "").strip()
        amt = parse_amt(r.get("thstrm_amount"))
        if amt is None:
            continue
        if sj in ("IS", "CIS"):
            if op is None and (aid == "dart_OperatingIncomeLoss" or nm.startswith("영업이익") or nm.startswith("영업손익")
                               or nm.startswith("영업손실")):
                op = amt
            if gp is None and (aid == "ifrs-full_GrossProfit" or nm.startswith("매출총이익") or nm.startswith("매출총손익")):
                gp = amt
            if sga is None and (aid == "dart_TotalSellingGeneralAdministrativeExpenses" or nm.startswith("판매비와관리비")
                                or nm.startswith("판매비와일반관리비")):
                sga = amt
            if ni is None and (aid == "ifrs-full_ProfitLossAttributableToOwnersOfParent"
                               or "지배기업" in nm and "소유주" in nm and "당기" in nm
                               or nm in ("지배기업소유주지분", "지배기업의소유주에게귀속되는당기순이익")):
                ni = amt
            if "감가상각" in nm or "무형자산상각" in nm or "Depreciation" in aid or "Amortisation" in aid:
                da_is += amt
                da_is_found = True
        elif sj == "CF":
            low_aid = aid
            is_da = ("상각" in nm and not any(x in nm for x in ("상각후원가", "대손", "할인발행", "사채", "현재가치", "손상")))
            is_da = is_da or ("Depreciation" in low_aid or "Amortisation" in low_aid) and "Impairment" not in low_aid
            if is_da:
                da_cf += amt
                da_found = True
        elif sj == "BS":
            if nm in {re.sub(r"\s+", "", x) for x in DEBT_NAMES}:
                debt += amt
            elif nm in {re.sub(r"\s+", "", x) for x in CASH_NAMES}:
                cash += amt
            elif nm in NCI_NAMES:
                nci += amt
    if op is None and gp is not None and sga is not None:
        op = gp - abs(sga)
    if ni is None:
        for r in rows:
            if (r.get("sj_div") or "") in ("IS", "CIS") and norm_nm(r.get("account_nm")) in ("당기순이익", "당기순이익(손실)", "연결당기순이익", "당기순손익"):
                ni = parse_amt(r.get("thstrm_amount"))
                if ni is not None:
                    break
    da = da_cf if da_found else (da_is if da_is_found else None)
    return {"op": op, "da": da, "cash": cash, "debt": debt, "nci": nci, "ni": ni}


def find_annual_rcept(corp_code, year):
    """해당 사업연도 사업보고서 접수번호"""
    try:
        r = requests.get(BASE + "list.json", params={
            "crtfc_key": API_KEY, "corp_code": corp_code, "bgn_de": f"{year + 1}0101", "end_de": f"{year + 1}1231",
            "pblntf_detail_ty": "A001", "last_reprt_at": "Y", "page_count": 20}, timeout=30).json()
    except Exception:
        return None
    best = None
    for it in r.get("list", []) or []:
        nm = it.get("report_nm", "")
        if "사업보고서" in nm and "기재정정" not in nm:
            best = it["rcept_no"]
            break
        if "사업보고서" in nm and best is None:
            best = it["rcept_no"]
    return best


def da_from_xbrl(corp_code, year, fs_div):
    """재무제표 API에 영업활동 상세가 없을 때, XBRL 원문에서 감가상각비+무형자산상각비를 추출 (원 단위)"""
    rcept = find_annual_rcept(corp_code, year)
    if not rcept:
        return None, "사업보고서 접수번호 없음"
    try:
        t0 = time.time()
        buf = io.BytesIO()
        with requests.get(BASE + "fnlttXbrl.xml", params={"crtfc_key": API_KEY, "rcept_no": rcept, "reprt_code": "11011"},
                          timeout=(15, 30), stream=True) as r:
            for chunk in r.iter_content(1 << 16):
                buf.write(chunk)
                if time.time() - t0 > 60 or buf.tell() > 60 * 1024 * 1024:
                    return None, "XBRL 다운로드 시간/용량 초과"
        zf = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    except Exception as e:
        return None, f"XBRL 다운로드 실패({type(e).__name__})"
    names = [n for n in zf.namelist() if n.lower().endswith((".xbrl", ".xml"))]
    names.sort(key=lambda n: (0 if n.lower().endswith(".xbrl") else 1))
    if not names:
        return None, "XBRL 파일 없음"
    try:
        root = ET.fromstring(zf.read(names[0]))
    except Exception:
        return None, "XBRL 파싱 실패"
    # 컨텍스트: 차원(세그먼트) 없는 당기 연간 기간
    ctx = {}
    for c in root.iter():
        if c.tag.endswith("}context"):
            seg = any(x.tag.endswith(("}segment", "}scenario")) for x in c.iter())
            st = en = None
            for x in c.iter():
                if x.tag.endswith("}startDate"): st = (x.text or "").strip()
                elif x.tag.endswith("}endDate"): en = (x.text or "").strip()
            if st and en and not seg:
                ctx[c.get("id")] = (st, en)
    if not ctx:
        return None, "XBRL 컨텍스트 없음"
    last_end = max(e for _, e in ctx.values())
    cur = {k for k, (a, e) in ctx.items() if e == last_end and 300 <= (dt.date.fromisoformat(e) - dt.date.fromisoformat(a)).days <= 380}
    found = {}
    for el in root.iter():
        if el.get("contextRef") in cur and el.text:
            local = el.tag.split("}")[-1]
            if ("Depreciation" in local or "Amortisation" in local or "Amortization" in local) and "Impairment" not in local \
               and "Accumulated" not in local and "Reversal" not in local:
                v = parse_amt(el.text)
                if v is not None:
                    found.setdefault(local, v)
    if not found:
        return None, "XBRL에 상각비 태그 없음"
    combo = [v for k, v in found.items() if "DepreciationAndAmortisation" in k and k.startswith("AdjustmentsFor")]
    if combo:
        return abs(combo[0]), None
    adj = {k: v for k, v in found.items() if k.startswith("AdjustmentsFor")}
    if adj:
        return abs(sum(adj.values())), None
    # 현금흐름 조정 항목이 없으면 비용 항목(주석)에서 큰 순으로 감가+무형만 합산
    dep = [v for k, v in found.items() if k in ("DepreciationExpense", "DepreciationPropertyPlantAndEquipment", "DepreciationOfPropertyPlantAndEquipment")]
    amo = [v for k, v in found.items() if k in ("AmortisationExpense", "AmortisationIntangibleAssetsOtherThanGoodwill")]
    if dep or amo:
        return abs(max(dep, default=0)) + abs(max(amo, default=0)), None
    return None, "XBRL 상각비 태그 분류 실패"


def parse_korean_money(s):
    """'1조 2,345억' / '2,345억' / '3,456,789' 같은 표기를 원 단위로"""
    if s is None:
        return None
    s = str(s).replace(",", "").replace(" ", "")
    m = re.match(r"^(?:(\d+(?:\.\d+)?)조)?(?:(\d+(?:\.\d+)?)억)?(?:(\d+(?:\.\d+)?)만)?$", s)
    if m and any(m.groups()):
        jo, eok, man = (float(x) if x else 0.0 for x in m.groups())
        return jo * 1e12 + eok * 1e8 + man * 1e4
    try:
        return float(s)
    except ValueError:
        return None


def fetch_mcap(code):
    """시가총액(원). 네이버 증권 모바일 API → 데스크톱 페이지 순으로 시도."""
    try:
        r = requests.get(f"https://m.stock.naver.com/api/stock/{code}/integration", headers=UA, timeout=15)
        if r.ok:
            j = r.json()
            for it in j.get("totalInfos", []):
                if it.get("code") == "marketValue" or it.get("key") == "시총":
                    v = parse_korean_money(it.get("value"))
                    if v:
                        return v, "naver_mobile"
    except Exception:
        pass
    try:
        r = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers=UA, timeout=15)
        if r.ok:
            r.encoding = r.apparent_encoding or "euc-kr"
            m = re.search(r'id="_market_sum"[^>]*>\s*([^<]+)<', r.text)
            if m:
                txt = re.sub(r"\s+", "", m.group(1))
                v = parse_korean_money(txt)
                if v:
                    return v * 1e8 if v < 1e9 and "조" not in txt and "억" not in txt else v, "naver_desktop"
    except Exception:
        pass
    # 마지막 폴백: 네이버 주가 API(종가) × DART 발행주식 수는 복잡하므로 polling API의 시가총액 필드 시도
    try:
        r = requests.get(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}", headers=UA, timeout=15)
        if r.ok:
            d = (r.json().get("datas") or [{}])[0]
            v = parse_korean_money(d.get("marketValue") or d.get("marketCap"))
            if v:
                return (v * 1e6 if v < 1e11 else v), "naver_polling"
    except Exception:
        pass
    return None, None


def quantiles(vals):
    vals = sorted(vals)
    n = len(vals)
    if n < 3:
        return None
    def q(p):
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        return vals[f] + (vals[c] - vals[f]) * (k - f)
    return {"down": round(q(0.25), 1), "base": round(statistics.median(vals), 1), "up": round(q(0.75), 1), "n": n}


def main():
    if not API_KEY:
        print("DART_API_KEY가 없어 peers.json을 갱신하지 않습니다.")
        return
    with open(SEED, encoding="utf-8") as f:
        seed = json.load(f)

    corp_map = load_corp_map()
    print(f"DART 상장사 매핑 {len(corp_map)}건")
    now = dt.datetime.utcnow() + dt.timedelta(hours=9)
    years = [now.year - 1, now.year - 2]

    cache = {}  # 종목코드 -> 결과 (같은 종목이 여러 업종에 있을 수 있음)

    def compute(name, code):
        if code in cache:
            return cache[code]
        out = {"name": name, "code": code, "ok": False}
        if code not in corp_map:
            out["reason"] = "DART 종목코드 없음"
            cache[code] = out
            return out
        corp_code, dart_name = corp_map[code]
        out["dart_name"] = dart_name
        rows = fs = year = None
        for y in years:
            rows, fs = fetch_fin(corp_code, y)
            if rows:
                year = y
                break
        if not rows:
            out["reason"] = "재무제표 조회 실패"
            cache[code] = out
            return out
        mt = extract_metrics(rows)
        out.update({"year": year, "fs": fs})
        if mt["da"] is None and time.time() - START > BUDGET:
            out["da_why"] = "시간 예산 초과"
        elif mt["da"] is None:
            print("  XBRL 조회:", name, flush=True)
            xda, xwhy = da_from_xbrl(corp_code, year, fs)
            if xda is not None:
                mt["da"] = xda
                out["da_src"] = "xbrl"
            else:
                out["da_why"] = xwhy
        mcap, src = fetch_mcap(code)
        time.sleep(0.2)
        if not mcap:
            out["reason"] = "시가총액 조회 실패"
            cache[code] = out
            return out
        out["mcap_eok"] = round(mcap / 1e8)
        out["mcap_src"] = src
        reasons = []
        if mt["op"] is not None and mt["da"] is not None:
            ebitda = mt["op"] + mt["da"]
            ev = mcap + mt["debt"] - mt["cash"] + mt["nci"]
            out["ebitda_eok"] = round(ebitda / 1e8, 1)
            out["ev_eok"] = round(ev / 1e8)
            if ebitda > 0 and ev > 0:
                mult = ev / ebitda
                if 0 < mult <= 50:
                    out["evEbitda"] = round(mult, 1)
                else:
                    reasons.append(f"EV/EBITDA 범위 밖({mult:.1f})")
            else:
                reasons.append("EBITDA 또는 EV가 0 이하")
        else:
            reasons.append("영업이익 미식별" if mt["op"] is None else "감가상각비 미식별(" + str(out.get("da_why", "")) + ")")
        if mt["ni"] is not None and mt["ni"] > 0:
            per = mcap / mt["ni"]
            if 0 < per <= 100:
                out["per"] = round(per, 1)
            else:
                reasons.append(f"PER 범위 밖({per:.1f})")
        else:
            reasons.append("지배주주순이익 없음/적자")
        out["ok"] = "evEbitda" in out or "per" in out
        if reasons:
            out["reason"] = "; ".join(reasons)
        cache[code] = out
        time.sleep(0.2)
        return out

    sectors_out = []
    for s in seed["sectors"]:
        peers = []
        for name, code in s["peers"]:
            try:
                peers.append(compute(name, code))
            except Exception as e:
                peers.append({"name": name, "code": code, "ok": False, "reason": f"오류: {e}"})
        ev_vals = [p["evEbitda"] for p in peers if "evEbitda" in p]
        per_vals = [p["per"] for p in peers if "per" in p]
        sectors_out.append({
            "id": s["id"], "name": s["name"], "keywords": s["keywords"],
            "stats": {"evEbitda": quantiles(ev_vals), "per": quantiles(per_vals)},
            "peers": peers,
        })
        st = sectors_out[-1]["stats"]
        print(f"{s['name']}: EV/EBITDA {st['evEbitda']} PER {st['per']} (유효 {len(ev_vals)}/{len(peers)})")

    out = {"updated": now.strftime("%Y%m%d"),
           "note": "최근 사업연도 재무제표(DART)와 현재 시가총액(네이버 증권)으로 계산한 참고용 배수입니다. 25%/중앙값/75% 분위수를 보수/기본/낙관에 대응시킵니다.",
           "sectors": sectors_out, "debug": DEBUG}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("peers.json 저장 완료")


if __name__ == "__main__":
    main()
