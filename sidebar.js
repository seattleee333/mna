function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// 왼쪽 사이드바: 메뉴(내비게이션)만 표시한다.
function renderSidebar(active) {
  const el = document.getElementById("sidebar");
  if (!el) return;
  el.innerHTML =
    '<div class="side-head"><a href="index.html">M&amp;A 데일리</a></div>' +
    '<nav class="side-nav">' +
      '<a href="index.html" class="' + (active === "daily" ? "on" : "") + '">딜클로징 리스트</a>' +
      '<a href="listings.html" class="' + (active === "listings" ? "on" : "") + '">매물·인수희망 리스트</a>' +
    '</nav>';
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
      list.innerHTML = data.slice(0, 12).map(n => {
        const sources = n.sources && n.sources.length ? escHtml(n.sources.slice(0, 3).join(", ")) : "";
        const countBadge = n.outlet_count > 1 ? '<span class="nc-count">' + n.outlet_count + '곳</span>' : "";
        return '<a class="news-card" target="_blank" rel="noopener" href="' + escHtml(n.link) + '">' +
          '<span class="nc-title">' + escHtml(n.title) + '</span>' +
          '<span class="nc-meta">' + countBadge + sources + '</span>' +
          '</a>';
      }).join("");
    })
    .catch(() => {
      const list = document.getElementById("newsCardList");
      if (list) list.innerHTML = '<div class="side-empty">뉴스를 불러올 수 없습니다.</div>';
    });
}
