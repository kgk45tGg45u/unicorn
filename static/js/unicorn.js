if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  });
}

// Forms that were rendered by a library get Bootstrap's classes here (no inline script: content security policy).
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("form[data-bootstrap-fields] input:not([type=checkbox])").forEach(function (i) {
    i.classList.add("form-control");
  });
  document.querySelectorAll("form[data-bootstrap-fields] input[type=checkbox]").forEach(function (i) {
    i.classList.add("form-check-input");
  });
});
