"""업종별 M&A 동향판(sector_board.json) 생성.

- 공시 사례(ma_cases_view.json): 최근 5년 상장사 인수 공시를 업종별로 집계 (그룹사 내 거래 제외)
- 뉴스(news.json): 제목 키워드로 업종·거래 단계를 분류해 최근 30일 흐름을 집계 (AI 없이 규칙 기반)
- 상장 피어 배수(peers.json, industry_mult.json): 업종별 PER·EV/EBITDA

외부 접속이 없는 순수 계산이라 로컬에서도, 자동 작업에서도 같은 결과가 나온다.
"""
import json
import os
import re
import statistics
import datetime as dt

OUT = "sector_board.json"
WINDOW_FROM = None   # 데이터의 since 값을 쓴다
NEWS_DAYS = 30

# ── 업종 정의 ──────────────────────────────────────────────
# ksic: 공시 대상회사 업종코드 앞 2자리 / tg: 세부 업종코드 접두어(우선 적용) / text: 대상 회사 사업내용 문구 키워드(우선 적용)
# news: 기사 제목 키워드(회사명 포함). 위에 있는 업종부터 먼저 맞춘다.
# peers: peers.json 업종 id
SECTORS = [
    dict(id="cosmetics", name="화장품·뷰티", kind="op", tg=["2042"],
         text=r"화장품|뷰티|코스메틱|스킨케어|화장품용기|화장품 용기",
         news=r"화장품|뷰티|코스메틱|스킨케어|아모레|LG생활건강|코스맥스|한국콜마|에이피알|올리브영|화장품 용기|펌텍",
         peers=["cosmetics_brand"]),
    dict(id="battery", name="2차전지·배터리소재", kind="op", tg=["282"],
         text=r"2차전지|이차전지|배터리|양극재|음극재|전해액|분리막|리튬",
         news=r"2차전지|이차전지|배터리|양극재|음극재|전해액|분리막|리튬|에너지저장|ESS|LG에너지솔루션|삼성SDI|SK온|에코프로|포스코퓨처엠|엘앤에프",
         peers=["battery"]),
    dict(id="power", name="전력기기·전기장비", kind="op", ksic=["28"], tg=["281", "283"],
         text=r"배전반|수배전|변압기|전력기기|전력 기기|전선|케이블|전력설비|차단기|개폐기|전동기|발전기|인버터|전기장비|전력변환",
         news=r"전력기기|배전반|변압기|전선|케이블|차단기|송배전|전력망|전력 인프라|전기장비|LS일렉트릭|LS ELECTRIC|효성중공업|HD현대일렉트릭|대한전선|LS전선|가온전선|일진전기|제룡전기|산일전기",
         peers=["power_small", "power_equipment"]),
    dict(id="semi", name="전자부품·반도체", kind="op", ksic=["26"],
         text=r"반도체|PCB|인쇄회로|전자부품|디스플레이|OLED|센서|카메라모듈|MLCC|웨이퍼|패키징|LED|통신장비",
         news=r"반도체|HBM|웨이퍼|PCB|기판|전자부품|디스플레이|OLED|센서|카메라모듈|MLCC|소부장|삼성전자|SK하이닉스|삼성전기|LG이노텍|통신장비",
         peers=["semicon_electronics"]),
    dict(id="bio", name="의약·바이오", kind="op", ksic=["21"],
         text=r"의약품|제약|바이오|신약|의료용 물질|CDMO|백신",
         news=r"바이오|제약|의약|신약|CDMO|백신|셀트리온|삼성바이오|유한양행|한미약품|녹십자|동아에스티|SK바이오|HK이노엔|오스코텍",
         peers=["pharma"]),
    dict(id="medical", name="의료기기·정밀기기", kind="op", ksic=["27"],
         text=r"의료기기|의료용 기기|정밀|광학|측정|계측|치과|임플란트|진단",
         news=r"의료기기|헬스케어|진단|임플란트|덴탈|임상|병원 인수|임플란트",
         peers=["medical"]),
    dict(id="chem", name="화학·소재", kind="op", ksic=["20", "22"],
         text=r"화학|석유화학|합성수지|도료|접착|필름|플라스틱|고무|정밀화학|첨가제",
         news=r"화학|석유화학|합성수지|도료|접착제|필름|플라스틱|소재|정밀화학|롯데케미칼|금호석유|한화솔루션|LG화학|OCI|SKC|코오롱",
         peers=["chemicals"]),
    dict(id="metal", name="철강·금속·기타소재", kind="op", ksic=["23", "24", "25", "16", "17", "18"],
         text=r"철강|금속|비철|알루미늄|구리|동박|스틸|주물|금속가공|시멘트|제지|펄프",
         news=r"철강|금속|비철|알루미늄|동박|스틸|주물|시멘트|제지|고려아연|풍산|세아|동국제강|현대제철|포스코",
         peers=["metals"]),
    dict(id="defense", name="방산·조선·항공우주", kind="op", ksic=["31"],
         text=r"방산|조선|선박|항공|우주|무기|총포탄|군수",
         news=r"방산|조선업|조선사|조선소|조선 |선박|항공우주|우주|KAI|한국항공우주|한화에어로|한화오션|HD현대중공업|삼성중공업|HD한국조선|LIG넥스원|방위",
         peers=["defense_ship"]),
    dict(id="it", name="IT·소프트웨어·게임", kind="op", ksic=["58", "61", "62", "63"],
         text=r"소프트웨어|게임|IT서비스|시스템 통합|클라우드|플랫폼|핀테크|보안|앱 |SaaS|통신",
         news=r"게임|소프트웨어|(?<![A-Za-z])SW(?![A-Za-z])|IT서비스|(?<![A-Za-z])SI(?![A-Za-z])|클라우드|플랫폼|핀테크|보안|(?<![A-Za-z])AI(?![A-Za-z])|인공지능|데이터센터|카카오|네이버|크래프톤|엔씨|넷마블|넥슨|컴투스|펄어비스|웹젠|통신사",
         peers=["software_it", "game_content"]),
    dict(id="media", name="미디어·콘텐츠·엔터", kind="op", ksic=["59", "60", "90"],
         text=r"영화|드라마|음악|웹툰|웹소설|엔터|방송|콘텐츠|공연|아티스트|영상",
         news=r"엔터|콘텐츠|드라마|영화|음악|웹툰|방송|하이브|SM |JYP|YG|CJ ENM|스튜디오|뮤지컬|공연",
         peers=["media_ent"]),
    dict(id="auto", name="자동차·부품", kind="op", ksic=["30"],
         text=r"자동차|차량|모빌리티|타이어|전장|변속기|시트",
         news=r"자동차|부품사|전장|타이어|모빌리티|전기차|현대차|기아|현대모비스|한온시스템|만도|한국타이어",
         peers=["auto_parts"]),
    dict(id="machine", name="기계·로봇·장비", kind="op", ksic=["29"],
         text=r"기계|로봇|자동화|공작기계|설비|산업용|엔지니어링|펌프|압축기|반도체 장비|제조 장비",
         news=r"로봇|기계|자동화|공작기계|설비|엔지니어링|반도체 장비|두산로보틱스|두산밥캣|HD현대건설기계|한화비전|두산에너빌리티",
         peers=["machinery"]),
    dict(id="consumer", name="식품·유통·소비재", kind="op", tg=["285"], ksic=["10", "11", "14", "15", "32", "33", "46", "47", "55", "56"],
         text=r"식품|음료|유통|프랜차이즈|외식|도소매|의류|패션|생활용품|가구|완구",
         news=r"식품|음료|유통|프랜차이즈|외식|편의점|이커머스|패션|의류|홈플러스|이마트|롯데쇼핑|CJ제일제당|오뚜기|농심|삼양|F&F|테일러메이드|스포츠",
         peers=["food_bev", "retail_ecom", "apparel"]),
    dict(id="energy", name="에너지·환경", kind="op", ksic=["19", "35", "36", "37", "38", "39"],
         text=r"태양광|풍력|신재생|발전|도시가스|LNG|수소|폐기물|수처리|환경|정유|연료전지|에너지",
         news=r"태양광|풍력|신재생|발전소|발전사|도시가스|LNG|수소|폐기물|수처리|환경|정유|에너지|SK이노베이션|GS칼텍스|S-OIL|한국전력|발전",
         peers=["energy_env"]),
    dict(id="logistics", name="물류·운송", kind="op", ksic=["49", "50", "51", "52", "53"],
         text=r"물류|택배|운송|해운|항공사|항만|운수|화물",
         news=r"물류|택배|운송|항만|항공사|화물|CJ대한통운|한진|팬오션|HMM|해운",
         peers=["logistics"]),
    dict(id="service", name="전문서비스·교육·의료서비스", kind="op", ksic=["70", "71", "72", "73", "74", "75", "85", "86", "87", "84"],
         text=r"컨설팅|광고|교육|병원|인력|연구개발|디자인|전문서비스",
         news=r"컨설팅|광고대행|교육|학원|병원|제일기획|이노션|렌탈|렌터카",
         peers=["advertising", "education_service"]),
    dict(id="construction", name="건설·부동산", kind="asset", ksic=["41", "42", "68"],
         text=r"건설|부동산|리츠|시행|건자재|호텔|임대|분양",
         news=r"건설|부동산|리츠|시행사|건자재|호텔|물류센터|오피스|분양|시공",
         peers=["construction"]),
    dict(id="finance", name="금융·투자", kind="asset", ksic=["64", "65", "66"],
         text=r"금융|투자업|캐피탈|보험|증권|조합|펀드|자산운용",
         news=r"증권사|저축은행|보험사|캐피탈|카드사|금융지주|생명보험|손해보험|은행 매각|자산운용|리스사",
         peers=[]),
]
BY_ID = {s["id"]: s for s in SECTORS}
KSIC2 = {}
for s in SECTORS:
    for k in s.get("ksic", []):
        KSIC2[k] = s["id"]
SERVICE_FALLBACK = "service"


def sector_of_case(e):
    """공시 사례 한 건의 업종 id. 못 찾으면 None."""
    tg = e.get("tg") or []
    for s in SECTORS:
        for pre in s.get("tg", []):
            if any(x.startswith(pre) for x in tg):
                return s["id"], "tg"
    txt = (e.get("tb") or "")
    if txt:
        for s in SECTORS:
            if s["id"] in ("it", "service", "finance", "construction", "energy", "consumer", "media"):
                continue
            if re.search(s["text"], txt):
                if not e.get("ti") or KSIC2.get(e["ti"]) in (None, s["id"]):
                    return s["id"], "text"
    ti = e.get("ti")
    if ti and ti in KSIC2:
        return KSIC2[ti], "ksic"
    if not ti:
        blob = (e.get("tb") or "") + " " + (e.get("t") or "")
        for s in SECTORS:
            if re.search(s["text"], blob):
                return s["id"], "text"
    return None, None


def sector_of_news(title):
    for s in SECTORS:
        if re.search(s["news"], title):
            return s["id"]
    return None


STAGES = [
    ("완료", re.compile(r"매각 완료|인수 완료|마무리|클로징|거래 종결|잔금|완료")),
    ("계약", re.compile(r"계약 체결|SPA|인수 확정|매각 확정|합의|계약")),
    ("우선협상", re.compile(r"우선협상|우선 협상|낙점|우협")),
    ("입찰", re.compile(r"본입찰|예비입찰|입찰|숏리스트|인수전|경쟁")),
    ("추진", re.compile(r"매각 추진|매각 착수|매각에 나|매각 나서|매물|내놓|매각 검토|매각 주관|매각설|인수 추진|인수 검토|인수 나서|인수 도전|인수 의향|지분 매각|팔기|팔아|매각 본격|매각 공고|공개경쟁")),
]


def stage_of(title):
    for name, rx in STAGES:
        if rx.search(title):
            return name
    return "기타"


DASH = r"[-‐‑‒–—―−|]"


def clean_title(t, sources=()):
    t = t.strip()
    for src in sources or ():
        if src and t.endswith(src):
            t = re.sub(r"\s*" + DASH + r"?\s*" + re.escape(src) + r"$", "", t).strip()
    return re.sub(r"\s+" + DASH + r"\s+[^-‐‑‒–—―−|]{1,30}$", "", t).strip()


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def window_bounds(since):
    """12개월 구간 5개: since 부터 1년씩. since 는 YYYYMMDD."""
    s = dt.datetime.strptime(since, "%Y%m%d")
    out = []
    for i in range(5):
        a = s.replace(year=s.year + i)
        b = s.replace(year=s.year + i + 1) - dt.timedelta(days=1)
        out.append((a.strftime("%Y%m%d"), b.strftime("%Y%m%d")))
    return out


def build_dart(cases, since):
    wins = window_bounds(since)
    end = wins[-1][1]

    def widx(d):
        for i, (a, b) in enumerate(wins):
            if a <= d <= b:
                return i
        return None

    rows = [e for e in cases if since <= e["d"] <= end]
    ext = [e for e in rows if not e.get("g")]
    per = {s["id"]: [] for s in SECTORS}
    unclassified = 0
    for e in ext:
        sid, _ = sector_of_case(e)
        if sid is None:
            unclassified += 1
            continue
        per[sid].append(e)
    stats = {}
    for sid, lst in per.items():
        yrs = [0] * 5
        for e in lst:
            i = widx(e["d"])
            if i is not None:
                yrs[i] += 1
        amts = [e["a"] for e in lst if e.get("a") is not None]
        recent = sorted(lst, key=lambda e: e["d"], reverse=True)[:6]
        stats[sid] = {
            "n": len(lst),
            "years": yrs,
            "median": round(statistics.median(amts)) if amts else None,
            "control": sum(1 for e in lst if (e.get("ty") or "").startswith("경영권")),
            "overseas": sum(1 for e in lst if e.get("f")),
            "recent": [
                {"d": e["d"], "b": e["b"], "t": re.sub(r"^\(주\)|^주식회사\s*|\s*\(주\)$|㈜", "", e["t"] or "").strip(),
                 "a": e.get("a"), "ty": e.get("ty"), "r": e.get("r")}
                for e in recent
            ],
        }
    cov = {"total": len(rows), "ext": len(ext), "classified": len(ext) - unclassified,
           "intra_group": len(rows) - len(ext)}
    return stats, wins, cov


def build_news(news, now):
    cut = (now - dt.timedelta(days=NEWS_DAYS)).strftime("%Y%m%d%H%M")
    recent = []
    for e in news:
        stamp = e.get("pub") or ((e.get("last_seen") or e.get("first_seen") or "") + "0000")
        if stamp >= cut:
            recent.append((stamp, e))
    per = {s["id"]: {"n": 0, "stages": {}, "live": []} for s in SECTORS}
    classified = 0
    for stamp, e in sorted(recent, key=lambda x: x[0], reverse=True):
        title = clean_title(e["title"], e.get("sources"))
        sid = sector_of_news(title)
        if not sid:
            continue
        classified += 1
        st = stage_of(title)
        p = per[sid]
        p["n"] += 1
        p["stages"][st] = p["stages"].get(st, 0) + 1
        if st in ("추진", "입찰", "우선협상") and len(p["live"]) < 8:
            p["live"].append({"title": title, "link": e["link"], "pub": stamp, "stage": st,
                              "src": (e.get("sources") or [""])[0]})
    cov = {"total": len(recent), "classified": classified, "days": NEWS_DAYS}
    return per, cov


def multiples(peers, mult_file):
    out = {}
    secs = {s["id"]: s for s in (peers or {}).get("sectors", [])}
    for s in SECTORS:
        blocks = []
        for pid in s["peers"]:
            ps = secs.get(pid)
            if not ps:
                continue
            st = ps.get("stats") or {}
            if st.get("per") or st.get("evEbitda") or st.get("evEbit"):
                blocks.append({"name": ps["name"], "per": st.get("per"), "ev": st.get("evEbitda"), "ebit": st.get("evEbit")})
        if blocks:
            out[s["id"]] = {"peers": blocks}
    # 소형 배전반 상장사: 흑자·영업이익률 5%↑ 인 곳만 (적자·일회성 이익 회사는 배수가 튀어서 제외)
    small = []
    for c in (mult_file or {}).get("companies", []):
        y = (c.get("years") or {}).get("2025")
        mc = c.get("mcap")
        if not y or not mc:
            continue
        op, ni, rev = y.get("op"), y.get("ni"), y.get("rev")
        if not (op and ni and rev) or op <= 0 or ni <= 0 or op / rev < 0.05:
            continue
        da = y.get("da")
        net = (y.get("debt") or 0) - (y.get("cash") or 0) + (y.get("nci") or 0)
        ev = mc + net
        ebitda = op + da if da is not None else None
        small.append({
            "name": re.sub(r"\(주\)|주식회사", "", c["name"]).strip(),
            "mcap": round(mc / 1e8), "per": round(mc / ni, 1),
            "ev_ebitda": round(ev / ebitda, 1) if ebitda else None,
            "ev_op": round(ev / op, 1),
        })
    if small:
        evs = [x["ev_ebitda"] or x["ev_op"] for x in small]
        pers = [x["per"] for x in small]
        out.setdefault("power", {})["small"] = {
            "rows": sorted(small, key=lambda x: -x["mcap"]),
            "ev_median": round(statistics.median(evs), 1), "ev_min": min(evs), "ev_max": max(evs),
            "per_median": round(statistics.median(pers), 1), "per_min": min(pers), "per_max": max(pers),
            "note": "2025 사업연도 실적과 시가총액 기준. 감가상각비를 못 구한 곳은 영업이익 기준이라 실제 EV/EBITDA는 이보다 낮아요.",
        }
    return out


def main():
    v = load("ma_cases_view.json", {"cases": []})
    cases = v.get("cases", [])
    stats_meta = load("ma_stats.json", {}) or {}
    since = stats_meta.get("since") or "20211027"
    news = load("news.json", []) or []
    peers = load("peers.json", {})
    mult = load("industry_mult.json", {})
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=9)

    dart, wins, dcov = build_dart(cases, since)
    nws, ncov = build_news(news, now)
    mm = multiples(peers, mult)

    sectors = []
    for s in SECTORS:
        sid = s["id"]
        sectors.append({
            "id": sid, "name": s["name"], "kind": s["kind"],
            "dart": dart[sid], "news": nws[sid], "mult": mm.get(sid),
        })
    sectors.sort(key=lambda x: (x["kind"] != "op", -x["dart"]["n"]))

    out = {
        "asof": now.strftime("%Y-%m-%d"),
        "cases_updated": v.get("updated"),
        "windows": [{"from": a, "to": b} for a, b in wins],
        "coverage": {"cases": dcov, "news": ncov},
        "sectors": sectors,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{OUT}: 업종 {len(sectors)}개 / 공시 {dcov['classified']}/{dcov['ext']}건 분류"
          f" ({dcov['classified'] / max(dcov['ext'], 1):.0%}) / 뉴스 {ncov['classified']}/{ncov['total']}건 분류"
          f" ({ncov['classified'] / max(ncov['total'], 1):.0%})")


if __name__ == "__main__":
    main()
