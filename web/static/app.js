// Android has no webcal:// handler, so the subscribe button sends it to Google Calendar's "add by URL" page.
(function () {
  var subscribe = document.getElementById("subscribe");
  if (subscribe && /Android/i.test(navigator.userAgent)) subscribe.href = subscribe.getAttribute("data-android-href");
})();

// Type filter chips and the List / Calendar switch. The page works without JS as a plain list.
// URL hash keeps the state: "#concert", "#calendar", "#calendar/concert", "#concert/region". "highlight"
// is a filter too (see highlights.yaml). Events outside Munich (data-regional) are left out everywhere
// until the place menu is set to "Munich and region" ("region" at the end of the hash).
// "#source/<id>" (the event counts in the Sources footer) lists one source's events, whatever the type or place.
(function () {
  var chips = document.querySelectorAll(".chip[data-filter]");
  if (!chips.length) return;
  var empty = document.querySelector("main .empty");
  var past = document.getElementById("past");
  var spotlight = document.getElementById("spotlight");
  var listView = document.getElementById("list-view");
  var calView = document.getElementById("calendar-view");
  var viewButtons = document.querySelectorAll("[data-view]");
  var areas = document.querySelector(".place");
  var placeButton = areas && areas.querySelector(".place-button");
  var placeMenu = areas && areas.querySelector(".place-menu");
  var areaButtons = document.querySelectorAll("[data-area]");
  var sourceChip = document.querySelector(".source-chip");
  var emptyText = empty && empty.textContent;
  var state = { view: "list", type: "all", region: false, source: null };

  var FC_SRC = "https://cdn.jsdelivr.net/npm/fullcalendar@6.1.22/index.global.min.js";
  var FC_SRI = "sha384-a9qx08ufzJ+0qbHzdqA+GYiSayQQB5BK2YGS/HQT9cxhQm+GhiXFj1ByVXa93ZRR";
  var calendar = null;
  var calendarLoading = false;

  function readHash() {
    var parts = location.hash.slice(1).split("/");
    state.view = "list";
    if (parts[0] === "calendar") { state.view = "calendar"; parts.shift(); }
    state.source = null;
    if (parts[0] === "source" && sourceLink(parts[1])) { state.source = parts[1]; parts.splice(0, 2); }
    state.region = !!areas && parts[parts.length - 1] === "region";
    if (state.region) parts.pop();
    var type = parts[0] || "all";
    state.type = document.querySelector('.chip[data-filter="' + type + '"]') ? type : "all";
  }

  function writeHash() {
    var parts = [];
    if (state.view === "calendar") parts.push("calendar");
    if (state.source) parts.push("source", state.source);
    else if (state.type !== "all") parts.push(state.type);
    if (state.region) parts.push("region");
    history.replaceState(null, "", parts.length ? "#" + parts.join("/") : location.pathname);
  }

  function sourceLink(id) {
    return id && document.querySelector('[data-source-link="' + CSS.escape(id) + '"]');
  }

  function shown(type, highlight, regional, source) {
    if (state.source) return source === state.source;
    if (regional && areas && !state.region) return false;
    if (state.type === "highlight") return highlight;
    return state.type === "all" || type === state.type;
  }

  function applyList() {
    document.querySelectorAll(".card").forEach(function (card) {
      card.hidden = !shown(card.dataset.type, "highlight" in card.dataset, "regional" in card.dataset, card.dataset.source);
    });
    // Hide days and months that have nothing left to show
    document.querySelectorAll(".day").forEach(function (day) {
      day.hidden = !day.querySelector(".card:not([hidden])");
    });
    document.querySelectorAll(".month").forEach(function (month) {
      month.hidden = !month.querySelector(".day:not([hidden])");
    });
    if (past) past.hidden = !past.querySelector(".month:not([hidden])");
    // The highlights box is an overview: only above the full list
    if (spotlight) {
      spotlight.querySelectorAll("li").forEach(function (li) {
        li.hidden = "regional" in li.dataset && !!areas && !state.region;
      });
      spotlight.hidden = state.type !== "all" || !!state.source || !spotlight.querySelector("li:not([hidden])");
    }
    // Whether any upcoming event is left; the past section doesn't count
    return !!document.querySelector("#upcoming .month:not([hidden])");
  }

  function apply() {
    chips.forEach(function (chip) {
      chip.setAttribute("aria-pressed", String(!state.source && chip.dataset.filter === state.type));
    });
    sourceChip.hidden = !state.source;
    if (state.source) sourceChip.querySelector(".source-name").textContent = sourceLink(state.source).dataset.name;
    viewButtons.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.view === state.view));
    });
    if (areas) {
      areaButtons.forEach(function (b) {
        b.setAttribute("aria-checked", String((b.dataset.area === "region") === state.region));
      });
      areas.querySelector(".place-label").textContent = state.region ? "Munich and region" : "Munich";
      placeButton.classList.toggle("widened", state.region);  // also shows on phones, where the label is hidden
      // data-counts: "without with" the events outside Munich
      chips.forEach(function (chip) {
        chip.querySelector("span").textContent = chip.dataset.counts.split(" ")[state.region ? 1 : 0];
      });
    }
    var anyVisible = applyList();
    var onCalendar = state.view === "calendar";
    listView.hidden = onCalendar;
    calView.hidden = !onCalendar;
    if (empty) {
      empty.hidden = onCalendar || anyVisible;
      empty.textContent = state.source ? "No upcoming events from this source — see past events below." : emptyText;
    }
    if (onCalendar) showCalendar();
  }

  // --- calendar -----------------------------------------------------------
  function loadFullCalendar() {
    return new Promise(function (resolve, reject) {
      if (window.FullCalendar) return resolve();
      var s = document.createElement("script");
      s.src = FC_SRC;
      s.integrity = FC_SRI;
      s.crossOrigin = "anonymous";
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function typeColor(type) {
    var css = getComputedStyle(document.documentElement);
    return css.getPropertyValue("--t-" + type).trim() || css.getPropertyValue("--accent").trim();
  }

  function showCalendar() {
    if (calendar) {
      calendar.refetchEvents();
      calendar.updateSize();
      return;
    }
    if (calendarLoading) return;
    calendarLoading = true;
    calView.textContent = "Loading calendar…";
    loadFullCalendar().then(createCalendar, function () {
      calendarLoading = false;
      calView.textContent = "The calendar couldn't be loaded. Check your connection, or use the list view.";
    });
  }

  function createCalendar() {
    var all = JSON.parse(document.getElementById("calendar-data").textContent);
    var narrow = window.matchMedia("(max-width: 600px)").matches;
    var weekView = narrow ? "listWeek" : "timeGridWeek";
    var time24 = { hour: "2-digit", minute: "2-digit", hour12: false };
    // Week grid starts an hour before the earliest event (most are evenings)
    var firstHour = all.reduce(function (h, e) {
      return e.allDay ? h : Math.min(h, parseInt(e.start.slice(11, 13), 10));
    }, 18);
    firstHour = Math.max(0, firstHour - 1);
    calView.textContent = "";
    calendar = new FullCalendar.Calendar(calView, {
      // Event times are naive Munich wall-clock; rendering in UTC shows them exactly as written.
      timeZone: "UTC",
      now: function () {
        var d = new Date();
        return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()));
      },
      initialView: "dayGridMonth",
      firstDay: 1,
      height: "auto",
      headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth," + weekView + ",year" },
      views: {
        dayGridMonth: { buttonText: "Month" },
        timeGridWeek: {
          buttonText: "Week",
          dayHeaderFormat: { weekday: "short", day: "numeric", month: "short", omitCommas: true },
        },
        listWeek: { buttonText: "Week" },
        // The next 12 months from the current one, rather than a calendar year that is mostly past
        year: { type: "multiMonth", duration: { months: 12 }, buttonText: "Year", dayMaxEvents: false },
      },
      buttonText: { today: "Today" },
      eventTimeFormat: time24,
      slotLabelFormat: time24,
      slotMinTime: (firstHour < 10 ? "0" : "") + firstHour + ":00:00",
      slotDuration: "01:00:00",
      scrollTime: "17:00:00",
      dayMaxEvents: 4,
      navLinks: true,
      navLinkDayClick: function (date) { calendar.changeView(weekView, date); },
      events: function (info, success) {
        success(all.filter(function (e) {
          return shown(e.extendedProps.type, !!e.extendedProps.highlight, !!e.extendedProps.regional, e.extendedProps.source);
        }).map(function (e) {
          var color = typeColor(e.extendedProps.type);
          return Object.assign({}, e, { backgroundColor: color, borderColor: color });
        }));
      },
      eventDidMount: function (info) {
        var p = info.event.extendedProps;
        info.el.title = [p.time, info.event.title, p.venue, p.label].filter(Boolean).join(" · ");
      },
      eventClick: function (info) {
        if (!info.event.url) return;
        info.jsEvent.preventDefault();
        window.open(info.event.url, "_blank", "noopener");
      },
    });
    calendar.render();
    // Re-read the type colours when the system switches between light and dark
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      calendar.refetchEvents();
    });
  }

  // --- wiring ---------------------------------------------------------------
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      state.type = chip.dataset.filter;
      state.source = null;
      writeHash();
      apply();
    });
  });
  sourceChip.addEventListener("click", function () {
    state.source = null;
    writeHash();
    apply();
  });
  document.querySelectorAll("[data-source-link]").forEach(function (link) {
    link.addEventListener("click", function (e) {
      e.preventDefault();
      state.source = link.dataset.sourceLink;
      state.type = "all";
      writeHash();
      apply();
      document.querySelector("main").scrollIntoView({ behavior: "smooth" });
    });
  });
  // Typed or pasted hashes, and back/forward
  window.addEventListener("hashchange", function () { readHash(); apply(); });
  // --- place menu -----------------------------------------------------------
  function openMenu(open) {
    placeMenu.hidden = !open;
    placeButton.setAttribute("aria-expanded", String(open));
    if (open) (placeMenu.querySelector('[aria-checked="true"]') || areaButtons[0]).focus();
  }
  if (areas) {
    areas.hidden = false;
    placeButton.addEventListener("click", function () { openMenu(placeMenu.hidden); });
    areaButtons.forEach(function (b) {
      b.addEventListener("click", function () {
        state.region = b.dataset.area === "region";
        openMenu(false);
        placeButton.focus();
        writeHash();
        apply();
      });
    });
    placeMenu.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        var i = Array.prototype.indexOf.call(areaButtons, document.activeElement);
        areaButtons[(i + (e.key === "ArrowDown" ? 1 : areaButtons.length - 1)) % areaButtons.length].focus();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !placeMenu.hidden) { openMenu(false); placeButton.focus(); }
    });
    document.addEventListener("click", function (e) {
      if (!placeMenu.hidden && !areas.contains(e.target)) openMenu(false);
    });
  }
  viewButtons.forEach(function (b) {
    b.addEventListener("click", function () {
      state.view = b.dataset.view;
      writeHash();
      apply();
    });
  });
  if (calView) document.querySelector(".views").hidden = false;
  readHash();
  apply();
})();
