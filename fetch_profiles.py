"""상장사 12월 결산 사업보고서(최신 사업연도) → 사업내용·주요제품·원재료·매출·재무 요약 수집.
- 대상: list.json(정기공시 A001)에서 '사업보고서 (YYYY.12)' 를 낸 상장사 (종목코드 있는 법인)
- 텍스트: 사업보고서 원문(document.xml)의 'II. 사업의 내용' 1~4절
- 재무: fnlttMultiAcnt (최대 100개사씩) — 최근 3개년 매출·영업이익·순이익·자산·부채·자본
결과: company_profiles.jsonl  (환경변수 PILOT=회사명,회사명 이면 일부만 수행해 profiles_pilot.json 저장)
"""
import os, re, io, json, time, zipfile, html as htmllib, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import requests

API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/"
PILOT = [x.strip() for x in os.environ.get("PILOT", "").split(",") if x.strip()]
FY = int(os.environ.get("FY", "2025"))
OUT = "company_profiles.jsonl"
CACHE = "profiles_cache.json"
LOG = "profiles_log.txt"
CAP = 12000                       # 절당 최대 글자 수
START = time.time()
BUDGET = 150 * 60
_lock = threading.Lock()
_logs = []


def log(m):
    print(m, flush=True); _logs.append(str(m))


def call(name, params, raw=False, tries=3):
    for i in range(tries):
        try:
            r = requests.get(BASE + name, params=dict(params, crtfc_key=API_KEY), timeout=60)
            r.raise_for_status()
            return r.content if raw else r.json()
        except (requests.RequestException, ValueError):
            time.sleep(1.5 * (i + 1))
    return None if raw else {"status": "999"}


def find_reports():
    """FY 사업보고서(12월 결산) 목록: corp_code -> 가장 최근 접수"""
    best = {}
    y = FY + 1
    for m in range(1, 13):
        bgn = dt.date(y, m, 1)
        if bgn > dt.date.today():
            break
        end = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        page = 1
        while True:
            d = call("list.json", {"bgn_de": bgn.strftime("%Y%m%d"), "end_de": min(end, dt.date.today()).strftime("%Y%m%d"),
                                   "pblntf_detail_ty": "A001", "page_no": page, "page_count": 100})
            if d.get("status") != "000":
                break
            for it in d.get("list", []):
                nm = it.get("report_nm", "")
                if "사업보고서" in nm and f"({FY}.12)" in nm and (it.get("stock_code") or "").strip():
                    cc = it["corp_code"]
                    if cc not in best or it["rcept_no"] > best[cc]["rcept_no"]:
                        best[cc] = {"corp_code": cc, "name": it["corp_name"], "code": it["stock_code"].strip(),
                                    "rcept_no": it["rcept_no"], "report_nm": nm.strip(), "date": it["rcept_dt"]}
            if page >= int(d.get("total_page", 1)):
                break
            page += 1
    return best


def num(v):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


ACCS = {"매출액": "rev", "수익(매출액)": "rev", "영업수익": "rev", "영업이익": "op", "영업이익(손실)": "op",
        "당기순이익": "ni", "당기순이익(손실)": "ni", "자산총계": "asset", "부채총계": "debt", "자본총계": "equity"}


def fetch_fin(corps):
    """corp_code 목록 → {corp_code: {fs, years:{2025:{rev,..}}}} (원)"""
    out = {}
    ids = list(corps)
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        d = call("fnlttMultiAcnt.json", {"corp_code": ",".join(chunk), "bsns_year": str(FY), "reprt_code": "11011"})
        if d.get("status") != "000":
            log(f"재무 조회 실패 {i}: {d.get('status')} {d.get('message')}")
            continue
        by = {}
        for r in d.get("list", []):
            by.setdefault(r["corp_code"], []).append(r)
        for cc, rows in by.items():
            for fsd in ("CFS", "OFS"):
                sub = [r for r in rows if r.get("fs_div") == fsd]
                if not sub:
                    continue
                years = {str(FY): {}, str(FY - 1): {}, str(FY - 2): {}}
                for r in sub:
                    k = ACCS.get((r.get("account_nm") or "").strip())
                    if not k:
                        continue
                    for yy, f in ((FY, "thstrm_amount"), (FY - 1, "frmtrm_amount"), (FY - 2, "bfefrmtrm_amount")):
                        v = num(r.get(f))
                        if v is not None and k not in years[str(yy)]:
                            years[str(yy)][k] = v
                out[cc] = {"fs": "연결" if fsd == "CFS" else "별도", "years": years}
                break
        time.sleep(0.2)
    return out


# ── 원문에서 사업의 내용 1~4절 추출 ──
def norm(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV").replace("Ⅴ", "V")
    return re.sub(r"\s+", "", s)


def to_text(frag):
    t = re.sub(r"</(TR|P|BR|TITLE)\s*>", "\n", frag)
    t = re.sub(r"</(TD|TH|TE|TU)\s*>", " | ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", x).strip(" |") for x in t.split("\n")]
    return "\n".join(x for x in lines if x)


TARGETS = [("overview", 1, "사업의개요"), ("products", 2, "주요제품"), ("materials", 3, "원재료"), ("sales", 4, "매출및수주")]
ROMAN = re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.")


def doc_xml(rcept):
    raw = call("document.xml", {"rcept_no": rcept}, raw=True)
    if not raw or raw[:5] == b"<?xml":
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = z.namelist()
        # 가장 큰 xml이 본문
        name = max(names, key=lambda n: z.getinfo(n).file_size)
        data = z.read(name)
    except Exception:
        return None
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return None


def extract(xml, debug=False):
    titles = [(m.start(), m.end(), norm(m.group(1))) for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S)]
    if debug:
        log("   제목 샘플: " + " / ".join(t[2][:22] for t in titles[:45]))
    # 'II. 사업의 내용' 위치
    start_i = next((i for i, t in enumerate(titles) if re.match(r"^II\.?사업의내용", t[2])), None)
    if start_i is None:
        return {}
    res = {}
    for key, n, kw in TARGETS:
        s = next((i for i in range(start_i, len(titles)) if re.match(rf"^{n}\.", titles[i][2]) and kw in titles[i][2]), None)
        if s is None:
            continue
        e = len(titles)
        for j in range(s + 1, len(titles)):
            t = titles[j][2]
            if t.startswith(f"{n + 1}.") or ROMAN.match(t):
                e = j
                break
        end_pos = titles[e][0] if e < len(titles) else len(xml)
        txt = to_text(xml[titles[s][1]:end_pos])
        res[key] = txt[:CAP] + (" …(이하 생략)" if len(txt) > CAP else "")
        res[key + "_len"] = len(txt)
    return res


def eok(v):
    return None if v is None else round(v / 1e8, 1)


def main():
    reps = find_reports()
    log(f"{FY}년 12월 결산 사업보고서 제출 상장사 {len(reps)}곳")
    if PILOT:
        reps = {k: v for k, v in reps.items() if v["name"] in PILOT}
        log(f"시범 대상: {[v['name'] for v in reps.values()]}")
    fin = fetch_fin(reps.keys())
    log(f"재무 확보 {len(fin)}곳")
    cache = json.load(open(CACHE, encoding="utf-8")) if (os.path.exists(CACHE) and not PILOT) else {}
    first = {"n": 0}

    def work(r):
        if r["rcept_no"] in cache or time.time() - START > BUDGET:
            return
        xml = doc_xml(r["rcept_no"])
        time.sleep(0.05)
        if xml is None:
            return
        dbg = PILOT and first["n"] < 3
        if dbg:
            first["n"] += 1
            log(f"[{r['name']}] 원문 {len(xml):,}자")
        sec = extract(xml, debug=dbg)
        if dbg:
            log("   추출: " + str({k: v for k, v in sec.items() if k.endswith('_len')}))
        with _lock:
            cache[r["rcept_no"]] = sec

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, reps.values()))
    rows = []
    for cc, r in sorted(reps.items(), key=lambda x: x[1]["code"]):
        sec = cache.get(r["rcept_no"], {})
        f = fin.get(cc, {})
        row = {"종목코드": r["code"], "회사명": r["name"], "사업연도": FY, "접수일": r["date"], "보고서": r["report_nm"],
               "공시링크": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
               "사업의 개요": sec.get("overview"), "주요 제품 및 서비스": sec.get("products"),
               "원재료 및 생산설비": sec.get("materials"), "매출 및 수주상황": sec.get("sales"),
               "재무구분": f.get("fs")}
        for y in (FY, FY - 1, FY - 2):
            d = (f.get("years") or {}).get(str(y), {})
            for k, lab in (("rev", "매출액"), ("op", "영업이익"), ("ni", "순이익"), ("asset", "자산총계"), ("debt", "부채총계"), ("equity", "자본총계")):
                row[f"{y} {lab}(억)"] = eok(d.get(k))
        rows.append(row)
    if PILOT:
        json.dump(rows, open("profiles_pilot.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        with open(OUT, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    ok = sum(1 for r in rows if r["사업의 개요"])
    log(f"완료: {len(rows)}곳 / 본문 추출 성공 {ok}곳 / 재무 {sum(1 for r in rows if r['재무구분'])}곳")


if __name__ == "__main__":
    try:
        main()
    finally:
        open(LOG, "w", encoding="utf-8").write("\n".join(_logs))
