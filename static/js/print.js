// The "Print" link of an invoice. No inline script: content security policy.
document.addEventListener("click", function (event) {
  if (event.target.closest("[data-print]")) {
    event.preventDefault();
    window.print();
  }
});
