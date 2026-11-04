// Fixture "analytics tag": sets a cookie, a storage item and sends a pixel,
// unless the visitor has rejected (an honest site).
if (localStorage.getItem("cmp_state") !== "rejected") {
  document.cookie = "_fx_id=abc123; path=/";
  localStorage.setItem("fx_state", "1");
  fetch("/pixel.gif?uid=secret123&page=home");
}
