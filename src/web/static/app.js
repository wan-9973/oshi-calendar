/* 個人化はlocalStorageのみ（R8・規約12条対応）。サーバーへ個人データは送らない。 */
(function () {
  "use strict";
  var KEY = "oshi_list_v1";
  var toastTimer;

  function loadList() {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); }
    catch (e) { return []; }
  }

  function saveList(list) {
    localStorage.setItem(KEY, JSON.stringify(list));
  }

  function showToast(message) {
    var toast = document.getElementById("toast");
    if (!toast) return;
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(function () { toast.hidden = true; }, 2800);
  }

  function showPageSkeleton() {
    var skeleton = document.getElementById("page-skeleton");
    if (!skeleton) return;
    skeleton.hidden = false;
    document.body.classList.add("skeleton-visible");
  }

  function hidePageSkeleton() {
    var skeleton = document.getElementById("page-skeleton");
    if (skeleton) skeleton.hidden = true;
    document.body.classList.remove("skeleton-visible");
  }

  /* --- トップ: 検索とプログレス表示（§8.4） --- */
  var form = document.getElementById("search-form");
  if (form) {
    var input = document.getElementById("search-input");
    var query = new URLSearchParams(location.search).get("q");
    if (query && input && !input.value) input.value = query;

    var setSearchLoading = function (loading) {
      var submit = document.getElementById("search-submit");
      if (!submit) return;
      submit.disabled = loading;
      form.setAttribute("aria-busy", loading ? "true" : "false");
      submit.querySelector(".button-label").hidden = loading;
      submit.querySelector(".button-spinner").hidden = !loading;
    };

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var name = input.value.trim();
      if (!name) return;
      var progress = document.getElementById("search-progress");
      var bar = document.getElementById("search-bar");
      var msg = document.getElementById("search-message");
      var err = document.getElementById("search-error");
      err.hidden = true;
      progress.hidden = false;
      setSearchLoading(true);
      var stages = ["書籍を検索中", "CDを検索中", "DVD/Blu-rayを検索中", "雑誌を検索中",
                    "ゲームを検索中", "電子書籍を検索中", "グッズを検索中", "結果をまとめています"];
      var sim = 0;
      bar.max = 8;
      bar.value = 0;
      msg.textContent = stages[0];
      var simTimer = setInterval(function () {
        if (sim < stages.length - 1) {
          sim++;
          bar.value = sim;
          msg.textContent = stages[sim];
        }
      }, 1300);

      var failSearch = function (message) {
        clearInterval(simTimer);
        progress.hidden = true;
        err.textContent = message;
        err.hidden = false;
        setSearchLoading(false);
      };

      fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name })
      }).then(function (r) {
        if (r.status === 429) throw new Error("検索が混み合っています。1分ほど待ってからお試しください。");
        if (!r.ok) throw new Error("検索を開始できませんでした。");
        return r.json();
      }).then(function (data) {
        clearInterval(simTimer);
        if (data.status === "cached" || data.status === "done") {
          showPageSkeleton();
          location.href = "/oshi/" + data.oshi_id;
          return;
        }
        var timer = setInterval(function () {
          fetch("/api/search/" + data.job_id).then(function (r) {
            if (!r.ok) throw new Error();
            return r.json();
          }).then(function (st) {
            bar.max = st.total;
            bar.value = st.step;
            msg.textContent = st.message;
            if (st.status === "done") {
              clearInterval(timer);
              showPageSkeleton();
              location.href = "/oshi/" + st.oshi_id;
            }
            if (st.status === "error") {
              clearInterval(timer);
              failSearch("一時的に取得できません。時間をおいてお試しください。");
            }
          }).catch(function () {
            clearInterval(timer);
            failSearch("検索状況を取得できませんでした。もう一度お試しください。");
          });
        }, 1200);
      }).catch(function (e) {
        failSearch(e.message);
      });
    });
  }

  /* --- 推しページ: お気に入り登録・媒体フィルタ --- */
  var fav = document.getElementById("fav-btn");
  if (fav) {
    var id = parseInt(fav.dataset.oshiId, 10);
    var name = fav.dataset.oshiName;
    var renderFavorite = function () {
      var on = loadList().some(function (o) { return o.id === id; });
      fav.textContent = on ? "♥ 追加済み" : "☆ マイ推しリストに追加";
      fav.setAttribute("aria-pressed", on ? "true" : "false");
      fav.classList.toggle("is-active", on);
      fav.title = on ? "タップするとマイ推しリストから解除します" : "マイ推しリストに追加します";
    };
    fav.addEventListener("click", function () {
      var list = loadList();
      var index = list.findIndex(function (o) { return o.id === id; });
      if (index >= 0) {
        list.splice(index, 1);
        showToast("マイ推しリストから解除しました");
      } else {
        list.push({ id: id, name: name });
        showToast("マイ推しリストに追加しました");
      }
      saveList(list);
      renderFavorite();
    });
    renderFavorite();
  }

  var timeline = document.getElementById("calendar-timeline");
  document.querySelectorAll(".tab").forEach(function (button) {
    button.addEventListener("click", function () {
      if (button.disabled) return;
      document.querySelectorAll(".tab").forEach(function (other) {
        var active = other === button;
        other.classList.toggle("active", active);
        other.setAttribute("aria-pressed", active ? "true" : "false");
      });
      if (!timeline) return;
      var tab = button.dataset.tab;
      timeline.querySelectorAll(".card").forEach(function (card) {
        card.hidden = tab !== "all" && card.dataset.media !== tab;
      });
      timeline.querySelectorAll("[data-variation-group]").forEach(function (group) {
        group.hidden = !group.querySelector(".card:not([hidden])");
      });
      timeline.querySelectorAll("[data-date-group]").forEach(function (dateGroup) {
        dateGroup.hidden = !dateGroup.querySelector("[data-variation-group]:not([hidden])");
      });
    });
  });

  /* --- マイページ: localStorageから各推しのサマリを描画 --- */
  var myList = document.getElementById("my-list");
  if (myList) {
    var list = loadList();
    if (list.length) {
      myList.innerHTML = "";
      list.forEach(function (oshi) {
        var section = document.createElement("section");
        section.className = "my-oshi-card";
        section.innerHTML = '<h2><a href="/oshi/' + oshi.id + '"></a></h2>' +
          '<div class="summary" aria-busy="true"><div class="skeleton-line"></div><div class="skeleton-line short"></div></div>';
        section.querySelector("a").textContent = oshi.name;
        myList.appendChild(section);
        fetch("/api/oshi/" + oshi.id + "/summary").then(function (r) {
          if (!r.ok) throw new Error();
          return r.json();
        }).then(function (data) {
          var box = section.querySelector(".summary");
          box.innerHTML = "";
          box.setAttribute("aria-busy", "false");
          var makeList = function (title, items) {
            if (!items.length) return;
            var heading = document.createElement("h3");
            heading.textContent = title;
            box.appendChild(heading);
            var ul = document.createElement("ul");
            items.forEach(function (card) {
              var li = document.createElement("li");
              var link = document.createElement("a");
              link.href = card.url;
              link.rel = "nofollow sponsored";
              link.target = "_blank";
              link.textContent = card.title;
              li.appendChild(link);
              li.appendChild(document.createTextNode(
                (card.sales_date ? "（" + card.sales_date + "）" : "") +
                " [" + card.fetched_at + "] 時点の情報"));
              ul.appendChild(li);
            });
            box.appendChild(ul);
          };
          makeList("今後の発売予定", data.upcoming);
          makeList("新着", data.new_items);
          if (!data.upcoming.length && !data.new_items.length) {
            box.textContent = "直近の供給情報はありません。";
          }
        }).catch(function () {
          var box = section.querySelector(".summary");
          box.setAttribute("aria-busy", "false");
          box.textContent = "情報を取得できませんでした。";
        });
      });
    }
  }

  /* --- 共通: ページ遷移、トップへ戻る --- */
  document.addEventListener("click", function (event) {
    var link = event.target.closest("a");
    if (!link || link.target === "_blank" || event.defaultPrevented ||
        event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    try {
      var target = new URL(link.href, location.href);
      if (target.origin === location.origin && target.href !== location.href) showPageSkeleton();
    } catch (e) { /* 不正なURLはブラウザ標準処理に任せる */ }
  });
  window.addEventListener("pageshow", hidePageSkeleton);

  var backToTop = document.getElementById("back-to-top");
  if (backToTop) {
    var updateBackToTop = function () { backToTop.hidden = window.scrollY < 480; };
    window.addEventListener("scroll", updateBackToTop, { passive: true });
    backToTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    updateBackToTop();
  }
})();
