// The app, inside the indexes: new courses, new lectures (the lecture file and the slides,
// dropped or picked), the jobs in progress, the ✎ that renames a course or retitles a
// lecture, and the 🗑 that sends them to the trash. The server wants the X-Recap header on
// every API request, and it decides formats, states and trash days: they come from the page
// (data-*) and from the JSON.
(function () {
  "use strict";

  var HEADERS = { "X-Recap": "1" };
  var DAYS = $("[data-trash-days]").dataset.trashDays;
  var IN_TRASH = "goes to the trash for " + DAYS + " days.";
  function $(selector, root) { return (root || document).querySelector(selector); }
  function esc(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function megabytes(bytes) { return (bytes / 1048576).toFixed(bytes < 10485760 ? 1 : 0) + " MB"; }
  function duration(s) {
    var h = Math.floor(s / 3600), min = Math.floor(s % 3600 / 60), sec = s % 60;
    return (h ? h + ":" + String(min).padStart(2, "0") : min) + ":" + String(sec).padStart(2, "0");
  }

  // An API request: JSON both ways; a server error becomes an Error with the server's
  // message.
  function request(method, url, data) {
    var headers = Object.assign({}, HEADERS, data === undefined ? {} : { "Content-Type": "application/json" });
    return fetch(url, { method: method, headers: headers,
                        body: data === undefined ? undefined : JSON.stringify(data) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          if (!r.ok) throw errorFrom(r.status, body);
          return body;
        });
      }, function () { throw new Error("PoliTo Recap is not answering: is it still running?"); });
  }
  function errorFrom(status, body) { return new Error((body && body.error) || "Error " + status); }

  function api(course, lecture) {
    return "/api/courses/" + encodeURIComponent(course) + (lecture === undefined ? "" : "/lectures/" + encodeURIComponent(lecture));
  }

  // Deleting, from one place: the 🗑 next to a course (home) or a lecture (course list), and
  // "🗑 Cancel" on the card of a lecture being processed. After the confirmation it goes to
  // the trash, stopping the job if there is one; the entry disappears at once, and the page
  // reloads as soon as no upload is under way.
  var QUESTIONS = {
    course: function (d) { return "Delete the course “" + d.course + "” with all its lectures? Everything " + IN_TRASH; },
    lecture: function (d) { return "Delete the lecture “" + d.name + "” (" + d.lecture + ")? The lecture " + IN_TRASH; },
    job: function (d) { return "Cancel “" + d.lecture + "”? The job stops, and the lecture with its file and slides " + IN_TRASH; },
  };
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-delete]");
    if (!button) return;
    var d = button.dataset;
    if (!confirm(QUESTIONS[d.delete](d))) return;
    button.disabled = true;
    request("DELETE", api(d.course, d.lecture))
      .then(function () {
        button.closest("li").remove();
        if (panel) refresh();
        reloadPending = true;
        reloadIfPossible();
      }, function (err) { button.disabled = false; alert(err.message); });
  });

  // The ✎: next to a course (home) it renames it, next to a lecture (course list) it changes
  // its title, the bold one; the file name stays. The prompt offers the current name
  // (data-name), or the one typed last time if the server rejected it. The server rebuilds the
  // pages that carry them, about 4 seconds per lecture; meanwhile the page does not reload and
  // takes no new lecture, then it reloads and shows the result. The title is sent even when
  // unchanged: the page is rebuilt (it repairs one a blackout left behind); a course name is
  // not, it is already there. This browser's "Studied" ticks live under the course name
  // (appunti:course/lecture): if the course is renamed this page moves them when the answer
  // arrives, so until then leaving the page asks first. In other browsers they stay under the
  // old name.
  var editing = null;                // the edit in flight (leaving the page asks first: below)
  var EDITS = {
    course: {
      question: "New course name:",
      guardsUnload: true,                           // closing the page would leave the ticks under the old name
      send: function (d, name) {
        return request("POST", api(d.course) + "/rename", { name: name })
          .then(function () { moveTicks(d.course + "/", name + "/"); });
      },
    },
    lecture: {
      question: "New lecture title:",
      evenUnchanged: true,
      send: function (d, title) { return request("POST", api(d.course, d.lecture) + "/title", { title: title }); },
    },
  };
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-edit]");
    if (!button || editing) return;
    if (busy || chosen.length) { alert("First upload or remove the new lecture: after the change the page reloads."); return; }
    var d = button.dataset, edit = EDITS[d.edit];
    var value = prompt(edit.question, d.attempt || d.name);
    delete d.attempt;
    if (value === null || !(value = value.trim()) || (value === d.name && !edit.evenUnchanged)) return;
    var label = button.textContent;
    editing = edit;
    button.disabled = true;
    button.textContent = "…";
    edit.send(d, value)
      .then(function () { reloadPending = true; },
            function (err) { d.attempt = value; button.disabled = false; button.textContent = label; alert(err.message); })
      .then(function () { editing = null; reloadIfPossible(); });
  });
  // The ticks under the new name belong to a course that no longer exists (deleted, then the
  // name reused): gone, before moving the old name's ones there.
  function moveTicks(before, after) {
    eachTick(after, function (k) { localStorage.removeItem(k); });
    eachTick(before, function (k, rest) {
      localStorage.setItem(STORAGE_PREFIX + after + rest, localStorage.getItem(k));
      localStorage.removeItem(k);
    });
  }
  // fn(key, rest) for every tick under a name that starts with `prefix` (rest is what follows).
  function eachTick(prefix, fn) {
    try {
      Object.keys(localStorage).forEach(function (k) {
        if (k.indexOf(STORAGE_PREFIX + prefix) === 0) fn(k, k.slice((STORAGE_PREFIX + prefix).length));
      });
    } catch (err) { }
  }

  // Brings `old` to match `fresh` touching only what changes: the equal nodes stay the same,
  // so focus, clicks, selection and animations survive the redraw.
  function sync(old, fresh) {
    while (old.childNodes.length > fresh.childNodes.length) old.removeChild(old.lastChild);
    Array.prototype.forEach.call(fresh.childNodes, function (n, i) {
      var o = old.childNodes[i];
      if (!o) { old.appendChild(n.cloneNode(true)); return; }
      if (o.nodeName !== n.nodeName) { old.replaceChild(n.cloneNode(true), o); return; }
      if (n.nodeType === Node.TEXT_NODE) { if (o.nodeValue !== n.nodeValue) o.nodeValue = n.nodeValue; return; }
      Array.prototype.slice.call(o.attributes).forEach(function (a) { if (!n.hasAttribute(a.name)) o.removeAttribute(a.name); });
      Array.prototype.forEach.call(n.attributes, function (a) { if (o.getAttribute(a.name) !== a.value) o.setAttribute(a.name, a.value); });
      sync(o, n);
    });
  }

  // On the home: if there is a new version on GitHub, a line says so (updates.py).
  var update = $("#update");
  if (update) {
    request("GET", "/api/version").then(function (v) {
      if (!v.newer) return;
      update.innerHTML = "Version " + esc(v.latest) + " is out (you have " + esc(v.current) + "): " +
        '<a href="' + esc(v.url) + '" target="_blank" rel="noopener">release notes</a>. ' +
        "To update, run <code>docker compose pull</code> and then <code>docker compose up -d</code>.";
      update.hidden = false;
    }, function () { });
  }

  // On the home: "+ New course" turns into a field; the created course opens at once.
  var newCourse = $("#new-course");
  if (newCourse) {
    var form = $("form", newCourse), openButton = $(".add-open", newCourse), courseError = $(".error-message", newCourse);
    openButton.addEventListener("click", function () { openButton.hidden = true; form.hidden = false; form.course.focus(); });
    $(".cancel", newCourse).addEventListener("click", function () {
      form.hidden = true; openButton.hidden = false; courseError.textContent = "";
    });
    form.course.addEventListener("input", function () { courseError.textContent = ""; });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var name = form.course.value.trim();
      if (!name) { courseError.textContent = "Type the course name."; return; }
      request("POST", "/api/courses", { name: name })
        .then(function (r) { location.href = r.url; })
        .catch(function (err) { courseError.textContent = err.message; });
    });
  }

  // In the course: the new lecture (further down) and the jobs. The state is polled every
  // second while something is queued or running; if the app does not answer, the panel says
  // so and retries every 3 seconds. A finished lecture enters the list by reloading the page,
  // but not at the expense of a new lecture picked or uploading: then the reload waits. It
  // shows as "✓ Ready" only on the page that saw it running, until that reload.
  var upload = $("#upload"), chosen = [], busy = false;
  var panel = $("#jobs"), active = {}, seen = {}, timer = null, reloadPending = false, disconnected = false;
  function reloadIfPossible() { if (reloadPending && !busy && !chosen.length && !editing) location.reload(); }
  // Leaving the page asks first while something would be lost: an upload in flight, or a
  // course rename whose ticks have not moved yet.
  window.addEventListener("beforeunload", function (e) {
    if (busy || (editing && editing.guardsUnload)) { e.preventDefault(); e.returnValue = ""; }
  });
  function refresh() {
    if (!panel) return;
    clearTimeout(timer);
    var jobsError = $(".error-message", panel);
    request("GET", api(panel.dataset.course) + "/jobs")
      .then(function (r) {
        if (disconnected) { jobsError.textContent = ""; disconnected = false; }
        var justDone = r.jobs.some(function (j) { return j.state === "done" && active[j.id]; });
        active = {};
        r.jobs.forEach(function (j) { if (j.active) active[j.id] = seen[j.id] = true; });
        draw(r);
        if (justDone) { reloadPending = true; setTimeout(reloadIfPossible, 1500); }
        if (Object.keys(active).length) timer = setTimeout(refresh, 1000);
      })
      .catch(function (err) { disconnected = true; jobsError.textContent = err.message; timer = setTimeout(refresh, 3000); });
  }
  function draw(r) {
    var items = r.jobs.filter(function (j) { return j.state !== "done" || seen[j.id]; }).map(jobCard);
    panel.hidden = !items.length;
    var fresh = document.createElement("ul");
    fresh.innerHTML = items.join("");
    sync($(".job-list", panel), fresh);
  }
  // The actions of an unfinished lecture: Resume (if an error stopped it) and Cancel.
  function actions(name, resumable) {
    var data = ' type="button" data-course="' + esc(panel.dataset.course) + '" data-lecture="' + esc(name) + '"';
    return '<span class="actions">' + (resumable ? '<button class="button resume"' + data + ">Resume</button>" : "") +
      '<button class="button delete" data-delete="job"' + data + ">🗑 Cancel</button></span>";
  }
  function jobCard(j) {
    var head = '<div class="job-head"><b>' + esc(j.lecture) + "</b>";
    if (j.state === "done")
      return '<li class="job state-done">' + head + '<span class="state">✓ Ready</span><a href="' +
        esc(j.page) + '">Open the lecture →</a></div></li>';
    var current = j.steps.filter(function (s) { return s.state === "running"; })[0];
    var detail = j.state === "queued" ? "Queued: waiting for the one before to finish" :
      j.state === "error" ? "Stopped" : "Running · " + Math.round(j.fraction * 100) + "%";
    return '<li class="job state-' + j.state + (current && current.id === "report" ? " awaiting-report" : "") +
      '">' + head + '<span class="state">' + detail + "</span>" + actions(j.lecture, j.state === "error") +
      '</div><div class="bar"><i style="width:' + Math.round(j.fraction * 100) + '%"></i></div>' +
      '<ol class="steps">' + j.steps.map(step).join("") + "</ol>" +
      (j.error ? '<p class="error-message">' + esc(j.error) + "</p>" : "") + "</li>";
  }
  function step(s) {
    var note = s.note;
    if (s.state === "running") {
      var amount = s.id === "report" ? "The model is writing the notes" :
        s.fraction > 0 ? Math.round(s.fraction * 100) + "%" : "";
      note = [amount, s.seconds !== null ? duration(s.seconds) : ""].filter(Boolean).join(" · ");
    } else if (s.state === "done" && s.seconds !== null) {
      note = [note, duration(s.seconds)].filter(Boolean).join(" · ");
    }
    return '<li class="step-' + s.state + '"><span class="mark"></span><span>' + esc(s.name) +
      '</span><span class="note">' + esc(note) + "</span></li>";
  }
  // Resume puts a lecture stopped by an error back in the queue.
  if (panel) {
    panel.addEventListener("click", function (e) {
      var button = e.target.closest(".resume"), jobsError = $(".error-message", panel);
      if (!button) return;
      button.disabled = true;
      jobsError.textContent = "";
      request("POST", api(button.dataset.course, button.dataset.lecture) + "/resume")
        .then(refresh, function (err) { button.disabled = false; jobsError.textContent = err.message; });
    });
    refresh();
  }

  // In the course: a new lecture. You pick (or drop) the lecture file — a video or an audio,
  // only one: the last picked replaces the other — and the PDFs; "Process" uploads them one at
  // a time, then hands the lecture to the queue.
  if (!upload) return;
  var VIDEO = upload.dataset.video, AUDIO = upload.dataset.audio, PDF = upload.dataset.pdf;
  var picker = $("input[type=file]", upload), zone = $(".dropzone", upload), chosenList = $(".chosen", upload);
  var uploadError = $(".error-message", upload), processButton = $(".process", upload);
  var uploadStatus = $(".upload-status", upload), language = $(".language select", upload);
  // The language picked last time, if it is still one of the choices: most uploads are in the same one.
  var lastLanguage = Saved.get("language", "");
  if (Array.prototype.some.call(language.options, function (o) { return o.value === lastLanguage; })) language.value = lastLanguage;
  language.addEventListener("change", function () { Saved.set("language", language.value); });
  var stopButton = $(".stop", upload), sending = null, stopped = false;     // the file being sent; Cancel pressed
  function extension(name) { return name.slice(name.lastIndexOf(".")).toLowerCase(); }
  function lectureFile() { return chosen.filter(function (f) { return extension(f.name) !== PDF; })[0]; }
  function slides() { return chosen.filter(function (f) { return extension(f.name) === PDF; }); }
  function add(files) {
    if (editing) { uploadError.textContent = "Wait for the change to finish: then the page reloads."; return; }
    uploadError.textContent = "";
    Array.prototype.forEach.call(files, function (f) {
      var ext = extension(f.name);
      if (ext !== VIDEO && ext !== AUDIO && ext !== PDF) {
        uploadError.textContent = "“" + f.name + "” is not supported: use the " + VIDEO + " video or the " + AUDIO +
          " audio, and the " + PDF + " slides.";
        return;
      }
      chosen = chosen.filter(function (g) {
        return g.name !== f.name && !(ext !== PDF && extension(g.name) !== PDF);
      });
      chosen.push(f);
    });
    showChosen();
  }
  function showChosen() {
    var sorted = (lectureFile() ? [lectureFile()] : []).concat(slides());
    chosenList.innerHTML = sorted.map(function (f) {
      var ext = extension(f.name), kind = ext === VIDEO ? "video" : ext === AUDIO ? "audio" : "slides";
      return '<li><span class="file-kind ' + kind + '">' + kind + "</span><span>" + esc(f.name) +
        '</span><span class="size">' + megabytes(f.size) + '</span><button type="button" data-name="' + esc(f.name) +
        '" aria-label="Remove ' + esc(f.name) + '">×</button></li>';
    }).join("");
  }
  chosenList.addEventListener("click", function (e) {
    var button = e.target.closest("button");
    if (!button || busy) return;
    chosen = chosen.filter(function (f) { return f.name !== button.dataset.name; });
    showChosen();
    reloadIfPossible();
  });
  picker.addEventListener("change", function () { add(picker.files); picker.value = ""; });
  // A file dropped anywhere on the page joins the picked ones (while uploading, it is ignored):
  // without this, Chrome would open the file in the tab, and the choice or the upload in
  // progress would be lost. The zone lights up while a file is dragged over it.
  ["dragover", "drop"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types, "Files") < 0) return;
      e.preventDefault();
      if (type === "drop" && !busy) add(e.dataTransfer.files);
    });
  });
  zone.addEventListener("dragover", function () { zone.classList.add("dragging"); });
  ["dragleave", "drop"].forEach(function (type) {
    zone.addEventListener(type, function () { zone.classList.remove("dragging"); });
  });

  // Cancel, while uploading: stops the file in flight; the chain below notices at the next
  // step, and has the server remove what had already arrived.
  stopButton.addEventListener("click", function () {
    stopped = true;
    stopButton.hidden = true;
    if (sending) sending.abort();
  });
  function unlessStopped() { if (stopped) throw new Error("cancelled"); }
  function send(uploadId, file, doneBytes, total) {
    return new Promise(function (resolve, reject) {
      var x = sending = new XMLHttpRequest();
      x.onabort = function () { reject(new Error("cancelled")); };
      x.open("PUT", "/api/uploads/" + uploadId + "/" + encodeURIComponent(file.name));
      Object.keys(HEADERS).forEach(function (k) { x.setRequestHeader(k, HEADERS[k]); });
      x.upload.onprogress = function (e) {
        uploadStatus.textContent = "Uploading " + Math.round((doneBytes + e.loaded) / total * 100) + "% · " +
          megabytes(doneBytes + e.loaded) + " of " + megabytes(total);
      };
      x.onload = function () {
        if (x.status < 300) { resolve(); return; }
        var body = null;
        try { body = JSON.parse(x.responseText); } catch (err) { }
        reject(errorFrom(x.status, body));
      };
      x.onerror = function () { reject(new Error("Upload interrupted: is PoliTo Recap still running?")); };
      x.send(file);
    });
  }
  processButton.addEventListener("click", function () {
    if (busy) return;
    var file = lectureFile(), pdfs = slides();
    if (!file || !pdfs.length) {
      uploadError.textContent = !file && !pdfs.length ? "The lecture (" + VIDEO + " or " + AUDIO + ") and the slides (" + PDF + ") are missing." :
        !file ? "The lecture is missing: " + VIDEO + " video or " + AUDIO + " audio." : "The slides are missing (" + PDF + ").";
      return;
    }
    busy = true;
    stopped = false;
    upload.classList.add("busy");
    picker.disabled = language.disabled = true;
    stopButton.hidden = false;
    uploadError.textContent = "";
    var all = [file].concat(pdfs), total = all.reduce(function (s, f) { return s + f.size; }, 0), uploadId;
    var target = { course: upload.dataset.course, lecture: file.name, slides: pdfs.map(function (f) { return f.name; }),
                   language: language.value };
    // The server checks where the lecture goes before a single byte is sent (and again at the end).
    request("POST", "/api/uploads", target)
      .then(function (r) {
        uploadId = r.id;
        return all.reduce(function (chain, f, i) {
          var before = all.slice(0, i).reduce(function (s, g) { return s + g.size; }, 0);
          return chain.then(function () { unlessStopped(); return send(uploadId, f, before, total); });
        }, Promise.resolve());
      })
      .then(function () {
        unlessStopped();
        stopButton.hidden = true;               // from here on the lecture is cancelled from its card
        uploadStatus.textContent = "Uploaded: the lecture is joining the queue…";
        var delivery = Object.assign({ upload: uploadId }, target);
        uploadId = null;                        // the delivery consumes the upload, however it goes
        return request("POST", "/api/lectures", delivery);
      })
      .then(function () { chosen = []; showChosen(); uploadStatus.textContent = ""; refresh(); })
      .catch(function (err) {
        // Stopped or failed before the delivery: what had arrived is removed from the server.
        if (stopped) {
          chosen = [];
          showChosen();
          uploadStatus.textContent = "Upload cancelled.";
        } else {
          uploadError.textContent = err.message;
          uploadStatus.textContent = "";
        }
        if (uploadId) return request("DELETE", "/api/uploads/" + uploadId).catch(function (e) { uploadError.textContent = e.message; });
      })
      .then(function () {
        busy = false;
        sending = null;
        stopButton.hidden = true;
        picker.disabled = language.disabled = false;
        upload.classList.remove("busy");
        reloadIfPossible();
      });
  });
})();
