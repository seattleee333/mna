"""'5년 M&A 사례 리스트' 화면용 데이터 생성 → ma_cases_view.json
입력 : ma_cases.json (fetch_ma_cases.py), match_index.json (build_match_index.py: 상장사 업종코드·종속회사·사업 벡터)
추가 : 인수사 업종(buyer industry), 대상 회사 업종 추정(대상 사업 문장과 가장 비슷한 상장사들의 업종), 그룹사 내 거래 표시,
       M&A 종류(경영권 인수 / 지분 투자 / 영업양수), 해외 대상 표시
"""
import json, re, math, collections, datetime as dt
import build_match_index as B

CASES = "ma_cases.json"
INDEX = "match_index.json"
OUT = "ma_cases_view.json"


def nn(s):
    s = re.sub(r"\((?:해외\s*)?(?:비)?상장\)", "", str(s or ""))
    s = re.sub(r"㈜|\(주\)|주식회사|유한회사|\s|[.,·&\-]", "", s)
    return s.upper()

# ── 대상 회사 업종 판정 ─────────────────────────────────────────────
# 대상 회사는 대부분 비상장이라 업종코드가 없다. 아래 순서로 판정하고, 어떤 방식인지 tq 에 남긴다.
#   x: 대상이 상장사 → 그 회사의 실제 KSIC      r: 공시의 '대상 주요사업' 문구에서 키워드 규칙
#   k: KSIC 항목 이름과 문구가 가장 비슷          e: 사업 문장이 가장 비슷한 상장사들의 업종(약한 추정)
# (정규식, KSIC 중분류 2자리) — 위에서부터 먼저 맞는 것 사용 (구체적인 것을 위에)
RULES = [
 (r"저축은행|은행|캐피탈|여신|대부업|할부금융|신용카드|신용정보|리스금융", "64"),
 (r"사모투자|투자조합|투자합자|펀드|신기술사업|벤처투자|투자회사|집합투자|프라이빗에쿼티|PEF|사업투자|투자업|투자목적|지주회사|SPAC|기업인수목적", "64"),
 (r"증권|자산운용|투자자문|투자중개|금융지원", "66"),
 (r"보험|손해사정", "65"),
 (r"부동산|리츠|오피스텔|분양|개발사업|토지|빌딩", "68"),
 (r"광고|마케팅|애드테크|미디어렙", "71"),
 (r"경영컨설팅|경영자문|컨설팅|법무|회계|세무", "71"),
 (r"양극재|음극재|전해액|분리막|동박|전구체", "20"),
 (r"2차전지|이차전지|배터리|축전지|리튬이온|ESS|에너지저장", "28"),
 (r"전기장비|배전반|변압기|전선|케이블|전력기기|전동기|모터|발전기", "28"),
 (r"위성통신|통신부품|정보통신기기|통신기기|휴대폰|스마트폰|핸드폰", "26"),
 (r"반도체|웨이퍼|디스플레이|OLED|PCB|인쇄회로|전자부품|커넥터|카메라모듈|센서|LED|광학|전자제품|통신장비|무선통신|안테나|MLCC", "26"),
 (r"의료기기|임플란트|진단기기|치과|의료용|의료장비|체외진단|미용기기|보청기", "27"),
 (r"제약|의약|신약|바이오|항체|세포치료|백신|건강기능|의약외품|헬스케어제품|CDMO|CMO|진단시약", "21"),
 (r"화장품|코스메틱|뷰티|스킨케어|색조|향료|퍼퓸", "20"),
 (r"화학|소재|수지|도료|접착|첨가제|합성|케미칼|필름|코팅", "20"),
 (r"플라스틱|사출|고무|합성수지|포장재|용기", "22"),
 (r"자동차부품|자동차 부품|자동차|차량|전기차|타이어|완성차", "30"),
 (r"조선|선박|항공기|항공우주|방산|무기|철도차량|위성|드론", "31"),
 (r"로봇|자동화|산업기계|기계|설비|장비제조|공작기계|반도체장비|펌프|밸브|공구|금형", "29"),
 (r"철강|비철|제철|압연|주조|단조|알루미늄|구리|동제련", "24"),
 (r"금속가공|금속제품|볼트|파이프|강관|방산부품|금속", "25"),
 (r"게임|모바일게임|소프트웨어 개발|SW 개발|앱 개발|메타버스|NFT|블록체인|가상자산", "58"),
 (r"시스템통합|SI |IT서비스|IT 서비스|솔루션|클라우드|SaaS|플랫폼|인공지능|AI |빅데이터|사이버보안|정보보안|보안", "62"),
 (r"포털|정보서비스|데이터베이스|검색|뉴스|콘텐츠 플랫폼|통계", "63"),
 (r"영화|드라마|영상제작|영상 제작|애니메이션|웹툰|음반|OTT|스튜디오|콘텐츠 제작|콘텐츠제작|웹드라마", "59"),
 (r"방송|채널사용|케이블TV|IPTV|라디오", "60"),
 (r"엔터테인먼트|매니지먼트|공연|아티스트|연예|스포츠|골프|레저|테마파크|카지노", "90"),
 (r"출판|도서|잡지|서적", "58"),
 (r"통신|인터넷망|통신망|IDC|데이터센터", "61"),
 (r"종합건설|건설업|시공|토목|건축공사|인테리어|플랜트|주택|도시개발", "41"),
 (r"전기공사|소방|설비공사|전문공사|통신공사|철거|조경", "42"),
 (r"태양광|신재생|풍력|발전|수소|연료전지|열병합|전력판매|도시가스|에너지", "35"),
 (r"폐기물|재활용|수처리|환경|폐수|자원순환|소각", "38"),
 (r"항공운송|항공사|저비용항공|항공", "51"),
 (r"물류|택배|운송|화물|해운|운수|포워딩|창고|풀필먼트", "52"),
 (r"식품|제과|제빵|가공식품|간편식|농산물|축산|수산|김치|조미|식자재|사료", "10"),
 (r"음료|주류|맥주|소주|위스키|와인|생수|커피", "11"),
 (r"섬유|방직|염색|직물|니트", "13"),
 (r"의류|패션|의복|아웃도어|속옷|란제리", "14"),
 (r"신발|가방|가죽|핸드백|잡화", "15"),
 (r"가구|침대|매트리스", "32"),
 (r"완구|문구|악기|스포츠용품|생활용품|위생용품|기타제품", "33"),
 (r"유통|도매|무역|상사|수출입|중개", "46"),
 (r"소매|쇼핑몰|이커머스|온라인몰|리테일|편의점|백화점|면세점|판매업|직영점|프랜차이즈 본부", "47"),
 (r"음식점|외식|레스토랑|카페|프랜차이즈", "56"),
 (r"호텔|리조트|숙박|여행사|관광|여행", "55"),
 (r"교육|학원|에듀|어학|출판교육", "85"),
 (r"병원|의원|요양|의료서비스|헬스케어 서비스|검진|건강검진|동물병원", "86"),
 (r"연구개발|R&D|기술개발|연구소", "70"),
 (r"엔지니어링|설계|감리|건축기술|측량|시험인증|인증", "72"),
 (r"인력|파견|아웃소싱|콜센터|경비|청소|시설관리|렌탈|임대", "75"),
 (r"자동차판매|중고차|차량판매|자동차 판매|부품판매", "45"),
]
RX = [(re.compile(p, re.I), c) for p, c in RULES]

def by_rules(text):
    for rx, code in RX:
        if rx.search(text):
            return code
    return None


_KS = None


def ksic_index():
    """KSIC 항목(3~5자리) 이름 색인 — 문구와 이름의 글자 조각 유사도로 업종을 찾는다."""
    global _KS
    if _KS:
        return _KS
    ks = json.load(open("ksic.json", encoding="utf-8"))
    docs = [(c, re.sub(r"\(.*?\)", "", n)) for c, n in ks["c"] if len(c) >= 3]
    toks = [B.tokens(n) for _, n in docs]
    df = collections.Counter(t for tk in toks for t in set(tk))
    idf = {t: math.log(len(docs) / (1 + n)) + 1 for t, n in df.items()}
    inv = collections.defaultdict(list)
    for i, tk in enumerate(toks):
        cnt = collections.Counter(tk)
        nr = math.sqrt(sum((v * idf[x]) ** 2 for x, v in cnt.items())) or 1
        for x, v in cnt.items():
            inv[x].append((i, v * idf[x] / nr))
    _KS = (docs, idf, inv)
    return _KS


def by_ksic_name(text):
    docs, idf, inv = ksic_index()
    cnt = collections.Counter(B.tokens(text))
    q = {t: (1 + math.log(n)) * idf[t] for t, n in cnt.items() if t in idf}
    if not q:
        return None, 0
    qn = math.sqrt(sum(w * w for w in q.values())) or 1
    sc = collections.defaultdict(float)
    for t, w in q.items():
        for i, cw in inv[t]:
            sc[i] += w / qn * cw
    if not sc:
        return None, 0
    i, s = max(sc.items(), key=lambda x: x[1])
    return docs[i][0][:2], s



def main():
    cases = json.load(open(CASES, encoding="utf-8"))["cases"]
    idx = json.load(open(INDEX, encoding="utf-8"))
    vocab, idf, comps = idx["vocab"], idx["idf"], idx["c"]
    vid = {t: i for i, t in enumerate(vocab)}

    # 상장사 사업 벡터 역색인 (대상 회사 업종 추정용)
    inv = collections.defaultdict(list)
    for ci, c in enumerate(comps):
        P = c["P"]
        for j in range(0, len(P), 2):
            inv[P[j]].append((ci, P[j + 1] / 100))

    by_code = {c["c"]: c for c in comps}
    by_name = {}
    for c in comps:
        if c.get("ic") and len(nn(c["n"])) >= 3:      # 짧은 흔한 이름(예: 신원)은 동명이사 오인 위험이 커서 제외
            by_name.setdefault(nn(c["n"]), c)

    def target_industry(c):
        """(업종 2자리, 판정 방식)"""
        listed = by_name.get(nn(c.get("t")))
        if listed:
            return listed["ic"][:2], "x"
        tb = (c.get("tb") or "").strip()
        r = by_rules(tb) if len(tb) >= 2 else None
        if r:
            return r, "r"
        pur = c.get("p") or ""
        r = by_rules(tb + " " + (c.get("t") or "")) or (by_rules(pur) if len(tb) < 2 else None)
        if r:
            return r, "r"
        k, sc = by_ksic_name((tb + " " + pur).strip())
        if k and sc >= 0.6:
            return k, "k"
        if len(tb) < 2:                  # 대상 사업 정보가 없으면 상호만으로는 맞히기 어려워 비워 둔다
            return "", ""
        e = est_industry(" ".join([c.get("t") or "", tb, tb, pur]))
        return (e, "e") if e else ("", "")
    # 그룹 표시용: 이름 앞 두 글자가 상장사 4곳 이상에서 쓰이는 접두어(삼성·현대·한화·롯데·SK 등)
    pref = collections.Counter(nn(c["n"])[:2] for c in comps if len(nn(c["n"])) >= 3)
    stems = {k for k, v in pref.items() if v >= 4}
    subs = {c["c"]: {nn(x) for x in c.get("sub", [])} for c in comps}

    def est_industry(text):
        cnt = collections.Counter(B.tokens(text))
        q = {}
        for t, n in cnt.items():
            i = vid.get(t)
            if i is not None:
                q[i] = (1 + math.log(n)) * idf[i]
        if not q:
            return None
        norm = math.sqrt(sum(w * w for w in q.values())) or 1
        score = collections.defaultdict(float)
        for i, w in q.items():
            for ci, cw in inv.get(i, ()):
                score[ci] += (w / norm) * cw
        top = sorted(score.items(), key=lambda x: -x[1])[:5]
        if not top or top[0][1] < 0.12:
            return None
        vote = collections.Counter()
        for ci, sc in top:
            ic = comps[ci].get("ic")
            if ic:
                vote[ic[:2]] += sc
        return vote.most_common(1)[0][0] if vote else None

    out = []
    for c in cases:
        b = by_code.get(c.get("bc"))
        tn = nn(c.get("t"))
        bn = nn(c.get("b"))
        foreign = not re.search(r"[가-힣]", c.get("t") or "")
        group = ""
        if b:
            if tn in subs.get(c["bc"], ()):
                group = "sub"
            elif len(bn) >= 3 and tn.startswith(bn[:3]):
                group = "name"
            elif bn[:2] in stems and tn.startswith(bn[:2]):
                group = "stem"
        k = c.get("k") or "stake"
        try:
            st = float(c["s"]) if c.get("s") else None
        except (TypeError, ValueError):
            st = None
        if k == "biz":
            ty = "영업양수"
        elif st is None:
            ty = "지분 취득(지분율 미확인)"
        elif st >= 50:
            ty = "경영권 인수(50%↑)"
        else:
            ty = "지분 투자(50% 미만)"
        ti, tq = target_industry(c)
        out.append({
            "d": c["d"], "b": c["b"], "bc": c.get("bc"), "t": c.get("t"), "tb": c.get("tb"), "a": c.get("a"), "s": c.get("s"),
            "p": c.get("p"), "cp": c.get("cp"), "r": c.get("r"), "k": k, "ty": ty,
            "g": group, "f": 1 if foreign else 0,
            "bi": (b.get("ic") or "")[:2] if b else "",
            "ti": ti, "tq": tq,
        })
    out.sort(key=lambda x: x["d"], reverse=True)
    json.dump({"updated": dt.date.today().isoformat(), "n": len(out), "cases": out},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    g = sum(1 for x in out if x["g"])
    print(f"{OUT}: {len(out)}건 (그룹사 내 {g}건, 해외 대상 {sum(x['f'] for x in out)}건, 대상 업종 {sum(1 for x in out if x['ti'])}건: "
          + ", ".join(f"{q}={n}" for q, n in collections.Counter(x['tq'] for x in out).items()) + ")")


if __name__ == "__main__":
    main()
