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


def extract_metrics(rows):
    op = None
    da = 0.0
    da_found = False
    cash = debt = nci = 0.0
    ni = None
    for r in rows:
        nm = (r.get("account_nm") or "").strip()
        aid = (r.get("account_id") or "").strip()
        sj = (r.get("sj_div") or "").strip()
        amt = parse_amt(r.get("thstrm_amount"))
        if amt is None:
            continue
        if sj in ("IS", "CIS"):
            if aid == "dart_OperatingIncomeLoss" or nm in ("영업이익", "영업이익(손실)"):
                if op is None:
                    op = amt
            if ni is None and (aid == "ifrs-full_ProfitLossAttributableToOwnersOfParent"
                               or nm in ("지배기업의 소유주에게 귀속되는 당기순이익", "지배기업 소유주지분", "지배기업소유주지분",
                                         "지배기업의 소유주에게 귀속되는 당기순이익(손실)")):
                ni = amt
        elif sj == "CF":
            if "상각" in nm and "상각후원가" not in nm and "대손" not in nm and "할인발행" not in nm and "사채" not in nm:
                da += amt
                da_found = True
        elif sj == "BS":
            if nm in DEBT_NAMES:
                debt += amt
            elif nm in CASH_NAMES:
                cash += amt
            elif nm in NCI_NAMES:
                nci += amt
    if ni is None:
        for r in rows:
            if (r.get("sj_div") or "") in ("IS", "CIS") and (r.get("account_nm") or "").strip() in ("당기순이익", "당기순이익(손실)", "연결당기순이익"):
                ni = parse_amt(r.get("thstrm_amount"))
                if ni is not None:
                    break
    return {"op": op, "da": da if da_found else None, "cash": cash, "debt": debt, "nci": nci, "ni": ni}


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
            reasons.append("영업이익/감가상각비 항목 미식별")
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
           "sectors": sectors_out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("peers.json 저장 완료")


if __name__ == "__main__":
    main()
