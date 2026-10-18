"""임시 점검: 애드포러스(397810)의 2026년 공시 목록과 온더플래닛 인수 공시 원문 → adforus_check.txt"""
import io, re, json, zipfile
import fetch_profiles as fp

OUT = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); OUT.append(s)

def corp_codes():
    raw = fp.call("corpCode.xml", {}, raw=True)
    z = zipfile.ZipFile(io.BytesIO(raw)); x = z.read(z.namelist()[0]).decode("utf-8")
    rows = re.findall(r"<list>(.*?)</list>", x, re.S)
    out = []
    for r in rows:
        g = lambda t: (re.search(r"<%s>(.*?)</%s>" % (t, t), r, re.S) or [None, ""])[1].strip()
        out.append((g("corp_code"), g("corp_name"), g("stock_code")))
    return out

def flist(code, bgn, end):
    rows, pg = [], 1
    while True:
        j = fp.call("list.json", {"corp_code": code, "bgn_de": bgn, "end_de": end, "page_no": pg, "page_count": 100})
        if not j or j.get("status") != "000": break
        rows += j.get("list", [])
        if pg >= int(j.get("total_page", 1)): break
        pg += 1
    return rows

cc = corp_codes()
ad = [c for c in cc if c[2] == "397810"]
tg = [c for c in cc if "온더플래닛" in c[1]]
p("애드포러스:", ad); p("온더플래닛 후보:", tg)
code = ad[0][0]
rows = flist(code, "20260101", "20261018")
p("애드포러스 2026 공시", len(rows))
for r in rows: p(r["rcept_dt"], r["rcept_no"], r["report_nm"], "|", r.get("flr_nm"))
hits = [r for r in rows if re.search(r"타법인|주식.*취득|양수|합병|유상증자|출자", r["report_nm"])]
for r in hits:
    xml = fp.doc_xml(r["rcept_no"])
    p("\n===== 원문:", r["rcept_no"], r["report_nm"], "len", len(xml or ""))
    if xml:
        t = fp.to_text(xml)
        i = t.find("온더플래닛")
        p("온더플래닛 포함:", i >= 0)
        p(t[:9000])
# 상세 API
for y in ("2026",):
    j = fp.call("otcprStkInvscrInhDecsn.json", {"corp_code": code, "bgn_de": "20260101", "end_de": "20261018"})
    p("\n상세 API otcprStkInvscrInhDecsn:", json.dumps(j, ensure_ascii=False)[:4000])
# 대상회사 재무
for c in tg[:2]:
    p("\n대상회사", c)
    for r in flist(c[0], "20240101", "20261018")[:30]: p(r["rcept_dt"], r["report_nm"])
    for yr in ("2025", "2024"):
        j = fp.call("fnlttSinglAcnt.json", {"corp_code": c[0], "bsns_year": yr, "reprt_code": "11011"})
        p(yr, "재무:", json.dumps(j, ensure_ascii=False)[:1500])
open("adforus_check.txt", "w", encoding="utf-8").write("\n".join(OUT))
