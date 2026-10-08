function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// 상단 내비게이션 메뉴
function renderSidebar(active) {
  const el = document.getElementById("topNav");
  if (!el) return;
  el.innerHTML =
    '<a href="deals.html" class="' + (active === "daily" ? "on" : "") + '">딜클로징 리스트</a>' +
    '<a href="listings.html" class="' + (active === "listings" ? "on" : "") + '">매물·인수희망 리스트</a>' +
    '<a href="sell.html" class="' + (active === "sell" ? "on" : "") + '">매각하기</a>';
}

// 오른쪽 패널: M&A 인기뉴스를 카드 형태로 표시한다 (메뉴와 분리된 영역).
function renderNewsPanel() {
  const el = document.getElementById("newsPanel");
  if (!el) return;
  el.innerHTML =
    '<div class="news-panel-title">M&amp;A 인기뉴스</div>' +
    '<div id="newsCardList" class="news-card-list">불러오는 중...</div>';

  fetch("news.json?t=" + Date.now())
    .then(r => (r.ok ? r.json() : []))
    .then(data => {
      const list = document.getElementById("newsCardList");
      if (!list) return;
      if (!data || !data.length) {
        list.innerHTML = '<div class="side-empty">아직 수집된 뉴스가 없습니다.</div>';
        return;
      }
      list.innerHTML = data.slice(0, 10).map((n, i) => {
        const source = n.sources && n.sources.length ? escHtml(n.sources[0]) : "";
        const countBadge = n.outlet_count > 1 ? '<span class="nc-count">+' + (n.outlet_count - 1) + '</span>' : "";
        return '<a class="news-card" target="_blank" rel="noopener" href="' + escHtml(n.link) + '">' +
          '<span class="nc-rank">' + (i + 1) + '</span>' +
          '<span class="nc-body">' +
            '<span class="nc-title">' + escHtml(n.title) + '</span>' +
            '<span class="nc-meta">' + source + countBadge + '</span>' +
          '</span>' +
          '</a>';
      }).join("");
    })
    .catch(() => {
      const list = document.getElementById("newsCardList");
      if (list) list.innerHTML = '<div class="side-empty">뉴스를 불러올 수 없습니다.</div>';
    });
}
