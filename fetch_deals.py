import os
import re
import io
import json
import time
import zipfile
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


def _has_batchim(word):
    if not word:
        return False
    ch = word[-1]
    code = ord(ch) - 0xAC00
    if 0 <= code < 11172:
        return (code % 28) != 0
    return False  # 한글 음절이 아니면(영문/숫자 등) 받침 없는 것으로 간주


def josa(word, with_batchim, without_batchim):
    return with_batchim if _has_batchim(word) else without_batchim


def eun_neun(word):
    return josa(word, "은", "는")


def i_ga(word):
    return josa(word, "이", "가")


def eul_reul(word):
    return josa(word, "을", "를")


def euro_ro(word):
    if word and word[-1] and _has_batchim(word) is False:
        return "로"
    # 받침이 'ㄹ'인 경우도 '로' (예: 서울로) - 간단히 처리
    if word:
        code = ord(word[-1]) - 0xAC00
        if 0 <= code < 11172 and (code % 28) == 8:  # 'ㄹ' 받침
            return "로"
    return "으로"


def fmt_amount(n):
    """숫자를 '750억원' 같은 한국어 금액 표현으로 바꾼다 (요약 문장에 넣기 위함)."""
    if n is None:
        return "금액 미상"
    if n >= 1e12:
        v = n / 1e12
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{s}조원"
    if n >= 1e8:
        return f"{round(n / 1e8):,}억원"
    if n >= 1e4:
        return f"{round(n / 1e4):,}만원"
    return f"{n:,}원"


def extract(endpoint, row, corp_name):
    """회사명을 넣어 인수회사/매도회사가 명확히 구분되는 필드와, 쉽게 읽히는 한 줄 요약을 만든다."""
    if endpoint == "otcprStkInvscrInhDecsn":
        # 이 공시를 낸 회사(corp_name)가 대상회사(target) 지분을 거래상대방(counterparty)으로부터 사들이는 경우
        eq = clean(row.get("atinh_eqrt"))
        target = clean(row.get("iscmp_cmpnm"))
        counterparty = clean(row.get("dlptn_cmpnm"))
        amount = parse_amount(row.get("inhdtl_inhprc"))
        eq_txt = f", 인수 후 지분율 {eq}%" if eq else ""
        return {
            "direction": "양수",
            "buyer": corp_name,
            "seller": counterparty,
            "target": target,
            "amount": amount,
            "note": f"인수 후 지분율 {eq}%" if eq else None,
            "summary": f"{corp_name}{i_ga(corp_name)} {counterparty or '거래상대방'}{euro_ro(counterparty or '거래상대방')}부터 "
                       f"{target or '대상회사'} 지분을 {fmt_amount(amount)}에 인수합니다{eq_txt}.",
        }
    if endpoint == "otcprStkInvscrTrfDecsn":
        # 이 공시를 낸 회사(corp_name)가 보유 중이던 대상회사(target) 지분을 거래상대방(counterparty)에게 파는 경우
        eq = clean(row.get("attrf_eqrt"))
        target = clean(row.get("iscmp_cmpnm"))
        counterparty = clean(row.get("dlptn_cmpnm"))
        amount = parse_amount(row.get("trfdtl_trfprc"))
        eq_txt = f", 처분 후 지분율 {eq}%" if eq else ""
        return {
            "direction": "양도",
            "buyer": counterparty,
            "seller": corp_name,
            "target": target,
            "amount": amount,
            "note": f"처분 후 지분율 {eq}%" if eq else None,
            "summary": f"{corp_name}{i_ga(corp_name)} 보유 중이던 {target or '대상회사'} 지분을 "
                       f"{counterparty or '거래상대방'}에 {fmt_amount(amount)}에 매각합니다{eq_txt}.",
        }
    if endpoint == "bsnInhDecsn":
        target = clean(row.get("inh_bsn"))
        counterparty = clean(row.get("dlptn_cmpnm"))
        amount = parse_amount(row.get("inh_prc"))
        return {
            "direction": "양수",
            "buyer": corp_name,
            "seller": counterparty,
            "target": target,
            "amount": amount,
            "note": None,
            "summary": f"{corp_name}{i_ga(corp_name)} {counterparty or '거래상대방'}{euro_ro(counterparty or '거래상대방')}부터 "
                       f"{target or '해당 영업'}{eul_reul(target or '해당 영업')} {fmt_amount(amount)}에 양수합니다.",
        }
    if endpoint == "bsnTrfDecsn":
        target = clean(row.get("trf_bsn"))
        counterparty = clean(row.get("dlptn_cmpnm"))
        amount = parse_amount(row.get("trf_prc"))
        return {
            "direction": "양도",
            "buyer": counterparty,
            "seller": corp_name,
            "target": target,
            "amount": amount,
            "note": None,
            "summary": f"{corp_name}{i_ga(corp_name)} {target or '해당 영업'}{eul_reul(target or '해당 영업')} "
                       f"{counterparty or '거래상대방'}에 {fmt_amount(amount)}에 양도합니다.",
        }
    if endpoint == "cmpMgDecsn":
        rt = clean(row.get("mg_rt"))
        target = clean(row.get("mgptncmp_cmpnm"))
        return {
            "direction": None,
            "buyer": corp_name,  # 합병 후 존속회사
            "seller": target,     # 합병으로 소멸되는 상대회사
            "target": target,
            "amount": None,
            "note": f"합병비율 {rt}" if rt else None,
            "summary": f"{corp_name}{i_ga(corp_name)} {target or '상대회사'}{eul_reul(target or '상대회사')} 흡수합병합니다"
                       + (f" (합병비율 {rt})" if rt else "") + ".",
        }
    if endpoint == "piicDecsn":
        keys = ["fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"]
        total = sum(parse_amount(row.get(k)) or 0 for k in keys)
        mthn = clean(row.get("ic_mthn"))
        return {
            "direction": None,
            "buyer": None,
            "seller": None,
            "target": None,
            "amount": total or None,
            "note": f"증자방식: {mthn}" if mthn else None,
            "summary": f"{corp_name}{i_ga(corp_name)} {mthn or '유상증자'} 방식으로 "
                       f"{fmt_amount(total or None)}{eul_reul(fmt_amount(total or None))} 조달합니다.",
        }
    return {}


# ---------- 상세 API가 매칭에 실패했을 때의 보완책: 공시 원문 직접 파싱 ----------
# "타법인주식및출자증권처분/취득결정" 같은 상세 API는 "금융위 주요사항보고서"로 접수된
# 건만 커버한다. 같은 제목이라도 "거래소(코스닥/유가증권시장본부) 소관"으로 접수되면
# 그 API엔 애초에 데이터가 없다 (회사 양식 차이가 아니라 접수 경로 차이).
# document.xml API는 접수번호만 있으면 접수 경로와 상관없이 공시 원문을 그대로
# 돌려주므로, 이걸로 표준 서식 표를 직접 파싱해서 보완한다.

RAW_DEBUG = []  # 임시 진단용 — 원인 파악 후 제거 예정


def fetch_raw_document(rcept_no):
    """공시서류 원문(zip, 내부는 utf-8 html)을 받아 합쳐진 텍스트로 반환한다."""
    try:
        r = requests.get(BASE + "document.xml", params={"crtfc_key": API_KEY, "rcept_no": rcept_no}, timeout=30)
        r.raise_for_status()
    except requests.RequestException:
        return None
    if not r.content.startswith(b"PK"):  # zip이 아니면(오류 JSON 등) 포기
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        return None
    texts = []
    for name in zf.namelist():
        try:
            raw_bytes = zf.read(name)
            try:
                texts.append(raw_bytes.decode("utf-8"))
            except UnicodeDecodeError:
                texts.append(raw_bytes.decode("euc-kr", errors="ignore"))
        except Exception:
            continue
    return "\n".join(texts) if texts else None


def strip_tags(html):
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_from_raw_doc(raw_html, corp_name, direction_hint):
    """'타법인 주식 및 출자증권 취득/처분결정' 표준 서식 원문에서 핵심 정보를 뽑아낸다.
    (규제상 정해진 서식이라 금융위/거래소 소관과 무관하게 표 구조는 동일하다.)"""
    text = strip_tags(raw_html)

    target = None
    m = re.search(r"회사명\s*\(국적\)\s*([가-힣A-Za-z0-9&·]+(?:\s*주식회사)?)", text)
    if m:
        target = m.group(1).strip()

    counterparty = None
    for pat in [r"거래상대방\s*[:：]\s*([가-힣A-Za-z0-9&·]+(?:\s*주식회사)?)",
                r"거래상대방\s+([가-힣A-Za-z0-9&·]+(?:\s*주식회사)?)"]:
        m = re.search(pat, text)
        if m:
            counterparty = m.group(1).strip()
            break

    amount = None
    for label in ["처분금액", "취득금액"]:
        m = re.search(label + r"\s*\(원\)\s*([\d,]+)", text)
        if m:
            amount = parse_amount(m.group(1))
            break

    if not target or amount is None:
        return None  # 핵심 정보를 못 찾으면 포기 (원문 형식이 또 다른 예외 케이스)

    if direction_hint == "양도":
        summary = (f"{corp_name}{i_ga(corp_name)} 보유 중이던 {target} 지분을 "
                   f"{(counterparty + '에') if counterparty else '제3자에'} {fmt_amount(amount)}에 매각합니다.")
        buyer, seller = counterparty, corp_name
    else:
        from_txt = f"{counterparty}{euro_ro(counterparty)}부터 " if counterparty else ""
        summary = f"{corp_name}{i_ga(corp_name)} {from_txt}{target} 지분을 {fmt_amount(amount)}에 인수합니다."
        buyer, seller = corp_name, counterparty

    return {
        "direction": direction_hint, "buyer": buyer, "seller": seller,
        "target": target, "amount": amount, "note": None, "summary": summary,
    }


MAX_ATTEMPTS = 5  # 이 횟수만큼 재시도해도 안 되면 포기하고 더 이상 조회하지 않는다

# 이 문구가 제목에 있으면 "금융위 주요사항보고서"가 아니라 "거래소 수시공시"로 접수된
# 건일 가능성이 커서, 애초에 이 상세 API들에 데이터가 없다 (구조적 한계, 재시도해도 소용없음).
NO_API_HINTS = ["정정", "자회사의 주요경영사항", "종속회사의주요경영사항", "종속회사의 주요경영사항"]


def enrich(deal, cache, stats, diag_budget):
    """상세 정보를 채운다. 다시 시도할 필요가 없으면 True."""
    endpoint = route(deal)
    if not endpoint:
        stats["no_api"] += 1  # 이 딜 유형은 DART에 상세 API 자체가 없음
        deal["no_detail_api"] = True
        return True
    title_flat = deal["report_nm"].replace(" ", "")
    if any(h.replace(" ", "") in title_flat for h in NO_API_HINTS):
        stats["skip_correction"] += 1
        deal["no_detail_api"] = True
        return True
    # 상세 API가 실제로 그 딜을 잡아두는 날짜가 목록 API의 접수일자(rcept_dt)와
    # 하루이틀 어긋나는 경우가 있어, 정확히 하루만 조회하지 않고 앞뒤로 여유를 두고 조회한다.
    base_day = dt.datetime.strptime(deal["date"], "%Y%m%d")
    win_bgn = (base_day - dt.timedelta(days=3)).strftime("%Y%m%d")
    win_end = (base_day + dt.timedelta(days=3)).strftime("%Y%m%d")
    key = (endpoint, deal["corp_code"], win_bgn, win_end)
    if key not in cache:
        data = call(endpoint + ".json", {
            "corp_code": deal["corp_code"], "bgn_de": win_bgn, "end_de": win_end,
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
        deal.update(extract(endpoint, row, deal["corp_name"]))
        stats["matched"] += 1
        return True

    stats["no_match"] += 1
    print(f"  매칭 실패 [{endpoint}] {deal['corp_name']} {deal['date']} "
          f"rcept_no={deal['rcept_no']}: 상세API가 {win_bgn}~{win_end} 기간에 반환한 건수={len(rows)}")

    # 보완책: 상세 API가 매칭 못한 건(주로 거래소 소관으로 접수돼 금융위 API에
    # 데이터가 없는 경우)은 공시 원문을 직접 받아 표준 서식을 파싱해본다.
    if endpoint in ("otcprStkInvscrInhDecsn", "otcprStkInvscrTrfDecsn"):
        direction_hint = "양수" if endpoint == "otcprStkInvscrInhDecsn" else "양도"
        raw = fetch_raw_document(deal["rcept_no"])
        if raw:
            parsed = extract_from_raw_doc(raw, deal["corp_name"], direction_hint)
            if parsed:
                deal.update(parsed)
                deal["source"] = "raw_document"
                stats["matched_raw"] += 1
                print(f"  원문 파싱으로 보완 성공: {deal['corp_name']} {deal['rcept_no']}")
                return True
            else:
                RAW_DEBUG.append({
                    "rcept_no": deal["rcept_no"], "corp_name": deal["corp_name"],
                    "raw_len": len(raw), "stripped_sample": strip_tags(raw)[:3000],
                })
                print(f"  원문은 받았으나 파싱 실패: {deal['corp_name']} {deal['rcept_no']} (len={len(raw)})")
        else:
            RAW_DEBUG.append({"rcept_no": deal["rcept_no"], "corp_name": deal["corp_name"], "raw": None})
            print(f"  원문 자체를 못 받음: {deal['corp_name']} {deal['rcept_no']}")

    # 원인 진단용: 실행당 최대 2건만, 훨씬 넓은(연간) 범위로 다시 조회해서
    # 이 회사가 이 상세 API에 애초에 데이터가 있기는 한지 확인해본다.
    if diag_budget[0] > 0:
        diag_budget[0] -= 1
        year = deal["date"][:4]
        try:
            wide = call(endpoint + ".json", {
                "corp_code": deal["corp_code"], "bgn_de": year + "0101", "end_de": year + "1231",
            })
            wstatus = wide.get("status")
            wrows = wide.get("list", []) if wstatus == "000" else []
            print(f"  [진단] {deal['corp_name']} {endpoint} {year}년 전체 조회 status={wstatus} "
                  f"건수={len(wrows)}")
            if wrows:
                sample = wrows[0]
                print(f"  [진단] 첫 건 rcept_no={sample.get('rcept_no')} "
                      f"필드수={len(sample)} 필드목록={sorted(sample.keys())}")
        except RuntimeError as e:
            print(f"  [진단] 조회 실패: {e}")

    deal["detail_attempts"] = deal.get("detail_attempts", 0) + 1
    if deal["detail_attempts"] >= MAX_ATTEMPTS:
        deal["no_detail_api"] = True
        stats["gave_up"] += 1
        print(f"  {MAX_ATTEMPTS}회 재시도해도 실패하여 포기: {deal['corp_name']} {deal['rcept_no']}")
        return True  # 더 이상 재시도하지 않음

    return False  # 다음 실행에서 다시 시도


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
    diag_budget = [2]  # 이번 실행에서 [진단] 로그를 남길 수 있는 횟수 (API 호출 아껴쓰기)
    stats = {"matched": 0, "matched_raw": 0, "no_match": 0, "no_api": 0, "api_error": 0, "skip_correction": 0, "gave_up": 0}
    for d in existing.values():
        if not d.get("corp_code"):
            continue
        # 이미 요약 문장(summary)까지 채워졌거나, 애초에 상세 API가 없는 유형으로
        # 확인된 건은 다시 조회하지 않는다. (구버전 스키마로 amount/note만 채워지고
        # summary가 없는 건은 재조회 대상에 포함시켜 새 스키마로 채운다.)
        has_detail = bool(d.get("summary"))
        if has_detail or d.get("no_detail_api"):
            continue
        try:
            if enrich(d, cache, stats, diag_budget):
                d["detail_done"] = True
                filled += 1
        except RuntimeError as e:
            print(f"상세 조회 중단/건너뜀: {e}")
            if "한도" in str(e):
                break

    deals = sorted(existing.values(), key=lambda d: (d["date"], d["rcept_no"]), reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    if RAW_DEBUG:
        with open("_debug_raw.json", "w", encoding="utf-8") as f:
            json.dump(RAW_DEBUG, f, ensure_ascii=False, indent=1)
    print(f"신규 {added}건 추가, 상세 처리 {filled}건, 전체 {len(deals)}건")
    print(f"상세 내역 - 채워짐:{stats['matched']} 원문보완:{stats['matched_raw']} 매칭실패:{stats['no_match']} "
          f"API없는유형:{stats['no_api']} API오류:{stats['api_error']} "
          f"정정/자회사공시건너뜀:{stats['skip_correction']} 포기(재시도한도):{stats['gave_up']}")


if __name__ == "__main__":
    main()
