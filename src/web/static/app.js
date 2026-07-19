/* 個人化はlocalStorageのみ（R8・規約12条対応）。サーバーへ個人データは送らない。 */
(function () {
  "use strict";
  var KEY = "oshi_list_v1";
  var toastTimer;

  function loadList() {
    try {
      var parsed = JSON.parse(localStorage.getItem(KEY) || "[]");
      if (!Array.isArray(parsed)) return [];
      var seen = {};
      return parsed.filter(function (item) {
        var id = Number(item && item.id);
        if (!Number.isInteger(id) || id <= 0 || seen[id]) return false;
        seen[id] = true;
        item.id = id;
        item.name = String(item.name || ("推し #" + id)).slice(0, 100);
        return true;
      }).slice(0, 50);
    }
    catch (e) { return []; }
  }

  function saveList(list) {
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, 50)));
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

  function appendTextElement(parent, tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  function parseIsoDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return null;
    var date = new Date(value + "T00:00:00");
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatJapaneseDate(value) {
    var date = parseIsoDate(value);
    if (!date) return "日付未定";
    return date.getFullYear() + "年" + (date.getMonth() + 1) + "月" + date.getDate() + "日";
  }

  function daysUntil(value) {
    var target = parseIsoDate(value);
    if (!target) return null;
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((target.getTime() - today.getTime()) / 86400000);
  }

  function escapeIcs(value) {
    return String(value || "").replace(/\\/g, "\\\\").replace(/\n/g, "\\n")
      .replace(/,/g, "\\,").replace(/;/g, "\\;");
  }

  function addOneDay(value) {
    var date = parseIsoDate(value);
    if (!date) return "";
    date.setDate(date.getDate() + 1);
    return date.getFullYear().toString().padStart(4, "0") +
      (date.getMonth() + 1).toString().padStart(2, "0") +
      date.getDate().toString().padStart(2, "0");
  }

  function downloadIcs(card, oshiName) {
    var release = (card.sales_date_iso || "").replace(/-/g, "");
    if (!/^\d{8}$/.test(release)) return;
    var stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    var uid = "oshi-" + (card.oshi_id || "item") + "-" + release + "-" + Date.now() + "@oshi-calendar";
    var lines = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Oshi Calendar//JP", "CALSCALE:GREGORIAN",
      "BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + stamp, "DTSTART;VALUE=DATE:" + release,
      "DTEND;VALUE=DATE:" + addOneDay(card.sales_date_iso),
      "SUMMARY:" + escapeIcs("【" + oshiName + "】" + card.title + " 発売日"),
      "DESCRIPTION:" + escapeIcs(card.url), "URL:" + card.url, "END:VEVENT", "END:VCALENDAR"
    ];
    var blob = new Blob([lines.join("\r\n") + "\r\n"], { type: "text/calendar;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "oshi-calendar-" + release + ".ics";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    showToast("カレンダーファイルを作成しました");
  }

  function fetchOshiSummary(oshi) {
    return fetch("/api/oshi/" + oshi.id + "/summary?limit=8").then(function (response) {
      if (!response.ok) throw new Error();
      return response.json();
    }).then(function (data) {
      data.name = data.name || oshi.name;
      return data;
    });
  }

  function groupCardData(cards) {
    var groups = [];
    var byKey = {};
    cards.forEach(function (card, index) {
      var titleKey = card.variation_key || "";
      var monthKey = card.sales_month || "";
      var canGroup = titleKey.length >= 4 && monthKey;
      var key = canGroup ? String(card.oshi_id || "") + "|" + titleKey + "|" + monthKey : "unique-" + index;
      if (!byKey[key]) {
        byKey[key] = { representative: card, variations: [] };
        groups.push(byKey[key]);
      } else {
        byKey[key].variations.push(card);
      }
    });
    return groups;
  }

  function createProductCard(card, options) {
    options = options || {};
    var shell = document.createElement("article");
    shell.className = "card-shell";
    shell.dataset.variationKey = card.variation_key || "";
    shell.dataset.salesMonth = card.sales_month || "";

    var link = document.createElement("a");
    link.className = "card";
    link.dataset.media = card.media_key || "";
    if (card.oshi_id) link.dataset.oshiId = String(card.oshi_id);
    link.href = card.url;
    link.rel = "nofollow sponsored";
    link.target = "_blank";

    var media = document.createElement("div");
    media.className = "card-media";
    if (card.image) {
      var image = document.createElement("img");
      image.src = card.image;
      image.alt = card.title;
      image.loading = "lazy";
      image.decoding = "async";
      image.width = 480;
      image.height = 480;
      media.appendChild(image);
    } else {
      var placeholder = document.createElement("div");
      placeholder.className = "image-placeholder";
      placeholder.setAttribute("role", "img");
      placeholder.setAttribute("aria-label", card.title + "の画像はありません");
      var icon = appendTextElement(placeholder, "span", "", "📦");
      icon.setAttribute("aria-hidden", "true");
      appendTextElement(placeholder, "small", "", "NO IMAGE");
      media.appendChild(placeholder);
    }
    link.appendChild(media);

    var body = document.createElement("div");
    body.className = "card-body";
    var badges = document.createElement("div");
    badges.className = "badge-row";
    appendTextElement(badges, "span", "badge", card.media || card.media_key || "その他");
    if (card.is_new) appendTextElement(badges, "span", "badge new", "NEW");
    if (options.showOshi && card.oshi_name) {
      appendTextElement(badges, "span", "badge oshi-chip", card.oshi_name);
    }
    if (options.myOshi) appendTextElement(badges, "span", "badge my-oshi-badge", "♥ マイ推し");
    body.appendChild(badges);

    var title = appendTextElement(body, "h3", "", card.title);
    title.title = card.title;
    if (card.author) appendTextElement(body, "p", "author", card.author);

    var details = document.createElement("div");
    details.className = "card-details";
    if (card.sales_date) {
      var date = document.createElement("p");
      date.className = "date" + (card.is_upcoming ? " upcoming" : "");
      appendTextElement(date, "span", "detail-label", "発売日");
      appendTextElement(date, "strong", "", card.sales_date);
      if (card.is_upcoming) appendTextElement(date, "span", "upcoming-label", "発売前");
      details.appendChild(date);
    }
    if (card.price !== null && card.price !== undefined) {
      appendTextElement(details, "p", "price", new Intl.NumberFormat("ja-JP").format(card.price) + "円（税込）");
    } else {
      appendTextElement(details, "p", "price unavailable", "最新価格は楽天でご確認ください");
    }
    appendTextElement(details, "p", "fetched", "[" + card.fetched_at + "] 時点の情報");
    body.appendChild(details);
    link.appendChild(body);
    shell.appendChild(link);
    if (options.ics && parseIsoDate(card.sales_date_iso)) {
      var calendarButton = document.createElement("button");
      calendarButton.className = "calendar-add-button";
      calendarButton.type = "button";
      calendarButton.textContent = "📅 カレンダーに追加";
      calendarButton.setAttribute("aria-label", card.title + "の発売日をカレンダーに追加");
      calendarButton.addEventListener("click", function () {
        downloadIcs(card, card.oshi_name || options.oshiName || "推し");
      });
      shell.appendChild(calendarButton);
    }
    return shell;
  }

  function createVariationGroup(group, options) {
    var wrapper = document.createElement("div");
    wrapper.className = "variation-group";
    wrapper.dataset.variationGroup = "";
    wrapper.appendChild(createProductCard(group.representative, options));
    if (group.variations && group.variations.length) {
      var details = document.createElement("details");
      details.className = "variations";
      appendTextElement(details, "summary", "", "他" + group.variations.length + "件のバリエーションを見る");
      var grid = document.createElement("div");
      grid.className = "grid variation-grid";
      group.variations.forEach(function (card) { grid.appendChild(createProductCard(card, options)); });
      details.appendChild(grid);
      wrapper.appendChild(details);
    }
    return wrapper;
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

  /* --- トップ: localStorageの推しだけをクライアント側で個人化 --- */
  var personalizedSection = document.getElementById("personalized-section");
  if (personalizedSection) {
    var topList = loadList();
    var favoriteIds = {};
    topList.forEach(function (oshi) { favoriteIds[oshi.id] = true; });

    var weekGrid = document.getElementById("week-grid");
    if (weekGrid && topList.length) {
      var weekCards = Array.from(weekGrid.children);
      weekCards.forEach(function (shell, index) {
        shell.dataset.originalOrder = String(index);
        var link = shell.querySelector("a.card");
        var isFavorite = link && favoriteIds[parseInt(link.dataset.oshiId, 10)];
        shell.dataset.favoriteOrder = isFavorite ? "0" : "1";
        if (isFavorite && !link.querySelector(".my-oshi-badge")) {
          appendTextElement(link.querySelector(".badge-row"), "span", "badge my-oshi-badge", "♥ マイ推し");
        }
      });
      weekCards.sort(function (left, right) {
        return Number(left.dataset.favoriteOrder) - Number(right.dataset.favoriteOrder) ||
          Number(left.dataset.originalOrder) - Number(right.dataset.originalOrder);
      }).forEach(function (shell) { weekGrid.appendChild(shell); });
    }

    if (topList.length) {
      personalizedSection.hidden = false;
      var topTargets = topList.slice(0, 10);
      Promise.all(topTargets.map(function (oshi) {
        return fetchOshiSummary(oshi).catch(function () { return null; });
      })).then(function (summaries) {
        summaries = summaries.filter(Boolean);
        var future = [];
        var recent = [];
        summaries.forEach(function (summary) {
          future = future.concat(summary.upcoming || []);
          recent = recent.concat(summary.recent || []);
        });
        future.sort(function (a, b) { return (a.sales_date_iso || "").localeCompare(b.sales_date_iso || ""); });
        recent.sort(function (a, b) { return (b.first_seen_at || "").localeCompare(a.first_seen_at || ""); });
        var selected = future.length ? future : recent;
        var unique = [];
        var seenUrls = {};
        selected.forEach(function (card) {
          if (!seenUrls[card.url] && unique.length < 8) {
            seenUrls[card.url] = true;
            unique.push(card);
          }
        });
        var grid = document.getElementById("personalized-grid");
        var title = document.getElementById("personalized-title");
        var note = document.getElementById("personalized-note");
        document.getElementById("personalized-loading").hidden = true;
        title.textContent = future.length ? "あなたの推しの発売予定" : "登録中の推しの新着";
        if (topList.length > 10) note.textContent = "表示速度を保つため、先頭10件の推しから直近情報を表示しています。";
        if (!unique.length) {
          note.textContent = "登録中の推しの供給情報はまだありません。";
        } else {
          unique.forEach(function (card) {
            grid.appendChild(createProductCard(card, { showOshi: true, myOshi: true }));
          });
        }
        personalizedSection.setAttribute("aria-busy", "false");
      });
    }
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

  /* --- 推しページ: 新着順を24件ずつ追加描画 --- */
  var loadMore = document.getElementById("load-more-items");
  if (loadMore) {
    loadMore.addEventListener("click", function () {
      var grid = document.getElementById("newest-grid");
      var status = document.getElementById("load-more-status");
      var offset = parseInt(loadMore.dataset.offset, 10) || 0;
      var total = parseInt(loadMore.dataset.total, 10) || 0;
      loadMore.disabled = true;
      loadMore.setAttribute("aria-busy", "true");
      status.textContent = "商品を読み込んでいます…";
      fetch("/api/oshi/" + loadMore.dataset.oshiId + "/items?offset=" + offset + "&limit=24")
        .then(function (response) {
          if (!response.ok) throw new Error();
          return response.json();
        })
        .then(function (data) {
          data.groups.forEach(function (group) { grid.appendChild(createVariationGroup(group)); });
          loadMore.dataset.offset = String(data.next_offset);
          var remaining = Math.max(0, total - data.next_offset);
          status.textContent = data.items.length + "件を追加しました。";
          if (!data.has_more) {
            loadMore.remove();
          } else {
            loadMore.querySelector(".load-more-count").textContent = "（残り" + remaining + "件）";
            loadMore.disabled = false;
            loadMore.setAttribute("aria-busy", "false");
          }
        })
        .catch(function () {
          status.textContent = "読み込めませんでした。もう一度お試しください。";
          loadMore.disabled = false;
          loadMore.setAttribute("aria-busy", "false");
        });
    });
  }

  /* --- マイページ: localStorageだけで統合カレンダー・移行・並べ替え --- */
  var myList = document.getElementById("my-list");
  if (myList) {
    var myCalendar = document.getElementById("my-calendar");
    var myTimeline = document.getElementById("my-calendar-timeline");
    var myCalendarNote = document.getElementById("my-calendar-note");
    var mySummaryCache = {};
    var myCalendarCache = {};
    var myCurrentList = [];
    var myMonths = [];
    var myMonthIndex = 0;

    var emptyMyList = function () {
      myList.innerHTML = '<div class="empty-state"><span class="empty-illustration" aria-hidden="true">💗</span>' +
        '<h2>まだ推しが登録されていません</h2><p>推しページの「☆ マイ推しリストに追加」から登録できます。</p>' +
        '<a class="primary-link" href="/">推しを検索する</a></div>';
    };

    var copyText = function (value) {
      if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(value);
      var area = document.createElement("textarea");
      area.value = value;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      return Promise.resolve();
    };

    var importIds = function (value) {
      try {
        var parsedUrl = new URL(value, location.href);
        var raw = new URLSearchParams(parsedUrl.hash.replace(/^#/, "")).get("import");
        if (!raw && /^\d+(,\d+)*$/.test(value.trim())) raw = value.trim();
        var seen = {};
        return (raw || "").split(",").map(Number).filter(function (id) {
          if (!Number.isInteger(id) || id <= 0 || seen[id]) return false;
          seen[id] = true;
          return true;
        }).slice(0, 50);
      } catch (error) {
        return [];
      }
    };

    var runImport = function (ids) {
      if (!ids.length) {
        showToast("インポートできる推しIDが見つかりませんでした");
        return Promise.resolve(false);
      }
      if (!window.confirm(ids.length + "件の推しを現在のリストへ追加しますか？\n既存の推しは削除されません。")) {
        return Promise.resolve(false);
      }
      return Promise.all(ids.map(function (id) {
        return fetchOshiSummary({ id: id, name: "推し #" + id }).catch(function () { return null; });
      })).then(function (summaries) {
        var list = loadList();
        var existing = {};
        list.forEach(function (oshi) { existing[oshi.id] = true; });
        var added = 0;
        summaries.filter(Boolean).forEach(function (summary) {
          if (!existing[summary.id] && list.length < 50) {
            list.push({ id: summary.id, name: summary.name });
            existing[summary.id] = true;
            added++;
          }
        });
        saveList(list);
        showToast(added ? added + "件をマイ推しリストへ追加しました" : "追加済みの推しです");
        return true;
      });
    };

    var chooseMonthIndex = function (months) {
      var now = new Date();
      var current = now.getFullYear().toString().padStart(4, "0") + "-" +
        (now.getMonth() + 1).toString().padStart(2, "0");
      var exact = months.indexOf(current);
      if (exact >= 0) return exact;
      var future = months.findIndex(function (month) { return month > current; });
      return future >= 0 ? future : Math.max(0, months.length - 1);
    };

    var timelineLabel = function (card) {
      var date = parseIsoDate(card.sales_date_iso);
      if (!date) return "日付未定";
      if (card.sales_date_precision !== "day") return (date.getMonth() + 1) + "月中（日付未確定）";
      return (date.getMonth() + 1) + "月" + date.getDate() + "日（" +
        ["日", "月", "火", "水", "木", "金", "土"][date.getDay()] + "）";
    };

    var renderCombinedTimeline = function (cards) {
      myTimeline.innerHTML = "";
      if (!cards.length) {
        var empty = document.createElement("div");
        empty.className = "empty-state";
        appendTextElement(empty, "span", "empty-illustration", "🗓️").setAttribute("aria-hidden", "true");
        appendTextElement(empty, "h2", "", "この月の発売予定はありません。");
        appendTextElement(empty, "p", "", "前後の供給月へ移動して確認できます。");
        myTimeline.appendChild(empty);
        return;
      }
      cards.sort(function (a, b) { return (a.sales_date_iso || "").localeCompare(b.sales_date_iso || ""); });
      var days = [];
      var byDay = {};
      cards.forEach(function (card) {
        var key = card.sales_date_precision === "day" ? card.sales_date_iso : (card.sales_month + "-00");
        if (!byDay[key]) {
          byDay[key] = [];
          days.push(key);
        }
        byDay[key].push(card);
      });
      days.sort().forEach(function (key) {
        var daySection = document.createElement("section");
        daySection.className = "timeline-day";
        daySection.dataset.dateGroup = "";
        var heading = document.createElement("h2");
        var dot = document.createElement("span");
        dot.className = "timeline-dot";
        dot.setAttribute("aria-hidden", "true");
        heading.appendChild(dot);
        heading.appendChild(document.createTextNode(timelineLabel(byDay[key][0])));
        daySection.appendChild(heading);
        var grid = document.createElement("div");
        grid.className = "timeline-grid";
        groupCardData(byDay[key]).forEach(function (group) {
          grid.appendChild(createVariationGroup(group, { showOshi: true, ics: true }));
        });
        daySection.appendChild(grid);
        myTimeline.appendChild(daySection);
      });
    };

    var loadMyCalendarMonth = function () {
      if (!myMonths.length) {
        document.getElementById("my-calendar-month").textContent = "供給月なし";
        renderCombinedTimeline([]);
        document.getElementById("my-calendar-loading").hidden = true;
        myCalendar.setAttribute("aria-busy", "false");
        return Promise.resolve();
      }
      var monthKey = myMonths[myMonthIndex];
      var parts = monthKey.split("-");
      var cacheKey = myCurrentList.map(function (oshi) { return oshi.id; }).join(",") + "|" + monthKey;
      document.getElementById("my-calendar-month").textContent = Number(parts[0]) + "年" + Number(parts[1]) + "月";
      var previous = document.getElementById("my-calendar-prev");
      var next = document.getElementById("my-calendar-next");
      previous.disabled = myMonthIndex === 0;
      next.disabled = myMonthIndex === myMonths.length - 1;
      myCalendar.setAttribute("aria-busy", "true");
      document.getElementById("my-calendar-loading").hidden = false;
      myTimeline.innerHTML = "";
      myCalendarNote.textContent = "登録中の推しを順番に確認しています…";

      var request = myCalendarCache[cacheKey] ? Promise.resolve(myCalendarCache[cacheKey]) :
        Promise.all(myCurrentList.map(function (oshi) {
          return fetch("/api/oshi/" + oshi.id + "/calendar?y=" + parts[0] + "&m=" + parts[1] + "&limit=48")
            .then(function (response) { if (!response.ok) throw new Error(); return response.json(); })
            .catch(function () { return null; });
        })).then(function (responses) {
          myCalendarCache[cacheKey] = responses.filter(Boolean);
          return myCalendarCache[cacheKey];
        });

      return request.then(function (responses) {
        var cards = [];
        var truncated = 0;
        responses.forEach(function (response) {
          cards = cards.concat(response.items || []);
          if (response.truncated) truncated++;
        });
        renderCombinedTimeline(cards);
        document.getElementById("my-calendar-loading").hidden = true;
        myCalendarNote.textContent = cards.length + "件の供給を表示" +
          (truncated ? "（一部の推しは48件まで）" : "") + "。リストはブラウザ内だけに保存されています。";
        myCalendar.setAttribute("aria-busy", "false");
      });
    };

    var renderOshiSections = function () {
      myList.innerHTML = "";
      myCurrentList.forEach(function (oshi, index) {
        var summary = mySummaryCache[oshi.id];
        var section = document.createElement("section");
        section.className = "my-oshi-card";
        var header = document.createElement("div");
        header.className = "my-oshi-header";
        var heading = document.createElement("h2");
        var pageLink = appendTextElement(heading, "a", "", summary ? summary.name : oshi.name);
        pageLink.href = "/oshi/" + oshi.id;
        header.appendChild(heading);
        var actions = document.createElement("div");
        actions.className = "oshi-order-actions";
        [["↑", "上へ移動", -1], ["↓", "下へ移動", 1]].forEach(function (config) {
          var button = appendTextElement(actions, "button", "icon-button", config[0]);
          button.type = "button";
          button.title = config[1];
          button.setAttribute("aria-label", (summary ? summary.name : oshi.name) + "を" + config[1]);
          button.disabled = index + config[2] < 0 || index + config[2] >= myCurrentList.length;
          button.addEventListener("click", function () {
            var list = loadList();
            var target = index + config[2];
            var moved = list.splice(index, 1)[0];
            list.splice(target, 0, moved);
            saveList(list);
            renderMyPage();
          });
        });
        var remove = appendTextElement(actions, "button", "remove-button", "削除");
        remove.type = "button";
        remove.addEventListener("click", function () {
          if (!window.confirm((summary ? summary.name : oshi.name) + "をマイ推しリストから削除しますか？")) return;
          var list = loadList().filter(function (item) { return item.id !== oshi.id; });
          saveList(list);
          myCalendarCache = {};
          renderMyPage();
          showToast("マイ推しリストから削除しました");
        });
        header.appendChild(actions);
        section.appendChild(header);

        if (!summary) {
          appendTextElement(section, "p", "error", "情報を取得できませんでした。");
        } else {
          var card = summary.upcoming && summary.upcoming[0];
          if (card) {
            var remaining = daysUntil(card.sales_date_iso);
            appendTextElement(section, "p", "supply-summary", "次の発売予定: " +
              formatJapaneseDate(card.sales_date_iso) + (remaining === null ? "" : "（あと" + remaining + "日）"));
          } else {
            card = summary.latest_supply;
            appendTextElement(section, "p", "supply-summary", card && card.sales_month ?
              "直近の供給: " + card.sales_month.replace("-", "年") + "月" : "供給情報はまだありません。");
          }
          if (card) {
            var oneCard = document.createElement("div");
            oneCard.className = "my-summary-grid";
            oneCard.appendChild(createProductCard(card, { ics: true, oshiName: summary.name }));
            section.appendChild(oneCard);
          }
        }
        myList.appendChild(section);
      });
    };

    var renderMyPage = function () {
      myCurrentList = loadList();
      var exportButton = document.getElementById("export-list");
      exportButton.disabled = !myCurrentList.length;
      if (!myCurrentList.length) {
        myCalendar.hidden = true;
        emptyMyList();
        return Promise.resolve();
      }
      myCalendar.hidden = false;
      myList.innerHTML = '<div class="skeleton-card"><div class="skeleton-line"></div><div class="skeleton-line short"></div></div>';
      return Promise.all(myCurrentList.map(function (oshi) {
        if (mySummaryCache[oshi.id]) return Promise.resolve(mySummaryCache[oshi.id]);
        return fetchOshiSummary(oshi).then(function (summary) {
          mySummaryCache[oshi.id] = summary;
          return summary;
        }).catch(function () { return null; });
      })).then(function (summaries) {
        myMonths = Array.from(new Set(summaries.filter(Boolean).flatMap(function (summary) {
          return summary.available_months || [];
        }))).sort();
        myMonthIndex = chooseMonthIndex(myMonths);
        renderOshiSections();
        return loadMyCalendarMonth();
      });
    };

    document.getElementById("my-calendar-prev").addEventListener("click", function () {
      if (myMonthIndex > 0) { myMonthIndex--; loadMyCalendarMonth(); }
    });
    document.getElementById("my-calendar-next").addEventListener("click", function () {
      if (myMonthIndex < myMonths.length - 1) { myMonthIndex++; loadMyCalendarMonth(); }
    });
    document.getElementById("export-list").addEventListener("click", function () {
      var list = loadList();
      if (!list.length) return;
      var shareUrl = location.origin + "/my#import=" + encodeURIComponent(list.map(function (oshi) { return oshi.id; }).join(","));
      copyText(shareUrl).then(function () { showToast("エクスポートURLをコピーしました"); });
    });
    document.getElementById("import-list").addEventListener("click", function () {
      var value = window.prompt("エクスポートURLを貼り付けてください");
      if (!value) return;
      runImport(importIds(value)).then(function (changed) { if (changed) renderMyPage(); });
    });
    document.getElementById("import-help").addEventListener("click", function (event) {
      var help = document.getElementById("import-help-text");
      help.hidden = !help.hidden;
      event.currentTarget.setAttribute("aria-expanded", help.hidden ? "false" : "true");
    });

    var hashIds = importIds(location.href);
    if (location.hash.indexOf("#import=") === 0) {
      history.replaceState(null, "", location.pathname + location.search);
      runImport(hashIds).then(function () { renderMyPage(); });
    } else {
      renderMyPage();
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
