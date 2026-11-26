"""종자·농업 투입재 상장사 Peer 재무 원문 수집 → seed_peers.json (main 에는 올리지 않음)

- DART 단일회사 전체 재무제표(연결) : 2025 사업보고서, 2025 반기, 2026 반기 (+ 2026 3분기 참고)
- 주식 총수 현황(발행주식수·자기주식), 보고서 접수번호
- 2025 사업보고서 본문 'II. 사업의 내용' 중 부문별 매출 표
- 일별 종가 (KRX 정보데이터시스템 우선, 실패 시 네이버 금융 일봉)
"""
import io, os, re, json, time, zipfile
from html import unescape
import requests
from fetch_peers import load_corp_map

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
CODES = {"054050": "NH농우바이오", "002100": "경농", "154030": "아시아종묘", "025860": "남해화학", "097870": "효성오앤비"}
MAIN = {"054050", "002100"}
REP = [("2025", "11011"), ("2025", "11012"), ("2026", "11012"), ("2026", "11014"), ("2024", "11011")]
out = {"fin": {}, "stock": {}, "list": {}, "biz": {}, "price": {}, "log": []}


def get(path, **p):
    p["crtfc_key"] = API_KEY
    for a in range(4):
        try:
            r = requests.get(BASE + path, params=p, timeout=60)
            if path.endswith(".xml"):
                return r.content
            j = r.json()
            if j.get("status") == "020":
                time.sleep(5); continue
            return j
        except Exception as e:
            time.sleep(2 + a)
    return None


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()


cm = load_corp_map()
for sc, nm in CODES.items():
    corp = cm[sc][0]
    out["log"].append(f"{nm} corp_code={corp}")
    j = get("list.json", corp_code=corp, bgn_de="20240101", end_de="20261127", pblntf_ty="A", page_count=100)
    out["list"][sc] = [{k: x[k] for k in ("report_nm", "rcept_no", "rcept_dt")} for x in (j or {}).get("list", [])]
    for y, rc in REP:
        if sc not in MAIN and rc in ("11012",) and y == "2025":
            pass
        for fs in ("CFS", "OFS"):
            j = get("fnlttSinglAcntAll.json", corp_code=corp, bsns_year=y, reprt_code=rc, fs_div=fs)
            if j and j.get("status") == "000":
                out["fin"][f"{sc}_{y}_{rc}"] = {"fs": fs, "rows": [{k: x.get(k) for k in ("rcept_no", "sj_div", "sj_nm", "account_id", "account_nm", "account_detail", "thstrm_amount", "thstrm_add_amount", "frmtrm_amount", "frmtrm_add_amount", "ord")} for x in j["list"]]}
                break
            time.sleep(0.2)
        j = get("stockTotqySttus.json", corp_code=corp, bsns_year=y, reprt_code=rc)
        if j and j.get("status") == "000":
            out["stock"][f"{sc}_{y}_{rc}"] = j["list"]
        time.sleep(0.2)
    # 2025 사업보고서 본문 - 사업의 내용
    rep = [x for x in out["list"][sc] if x["report_nm"].startswith("사업보고서") and "2025.12" in x["report_nm"]]
    if rep and sc in MAIN:
        b = get("document.xml", rcept_no=rep[0]["rcept_no"])
        try:
            z = zipfile.ZipFile(io.BytesIO(b))
            docs = []
            for n in z.namelist():
                raw = z.read(n)
                for enc in ("utf-8", "euc-kr", "cp949"):
                    try:
                        t = raw.decode(enc); break
                    except Exception:
                        t = raw.decode("utf-8", "ignore")
                docs.append((n, t))
            docs.sort(key=lambda d: -len(d[1]))
            xml = docs[0][1]
            i = xml.find("사업의 내용")
            j2 = xml.find("재무에 관한 사항", i + 10)
            sec = xml[i:j2 if j2 > 0 else i + 400000]
            tabs = []
            for tm in re.finditer(r"<TABLE[^>]*>(.*?)</TABLE>", sec, re.S | re.I):
                before = clean(sec[max(0, tm.start() - 600):tm.start()])[-300:]
                rows = []
                for rm in re.finditer(r"<TR[^>]*>(.*?)</TR>", tm.group(1), re.S | re.I):
                    cells = [clean(c) for c in re.findall(r"<(?:TD|TE|TH|TU)[^>]*>(.*?)</(?:TD|TE|TH|TU)>", rm.group(1), re.S | re.I)]
                    if any(cells):
                        rows.append(cells)
                tabs.append({"before": before, "rows": rows[:40]})
            out["biz"][sc] = {"rcept_no": rep[0]["rcept_no"], "tables": tabs, "text": clean(sec)[:60000],
                              "page_hint": [n for n, _ in docs]}
        except Exception as e:
            out["log"].append(f"{nm} 본문 오류 {e}")

# 일별 종가
ISIN = {"054050": "KR7054050009", "002100": "KR7002100007"}
for sc in MAIN:
    got = None
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020103"})
        r = s.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd", data={
            "bld": "dbms/MDC/STAT/standard/MDCSTAT01701", "locale": "ko_KR", "isuCd": ISIN[sc], "isuCd2": sc,
            "strtDd": "20260501", "endDd": "20261127", "adjStkPrc_check": "Y", "adjStkPrc": "2", "share": "1", "money": "1", "csvxls_isNo": "false"}, timeout=30)
        rows = r.json().get("output") or []
        if rows:
            got = {"src": "KRX 정보데이터시스템 개별종목 시세추이(MDCSTAT01701)", "rows": [(x["TRD_DD"], x["TDD_CLSPRC"]) for x in rows]}
    except Exception as e:
        out["log"].append(f"KRX {sc} 실패 {e}")
    if not got:
        try:
            r = requests.get("https://fchart.stock.naver.com/sise.nhn", params={"symbol": sc, "timeframe": "day", "count": 200, "requestType": 0}, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            items = re.findall(r'data="([^"]+)"', r.text)
            got = {"src": "네이버 금융 일봉(fchart, KRX 시세 재배포)", "rows": [(x.split("|")[0], x.split("|")[4]) for x in items]}
        except Exception as e:
            out["log"].append(f"naver {sc} 실패 {e}")
    out["price"][sc] = got

json.dump(out, open("seed_peers.json", "w", encoding="utf-8"), ensure_ascii=False)
print("\n".join(out["log"]))
print({k: len(v["rows"]) for k, v in out["fin"].items()})
print({k: (v or {}).get("src") and len(v["rows"]) for k, v in out["price"].items()})
