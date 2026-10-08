// 로그인 상태 관리 (브라우저 localStorage). 회원 정보 검증·저장은 Apps Script(구글시트)가 담당한다.
(function () {
  const C = window.MNA_CONFIG || {};
  const KEY = "mnaUserV1";
  const A = {
    providers() {
      return {
        google: !!C.googleClientId, kakao: !!C.kakaoRestKey, naver: !!C.naverClientId
      };
    },
    enabled() {
      const p = A.providers();
      return !!C.appsScriptUrl && (p.google || p.kakao || p.naver);
    },
    user() {
      try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; }
    },
    save(u) { try { localStorage.setItem(KEY, JSON.stringify(u)); } catch (e) {} },
    logout() { try { localStorage.removeItem(KEY); } catch (e) {} },
    // 로그인이 필요한 페이지 맨 위에서 호출. 로그인 설정이 아직 없으면 막지 않는다.
    require() {
      if (!A.enabled() || A.user()) return true;
      const next = location.pathname.split("/").pop() + location.search;
      location.replace("login.html?next=" + encodeURIComponent(next));
      return false;
    }
  };
  window.MNA_AUTH = A;
})();
