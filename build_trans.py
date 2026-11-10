"""업종 간 인수 패턴 표 → ma_trans.json
최근 5년 상장사 타법인 취득 사례(ma_cases_view.json)에서 '대상 회사 업종(KSIC 중분류) → 인수한 회사 업종'을 센다.
AI 매칭(match.js)이 '이 업종 회사를 실제로 사 간 업종'을 점수에 넣을 때 쓴다.
계열사·해외 법인 출자, 금융·부동산·펀드 출자는 뺀다. 사례마다 한 줄씩 저장해 채점 때 그 사례만 빼고 계산할 수 있게 한다.
"""
import re
import json
import datetime as dt

FIN = re.compile(r"투자|펀드|조합|부동산|금융|자산운용|캐피탈|저축은행|보험|신탁|임대|SPC|PFV|특수목적")


def nn(x):
    x = re.sub(r"㈜|\(주\)|주식회사|\(.*?\)|\s|[.,·&\-]", "", str(x or ""))
    return x.upper()


def main():
    v = json.load(open("ma_cases_view.json", encoding="utf-8"))["cases"]
    rows, seen = [], set()
    for c in v:
        ti, bk = c.get("ti") or "", c.get("bk") or ""
        if c.get("g") or c.get("f") or not ti or len(bk) < 2 or ti in ("64", "65", "66", "68"):
            continue
        if FIN.search(c.get("tb") or ""):
            continue
        b, t = nn(c.get("b")), nn(c.get("t"))
        if len(b) >= 2 and t.startswith(b[:2]):
            continue
        key = (c.get("bc"), t)
        if key in seen:       # 같은 회사를 여러 번 나눠 산 경우는 한 번만
            continue
        seen.add(key)
        rows.append([ti, bk[:3], c.get("bc"), c.get("r"), t[:20]])
    json.dump({"built": dt.date.today().isoformat(), "rows": rows}, open("ma_trans.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"ma_trans.json: 사례 {len(rows)}건")


if __name__ == "__main__":
    main()
