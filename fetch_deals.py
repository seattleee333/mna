import os
import re
import html as _html
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


_CORP_WORDS = re.compile(r"주식회사|\(주\)|㈜")


def short_name(name):
    """'주식회사', '(주)' 같은 법인 표기를 떼고 짧게 만든다 (요약 문장용)."""
    if not name:
        return name
    s = _CORP_WORDS.sub("", name).strip()
    return s or name


def _trim_num(s):
    return s.rstrip("0").rstrip(".") or "0" if "." in s else s


def fmt_ratio(rt):
    """'(주)A : B(주) = 1.0000000 : 0.0000000' 같은 합병비율 문자열에서 '1 : 0'만 남긴다."""
    if not rt:
        return rt
    m = re.search(r"([\d.]+)\s*:\s*([\d.]+)\s*$", rt)
    if m:
        return f"{_trim_num(m.group(1))} : {_trim_num(m.group(2))}"
    return rt


def infer_kind(d):
    """요약 문장의 틀을 결정하는 거래 종류. 예전에 저장된 건은 kind가 없어 다른 필드로 추정한다."""
    if d.get("kind"):
        return d["kind"]
    c, dr = d.get("category"), d.get("direction")
    if c == "타법인 주식 취득·처분":
        return {"양수": "stake_in", "양도": "stake_out"}.get(dr)
    if c == "영업양수도":
        return {"양수": "biz_in", "양도": "biz_out"}.get(dr)
    if c == "합병" and d.get("buyer"):
        return "merger"
    if c == "유상증자":
        return "capital"
    return None


def build_summary(d):
    """'A가 B 지분을 150억원에 인수합니다 (인수 후 지분율 35.2%)' 형태의 한 줄 요약.
    금액·지분율처럼 공시에 없는 항목은 문장에서 뺀다."""
    kind = infer_kind(d)
    a = short_name(d["corp_name"])
    tgt = short_name(d.get("target"))
    amt = d.get("amount")
    money = f"{fmt_amount(amt)}에 " if amt else ""
    note = d.get("note") or ""
    pct = f" ({note})" if "지분율" in note else ""
    if kind == "stake_in":
        return f"{a}{i_ga(a)} {tgt or '대상회사'} 지분을 {money}인수합니다{pct}."
    if kind == "stake_out":
        return f"{a}{i_ga(a)} 보유 중이던 {tgt or '대상회사'} 지분을 {money}매각합니다{pct}."
    if kind in ("biz_in", "biz_out"):
        t = tgt or "해당 영업"
        return f"{a}{i_ga(a)} {t}{eul_reul(t)} {money}{'양수' if kind == 'biz_in' else '양도'}합니다."
    if kind == "merger":
        t = tgt or "상대회사"
        return f"{a}{i_ga(a)} {t}{eul_reul(t)} 흡수합병합니다."
    if kind == "merger_done":
        if tgt:
            return f"{a}{i_ga(a)} {tgt}{eul_reul(tgt)} 흡수합병했습니다" + (f" ({note})" if note else "") + "."
        return f"{a}{i_ga(a)} 합병을 완료했습니다" + (f" ({note})" if note else "") + "."
    if kind == "capital":
        if amt:
            how = note.replace("증자방식:", "").strip()
            fm = fmt_amount(amt)
            return f"{a}{i_ga(a)} {how + ' 방식으로 ' if how else ''}{fm}{eul_reul(fm)} 조달합니다."
        return f"{a}{i_ga(a)} 유상증자를 결정했습니다."
    return None


def finalize_summary(deal):
    note = deal.get("note") or ""
    if note.startswith("합병비율 "):
        deal["note"] = "합병비율 " + fmt_ratio(note[len("합병비율 "):])
    s = build_summary(deal)
    if s:
        deal["summary"] = s
        deal["sum_v"] = 2
        deal["kind"] = infer_kind(deal)


def extract(endpoint, row, corp_name):
    """상세 API 응답 한 행에서 거래 정보를 뽑는다. 요약 문장은 build_summary가 만든다."""
    if endpoint == "otcprStkInvscrInhDecsn":
        # 이 공시를 낸 회사(corp_name)가 대상회사(target) 지분을 거래상대방(counterparty)으로부터 사들이는 경우
        eq = clean(row.get("atinh_eqrt"))
        return {
            "kind": "stake_in", "direction": "양수",
            "buyer": corp_name, "seller": clean(row.get("dlptn_cmpnm")),
            "target": clean(row.get("iscmp_cmpnm")),
            "amount": parse_amount(row.get("inhdtl_inhprc")),
            "note": f"인수 후 지분율 {eq}%" if eq else None,
        }
    if endpoint == "otcprStkInvscrTrfDecsn":
        # 이 공시를 낸 회사(corp_name)가 보유 중이던 대상회사(target) 지분을 거래상대방(counterparty)에게 파는 경우
        eq = clean(row.get("attrf_eqrt"))
        return {
            "kind": "stake_out", "direction": "양도",
            "buyer": clean(row.get("dlptn_cmpnm")), "seller": corp_name,
            "target": clean(row.get("iscmp_cmpnm")),
            "amount": parse_amount(row.get("trfdtl_trfprc")),
            "note": f"처분 후 지분율 {eq}%" if eq else None,
        }
    if endpoint == "bsnInhDecsn":
        return {
            "kind": "biz_in", "direction": "양수",
            "buyer": corp_name, "seller": clean(row.get("dlptn_cmpnm")),
            "target": clean(row.get("inh_bsn")),
            "amount": parse_amount(row.get("inh_prc")), "note": None,
        }
    if endpoint == "bsnTrfDecsn":
        return {
            "kind": "biz_out", "direction": "양도",
            "buyer": clean(row.get("dlptn_cmpnm")), "seller": corp_name,
            "target": clean(row.get("trf_bsn")),
            "amount": parse_amount(row.get("trf_prc")), "note": None,
        }
    if endpoint == "cmpMgDecsn":
        rt = fmt_ratio(clean(row.get("mg_rt")))
        target = clean(row.get("mgptncmp_cmpnm"))
        return {
            "kind": "merger", "direction": None,
            "buyer": corp_name,  # 합병 후 존속회사
            "seller": target,    # 합병으로 소멸되는 상대회사
            "target": target, "amount": None,
            "note": f"합병비율 {rt}" if rt else None,
        }
    if endpoint == "piicDecsn":
        keys = ["fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"]
        total = sum(parse_amount(row.get(k)) or 0 for k in keys)
        mthn = clean(row.get("ic_mthn"))
        return {
            "kind": "capital", "direction": None,
            "buyer": None, "seller": None, "target": None,
            "amount": total or None,
            "note": f"증자방식: {mthn}" if mthn else None,
        }
    return {}


# ---------- 상세 API가 매칭에 실패했을 때의 보완책: 공시 원문 직접 파싱 ----------
# "타법인주식및출자증권처분/취득결정" 같은 상세 API는 "금융위 주요사항보고서"로 접수된
# 건만 커버한다. 같은 제목이라도 "거래소(코스닥/유가증권시장본부) 소관"으로 접수되면
# 그 API엔 애초에 데이터가 없다 (회사 양식 차이가 아니라 접수 경로 차이).
# document.xml API는 접수번호만 있으면 접수 경로와 상관없이 공시 원문을 그대로
# 돌려주므로, 이걸로 표준 서식 표를 직접 파싱해서 보완한다.

_RAW_ERR = [""]


def fetch_raw_document(rcept_no):
    """공시서류 원문(zip, 내부는 utf-8 html)을 받아 합쳐진 텍스트로 반환한다."""
    try:
        r = requests.get(BASE + "document.xml", params={"crtfc_key": API_KEY, "rcept_no": rcept_no}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        _RAW_ERR[0] = "request:" + type(e).__name__
        return None
    if not r.content.startswith(b"PK"):  # zip이 아니면(오류 JSON 등) 포기
        _RAW_ERR[0] = "notzip:" + r.content[:160].decode("utf-8", errors="ignore").replace("\n", " ")
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
    text = _html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# 회사명: '주식회사 OOO', 'OOO 주식회사', '(주)OOO', 'OOO(주)' 형태를 모두 한 덩어리로 잡는다.
_TOK = r"[가-힣A-Za-z0-9&·.\-]+"
_CORP = r"(?:(?:주식회사|\(주\)|㈜)\s*)?" + _TOK + r"(?:\s*(?:주식회사|\(주\)|㈜))?"
_GENERIC = {"주식회사", "(주)", "㈜", "제3자", "-", ""}


def _clean_name(name):
    name = name.strip()
    # 끝에 붙은 영문/약칭 병기 '(IDIENCE CO., LTD.)', '(GSHM)' 제거. '(주)'는 유지.
    name = re.sub(r"\s*\((?=[^)]*[A-Za-z])[^)가-힣]*\)\s*$", "", name)
    return name.strip()


def _valid_name(name):
    if not name:
        return False
    core = re.sub(r"주식회사|\(주\)|㈜|\s", "", name)
    return len(core) >= 2 and name not in _GENERIC


def extract_from_raw_doc(raw_html, corp_name, direction_hint):
    """'타법인 주식 및 출자증권 취득/처분결정' 표준 서식 원문에서 핵심 정보를 뽑아낸다.
    (규제상 정해진 서식이라 금융위/거래소 소관과 무관하게 표 구조는 동일하다.)"""
    text = strip_tags(raw_html)

    target = None
    cands = []
    m = re.search(r"회사명\s+(.{2,100}?)\s+국적\s", text)           # 거래소 접수 서식
    if m:
        cands.append(m.group(1))
    m = re.search(r"회사명\s*\(국적\)\s*(.{2,100}?)\s*[\(（]\s*(?:대한민국|[가-힣]{2,6})\s*[\)）]", text)  # 금융위 서식
    if m:
        cands.append(m.group(1))
    m = re.search(r"회사명\s*\(국적\)\s*(" + _CORP + ")", text)   # 마지막 보루(기존 방식)
    if m:
        cands.append(m.group(1))
    for c in cands:
        c = _clean_name(c)
        if _valid_name(c):
            target = c
            break

    counterparty = None
    for pat in [r"거래상대방\s*[:：]\s*(" + _CORP + ")",
                r"거래상대방\s+(" + _CORP + ")"]:
        m = re.search(pat, text)
        if m and _valid_name(m.group(1).strip()):
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

    # 취득/처분 후 지분율 (표준 서식: '취득후 소유주식수 및 지분비율 ... 지분비율(%) 35.2')
    note = None
    m = re.search(r"(?:취득|처분)\s*후\s*소유주식수\s*및\s*지분비율.{0,80}?지분비율\s*\(%\)\s*([\d.,]+)", text)
    if m:
        note = f"{'처분' if direction_hint == '양도' else '인수'} 후 지분율 {m.group(1)}%"

    if direction_hint == "양도":
        buyer, seller, kind = counterparty, corp_name, "stake_out"
    else:
        buyer, seller, kind = corp_name, counterparty, "stake_in"

    return {
        "kind": kind, "direction": direction_hint, "buyer": buyer, "seller": seller,
        "target": target, "amount": amount, "note": note,
    }


# 합병등종료보고서(합병): DART에 구조화 API가 없고, 서식에 '상대회사' 표 대신 문장으로
# "존속회사인 A는 소멸회사인 B의 발행주식 100%를 보유하고 있으며 ..." 식으로 적혀 있다.
_CORP_NG = r"(?:(?:주식회사|\(주\)|㈜)\s*)?[가-힣A-Za-z0-9&·.\-]+?(?:\s*(?:주식회사|\(주\)|㈜))?"
_TAIL_PARTICLE = re.compile(r"(?<=[가-힣A-Za-z0-9)])(?:의|은|는|이|가|을|를|와|과)$")


def extract_merger_done(raw_html):
    """합병등종료보고서(합병) 원문에서 소멸회사와 합병기일을 뽑는다. 제출회사가 존속회사다."""
    text = strip_tags(raw_html)
    if "합병" not in text:
        return None

    target = None
    m = re.search(r"소멸회사\s*(?:인|은|는|:)?\s*(" + _CORP + ")", text)
    if m:
        cand = _clean_name(_TAIL_PARTICLE.sub("", m.group(1).strip()))
        if _valid_name(cand):
            target = cand
    if not target:
        m = re.search("(" + _CORP_NG + r")\s*의\s*(?:발행\s*주식|지분)\s*[을를]?\s*(?:총\s*)?(?:100\s*%|전부)", text)
        if m and _valid_name(m.group(1).strip()):
            target = _clean_name(m.group(1).strip())

    note = None
    m = re.search(r"합병\s*기일\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        note = f"합병기일 {m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"

    if not target and not note:
        return None
    return {
        "kind": "merger_done", "direction": None,
        "buyer": None, "seller": target, "target": target, "amount": None, "note": note,
    }


def try_raw_document(deal, endpoint, stats):
    """공시 원문을 받아 파싱해서 deal을 채운다. 성공하면 True."""
    direction_hint = "양수" if endpoint == "otcprStkInvscrInhDecsn" else "양도"
    raw = fetch_raw_document(deal["rcept_no"])
    if not raw:
        print(f"  원문 자체를 못 받음: {deal['corp_name']} {deal['rcept_no']} ({_RAW_ERR[0]})")
        deal["raw_probe"] = {"fetch_failed": _RAW_ERR[0]}
        return False
    parsed = extract_from_raw_doc(raw, deal["corp_name"], direction_hint)
    if not parsed:
        print(f"  원문은 받았으나 파싱 실패: {deal['corp_name']} {deal['rcept_no']} (len={len(raw)})")
        # 임시 진단: 왜 실패했는지 확인할 수 있게 핵심 라벨 주변 원문 일부를 남긴다.
        txt = strip_tags(raw)
        i = txt.find("회사명")
        j = txt.find("금액")
        deal["raw_probe"] = {"len": len(txt), "head": txt[:200],
                             "near_corp": txt[max(i, 0):max(i, 0) + 250] if i >= 0 else None,
                             "near_amt": txt[max(j - 60, 0):j + 200] if j >= 0 else None}
        return False
    deal.update(parsed)
    deal["source"] = "raw_document"
    deal["raw_v"] = 3
    deal.pop("raw_probe", None)
    finalize_summary(deal)
    stats["matched_raw"] += 1
    print(f"  원문 파싱으로 보완 성공: {deal['corp_name']} {deal['rcept_no']}")
    return True


def try_merger_done(deal, stats):
    """합병등종료보고서(합병) 원문을 파싱해 'A가 B를 흡수합병했습니다'를 만든다. 성공하면 True."""
    raw = fetch_raw_document(deal["rcept_no"])
    if not raw:
        print(f"  원문 자체를 못 받음: {deal['corp_name']} {deal['rcept_no']} ({_RAW_ERR[0]})")
        return False
    parsed = extract_merger_done(raw)
    if not parsed:
        print(f"  합병종료 원문 파싱 실패: {deal['corp_name']} {deal['rcept_no']} (len={len(raw)})")
        return False
    deal.update(parsed)
    deal["source"] = "raw_document"
    deal["raw_v"] = 3
    finalize_summary(deal)
    stats["matched_raw"] += 1
    print(f"  합병종료 원문 파싱 성공: {deal['corp_name']} {deal['rcept_no']}")
    return True


MAX_ATTEMPTS = 5  # 이 횟수만큼 재시도해도 안 되면 포기하고 더 이상 조회하지 않는다

# 이 문구가 제목에 있으면 거래소 수시공시(자회사 공시)로 접수된 건이라 상세 API에 데이터가 없다.
# ('정정' 공시는 여기 넣지 않는다: 정정본도 상세 API에 같은 접수번호로 잡히는 경우가 많다.)
NO_API_HINTS = ["자회사의 주요경영사항", "종속회사의주요경영사항", "종속회사의 주요경영사항"]


def _flat(deal):
    return deal["report_nm"].replace(" ", "")


def is_subsidiary_notice(deal):
    t = _flat(deal)
    return any(h.replace(" ", "") in t for h in NO_API_HINTS)


def is_merger_done(deal):
    return deal["category"] == "합병" and "합병등종료보고서(합병)" in _flat(deal)


def enrich(deal, cache, stats, diag_budget):
    """상세 정보를 채운다. 다시 시도할 필요가 없으면 True."""
    if is_merger_done(deal):
        if try_merger_done(deal, stats):
            return True
        deal["detail_attempts"] = deal.get("detail_attempts", 0) + 1
        if deal["detail_attempts"] >= MAX_ATTEMPTS:
            deal["no_detail_api"] = True  # 마지막에 제목 기반 요약으로 채운다
            return True
        return False
    endpoint = route(deal)
    if not endpoint:
        stats["no_api"] += 1  # 이 딜 유형은 DART에 상세 API 자체가 없음 (마지막에 제목 기반 요약으로 채운다)
        deal["no_detail_api"] = True
        return True
    if is_subsidiary_notice(deal):
        # 상세 API엔 없는 유형이지만, 타법인 주식 건은 공시 원문(표준 서식)을 직접 파싱해 요약을 만든다.
        if endpoint in ("otcprStkInvscrInhDecsn", "otcprStkInvscrTrfDecsn"):
            if try_raw_document(deal, endpoint, stats):
                return True
        stats["skip_correction"] += 1
        deal["no_detail_api"] = True
        return True
    correction = "정정" in _flat(deal)
    # 상세 API가 실제로 그 딜을 잡아두는 날짜가 목록 API의 접수일자(rcept_dt)와
    # 하루이틀 어긋나는 경우가 있어, 정확히 하루만 조회하지 않고 앞뒤로 여유를 두고 조회한다.
    # 정정 공시는 원 공시가 며칠 앞서 있으므로 조회 기간을 더 앞으로 넓힌다.
    base_day = dt.datetime.strptime(deal["date"], "%Y%m%d")
    win_bgn = (base_day - dt.timedelta(days=30 if correction else 3)).strftime("%Y%m%d")
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
    if row is None and len(rows) == 1 and not correction:
        row = rows[0]
    if row is None and correction:
        # 정정 공시의 접수번호는 상세 API에 없고 원 공시 접수번호로만 잡히므로,
        # 같은 회사의 직전(원) 공시 행을 가져온다.
        earlier = [x for x in rows if x.get("rcept_no") and x["rcept_no"] < deal["rcept_no"]]
        if earlier:
            row = max(earlier, key=lambda x: x["rcept_no"])
    if row:
        deal.update(extract(endpoint, row, deal["corp_name"]))
        finalize_summary(deal)
        stats["matched"] += 1
        return True

    stats["no_match"] += 1
    print(f"  매칭 실패 [{endpoint}] {deal['corp_name']} {deal['date']} "
          f"rcept_no={deal['rcept_no']}: 상세API가 {win_bgn}~{win_end} 기간에 반환한 건수={len(rows)}")

    # 보완책: 상세 API가 매칭 못한 건(주로 거래소 소관으로 접수돼 금융위 API에
    # 데이터가 없는 경우)은 공시 원문을 직접 받아 표준 서식을 파싱해본다.
    if endpoint in ("otcprStkInvscrInhDecsn", "otcprStkInvscrTrfDecsn"):
        if try_raw_document(deal, endpoint, stats):
            return True

    if correction:
        # 정정 공시는 재시도해도 소용없다. 마지막 단계에서 같은 회사의 원 공시 요약을 가져오거나 제목 기반 요약을 쓴다.
        deal["no_detail_api"] = True
        return True

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


# ---------- 마지막 단계: 상세 정보를 못 얻은 건의 요약 채우기 ----------

_SIBLING_FIELDS = ("kind", "summary", "target", "buyer", "seller", "amount", "direction", "note")


def find_sibling(deal, all_deals):
    """정정 공시처럼 내용이 같은 원 공시(같은 회사·같은 분류·같은 유형, 60일 이내)의 요약을 찾는다."""
    if route(deal) is None:
        return None  # 상세 API가 없는 유형은 같은 회사라도 다른 건일 수 있어 가져오지 않는다
    base = dt.datetime.strptime(deal["date"], "%Y%m%d")
    best = None
    for o in all_deals:
        if (o is deal or o.get("corp_code") != deal["corp_code"] or o["category"] != deal["category"]
                or not o.get("summary") or o.get("summary_src")):
            continue
        if route(o) != route(deal) or is_subsidiary_notice(o) != is_subsidiary_notice(deal):
            continue
        gap = abs((dt.datetime.strptime(o["date"], "%Y%m%d") - base).days)
        if gap <= 60 and (best is None or gap < best[0]):
            best = (gap, o)
    return best[1] if best else None


# (분류, 제목에 있는 문구) → 제목만으로 말할 수 있는 사실. 위에서부터 먼저 맞는 것을 쓴다.
_TITLE_FACTS = [
    ("최대주주 변경", "주식담보제공계약해제", "최대주주 변경을 수반하는 주식담보제공 계약이 해제·취소됐습니다"),
    ("최대주주 변경", "주식담보제공", "최대주주 변경을 수반하는 주식담보제공 계약을 체결했습니다"),
    ("최대주주 변경", "주식양수도계약", "최대주주 변경을 수반하는 주식양수도 계약을 체결했습니다"),
    ("최대주주 변경", "소유주식변동신고서", "최대주주 등의 소유주식 변동을 신고했습니다"),
    ("최대주주 변경", "", "최대주주가 변경됐습니다"),
    ("합병", "합병등종료보고서(자산양수도)", "자산양수도를 완료했습니다"),
    ("합병", "합병등종료보고서(영업양수도)", "영업양수도를 완료했습니다"),
    ("합병", "합병등종료보고서", "합병을 완료했습니다"),
    ("합병", "회사합병결정", "합병을 결정했습니다"),
    ("합병", "증권신고서(합병)", "합병 증권신고서를 제출했습니다"),
    ("합병", "", "합병 관련 공시를 냈습니다"),
    ("분할", "", "회사분할을 결정했습니다"),
    ("주식교환·이전", "", "주식교환·이전을 결정했습니다"),
    ("공개매수", "결과보고서", "공개매수 결과를 보고했습니다"),
    ("공개매수", "신고서", "공개매수를 신고했습니다"),
    ("공개매수", "", "공개매수를 진행합니다"),
    ("유상증자", "", "유상증자를 결정했습니다"),
    ("영업양수도", "양수", "영업 양수를 결정했습니다"),
    ("영업양수도", "", "영업 양도를 결정했습니다"),
    ("타법인 주식 취득·처분", "양수", "타법인 주식 취득을 결정했습니다"),
    ("타법인 주식 취득·처분", "취득", "타법인 주식 취득을 결정했습니다"),
    ("타법인 주식 취득·처분", "", "타법인 주식 처분을 결정했습니다"),
]


def title_summary(deal):
    """상세 정보를 끝내 못 얻은 건에 쓰는, 제목에서 알 수 있는 사실만 담은 요약."""
    a = short_name(deal["corp_name"])
    t = _flat(deal)
    fact = None
    for cat, kw, text in _TITLE_FACTS:
        if deal["category"] == cat and kw in t:
            fact = text
            break
    if not fact:
        return None
    if is_subsidiary_notice(deal) and not fact.startswith("최대주주"):
        return f"{a}의 종속회사가 {fact}."
    if fact.startswith("최대주주가"):
        return f"{a}의 {fact}."
    return f"{a}{i_ga(a)} {fact}."


def fill_fallback_summaries(all_deals):
    """상세 요약이 없는 건을 채운다. 1) 예전 형식 요약을 새 형식으로 다시 만들고
    2) 정정 공시는 같은 회사의 원 공시 요약을 가져오고 3) 그래도 없으면 제목 기반 요약을 쓴다."""
    for d in all_deals:
        if d.get("summary") and not d.get("summary_src") and d.get("sum_v") != 2 and infer_kind(d):
            finalize_summary(d)  # 저장된 필드(대상·금액·지분율)로 새 형식 요약을 다시 만든다
    for d in all_deals:
        if d.get("summary") or not d.get("no_detail_api") or not d.get("corp_code"):
            continue
        sib = find_sibling(d, all_deals)
        if sib:
            for k in _SIBLING_FIELDS:
                d[k] = sib.get(k)
            d["summary_src"] = "original"
            continue
        s = title_summary(d)
        if s:
            d["summary"] = s
            d["summary_src"] = "title"


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
        # 제목 기반 임시 요약은 정정 공시 매칭 개선 후 한 번 다시 연다.
        if d.get("summary_src") == "title" and d.get("fix_v") != 5:
            for k in ("summary", "summary_src", "sum_v", "kind", "no_detail_api"):
                d.pop(k, None)
            d["fix_v"] = 5
            d["detail_attempts"] = 0
        has_detail = bool(d.get("summary"))
        if d.get("source") == "raw_document" and d.get("raw_v") != 3:
            ep = route(d)
            if ep and try_raw_document(d, ep, stats):
                d["detail_done"] = True
            else:
                for k in ("summary", "target", "buyer", "seller", "amount", "direction", "note", "source"):
                    d.pop(k, None)
                d["raw_retried"] = 3
            continue
        # 원문 파싱 보완책이 생기기 전에 '상세 API 없음/포기'로 닫힌 타법인 주식 건은 한 번 다시 연다.
        if (not has_detail and d.get("no_detail_api") and d["category"] == "타법인 주식 취득·처분"
                and d.get("source") != "raw_document" and d.get("raw_retried") != 3):
            d["raw_retried"] = 3
            d.pop("no_detail_api", None)
            d["detail_attempts"] = 0
        # 합병종료·정정 공시 처리를 추가하기 전에 닫힌 요약 없는 건도 한 번 다시 연다.
        if not has_detail and d.get("no_detail_api") and d.get("fix_v") not in (4, 5):
            d["fix_v"] = 4
            d.pop("no_detail_api", None)
            d["detail_attempts"] = 0
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

    fill_fallback_summaries(list(existing.values()))

    deals = sorted(existing.values(), key=lambda d: (d["date"], d["rcept_no"]), reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    print(f"신규 {added}건 추가, 상세 처리 {filled}건, 전체 {len(deals)}건")
    print(f"상세 내역 - 채워짐:{stats['matched']} 원문보완:{stats['matched_raw']} 매칭실패:{stats['no_match']} "
          f"API없는유형:{stats['no_api']} API오류:{stats['api_error']} "
          f"정정/자회사공시건너뜀:{stats['skip_correction']} 포기(재시도한도):{stats['gave_up']}")


if __name__ == "__main__":
    main()
