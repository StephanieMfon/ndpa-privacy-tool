// Fixture consent banner. Configured with data- attributes on its own <script> tag:
//   layout: bottom | topbar | modal      buttons: accept,reject,manage,close (first layer)
//   panel: yes (Manage opens a panel with Reject all)   shadow: yes (open shadow DOM)
//   fake: yes (Reject is recorded but a cookie is still set 300 ms later)   reopen: no (no footer link)
(() => {
  const cfg = document.currentScript.dataset;
  const record = (choice) => {
    localStorage.setItem("cmp_state", choice);
    document.cookie = "cmp_consent=" + choice + "; max-age=31536000; path=/";
  };
  if (cfg.reopen !== "no") {
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = "Cookie settings";
    document.body.appendChild(link);
  }
  if (localStorage.getItem("cmp_state")) return;

  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = cfg.shadow === "yes" ? host.attachShadow({ mode: "open" }) : host;
  const place = {
    bottom: "left:0;right:0;bottom:0;",
    topbar: "left:0;right:0;top:0;",
    modal: "left:50%;top:50%;transform:translate(-50%,-50%);width:600px;height:400px;",
  }[cfg.layout];
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;z-index:9999;background:#222;color:#fff;padding:16px;" + place;
  if (cfg.layout === "modal") {
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9998;";
    overlay.appendChild(box);
    root.appendChild(overlay);
  } else {
    root.appendChild(box);
  }

  const done = (choice) => {
    if (choice === "accepted" || choice === "rejected") record(choice);
    if (choice === "accepted") document.cookie = "_fx_after=1; path=/";
    if (choice === "rejected" && cfg.fake === "yes") {
      setTimeout(() => { document.cookie = "_late_id=9; path=/"; }, 300);
    }
    host.remove();
  };
  const button = (label, onclick, aria) => {
    const b = document.createElement("button");
    b.textContent = label;
    if (aria) b.setAttribute("aria-label", aria);
    b.style.cssText = "padding:8px 16px;margin:4px;";
    b.addEventListener("click", onclick);
    return b;
  };
  const firstLayer = () => {
    box.innerHTML = "<p>We use cookies to improve your experience.</p>";
    const row = cfg.wrap === "yes" ? box.appendChild(document.createElement("div")) : box;
    const wanted = (cfg.buttons || "").split(",");
    if (wanted.includes("accept")) row.appendChild(button(cfg.accept || "Accept all", () => done("accepted")));
    if (wanted.includes("reject")) row.appendChild(button("Reject all", () => done("rejected")));
    if (wanted.includes("manage")) row.appendChild(button("Manage preferences", panel));
    if (wanted.includes("close")) row.appendChild(button("\u00d7", () => done("closed"), "Close"));
  };
  const panel = () => {
    box.innerHTML = "<p>Cookie preferences. Choose which cookies we may use.</p>"
      + "<label><input type='checkbox'> Analytics</label> <label><input type='checkbox'> Advertising</label><br>";
    box.appendChild(button("Reject all", () => done("rejected")));
    box.appendChild(button("Accept all", () => done("accepted")));
  };
  firstLayer();
})();
