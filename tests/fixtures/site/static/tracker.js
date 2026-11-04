document.cookie = "_fx_id=abc123; path=/";
localStorage.setItem("fx_state", "1");
fetch("/pixel.gif?uid=secret123&page=home");
