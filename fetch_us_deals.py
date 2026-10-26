"""미국 M&A 딜 수집 — SEC EDGAR(공식, 무료·키 불필요)의 8-K 공시에서 인수·매각 건을 찾는다.

1) 일별 인덱스(daily-index)에서 8-K 목록을 받는다.
2) 각 공시 앞부분(헤더)의 Item 번호로 거른다: 2.01(인수·처분 완료), 1.01(중요 계약 체결, 인수 관련 키워드가 있는 것만)
3) 본문을 읽어 누가 누구를 얼마에 인수했는지 한글로 요약한다.
   - ANTHROPIC_API_KEY가 있으면 Claude로 요약·번역, 없으면 금액 후보만 뽑아 간단히 표시한다.
결과: us_deals.json (이어하기 캐시: us_cache.json)
"""
import os, re, json, time, html as htmllib, datetime as dt
import requests

UA = os.environ.get("SEC_USER_AGENT") or "ALL-ABOUT-MNA/1.0 (https://github.com/seattleee333/mna)"
SINCE = os.environ.get("US_SINCE") or "20261001"
OUT, CACHE = "us_deals.json", "us_cache.json"
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("US_MODEL", "claude-haiku-4-5-20251001")
MAX_FILINGS = int(os.environ.get("US_MAX", "4000"))
MAX_LLM = 250
START = time.time()
BUDGET = 80 * 60

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
_last = [0.0]
log_lines = []


def log(m):
    print(m, flush=True)
    log_lines.append(m)


def throttle():
    d = time.time() - _last[0]
    if d < 0.13:      # SEC 권고: 초당 10건 이하
        time.sleep(0.13 - d)
    _last[0] = time.time()


def get(url, **kw):
    for i in range(3):
        throttle()
        try:
            r = S.get(url, timeout=40, **kw)
            if r.status_code in (429, 503):
                time.sleep(5 * (i + 1))
                continue
            return r
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    return None


def days():
    d = dt.datetime.strptime(SINCE, "%Y%m%d").date()
    today = dt.date.today()
    while d <= today:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def daily_8k(d):
    q = (d.month - 1) // 3 + 1
    r = get(f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/QTR{q}/form.{d.strftime('%Y%m%d')}.idx")
    if r is None or r.status_code != 200:
        log(f"  인덱스 응답 {None if r is None else r.status_code}: " + ("" if r is None else r.text[:200].replace("\n", " ")))
        return None if (r is not None and r.status_code == 404) else []
    if not getattr(daily_8k, "shown", False):
        daily_8k.shown = True
        log("  인덱스 샘플: " + " // ".join(r.text.splitlines()[:12])[:900])
    out = []
    for line in r.text.splitlines():
        m = re.match(r"^8-K\s+(.+?)\s+(\d{1,10})\s+(\d{8})\s+(edgar/data/\d+/(\d{10}-\d{2}-\d{6})\.txt)\s*$", line)
        if m:
            out.append({"filer": m.group(1).strip(), "cik": m.group(2), "date": m.group(3), "path": m.group(4), "acc": m.group(5)})
    return out


def read_head(path, nbytes):
    r = get("https://www.sec.gov/Archives/" + path, stream=True)
    if r is None or r.status_code not in (200, 206):
        return None
    buf = b""
    for chunk in r.iter_content(8192):
        buf += chunk
        if len(buf) >= nbytes:
            break
    r.close()
    return buf.decode("latin-1", "replace")


def header_items(head):
    items = re.findall(r"ITEM INFORMATION:\s*(.+)", head)
    return [i.strip() for i in items]


DEAL_RE = re.compile(r"(Agreement and Plan of Merger|Merger Agreement|Stock Purchase Agreement|Asset Purchase Agreement|Share Purchase Agreement|"
                     r"Membership Interest Purchase|Equity Purchase Agreement|Purchase and Sale Agreement|to acquire|agreed to acquire|will acquire|"
                     r"to be acquired|tender offer|acquisition of)", re.I)


EXCL_RE = re.compile(r"(Equity Line|ELOC|Common Stock Purchase Agreement|Securities Purchase Agreement|Power Purchase Agreement|"
                     r"Registration Rights Agreement|Credit Agreement|Loan Agreement|Note Purchase Agreement|Underwriting Agreement|"
                     r"At[- ]the[- ]Market|Sales Agreement|Lease Agreement)", re.I)


def body_text(raw):
    m = re.search(r"<TEXT>(.*?)(</TEXT>|$)", raw, re.S | re.I)
    t = m.group(1) if m else raw
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


AMT_RE = re.compile(r"\$\s?[\d][\d,\.]*\s?(?:million|billion|thousand)?", re.I)


def good_amount(w):
    for a in AMT_RE.finditer(w):
        t = a.group(0).strip().rstrip(".,")
        tail = w[a.end(): a.end() + 25].lower()
        if "per share" in tail or "per unit" in tail:
            continue
        digits = re.sub(r"[^\d]", "", t.split(".")[0] if re.search(r"million|billion", t, re.I) else t)
        if re.search(r"million|billion", t, re.I) or (digits and len(digits) >= 7):
            return t
    return None


def fallback(f, text, items):
    amt = None
    for m in re.finditer(r"(consideration|purchase price|aggregate|valued at|enterprise value|for approximately|for a total)", text, re.I):
        w = text[max(0, m.start() - 150): m.end() + 250]
        amt = good_amount(w)
        if amt:
            break
    return {"acquirer": None, "target": None, "amount": amt, "stake": None, "kind": None, "summary_ko": None,
            "summary_en": key_sentence(text, items)}


KEY_RE = re.compile(r"(acqui|merg|sold|sale of|purchase|dispos|divest|tender offer)", re.I)


def key_sentence(text, items):
    """공시 본문에서 인수·매각을 설명하는 핵심 문장 하나를 그대로 뽑는다(영문)."""
    m = re.search(r"Item\s+(2\.01|1\.01)[^A-Za-z]{0,10}[A-Za-z ,\-]{0,90}", text)
    body = text[m.end():] if m else text
    for sent in re.split(r"(?<=[\.;])\s+(?=[A-Z])", body[:6000]):
        if KEY_RE.search(sent) and len(sent) > 40 and "us-gaap" not in sent and not re.search(r"\d{10} (true|false)", sent):
            return sent.strip()[:320]
    return None


PROMPT = """아래는 미국 SEC 8-K 공시(제출 회사: {filer}) 본문 일부다. M&A(인수·합병·지분/사업 매각) 건인지 판단해 JSON으로만 답하라.
{{"is_deal": true/false, "kind": "인수 완료"|"합병·인수 계약"|"매각 완료"|"매각 계약"|"기타",
 "acquirer": "인수(매수)하는 쪽 이름(영문 원문)", "target": "인수 대상 또는 매각 대상(영문 원문)", "seller": "매도인(있으면, 없으면 null)",
 "amount": "거래금액(예: $1.2 billion, 없으면 null)", "stake": "취득 지분율(예: 100%, 없으면 null)",
 "summary_ko": "한 문장 한국어 요약. 예: ‘A사가 B사를 약 12억 달러에 인수 완료’. 금액·지분이 본문에 없으면 만들지 말고 생략"}}
M&A가 아니면 is_deal을 false로. 금액을 추측하지 마라.

본문:
{text}"""


def llm(f, text):
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=90,
                      headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 600,
                            "messages": [{"role": "user", "content": PROMPT.format(filer=f["filer"], text=text[:12000])}]})
    if r.status_code != 200:
        log(f"  LLM 오류 {r.status_code}: {r.text[:200]}")
        return None
    try:
        t = r.json()["content"][0]["text"]
        return json.loads(t[t.index("{"): t.rindex("}") + 1])
    except Exception:
        return None


# ── 올해 전체(과거 구간) 수집: 일별 인덱스를 전부 읽는 대신 SEC 전문검색(efts)으로 후보만 모은다 ──
EFTS_QUERIES = ['"Completion of Acquisition or Disposition of Assets"', '"Item 2.01"',
                '"Agreement and Plan of Merger"', '"Stock Purchase Agreement"', '"Asset Purchase Agreement"',
                '"Merger Agreement"', '"Membership Interest Purchase Agreement"', '"Share Purchase Agreement"']


def efts_candidates(since):
    """since(YYYYMMDD)부터 오늘까지 8-K 중 Item 2.01·1.01 이 있는 건을 월별로 모은다."""
    out = {}
    d = dt.datetime.strptime(since, "%Y%m%d").date().replace(day=1)
    start_day = dt.datetime.strptime(since, "%Y%m%d").date()
    today = dt.date.today()
    while d <= today:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        a, b = max(d, start_day), min(nxt - dt.timedelta(days=1), today)
        for q in EFTS_QUERIES:
            frm = 0
            while frm < 2000 and time.time() - START < BUDGET:
                r = get("https://efts.sec.gov/LATEST/search-index", params={
                    "q": q, "forms": "8-K", "dateRange": "custom", "startdt": a.isoformat(), "enddt": b.isoformat(), "from": frm})
                if r is None or r.status_code != 200:
                    log(f"  efts 응답 {None if r is None else r.status_code} ({q} {a}~{b} from={frm})")
                    break
                hits = (r.json().get("hits") or {}).get("hits") or []
                for h in hits:
                    src = h.get("_source") or {}
                    items = src.get("items") or []
                    if "2.01" not in items and "1.01" not in items:
                        continue
                    adsh = src.get("adsh") or ""
                    ciks = src.get("ciks") or []
                    if not adsh or not ciks:
                        continue
                    name = re.sub(r"\s*\(CIK[^)]*\)|\s*\([A-Z.\-, ]{1,12}\)", "", (src.get("display_names") or [""])[0]).strip()
                    cik = str(int(ciks[0]))
                    out[adsh] = {"filer": name, "cik": cik, "date": (src.get("file_date") or "").replace("-", ""),
                                 "path": f"edgar/data/{cik}/{adsh}.txt", "acc": adsh}
                if len(hits) < 100:
                    break
                frm += 100
        log(f"  {a}~{b}: 누적 후보 {len(out)}건")
        d = nxt
    return list(out.values())


def main():
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    if cache.get("ver") != 2:       # 필터 규칙이 바뀌면 처음부터 다시 판정
        cache = {"ver": 2}
    seen = cache.setdefault("seen", {})
    filings = []
    if os.environ.get("US_BACKFILL") == "1":
        filings = efts_candidates(SINCE)
        log(f"전문검색 후보 {len(filings)}건")
    for d in ([] if os.environ.get("US_BACKFILL") == "1" else days()):
        if d.strftime("%Y%m%d") < dt.date.today().strftime("%Y%m%d") and cache.get("idx_done", {}).get(d.strftime("%Y%m%d")):
            continue
        res = daily_8k(d)
        if res is None:
            log(f"  {d} 인덱스 없음(휴장)")
            cache.setdefault("idx_done", {})[d.strftime("%Y%m%d")] = True
            continue
        log(f"  {d} 8-K {len(res)}건")
        filings += res
        if res and d < dt.date.today():
            cache.setdefault("idx_done", {})[d.strftime("%Y%m%d")] = True
    new = [f for f in filings if f["acc"] not in seen][:MAX_FILINGS]
    log(f"새로 확인할 8-K {len(new)}건")
    n_llm = n_deal = 0
    for i, f in enumerate(new):
        if time.time() - START > BUDGET:
            log("시간 예산 초과 - 이번 실행은 여기까지")
            break
        head = read_head(f["path"], 160000)
        if head is None:
            continue
        items = header_items(head)
        is201 = any("Completion of Acquisition or Disposition" in x for x in items)
        is101 = any("Material Definitive Agreement" in x for x in items)
        if not (is201 or is101):
            seen[f["acc"]] = None
            continue
        text = body_text(head)
        if not is201 and (not DEAL_RE.search(text[:6000]) or EXCL_RE.search(text[:4000])):
            seen[f["acc"]] = None
            continue
        info = None
        if ANTHROPIC_KEY and n_llm < MAX_LLM:
            n_llm += 1
            info = llm(f, text)
            if info is not None and not info.get("is_deal"):
                seen[f["acc"]] = None
                continue
        if info is None:
            info = fallback(f, text, items)
            info["kind"] = "인수·매각 완료" if is201 else "계약 체결"
        if not info.get("summary_ko") and not info.get("summary_en"):
            seen[f["acc"]] = None
            continue
        info.update({"filer": f["filer"], "cik": f["cik"], "date": f["date"], "acc": f["acc"],
                     "item": "2.01" if is201 else "1.01",
                     "url": f"https://www.sec.gov/Archives/{f['path']}"})
        seen[f["acc"]] = info
        n_deal += 1
        if i % 100 == 0:
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    deals = sorted([v for v in seen.values() if v], key=lambda x: (x["date"], x["acc"]), reverse=True)
    old_since = SINCE
    try:
        old_since = min(SINCE, json.load(open(OUT, encoding="utf-8")).get("since") or SINCE)
    except Exception:
        pass
    json.dump({"updated": dt.date.today().strftime("%Y%m%d"), "since": old_since, "llm": bool(ANTHROPIC_KEY), "deals": deals},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"저장: 딜 {len(deals)}건 (이번 신규 {n_deal}건, LLM {n_llm}건)")


if __name__ == "__main__":
    try:
        main()
    finally:
        open("us_log.txt", "w", encoding="utf-8").write("\n".join(log_lines[-200:]))
