(function () {
  var ranked = document.getElementById("ranked");
  if (!ranked) return;
  var unranked = document.getElementById("unranked");
  var brand = document.getElementById("brand");
  var shelf = document.getElementById("shelf");
  var size = document.getElementById("size");
  var stock = document.getElementById("stock");
  var query = document.getElementById("q");
  var sort = document.getElementById("sort");
  var count = document.getElementById("count");

  function rows(table) {
    return Array.prototype.slice.call(table.querySelectorAll("tbody tr"));
  }

  function matches(row) {
    if (brand.value && row.getAttribute("data-brand") !== brand.value) return false;
    if (stock.value && row.getAttribute("data-stock") !== stock.value) return false;
    var years = Number(row.getAttribute("data-shelf"));
    if (shelf.value === "unknown") {
      if (years >= 0) return false;
    } else if (shelf.value) {
      if (!(years >= Number(shelf.value))) return false;
    }
    var daysRaw = row.getAttribute("data-days");
    var days = daysRaw === "" || daysRaw === null ? null : Number(daysRaw);
    if (size.value === "small" && !(days !== null && days < 14)) return false;
    if (size.value === "medium" && !(days !== null && days >= 14 && days < 60)) return false;
    if (size.value === "large" && !(days !== null && days >= 60 && days < 180)) return false;
    if (size.value === "xlarge" && !(days !== null && days >= 180)) return false;
    var needle = query.value.trim().toLowerCase();
    if (needle) {
      var hay = (row.getAttribute("data-name") || "").toLowerCase();
      if (hay.indexOf(needle) === -1) return false;
    }
    return true;
  }

  function numberValue(row, key) {
    var value = Number(row.getAttribute(key));
    return isNaN(value) ? null : value;
  }

  function apply() {
    var shownRanked = 0;
    var shownOther = 0;
    rows(ranked).forEach(function (row) {
      var ok = matches(row);
      row.hidden = !ok;
      if (ok) shownRanked += 1;
    });
    if (unranked) {
      rows(unranked).forEach(function (row) {
        var ok = matches(row);
        row.hidden = !ok;
        if (ok) shownOther += 1;
      });
    }
    var key = sort.value || "data-ppk";
    var body = ranked.querySelector("tbody");
    var ordered = rows(ranked).slice().sort(function (a, b) {
      var av = numberValue(a, key);
      var bv = numberValue(b, key);
      if (key === "data-shelf") {
        if (av !== null && av < 0) av = null;
        if (bv !== null && bv < 0) bv = null;
      }
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (av === bv) return 0;
      return av < bv ? -1 : 1;
    });
    ordered.forEach(function (row) {
      body.appendChild(row);
    });
    var rank = 1;
    rows(ranked).forEach(function (row) {
      var cell = row.querySelector(".rank");
      if (!cell) return;
      cell.textContent = row.hidden ? "" : String(rank++);
    });
    if (count) {
      count.textContent =
        "Showing " +
        shownRanked +
        " ranked kit" +
        (shownRanked === 1 ? "" : "s") +
        (unranked ? " and " + shownOther + " unverified kit" + (shownOther === 1 ? "" : "s") + "." : ".");
    }
  }

  [brand, shelf, size, stock, query, sort].forEach(function (el) {
    if (!el) return;
    el.addEventListener("input", apply);
    el.addEventListener("change", apply);
  });
  apply();
})();
