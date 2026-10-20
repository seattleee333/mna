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



# ── 세부 업종(KSIC 3~5자리) 규칙 ───────────────────────────────────
# 한 회사가 여러 제품을 하면 맞는 코드를 모두 tg 에 담는다. (정규식, KSIC 코드) — 코드의 앞 2자리가 중분류(ti)와 같을 때만 쓴다.
DETAIL = [
 (r"변압기|몰드변압기|주상변압기|리액터|변성기|CT/PT", "28112"),
 (r"전동기|모터|발전기|제너레이터|서보", "28111"),
 (r"UPS|무정전|정류기|인버터|컨버터|전력변환|전원공급장치|SMPS|충전기|전력반도체모듈", "28119"),
 (r"ESS|에너지저장장치|에너지 저장 장치", "28114"),
 (r"차단기|개폐기|보호계전기|계전기|퓨즈|전력기기|개폐장치|가스절연", "28121"),
 (r"배전반|수배전|분전반|자동제어반|제어반|배전함|MCC|스위치기어|전력설비", "28123"),
 (r"접속장치|커넥터|단자|소켓|배선기구", "28122"),
 (r"2차전지|이차전지|배터리|축전지|리튬이온|전지", "28202"),
 (r"광케이블|광섬유", "28301"),
 (r"전선|케이블|절연선|전력선|통신선|동선", "28302"),
 (r"LED조명|조명|램프|등기구", "28422"),
 (r"가전|밥솥|전기히터|청소기|세탁기|에어프라이어", "28519"),
 (r"인쇄회로기판|PCB|연성회로|FPCB|HDI|리지드|기판", "26222"),
 (r"메모리|DRAM|낸드|플래시메모리", "26111"),
 (r"시스템반도체|비메모리|팹리스|파운드리|반도체 설계|AP |이미지센서|전력반도체|전자집적회로", "26112"),
 (r"LED칩|발광다이오드|발광 다이오드", "26121"),
 (r"OLED|유기발광", "26212"),
 (r"LCD|액정|디스플레이", "26219"),
 (r"MLCC|적층세라믹|커패시터|축전기|콘덴서", "26291"),
 (r"저항기|칩저항", "26292"),
 (r"코일|인덕터|트랜스|유도자", "26294"),
 (r"센서|감지장치|감지기", "26295"),
 (r"카메라모듈|광학렌즈|렌즈", "27301"),
 (r"스마트폰|이동전화|휴대폰|핸드폰", "26422"),
 (r"통신장비|무선통신|중계기|안테나|기지국|위성통신|RF", "26429"),
 (r"유선통신|광통신|네트워크장비|스위치장비", "26410"),
 (r"방송장비", "26421"),
 (r"반도체장비|반도체 장비|반도체 제조용|식각|증착|세정장비", "29271"),
 (r"디스플레이장비|디스플레이 제조용", "29272"),
 (r"산업용로봇|로봇|협동로봇", "29280"),
 (r"펌프|압축기|컴프레서", "29131"),
 (r"밸브", "29133"),
 (r"베어링", "29141"),
 (r"감속기|기어|동력전달", "29142"),
 (r"승강기|엘리베이터|에스컬레이터", "29162"),
 (r"공조|공기조화|냉동|냉장|냉난방|칠러|항온항습", "29172"),
 (r"열교환기|보일러", "29176"),
 (r"포장기계|충전기계|세척기", "29192"),
 (r"공작기계|절삭|선반|머시닝|CNC", "29223"),
 (r"금형|주형", "29294"),
 (r"사출성형기|플라스틱 성형기", "29292"),
 (r"건설기계|굴삭기|지게차|크레인", "29241"),
 (r"농기계|트랙터|농업용 기계", "29210"),
 (r"식품기계|식품 가공기계", "29250"),
 (r"의료기기|진단기기|초음파|X-ray|엑스레이|방사선", "27112"),
 (r"치과|임플란트|덴탈", "27191"),
 (r"정형외과|보조기|인공관절|척추", "27192"),
 (r"안경|콘택트렌즈", "27193"),
 (r"측정기|계측기|분석기기|검사장비|시험장비", "27219"),
 (r"완제의약품|전문의약품|일반의약품|제네릭|신약|제약", "21210"),
 (r"바이오시밀러|백신|항체|세포치료|유전자치료|생물학적|단백질", "21102"),
 (r"원료의약품|의약용 화합물|API|항생", "21101"),
 (r"한약|한의약|생약", "21220"),
 (r"동물용의약품|동물약품", "21230"),
 (r"화장품|코스메틱|스킨케어|색조", "20423"),
 (r"세제|비누|치약|생활화학|방향제", "20422"),
 (r"도료|페인트|코팅제", "20411"),
 (r"잉크|토너", "20413"),
 (r"접착제|접착|점착", "20493"),
 (r"합성수지|레진|플라스틱 소재|컴파운드|PVC|PE|PP", "20202"),
 (r"합성고무|고무소재", "20201"),
 (r"산업용가스|산업용 가스|특수가스", "20121"),
 (r"석유화학|에틸렌|프로필렌|나프타", "20111"),
 (r"비료|농약|작물보호", "20311"),
 (r"감광재|포토레지스트|반도체 소재|CMP", "20491"),
 (r"포장용기|화장품용기|PET병|용기 제조|플라스틱 용기|튜브", "22232"),
 (r"필름", "22212"),
 (r"플라스틱 시트|플라스틱판", "22213"),
 (r"자동차 부품용 플라스틱|자동차용 플라스틱|내장재", "22241"),
 (r"타이어", "22111"),
 (r"고무패킹|오링|실링|가스켓", "22191"),
 (r"자동차 엔진|엔진부품", "30310"),
 (r"자동차 전장|자동차용 전기|와이어링하네스|하네스", "30332"),
 (r"제동|브레이크", "30392"),
 (r"시트|자동차 의자", "30393"),
 (r"조향|서스펜션|현가", "30391"),
 (r"차체|범퍼|프레임", "30320"),
 (r"동력전달|변속기|드라이브샤프트", "30331"),
 (r"승용차|완성차|전기차 제조|자동차 제조", "30121"),
 (r"특장차|화물차|버스|트럭|트레일러", "30201"),
 (r"선박|조선|선체", "31113"),
 (r"선박 부품|선박 기자재|선박용", "31114"),
 (r"철도차량|철도 부품", "31201"),
 (r"항공기 부품|항공 부품|항공기용", "31322"),
 (r"무인기|드론|무인항공", "31312"),
 (r"제철|고로|전기로|제강", "24112"),
 (r"압연|열연|냉연|강판|형강|철근", "24121"),
 (r"철강선|와이어|강선", "24123"),
 (r"강관|파이프|배관", "24132"),
 (r"알루미늄", "24212"),
 (r"동 제련|구리 제련|동제품|구리", "24211"),
 (r"아연|납 ", "24213"),
 (r"주물|주조", "24311"),
 (r"단조", "25912"),
 (r"도금|표면처리", "25922"),
 (r"볼트|너트|파스너|나사", "25941"),
 (r"스프링", "25943"),
 (r"탱크|저장용기|고압가스용기", "25122"),
 (r"금속캔|캔 제조", "25991"),
 (r"구조용 금속|철구조물|철골", "25112"),
 (r"방산|무기|총포탄|탄약|화약", "25200"),
 (r"시멘트", "23311"),
 (r"레미콘", "23322"),
 (r"판유리|건축용 유리|안전유리", "23111"),
 (r"디스플레이용 유리|디스플레이 유리", "23122"),
 (r"포장용 유리|유리용기|유리병", "23192"),
 (r"탄소섬유", "23995"),
 (r"김치", "10301"),
 (r"육가공|햄|소시지|도축|축산물", "10122"),
 (r"수산물가공|어묵|수산가공", "10219"),
 (r"유가공|우유|치즈|요거트|아이스크림", "10501"),
 (r"제과|과자|초콜릿|캔디", "10713"),
 (r"제빵|빵류|베이커리", "10712"),
 (r"면류|라면|국수", "10730"),
 (r"장류|소스|조미료|식초", "10743"),
 (r"건강기능식품|건기식|프로바이오틱스", "10797"),
 (r"도시락|HMR|간편식|조리식품|냉동식품", "10759"),
 (r"커피|원두", "10791"),
 (r"사료", "10801"),
 (r"제분|도정|곡물", "10611"),
 (r"맥주", "11112"),
 (r"소주|증류주|위스키|주류", "11122"),
 (r"생수|음료|탄산", "11209"),
 (r"의복|의류|패션|아웃도어", "14199"),
 (r"속옷|란제리", "14120"),
 (r"가방|핸드백", "15129"),
 (r"신발|구두|운동화", "15219"),
 (r"게임|모바일게임|온라인게임", "58211"),
 (r"소프트웨어|SW|솔루션|앱 개발|애플리케이션", "58222"),
 (r"시스템소프트웨어|운영체제|보안 소프트웨어", "58221"),
 (r"시스템통합|SI |IT서비스|IT 서비스|IT 컨설팅|클라우드", "62021"),
 (r"프로그래밍|개발 용역|SI개발|웹개발", "62010"),
 (r"데이터처리|빅데이터|데이터센터|호스팅", "63111"),
 (r"광고대행|광고 대행|미디어렙|마케팅 대행", "71310"),
 (r"옥외광고|전시|디스플레이광고", "71391"),
 (r"전자상거래|이커머스|온라인몰|쇼핑몰|통신판매", "47911"),
 (r"토목|도로|교량|터널", "41221"),
 (r"호텔|숙박|리조트", "55101"),
 (r"종합병원|병원|의료원", "86101"),
 (r"물류센터|풀필먼트|창고", "52913"),
]
def _wrap(p):
    """영문·숫자 약어(ESS, PCB, PE 등)는 단어 경계를 줘서 다른 낱말 속 글자에 걸리지 않게 한다."""
    out = []
    for a in p.split("|"):
        t = a.strip()
        out.append(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])" if re.fullmatch(r"[A-Za-z0-9/&\-]+", t) else a)
    return "|".join(out)


DX = [(re.compile(_wrap(p), re.I), c) for p, c in DETAIL]

def detail_codes(text, ksic_names):
    out = []
    for rx, code in DX:
        if code in ksic_names and rx.search(text) and code not in out:
            out.append(code)
    return out


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


def by_ksic_full(text):
    """문구와 가장 비슷한 KSIC 항목의 전체 코드(3~5자리)와 점수."""
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
    return docs[i][0], s



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

    ks_names = {c: n for c, n in json.load(open("ksic.json", encoding="utf-8"))["c"]}

    def comp_tags(comp, extra=""):
        """상장사의 실제 업종코드 + 사업보고서 '주요 제품' 문장에서 읽힌 더 세부적인 업종 코드들"""
        ic = comp.get("ic") or ""
        if not ic:
            return []
        txt = " ".join(((comp.get("e") or {}).get("P") or [])[:12]) + " " + extra
        more = [x for x in detail_codes(txt, ks_names) if x.startswith(ic) and x != ic]
        return [ic] + more[:4]

    def target_industry(c):
        """(업종 2자리, 판정 방식, 세부 업종 코드 목록)"""
        listed = by_name.get(nn(c.get("t")))
        if listed:
            return listed["ic"][:2], "x", comp_tags(listed, c.get("tb") or "")
        tb = (c.get("tb") or "").strip()
        pur = c.get("p") or ""
        ti, tq = "", ""
        r = by_rules(tb) if len(tb) >= 2 else None
        if r:
            ti, tq = r, "r"
        else:
            r = by_rules(tb + " " + (c.get("t") or "")) or (by_rules(pur) if len(tb) < 2 else None)
            if r:
                ti, tq = r, "r"
            else:
                k, sc = by_ksic_name((tb + " " + pur).strip())
                if k and sc >= 0.6:
                    ti, tq = k, "k"
                elif len(tb) >= 2:
                    e = est_industry(" ".join([c.get("t") or "", tb, tb, pur]))
                    if e:
                        ti, tq = e, "e"
        # 세부 업종: 대상 사업 문구(없으면 상호·목적)에서 제품 키워드로 찾는다. 앞 2자리가 위 업종과 같은 것만 인정.
        txt = tb if len(tb) >= 2 else ((c.get("t") or "") + " " + pur)
        tg = [x for x in detail_codes(txt, ks_names) if not ti or x[:2] == ti][:4]
        if not tg and tq in ("r", "k") and len(tb) >= 2:
            kc, ksc = by_ksic_full(tb)
            if kc and ksc >= 0.8 and len(kc) >= 3 and (not ti or kc[:2] == ti):
                tg = [kc]
        if tg and not ti:
            ti, tq = tg[0][:2], "r"
        return ti, tq, tg
    # 그룹 표시용 접두어: 같은 이름으로 시작하는 상장사가 4곳 이상인 접두어(삼성·현대·한화·롯데 등)는 그룹 이름으로 본다.
    # 단, 흔한 낱말(한국·에스·아이·케이 등)은 서로 다른 회사끼리도 겹치므로 제외한다.
    GENERIC = {"에스", "한국", "아이", "케이", "에이", "제이", "미래", "와이", "바이", "하이", "유니", "대한", "우리", "에코", "이노", "코스",
               "서울", "네오", "제일", "메디", "코오", "디와", "넥스", "그린", "한일", "동일", "엔에", "동양", "씨앤", "디에", "드림", "대원",
               "원익", "신세", "비엔", "에프", "이엔", "티에", "지에", "엠에", "인터", "글로", "뉴보", "에너", "바이오", "신성", "대성", "동방"}
    pref = collections.Counter(nn(c["n"])[:2] for c in comps if len(nn(c["n"])) >= 3)
    pref3 = collections.Counter(nn(c["n"])[:3] for c in comps if len(nn(c["n"])) >= 4)
    stems = {k for k, v in pref.items() if v >= 4} - GENERIC
    subs = {c["c"]: {nn(x) for x in c.get("sub", [])} for c in comps}
    bynm_all = {}
    for c in comps:
        if len(nn(c["n"])) >= 2:
            bynm_all.setdefault(nn(c["n"]), c)

    def group_of(c, b):
        """그룹사(계열) 내 거래 판정 → 'sub'(종속회사 명단) / 'parent'(모회사) / 'holder'(20%↑ 주주) / 'sibling'(형제회사) / 'name'·'stem'(상호) / ''"""
        tn, bn = nn(c.get("t")), nn(c.get("b"))
        if not tn or not bn:
            return ""
        if b:
            bsub = subs.get(c.get("bc"), set())
            if tn in bsub:
                return "sub"
            for sname in bsub:                       # 손자회사: 인수사의 상장 종속회사가 가진 종속회사
                sc = bynm_all.get(sname)
                if sc and tn in subs.get(sc["c"], ()):
                    return "sub"
            hold = [(nn(x[0]), x[1]) for x in (b.get("h") or []) if x and x[0]]
            if hold:
                top = hold[0][0]
                if hold[0][1] >= 20 and len(top) >= 2 and (tn == top or (len(top) >= 3 and tn.startswith(top))):
                    return "parent"
                par = bynm_all.get(top)
                if par and tn in subs.get(par["c"], ()):
                    return "sibling"
            for hn, pc in hold:
                if pc >= 20 and len(hn) >= 3 and (tn == hn or tn.startswith(hn)):
                    return "holder"
        # 상호로 추정 (인수사가 색인에 없는 리츠·금융사 등도 포함)
        if len(bn) >= 2 and tn.startswith(bn) and len(tn) > len(bn) and bn not in GENERIC:
            return "name"
        if len(tn) >= 3 and len(bn) > len(tn) and bn.startswith(tn):            # 인수사 이름이 대상 이름을 포함(예: 아이티센코어 → 아이티센)
            return "name"
        if len(bn) >= 4 and tn[:4] == bn[:4]:
            return "name"
        if len(bn) >= 3 and tn[:3] == bn[:3] and (bn[:2] not in GENERIC or pref3.get(bn[:3], 0) <= 4):
            return "name"
        if "금융" in bn and tn[:2] == bn[:2]:                                    # 우리금융지주 → 우리투자증권 등
            return "name"
        if bn[:2] in stems and tn.startswith(bn[:2]):
            return "stem"
        if len(bn) >= 3 and bn[:2] not in GENERIC and pref.get(bn[:2], 0) <= 3 and tn.startswith(bn[:2]) and re.match(r"[가-힣A-Za-z]", bn[:2]):
            return "name"
        return ""

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
        foreign = not re.search(r"[가-힣]", c.get("t") or "")
        group = group_of(c, b)
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
        ti, tq, tg = target_industry(c)
        out.append({
            "d": c["d"], "b": c["b"], "bc": c.get("bc"), "t": c.get("t"), "tb": c.get("tb"), "a": c.get("a"), "s": c.get("s"),
            "p": c.get("p"), "cp": c.get("cp"), "r": c.get("r"), "k": k, "ty": ty,
            "g": group, "f": 1 if foreign else 0,
            "bi": (b.get("ic") or "")[:2] if b else "",
            "ti": ti, "tq": tq, "tg": tg,
            "bk": (b.get("ic") or "") if b else "",
            "bt": comp_tags(b) if b else [],
        })
    out.sort(key=lambda x: x["d"], reverse=True)
    json.dump({"updated": dt.date.today().isoformat(), "n": len(out), "cases": out},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    g = sum(1 for x in out if x["g"])
    print(f"{OUT}: {len(out)}건 (그룹사 내 {g}건, 해외 대상 {sum(x['f'] for x in out)}건, 대상 업종 {sum(1 for x in out if x['ti'])}건: "
          + ", ".join(f"{q}={n}" for q, n in collections.Counter(x['tq'] for x in out).items()) + ")")


if __name__ == "__main__":
    main()
