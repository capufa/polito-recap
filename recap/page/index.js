// The indexes: for every lecture, how many of its slides are already ticked "Studied" in this
// browser (saved.js).
(function () {
  "use strict";
  Array.prototype.forEach.call(document.querySelectorAll(".lecture[data-key]"), function (el) {
    Saved.showStudied(el, Saved.get(el.dataset.key, {}), JSON.parse(el.dataset.ids));
  });
})();
