/* 個人化はlocalStorageのみ（R8・規約12条対応）。サーバーへ個人データは送らない。 */
(function () {
  "use strict";
  var KEY = "oshi_list_v1";

  function loadList() {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); }
    catch (e) { return []; }
  }
  function saveList(list) { localStorage.setItem(KEY, JSON.stringify(list)); }

  /* --- トップ: 検索とプログレス表示（§8.4） --- */
  var form = document.getElementById("search-form");
  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var name = document.getElementById("search-input").value.trim();
      if (!name) return;
      var progress = document.getElementById("search-progress");
      var bar = document.getElementById("search-bar");
      var msg = document.getElementById("search-message");
      var err = document.getElementById("search-error");
      err.hidden = true;
      progress.hidden = false;
      var stages = ["書籍を検索中", "CDを検索中", "DVD/Blu-rayを検索中", "雑誌を検索中",
                    "ゲームを検索中", "電子書籍を検索中", "グッズを検索中", "結果をまとめています"];
      var sim = 0;
      bar.max = 8; bar.value = 0; msg.textContent = stages[0];
      var simTimer = setInterval(function () {
        if (sim < stages.length - 1) { sim++; bar.value = sim; msg.textContent = stages[sim]; }
      }, 1300);
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
        if (data.status === "cached" || data.status === "done") { location.href = "/oshi/" + data.oshi_id; return; }
        progress.hidden = false;
        var timer = setInterval(function () {
          fetch("/api/search/" + data.job_id).then(function (r) { return r.json(); })
            .then(function (st) {
              bar.max = st.total; bar.value = st.step; msg.textContent = st.message;
              if (st.status === "done") { clearInterval(timer); location.href = "/oshi/" + st.oshi_id; }
              if (st.status === "error") { clearInterval(timer); progress.hidden = true; err.textContent = "一時的に取得できません。時間をおいてお試しください。"; err.hidden = false; }
            });
        }, 1200);
      }).catch(function (e) { clearInterval(simTimer); progress.hidden = true; err.textContent = e.message; err.hidden = false; });
    });
  }

  /* --- 推しページ: お気に入り登録・媒体タブ --- */
  var fav = document.getElementById("fav-btn");
  if (fav) {
    var id = parseInt(fav.dataset.oshiId, 10);
    var name = fav.dataset.oshiName;
    var render = function () {
      var on = loadList().some(function (o) { return o.id === id; });
      fav.textContent = on ? "★ マイ推しリストに追加済み（タップで解除）" : "☆ マイ推しリストに追加";
    };
    fav.addEventListener("click", function () {
      var list = loadList();
      var idx = list.findIndex(function (o) { return o.id === id; });
      if (idx >= 0) list.splice(idx, 1); else list.push({ id: id, name: name });
      saveList(list); render();
    });
    render();
  }
  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var tab = btn.dataset.tab;
      document.querySelectorAll("#tab-grid .card").forEach(function (card) {
        card.style.display = (tab === "all" || card.dataset.media === tab) ? "" : "none";
      });
    });
  });

  /* --- マイページ: localStorageから各推しのサマリを描画 --- */
  var myList = document.getElementById("my-list");
  if (myList) {
    var list = loadList();
    if (list.length) {
      myList.innerHTML = "";
      list.forEach(function (o) {
        var sec = document.createElement("section");
        sec.innerHTML = '<h2><a href="/oshi/' + o.id + '"></a></h2><div class="summary">読み込み中…</div>';
        sec.querySelector("a").textContent = o.name;
        myList.appendChild(sec);
        fetch("/api/oshi/" + o.id + "/summary").then(function (r) {
          if (!r.ok) throw new Error();
          return r.json();
        }).then(function (data) {
          var box = sec.querySelector(".summary");
          box.innerHTML = "";
          var mk = function (title, items) {
            if (!items.length) return;
            var h = document.createElement("h3"); h.textContent = title; box.appendChild(h);
            var ul = document.createElement("ul");
            items.forEach(function (c) {
              var li = document.createElement("li");
              var a = document.createElement("a");
              a.href = c.url; a.rel = "nofollow sponsored"; a.target = "_blank";
              a.textContent = c.title;
              li.appendChild(a);
              li.appendChild(document.createTextNode(
                (c.sales_date ? "（" + c.sales_date + "）" : "") + " [" + c.fetched_at + "] 時点"));
              ul.appendChild(li);
            });
            box.appendChild(ul);
          };
          mk("今後の発売予定", data.upcoming);
          mk("新着", data.new_items);
          if (!data.upcoming.length && !data.new_items.length)
            box.textContent = "直近の供給情報はありません。";
        }).catch(function () {
          sec.querySelector(".summary").textContent = "情報を取得できませんでした。";
        });
      });
    }
  }
})();
