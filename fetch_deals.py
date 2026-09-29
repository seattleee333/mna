import os
import json
import time
import datetime as dt

import requests

API_KEY = os.environ["DART_API_KEY"]
DAYS = int(os.environ.get("DAYS", "7"))
OUT = "deals.json"
BASE = "https://opendart.fss.or.kr/api/"

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


def call(name, params):
    p = dict(params)
    p["crtfc_key"] = API_KEY
    try:
        r = requests.get(BASE + name, params=p, timeout=30)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        # 오류 메시지에 인증키가 섞이지 않도록 내용은 숨긴다
        raise RuntimeError("DART 요청에 실패했습니다 (네트워크 또는 서버 오류)") from None


def fetch_day(day):
    """하루치 공시 목록을 전부 가져온다 (주말/휴일은 데이터 없음)."""
    items = []
    page = 1
    while True:
        data = call("list.json", {
            "bgn_de": day, "end_de": day, "page_no": page, "page_count": 100,
        })
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


# ---------- 딜 상세 (대상 회사, 상대방, 금액) ----------

def parse_amount(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace(" ", "")
    try:
        n = int(float(s))
    except ValueError:
        return None
    return n if n > 0 else None


def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "-") else s


def route(deal):
    """공시 종류에 맞는 DART 상세 API 이름을 고른다. 없으면 None."""
    t = deal["report_nm"].replace(" ", "")
    c = deal["category"]
    if c == "타법인 주식 취득·처분":
        return "otcprStkInvscrInhDecsn" if ("양수" in t or "취득" in t) else "otcprStkInvscrTrfDecsn"
    if c == "영업양수도":
        return "bsnInhDecsn" if "양수" in t else "bsnTrfDecsn"
    if c == "합병" and "회사합병결정" in t:
        return "cmpMgDecsn"
    if c == "유상증자":
        return "piicDecsn"
    return None


def extract(endpoint, row):
    if endpoint == "otcprStkInvscrInhDecsn":
        eq = clean(row.get("atinh_eqrt"))
        return {
            "direction": "양수",
            "target": clean(row.get("iscmp_cmpnm")),
            "counterparty": clean(row.get("dlptn_cmpnm")),
            "amount": parse_amount(row.get("inhdtl_inhprc")),
            "note": f"취득 후 지분율 {eq}%" if eq else None,
        }
    if endpoint == "otcprStkInvscrTrfDecsn":
        eq = clean(row.get("attrf_eqrt"))
        return {
            "direction": "양도",
            "target": clean(row.get("iscmp_cmpnm")),
            "counterparty": clean(row.get("dlptn_cmpnm")),
            "amount": parse_amount(row.get("trfdtl_trfprc")),
            "note": f"양도 후 지분율 {eq}%" if eq else None,
        }
    if endpoint == "bsnInhDecsn":
        return {
            "direction": "양수",
            "target": clean(row.get("inh_bsn")),
            "counterparty": clean(row.get("dlptn_cmpnm")),
            "amount": parse_amount(row.get("inh_prc")),
            "note": None,
        }
    if endpoint == "bsnTrfDecsn":
        return {
            "direction": "양도",
            "target": clean(row.get("trf_bsn")),
            "counterparty": clean(row.get("dlptn_cmpnm")),
            "amount": parse_amount(row.get("trf_prc")),
            "note": None,
        }
    if endpoint == "cmpMgDecsn":
        rt = clean(row.get("mg_rt"))
        return {
            "direction": None,
            "target": clean(row.get("mgptncmp_cmpnm")),
            "counterparty": None,
            "amount": None,
            "note": f"합병비율 {rt}" if rt else None,
        }
    if endpoint == "piicDecsn":
        keys = ["fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"]
        total = sum(parse_amount(row.get(k)) or 0 for k in keys)
        mthn = clean(row.get("ic_mthn"))
        return {
            "direction": None,
            "target": None,
            "counterparty": None,
            "amount": total or None,
            "note": f"증자방식: {mthn}" if mthn else None,
        }
    return {}


def enrich(deal, cache, stats):
    """상세 정보를 채운다. 다시 시도할 필요가 없으면 True."""
    endpoint = route(deal)
    if not endpoint:
        stats["no_api"] += 1  # 이 딜 유형은 DART에 상세 API 자체가 없음
        deal["no_detail_api"] = True
        return True
    if "정정" in deal["report_nm"]:
        stats["skip_correction"] += 1
        deal["no_detail_api"] = True
        return True
    key = (endpoint, deal["corp_code"], deal["date"])
    if key not in cache:
        data = call(endpoint + ".json", {
            "corp_code": deal["corp_code"], "bgn_de": deal["date"], "end_de": deal["date"],
        })
        status = data.get("status")
        if status == "013":
            rows = []
        elif status == "000":
            rows = data.get("list", [])
        elif status == "020":
            raise RuntimeError("DART 요청 한도 초과")
        else:
            stats["api_error"] += 1
            print(f"  상세 API 오류 [{endpoint}] {deal['corp_name']} {deal['date']}: "
                  f"status={status} message={data.get('message')}")
            return False  # 다음 실행에서 다시 시도
        cache[key] = rows
        time.sleep(0.1)
    rows = cache[key]
    row = next((x for x in rows if x.get("rcept_no") == deal["rcept_no"]), None)
    if row is None and len(rows) == 1:
        row = rows[0]
    if row:
        deal.update(extract(endpoint, row))
        stats["matched"] += 1
    else:
        stats["no_match"] += 1
        print(f"  매칭 실패 [{endpoint}] {deal['corp_name']} {deal['date']} "
              f"rcept_no={deal['rcept_no']}: 상세API가 그 날짜에 반환한 건수={len(rows)}")
        return False  # 원인 파악될 때까지 매번 다시 시도 (로그도 매번 남김)
    return True


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
            entry = existing.get(rcept_no, {})
            entry.update({
                "rcept_no": rcept_no,
                "date": it["rcept_dt"],
                "corp_code": it["corp_code"],
                "corp_name": it["corp_name"],
                "stock_code": it["stock_code"],
                "market": it.get("corp_cls", ""),
                "report_nm": it["report_nm"].strip(),
                "category": category,
            })
            existing[rcept_no] = entry
        print(f"{day} 목록 처리 완료")

    # 상세 정보(대상 회사, 상대방, 금액) 채우기
    cache = {}
    filled = 0
    stats = {"matched": 0, "no_match": 0, "no_api": 0, "api_error": 0, "skip_correction": 0}
    for d in existing.values():
        if not d.get("corp_code"):
            continue
        # 이미 상세 정보가 채워졌거나(target/amount/note 중 하나라도 있음),
        # 애초에 상세 API가 없는 유형으로 확인된 건은 다시 조회하지 않는다.
        has_detail = d.get("target") or d.get("amount") is not None or d.get("note")
        if has_detail or d.get("no_detail_api"):
            continue
        try:
            if enrich(d, cache, stats):
                d["detail_done"] = True
                filled += 1
        except RuntimeError as e:
            print(f"상세 조회 중단/건너뜀: {e}")
            if "한도" in str(e):
                break

    deals = sorted(existing.values(), key=lambda d: (d["date"], d["rcept_no"]), reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    print(f"신규 {added}건 추가, 상세 처리 {filled}건, 전체 {len(deals)}건")
    print(f"상세 내역 - 채워짐:{stats['matched']} 매칭실패:{stats['no_match']} "
          f"API없는유형:{stats['no_api']} API오류:{stats['api_error']} 정정건너뜀:{stats['skip_correction']}")


if __name__ == "__main__":
    main()
