// Üst bardaki sağlık rozetini /health'ten periyodik günceller.
// Tamamen lokal (aynı host) — internet gerektirmez.
(function () {
  const badge = document.getElementById("health-badge");
  if (!badge) return;

  const CLS = {
    ok: "badge badge-success",
    degraded: "badge badge-pending",
    down: "badge badge-failed",
  };

  async function poll() {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      const data = await r.json();
      const status = data.status || "down";
      badge.className = CLS[status] || "badge badge-pending";
      badge.title =
        "Durum: " + status +
        " · Kamera: " + data.cameras_ok + "/" + data.cameras_total +
        " · Bekleyen Shopify: " + ((data.shopify && data.shopify.failed_total) || 0);
    } catch (e) {
      badge.className = "badge badge-failed";
      badge.title = "Sağlık bilgisi alınamadı";
    }
  }

  poll();
  setInterval(poll, 10000);
})();
