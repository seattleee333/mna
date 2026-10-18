"""공시 제목 점검: 최근 N일의 주요사항보고서(B)·거래소공시(I) 제목을 모아, M&A·기업 인수와 관련될 만한 제목 유형을 빈도순으로 보여 준다.
(우리 수집 규칙이 놓치는 제목이 없는지 확인하는 용도. 결과: titles_scan.txt)
환경변수: DART_API_KEY, DAYS(기본 150)
"""
import os, re, time, collections, datetime as dt
import requests

KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api/list.json"
DAYS = int(os.environ.get("DAYS", "150"))
KW = ["양수", "양도", "인수", "취득", "처분", "합병", "분할", "교환", "이전", "공개매수", "최대주주", "경영권", "지분", "출자", "매각", "매수",
      "자산", "영업", "신주", "유상증자", "전환사채", "교환사채", "우회상장", "스핀", "SPAC", "기업인수목적"]
out = []


def get(params):
    for i in range(3):
        try:
            r = requests.get(BASE, params=dict(params, crtfc_key=KEY), timeout=40)
            return r.json()
        except Exception:
            time.sleep(2 * (i + 1))
    return {"status": "999"}


def norm(t):
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"^(\[[^\]]*\])+", "", t)          # [기재정정] 같은 머리말
    t = re.sub(r"^주요사항보고서\((.*)\)$", r"주요사항보고서·\1", t)
    return t


def main():
    end = dt.date.today()
    cnt, ex = collections.Counter(), {}
    d0 = end - dt.timedelta(days=DAYS)
    step = dt.timedelta(days=7)
    cur = d0
    calls = 0
    while cur <= end:
        e = min(cur + step - dt.timedelta(days=1), end)
        for ty in ("B", "I"):
            page = 1
            while True:
                d = get({"bgn_de": cur.strftime("%Y%m%d"), "end_de": e.strftime("%Y%m%d"), "pblntf_ty": ty, "page_no": page, "page_count": 100})
                calls += 1
                if d.get("status") != "000":
                    break
                for it in d.get("list", []):
                    n = norm(it.get("report_nm", ""))
                    cnt[n] += 1
                    ex.setdefault(n, (it.get("corp_name"), it.get("rcept_dt")))
                if page >= int(d.get("total_page", 1)):
                    break
                page += 1
                time.sleep(0.05)
        cur += step
    out.append(f"기간 {d0}~{end}, API {calls}회, 제목 유형 {len(cnt)}개")
    out.append("\n== M&A·인수 관련 키워드가 들어간 제목 (빈도순) ==")
    for t, c in cnt.most_common():
        if any(k in t for k in KW):
            out.append(f"{c:5d}  {t}   (예: {ex[t][0]} {ex[t][1]})")
    open("titles_scan.txt", "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out[:60]))


if __name__ == "__main__":
    main()
