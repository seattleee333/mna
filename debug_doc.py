"""공시 원문(document.xml) 접근 점검용 — 종류별로 몇 건만 받아서 구조를 ma_debug.txt에 남긴다."""
import os, io, json, zipfile, re, html
import requests
KEY = os.environ.get("DART_API_KEY", "")
c = json.load(open("ma_cache.json", encoding="utf-8"))
fl = sorted(c["filings"].values(), key=lambda f: f["date"], reverse=True)
out = []
for kind in ("disp", "biz_out", "acq"):
    for f in [x for x in fl if x["kind"] == kind][:2]:
        r = requests.get("https://opendart.fss.or.kr/api/document.xml", params={"crtfc_key": KEY, "rcept_no": f["rcept_no"]}, timeout=40)
        out.append(f"## {kind} {f['corp_name']} {f['rcept_no']} {f['report_nm']} → HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)}B")
        out.append("head: " + repr(r.content[:200]))
        try:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            out.append("zip: " + str(z.namelist()))
            data = z.read(z.namelist()[0])
            for enc in ("utf-8", "euc-kr"):
                try:
                    t = data.decode(enc); out.append("enc " + enc); break
                except UnicodeDecodeError:
                    continue
            t = html.unescape(re.sub(r"<[^>]+>", "\n", t)).replace("\xa0", " ")
            toks = [x.strip() for x in t.split("\n") if x.strip()]
            out.append(f"tokens {len(toks)}: " + " | ".join(toks[:200]))
        except Exception as e:
            out.append("zip 실패: " + repr(e))
open("ma_debug.txt", "w", encoding="utf-8").write("\n".join(out))
