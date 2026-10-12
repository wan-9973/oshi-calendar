/*
 * アクセス解析ローダー（欲望観測所と同じ GA4 + Microsoft Clarity 構成）。
 * - 計測IDはサーバーが <script data-*> 属性で渡す（本番かつID設定時のみ出力）。
 * - マイ推しリスト（localStorage）の中身は送信しない。/my と個人化欄は Clarity でマスクする。
 * - 送信するパラメータは文字列100字・数値・真偽値に限定する。
 */
(function () {
  "use strict";
  var script = document.currentScript || document.querySelector("script[data-analytics-schema-version]");
  if (!script) return;
  var GA_ID = script.getAttribute("data-ga-measurement-id") || "";
  var CLARITY_ID = script.getAttribute("data-clarity-project-id") || "";
  var SCHEMA_VERSION = script.getAttribute("data-analytics-schema-version") || "1";
  var PAGE_TYPE = (document.body && document.body.getAttribute("data-analytics-page-type")) || "other";

  var EVENTS = [
    "view_this_week", "view_upcoming", "view_newest",
    "select_navigation", "select_filter", "select_month",
    "click_rakuten", "search", "search_complete", "search_error",
    "add_my_oshi", "remove_my_oshi", "add_to_calendar",
    "load_more", "view_variations", "view_more",
    "scroll_depth", "engagement_milestone"
  ];

  /* --- GA4 --- */
  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  if (GA_ID) {
    window.gtag = window.gtag || gtag;
    var ga = document.createElement("script");
    ga.async = true;
    ga.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(GA_ID);
    document.head.appendChild(ga);
    window.gtag("js", new Date());
    window.gtag("set", { page_type: PAGE_TYPE, analytics_schema_version: SCHEMA_VERSION });
    window.gtag("config", GA_ID, {
      send_page_view: true,
      debug_mode: false,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      transport_type: "beacon"
    });
  }

  /* --- Microsoft Clarity（公式スニペット相当） --- */
  if (CLARITY_ID) {
    (function (c, l, a, r, i) {
      c[a] = c[a] || function () { (c[a].q = c[a].q || []).push(arguments); };
      var t = l.createElement(r);
      t.async = 1;
      t.src = "https://www.clarity.ms/tag/" + encodeURIComponent(i);
      var y = l.getElementsByTagName(r)[0];
      y.parentNode.insertBefore(t, y);
    })(window, document, "clarity", "script", CLARITY_ID);
    window.clarity("set", "page_type", PAGE_TYPE);
    window.clarity("set", "analytics_schema_version", SCHEMA_VERSION);
  }

  function clean(params) {
    var out = {};
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value === null || value === undefined || value === "") return;
      if (typeof value === "number" && isFinite(value)) out[key] = value;
      else if (typeof value === "boolean") out[key] = value;
      else out[key] = String(value).slice(0, 100);
    });
    return out;
  }

  function track(name, params) {
    if (EVENTS.indexOf(name) < 0) return;
    var payload = clean(params);
    payload.page_type = PAGE_TYPE;
    try { if (GA_ID && window.gtag) window.gtag("event", name, payload); } catch (e) { /* 計測失敗は無視 */ }
    try { if (CLARITY_ID && window.clarity) window.clarity("event", name); } catch (e) { /* 同上 */ }
  }

  function trackSearch(term) {
    var value = String(term || "").trim();
    if (value) track("search", { search_term: value });
  }

  window.OshiAnalytics = { schemaVersion: SCHEMA_VERSION, events: EVENTS.slice(), track: track, trackSearch: trackSearch };

  /* app.js が本スクリプトより先に記録したイベントを送信する */
  var queued = window.__oshiAnalyticsQueue || [];
  window.__oshiAnalyticsQueue = [];
  queued.forEach(function (item) { track(item[0], item[1]); });

  function sectionOf(el) {
    var section = el.closest("[data-content-section]");
    return section ? section.getAttribute("data-content-section") : "";
  }

  function positionOf(link) {
    var section = link.closest("[data-content-section]") || document;
    var cards = Array.prototype.slice.call(section.querySelectorAll("a.card"));
    var index = cards.indexOf(link);
    return index >= 0 ? index + 1 : null;
  }

  /* --- クリック計測（イベント委譲。JSで後から描画されるカードにも効く） --- */
  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;

    var card = target.closest("a.card");
    if (card) {
      track("click_rakuten", {
        link_location: "card",
        content_section: sectionOf(card),
        item_position: positionOf(card),
        media: card.getAttribute("data-media"),
        relation: card.getAttribute("data-relation")
      });
      return;
    }

    var tagged = target.closest("[data-analytics-event]");
    if (tagged) {
      track(tagged.getAttribute("data-analytics-event"), {
        target_id: tagged.getAttribute("data-target-id"),
        content_section: sectionOf(tagged)
      });
      return;
    }

    var mediaTab = target.closest("[data-tab]");
    if (mediaTab && !mediaTab.disabled) {
      track("select_filter", { filter_type: "media", filter_value: mediaTab.getAttribute("data-tab") });
      return;
    }
    var relationTab = target.closest("[data-relation-tab]");
    if (relationTab && !relationTab.disabled) {
      track("select_filter", { filter_type: "relation", filter_value: relationTab.getAttribute("data-relation-tab") });
      return;
    }

    var month = target.closest(".month-button, .primary-link[href*='m=']");
    if (month && !month.disabled && month.getAttribute("aria-disabled") !== "true") {
      var label = (month.id || "") + " " + (month.getAttribute("aria-label") || "") + " " + month.textContent;
      var direction = /prev|前/.test(label) ? "prev" : (/next|次/.test(label) ? "next" : "jump");
      track("select_month", { direction: direction, content_section: sectionOf(month) });
      return;
    }

    if (target.closest("#load-more-items")) track("load_more", { content_section: "newest" });
  });

  /* --- バリエーション・「さらに見る」を開いた --- */
  document.addEventListener("toggle", function (event) {
    var details = event.target;
    if (!details || details.tagName !== "DETAILS" || !details.open) return;
    if (details.classList.contains("variations")) track("view_variations", { content_section: sectionOf(details) });
    else if (details.classList.contains("top-more")) track("view_more", { content_section: sectionOf(details) });
  }, true);

  /* --- セクションが表示された（1ページ1回） --- */
  var sectionTargets = document.querySelectorAll("[data-analytics-section-event]");
  if (sectionTargets.length && "IntersectionObserver" in window) {
    var sectionObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        sectionObserver.unobserve(entry.target);
        track(entry.target.getAttribute("data-analytics-section-event"), { content_section: sectionOf(entry.target) });
      });
    }, { threshold: 0.6 });
    sectionTargets.forEach(function (el) { sectionObserver.observe(el); });
  }

  /* --- スクロール深度（25/50/75/90%、各1回） --- */
  var depthMarks = [25, 50, 75, 90];
  var depthSent = {};
  var depthTicking = false;
  function checkDepth() {
    depthTicking = false;
    var doc = document.documentElement;
    var scrollable = doc.scrollHeight - window.innerHeight;
    if (scrollable <= 0) return;
    var percent = Math.round((window.scrollY / scrollable) * 100);
    depthMarks.forEach(function (mark) {
      if (percent >= mark && !depthSent[mark]) {
        depthSent[mark] = true;
        track("scroll_depth", { percent_scrolled: mark });
      }
    });
  }
  window.addEventListener("scroll", function () {
    if (!depthTicking) { depthTicking = true; window.requestAnimationFrame(checkDepth); }
  }, { passive: true });

  /* --- 表示中の滞在時間（30秒/60秒/180秒、各1回） --- */
  var milestones = [30, 60, 180];
  var visibleSeconds = 0;
  setInterval(function () {
    if (document.visibilityState !== "visible") return;
    visibleSeconds += 5;
    while (milestones.length && visibleSeconds >= milestones[0]) {
      track("engagement_milestone", { seconds: milestones.shift() });
    }
  }, 5000);
})();
