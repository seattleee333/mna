"""AI 매칭(무료판)용 검색 색인 생성 → match_index.json
입력 : company_profiles.xlsx (사업의 개요·주요 제품·원재료·매출 본문 + 재무), ma_cache.json (5년 타법인 취득 공시)
방식 : 글자 2개 단위(bigram) TF-IDF 벡터를 사업(P)·원재료(M)·매출/고객(S) 세 영역으로 나눠 상위 항목만 저장하고,
       근거로 보여 줄 공시 원문 문장을 영역별로 몇 개씩 함께 저장한다. 매칭 계산은 브라우저(match.js)에서 한다.
       → AI API 비용 없음. 회사 데이터가 바뀌면(profiles 워크플로 후) 이 파일만 다시 돌리면 된다.
공개 저장소용이므로 공시(공개) 데이터만 쓴다. 매도 희망 기업 정보는 어디에도 저장하지 않는다.
"""
import re, json, math, collections, datetime as dt
import openpyxl

SRC = "company_profiles.xlsx"
MA = "ma_cache.json"
OUT = "match_index.json"
K = {"P": 80, "M": 40, "S": 40}          # 영역별 저장 항목 수
NSENT = {"P": 7, "M": 3, "S": 3}         # 영역별 근거 문장 수
HANGUL = re.compile(r"[가-힣]{2,}")
ALNUM = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9&\-]{1,7}(?![A-Za-z0-9])")   # match.js 와 동일 규칙


def tokens(text):
    out = []
    for w in HANGUL.findall(text):
        out.extend(w[i:i + 2] for i in range(len(w) - 1))
    out.extend(ALNUM.findall(text))
    return out


def sentences(text):
    text = re.sub(r"[ \t]+", " ", text.replace("|", " "))
    res = []
    for s in re.split(r"(?<=[.다음임함])\s+|\n", text):
        s = s.strip(" -·●○※▶■□◆◇ㆍ")
        if not (20 <= len(s) <= 140):
            continue
        han = len(re.findall(r"[가-힣]", s))
        dig = len(re.findall(r"[0-9]", s))
        if han / len(s) < 0.55 or dig / len(s) > 0.2:
            continue
        res.append(s)
    return res


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    H = rows[0]
    ix = {h: i for i, h in enumerate(H)}
    g = lambda r, k: r[ix[k]] if k in ix and r[ix[k]] is not None else ""

    comps = []
    for r in rows[1:]:
        P = f"{g(r, '사업의 개요')}\n{g(r, '주요 제품 및 서비스')}"
        M = str(g(r, "원재료 및 생산설비"))
        S = str(g(r, "매출 및 수주상황"))
        comps.append({"r": r, "txt": {"P": P, "M": M, "S": S}})

    # 문서 빈도 (영역 구분 없이 회사 단위)
    df = collections.Counter()
    for c in comps:
        c["tf"] = {k: collections.Counter(tokens(v)) for k, v in c["txt"].items()}
        for t in set().union(*[set(x) for x in c["tf"].values()]):
            df[t] += 1
    N = len(comps)
    # 너무 흔하거나(35% 초과) 한 번만 나온 토큰은 제외
    vocab = sorted(t for t, d in df.items() if 2 <= d <= 0.35 * N)
    vid = {t: i for i, t in enumerate(vocab)}
    idf = [round(math.log(N / df[t]), 2) for t in vocab]

    # 5년 인수 이력
    acq = collections.defaultdict(list)
    try:
        ma = json.load(open(MA, encoding="utf-8"))
        for f in ma.get("filings", {}).values():
            if f.get("kind") == "acq" and f.get("stock_code"):
                acq[f["stock_code"]].append(f["date"])
    except Exception:
        pass

    out = []
    for c in comps:
        r = c["r"]
        code = str(g(r, "종목코드")).zfill(6)
        item = {"c": code, "n": g(r, "회사명"), "m": g(r, "시장"), "u": g(r, "공시링크"), "fs": g(r, "재무구분")}

        def f(k):
            v = g(r, k)
            try:
                return round(float(v), 1)
            except (TypeError, ValueError):
                return None
        item["f"] = [f("2025 매출액(억)"), f("2025 영업이익(억)"), f("2025 자본총계(억)"), f("2025 부채총계(억)"), f("2024 매출액(억)")]
        d = sorted(acq.get(code, []))
        item["a"] = [len(d), d[-1] if d else ""]
        e = {}
        for key in ("P", "M", "S"):
            tf = c["tf"][key]
            w = {vid[t]: (1 + math.log(n)) * idf[vid[t]] for t, n in tf.items() if t in vid}
            top = sorted(w.items(), key=lambda x: -x[1])[:K[key]]
            norm = math.sqrt(sum(v * v for _, v in top)) or 1
            item[key] = [x for i, v in top for x in (i, max(1, round(v / norm * 100)))]
            # 근거 문장: 상위 토큰 가중치 합이 큰 문장
            top_ids = dict(top)
            scored = []
            for s in sentences(c["txt"][key]):
                st = set(vid[t] for t in tokens(s) if t in vid)
                sc = sum(top_ids.get(i, 0) for i in st) / math.sqrt(len(s))
                if sc > 0:
                    scored.append((sc, s))
            scored.sort(key=lambda x: -x[0])
            e[key] = [s for _, s in scored[:NSENT[key]]]
        item["e"] = e
        out.append(item)

    json.dump({"v": 1, "built": dt.date.today().isoformat(), "vocab": vocab, "idf": idf, "c": out},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{OUT}: 회사 {len(out)}곳, 어휘 {len(vocab)}개")


if __name__ == "__main__":
    main()
