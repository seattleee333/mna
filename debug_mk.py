import re, requests
from bs4 import BeautifulSoup
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
r = requests.get("https://stock.mk.co.kr/news/print/1173089", headers=UA, timeout=30)
paras = re.split(r"(?:<br\s*/?>\s*){2,}", r.text)
out = [f"HTTP {r.status_code} len {len(r.text)} paras {len(paras)}"]
for p in paras:
    t = re.sub(r"\s+", " ", BeautifulSoup(p, "html.parser").get_text(" ", strip=True))
    if len(t) > 15:
        out.append("- " + t[:600])
open("mk_debug.txt", "w", encoding="utf-8").write("\n".join(out))
