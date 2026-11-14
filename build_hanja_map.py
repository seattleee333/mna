"""한자 → 한글 독음 표(hanja_map.json) 만들기. 중국 간체·일본 신자체는 번체로 바꾼 뒤 독음을 찾는다.
일본·중국 공시 제목·회사명을 한국어로 보여줄 때 쓴다 (한 번만 돌리면 됨)."""
import json
import hanja
import opencc

cvs = [opencc.OpenCC(c) for c in ("s2t", "jp2t")]
out = {}
for cp in list(range(0x4E00, 0xA000)) + list(range(0x3400, 0x4DC0)):
    ch = chr(cp)
    for cand in [ch] + [c.convert(ch) for c in cvs]:
        try:
            r = hanja.translate(cand, "substitution")
        except Exception:
            continue
        if r and len(r) == 1 and "가" <= r <= "힣":
            out[ch] = r
            break
json.dump(out, open("hanja_map.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("독음", len(out), "자", {k: out.get(k) for k in "中国神华积水塗図売広沢鉄気発"})
