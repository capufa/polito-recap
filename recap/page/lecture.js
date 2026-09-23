// The lecture page: what moves. No libraries, no network; what stays saved (ticks, theme,
// speed) lives in the browser (saved.js).
(function () {
  "use strict";
  var page = document.body;
  function $(selector) { return document.querySelector(selector); }
  function $$(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }
  function flash(el) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }

  // The cards with their segments in seconds: for the player and for the summary points.
  var cards = $$(".card[data-intervals]").map(function (el) {
    return { el: el, spans: el.dataset.intervals.split(",").map(function (t) { return t.split("-").map(Number); }) };
  });
  function cardAt(second) {
    for (var i = 0; i < cards.length; i++)
      for (var j = 0; j < cards[i].spans.length; j++)
        if (second >= cards[i].spans[j][0] && second < cards[i].spans[j][1]) return cards[i].el;
    return null;
  }

  // The player — the video, or the audio of a voice-only lecture: a timestamp takes it to
  // that instant; while it plays, the card of what is on screen lights up (video only: the
  // audio has no segments, and no "Follow the video").
  var media = $("#media"), player = $(".player"), follow = $("#follow"), onScreen = null;
  function noMedia() { page.classList.add("no-media"); }
  if (media.error) noMedia();
  media.addEventListener("error", noMedia);
  media.addEventListener("timeupdate", function () {
    var el = cardAt(media.currentTime);
    if (el === onScreen) return;
    if (onScreen) onScreen.classList.remove("now");
    onScreen = el;
    if (!el) return;
    el.classList.add("now");
    if (follow && follow.checked) el.scrollIntoView({ block: "center" });     // smooth unless reduced motion (style.css)
  });
  function available() {
    if (!page.classList.contains("no-media")) return true;
    flash($(".media-missing"));
    return false;
  }
  function play() {
    var started = media.play();
    if (started && started.catch) started.catch(function () { });
  }
  function seek(second) {
    if (!available()) return;
    media.currentTime = second;
    play();
  }

  // The controls under the player: 5 seconds back or forward (also with the ← → arrows, from
  // anywhere except where you type), pause; and, in narrow windows, "collapse".
  var playButton = $("#play"), jump = $("#jump"), jumpTimer = null;
  function state() {
    player.classList.toggle("playing", !media.paused);
    playButton.setAttribute("aria-label", media.paused ? "Play" : "Pause");
  }
  media.addEventListener("play", state);
  media.addEventListener("pause", state);
  function skip(seconds) {
    if (!available()) return;
    var end = isFinite(media.duration) ? media.duration : Infinity;
    media.currentTime = Math.min(Math.max(media.currentTime + seconds, 0), end);
    jump.textContent = (seconds < 0 ? "−" : "+") + Math.abs(seconds) + " s";
    jump.classList.add("visible");
    clearTimeout(jumpTimer);
    jumpTimer = setTimeout(function () { jump.classList.remove("visible"); }, 700);
  }
  $("#back").addEventListener("click", function () { skip(-5); });
  $("#forward").addEventListener("click", function () { skip(5); });
  playButton.addEventListener("click", function () { if (media.paused) play(); else media.pause(); });
  $("#collapse").addEventListener("click", function () {
    var collapsed = player.classList.toggle("collapsed");
    this.setAttribute("aria-expanded", String(!collapsed));
    this.title = collapsed ? "Show the player" : "Collapse the player";
  });

  // The speed: from the slider, 0.5× to 2×; the button next to it goes back to 1×. It holds
  // for every lecture. defaultPlaybackRate keeps it even when the file reloads.
  var slider = $("#speed"), speedValue = $("#speed-value");
  function speed(v) {
    media.defaultPlaybackRate = media.playbackRate = v;
    slider.value = v;
    speedValue.textContent = v + "×";
    Saved.set("speed", v);
  }
  speed(Number(Saved.get("speed", 1)));
  slider.addEventListener("input", function () { speed(Number(slider.value)); });
  speedValue.addEventListener("click", function () { speed(1); });

  var lightbox = $("#lightbox"), lightboxImg = $("#lightbox img");
  lightbox.addEventListener("click", function () { lightbox.hidden = true; });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { lightbox.hidden = true; return; }
    if ((e.key !== "ArrowLeft" && e.key !== "ArrowRight") || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var target = e.target;
    if (target.isContentEditable || target.tagName === "TEXTAREA" || target.tagName === "SELECT" ||
        (target.tagName === "INPUT" && target.type !== "checkbox")) return;
    e.preventDefault();
    skip(e.key === "ArrowLeft" ? -5 : 5);
  });
  document.addEventListener("click", function (e) {
    var el = e.target.closest(".t");
    if (el) { seek(Number(el.dataset.s)); return; }
    el = e.target.closest(".goto");
    if (el) {
      var card = cardAt(Number(el.dataset.s));
      if (card) { card.scrollIntoView({ block: "center" }); flash(card); }
      return;
    }
    el = e.target.closest(".thumb");
    if (el) { var img = el.querySelector("img"); lightboxImg.src = img.src; lightboxImg.alt = img.alt; lightbox.hidden = false; }
  });

  // The explanations: three lines and "Read more"; the ones already short stay open, with no
  // button. The class sets the final height; the animation is only the transition, and if the
  // browser skips it (background tab, reduced motion) the text is right anyway.
  var reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  $$(".explanation").forEach(function (text) {
    var button = text.nextElementSibling;
    if (text.scrollHeight <= text.clientHeight + 4) { text.classList.remove("clamped"); button.remove(); return; }
    button.addEventListener("click", function () {
      var open = text.classList.contains("clamped"), from = text.getBoundingClientRect().height;
      text.classList.toggle("clamped", !open);
      if (!reducedMotion.matches && text.animate)
        text.animate([{ maxHeight: from + "px" }, { maxHeight: text.getBoundingClientRect().height + "px" }],
                     { duration: 450, easing: "ease" });
      button.setAttribute("aria-expanded", String(open));
      button.textContent = open ? "Show less" : "Read more";
    });
  });

  // "Studied": one tick per slide, saved for this lecture (course/lecture).
  var key = page.dataset.key, ticks = Saved.get(key, {}), boxes = $$(".tick input");
  var ids = boxes.map(function (b) { return b.dataset.id; }), progressBox = $(".progress");
  boxes.forEach(function (box) {
    var card = box.closest(".card");
    box.checked = Boolean(ticks[box.dataset.id]);
    card.classList.toggle("studied", box.checked);
    box.addEventListener("change", function () {
      if (box.checked) ticks[box.dataset.id] = true; else delete ticks[box.dataset.id];
      Saved.set(key, ticks);
      card.classList.toggle("studied", box.checked);
      Saved.showStudied(progressBox, ticks, ids);
    });
  });
  Saved.showStudied(progressBox, ticks, ids);

  // Search: ignoring accents and case; the entries that contain the text stay, highlighted.
  function normalize(text) { return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  var search = $("#search"), matches = $("#matches");
  var entries = $$(".entry").map(function (el) { return { el: el, text: normalize(el.textContent) }; });
  search.addEventListener("input", function () {
    var query = normalize(search.value.trim()), count = 0;
    page.classList.toggle("searching", query !== "");
    entries.forEach(function (v) {
      var hit = query === "" || v.text.indexOf(query) >= 0;
      v.el.classList.toggle("no-match", !hit);
      if (query && hit) count++;
      $$(".explanation", v.el).forEach(function (t) { t.classList.toggle("found", query !== "" && hit); });
    });
    $$(".section, .summary").forEach(function (s) { s.classList.toggle("empty", query !== "" && !s.querySelector(".entry:not(.no-match)")); });
    matches.textContent = query === "" ? "" : count === 0 ? "No results" : count === 1 ? "1 result" : count + " results";
    highlight(query);
  });
  function highlight(query) {
    if (!window.CSS || !CSS.highlights) return;
    var ranges = new Highlight();
    if (query) entries.forEach(function (v) {
      if (v.el.classList.contains("no-match")) return;
      var walker = document.createTreeWalker(v.el, NodeFilter.SHOW_TEXT), node;
      while ((node = walker.nextNode())) {
        var text = normalize(node.data);
        if (text.length !== node.data.length) continue;
        for (var i = text.indexOf(query); i >= 0; i = text.indexOf(query, i + query.length)) {
          var range = new Range();
          range.setStart(node, i);
          range.setEnd(node, i + query.length);
          ranges.add(range);
        }
      }
    });
    CSS.highlights.set("found", ranges);
  }

  // The table of contents follows the section being read; the cards appear as they arrive.
  if ("IntersectionObserver" in window) {
    var bySection = {};
    $$(".toc a").forEach(function (a) { bySection[a.hash.slice(1)] = a; });
    var sectionsInView = new IntersectionObserver(function (observed) {
      observed.forEach(function (o) {
        if (!o.isIntersecting) return;
        $$(".toc a").forEach(function (a) { a.classList.toggle("active", a === bySection[o.target.id]); });
      });
    }, { rootMargin: "-30% 0px -65% 0px" });
    $$(".section").forEach(function (s) { sectionsInView.observe(s); });
    var reveals = new IntersectionObserver(function (observed) {
      observed.forEach(function (o) { if (o.isIntersecting) { o.target.classList.add("revealed"); reveals.unobserve(o.target); } });
    }, { rootMargin: "0px 0px -6% 0px" });
    $$(".reveal").forEach(function (el) { reveals.observe(el); });
  } else {
    $$(".reveal").forEach(function (el) { el.classList.add("revealed"); });
  }

  // The theme: the button switches from light to dark and back, starting from the system's.
  $("#theme").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    Saved.set("theme", root.dataset.theme);
  });
})();
