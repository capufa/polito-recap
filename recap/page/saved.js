// What the browser keeps for the app, shared by the lecture page and the indexes: the theme,
// the speed and the "Studied" ticks, under STORAGE_PREFIX (set in the page's <head>). Ticks
// are saved per lecture (course/lecture, Lecture.key), one per slide id (deck:page). If the
// browser won't keep anything, the pages work anyway, forgetting.
var Saved = {
  get: function (name, fallback) {
    try { var v = localStorage.getItem(STORAGE_PREFIX + name); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
  },
  set: function (name, value) {
    try { localStorage.setItem(STORAGE_PREFIX + name, JSON.stringify(value)); } catch (e) { }
  },
  // Fills a study progress box (page.STUDY_PROGRESS): how many of the slide ids are ticked.
  // Only the lecture's own slides count: ticks of a deleted lecture with the same name do not.
  showStudied: function (box, ticks, ids) {
    var done = ids.filter(function (id) { return ticks[id]; }).length, all = ids.length;
    box.querySelector(".bar i").style.width = (all ? Math.round(done / all * 100) : 0) + "%";
    box.querySelector(".progress-text").textContent = done + " of " + all + (all === 1 ? " slide" : " slides") + " studied";
  },
};
