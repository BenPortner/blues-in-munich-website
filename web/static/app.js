// Type filter chips and the List / Calendar switch. The page works without JS as a plain list.
// URL hash keeps the state: "#concert", "#calendar", "#calendar/concert". "highlight" is a filter too:
// concerts in big venues.
(function () {
  var chips = document.querySelectorAll(".chip[data-filter]");
  if (!chips.length) return;
  var empty = document.querySelector("main .empty");
  var listView = document.getElementById("list-view");
  var calView = document.getElementById("calendar-view");
  var viewButtons = document.querySelectorAll(".chip[data-view]");
  var state = { view: "list", type: "all" };

  var FC_SRC = "https://cdn.jsdelivr.net/npm/fullcalendar@6.1.22/index.global.min.js";
  var FC_SRI = "sha384-a9qx08ufzJ+0qbHzdqA+GYiSayQQB5BK2YGS/HQT9cxhQm+GhiXFj1ByVXa93ZRR";
  var calendar = null;
  var calendarLoading = false;

  function readHash() {
    var parts = location.hash.slice(1).split("/");
    if (parts[0] === "calendar") { state.view = "calendar"; parts.shift(); }
    var type = parts[0] || "all";
    state.type = document.querySelector('.chip[data-filter="' + type + '"]') ? type : "all";
  }

  function writeHash() {
    var parts = [];
    if (state.view === "calendar") parts.push("calendar");
    if (state.type !== "all") parts.push(state.type);
    history.replaceState(null, "", parts.length ? "#" + parts.join("/") : location.pathname);
  }

  function shown(type, highlight) {
    if (state.type === "highlight") return highlight;
    return state.type === "all" || type === state.type;
  }

  function applyList() {
    document.querySelectorAll(".card").forEach(function (card) {
      card.hidden = !shown(card.dataset.type, "highlight" in card.dataset);
    });
    // Hide days and months that have nothing left to show
    document.querySelectorAll(".day").forEach(function (day) {
      day.hidden = !day.querySelector(".card:not([hidden])");
    });
    var anyVisible = false;
    document.querySelectorAll(".month").forEach(function (month) {
      month.hidden = !month.querySelector(".day:not([hidden])");
      anyVisible = anyVisible || !month.hidden;
    });
    return anyVisible;
  }

  function apply() {
    chips.forEach(function (chip) {
      chip.setAttribute("aria-pressed", String(chip.dataset.filter === state.type));
    });
    viewButtons.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.view === state.view));
    });
    var anyVisible = applyList();
    var onCalendar = state.view === "calendar";
    listView.hidden = onCalendar;
    calView.hidden = !onCalendar;
    if (empty) empty.hidden = onCalendar || anyVisible;
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
          return shown(e.extendedProps.type, !!e.extendedProps.highlight);
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
      writeHash();
      apply();
    });
  });
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
