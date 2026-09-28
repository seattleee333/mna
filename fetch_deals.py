import os
import json
import time
import datetime as dt

import requests

API_KEY = os.environ["DART_API_KEY"]
DAYS = int(os.environ.get("DAYS", "7"))
OUT = "deals.json"
URL = "https://opendart.fss.or.kr/api/list.json"

# (분류명, 공시 제목에 들어있는 키워드)  위에서부터 먼저 맞는 분류를 사용
CATEGORIES = [
    ("최대주주 변경", ["최대주주변경", "최대주주 변경"]),
    ("주식양수도", ["주식양수도", "주식 양수도"]),
    ("합병", ["합병"]),
    ("분할", ["회사분할", "분할결정"]),
    ("주식교환·이전", ["주식교환", "주식이전"]),
    ("영업양수도", ["영업양수", "영업양도"]),
    ("타법인 주식 취득·처분", ["타법인주식및출자증권"]),
    ("공개매수", ["공개매수"]),
    ("유상증자", ["유상증자결정"]),
]


def classify(title):
    t = title.replace(" ", "")
    for name, keywords in CATEGORIES:
        for k in keywords:
            if k.replace(" ", "") in t:
                return name
    return None


def fetch_day(day):
    """하루치 공시를 전부 가져온다 (주말/휴일은 데이터 없음)."""
    items = []
    page = 1
    while True:
        params = {
            "crtfc_key": API_KEY,
            "bgn_de": day,
            "end_de": day,
            "page_no": page,
            "page_count": 100,
        }
        try:
            r = requests.get(URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException:
            # 오류 메시지에 인증키가 섞이지 않도록 내용은 숨긴다
            raise RuntimeError("DART 요청에 실패했습니다 (네트워크 또는 서버 오류)") from None

        status = data.get("status")
        if status == "013":  # 조회된 데이터 없음
            break
        if status != "000":
            raise RuntimeError(f"DART 오류 {status}: {data.get('message')}")

        items.extend(data.get("list", []))
        if page >= int(data.get("total_page", 1)):
            break
        page += 1
        time.sleep(0.2)
    return items


def main():
    existing = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for d in json.load(f):
                existing[d["rcept_no"]] = d

    today = dt.datetime.utcnow() + dt.timedelta(hours=9)  # 한국 시간
    added = 0
    for i in range(DAYS):
        day = (today - dt.timedelta(days=i)).strftime("%Y%m%d")
        for it in fetch_day(day):
            if not it.get("stock_code", "").strip():
                continue  # 비상장사 제외
            category = classify(it.get("report_nm", ""))
            if not category:
                continue
            rcept_no = it["rcept_no"]
            if rcept_no not in existing:
                added += 1
            existing[rcept_no] = {
                "rcept_no": rcept_no,
                "date": it["rcept_dt"],
                "corp_name": it["corp_name"],
                "stock_code": it["stock_code"],
                "market": it.get("corp_cls", ""),
                "report_nm": it["report_nm"].strip(),
                "category": category,
            }
        print(f"{day} 처리 완료")

    deals = sorted(existing.values(), key=lambda d: (d["date"], d["rcept_no"]), reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    print(f"신규 {added}건 추가, 전체 {len(deals)}건")


if __name__ == "__main__":
    main()
