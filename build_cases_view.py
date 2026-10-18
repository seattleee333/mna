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
        text = " ".join([c.get("t") or "", c.get("tb") or "", c.get("tb") or "", c.get("p") or ""])
        out.append({
            "d": c["d"], "b": c["b"], "bc": c.get("bc"), "t": c.get("t"), "tb": c.get("tb"), "a": c.get("a"), "s": c.get("s"),
            "p": c.get("p"), "cp": c.get("cp"), "r": c.get("r"), "k": k, "ty": ty,
            "g": group, "f": 1 if foreign else 0,
            "bi": (b.get("ic") or "")[:2] if b else "",
            "ti": est_industry(text) or "",
        })
    out.sort(key=lambda x: x["d"], reverse=True)
    json.dump({"updated": dt.date.today().isoformat(), "n": len(out), "cases": out},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    g = sum(1 for x in out if x["g"])
    print(f"{OUT}: {len(out)}건 (그룹사 내 {g}건, 해외 대상 {sum(x['f'] for x in out)}건, 대상 업종 추정 {sum(1 for x in out if x['ti'])}건)")


if __name__ == "__main__":
    main()
