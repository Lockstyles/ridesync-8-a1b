const state = {
    page: "browse",
    actorId: 1,
    actor: null,
    entity: "riders",
    browsePage: 1,
    map: null,
    mapLayers: [],
    mapTimer: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const money = (value) => new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR", maximumFractionDigits: 2,
}).format(Number(value || 0));

const number = (value, digits = 0) => new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: digits,
}).format(Number(value || 0));

const dateTime = (value) => value
    ? new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
    : "—";

const shortDate = (value) => value
    ? new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short" }).format(new Date(value))
    : "—";

function statusBadge(status) {
    const css = String(status).toLowerCase().replaceAll(" ", "-");
    return `<span class="badge ${escapeHtml(css)}">${escapeHtml(status)}</span>`;
}

function loading(label = "Loading data…") {
    return `<div class="loading-state">${escapeHtml(label)}</div>`;
}

function empty(title, hint = "Try another filter or check back later.") {
    return `<div class="empty-state"><b>${escapeHtml(title)}</b><span>${escapeHtml(hint)}</span></div>`;
}

function errorState(message) {
    return `<div class="error-state"><b>Something went wrong</b><span>${escapeHtml(message)}</span></div>`;
}

async function api(path, options = {}) {
    const request = {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    };
    const response = await fetch(path, request);
    let body;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok) {
        const detail = body?.detail;
        const message = typeof detail === "string" ? detail : detail?.message || `Request failed (${response.status}).`;
        const err = new Error(message);
        err.status = response.status;
        throw err;
    }
    return body;
}

function toast(message, kind = "success") {
    const item = document.createElement("div");
    item.className = `toast ${kind === "error" ? "error" : ""}`;
    item.textContent = message;
    $("#toastStack").append(item);
    setTimeout(() => item.remove(), 3800);
}

function setButtonBusy(button, busy, label = "Working…") {
    if (!button) return;
    if (busy) {
        button.dataset.original = button.innerHTML;
        button.disabled = true;
        button.textContent = label;
    } else {
        button.disabled = false;
        if (button.dataset.original) button.innerHTML = button.dataset.original;
    }
}

function navigate(page) {
    state.page = page;
    document.body.dataset.page = page;
    $$(".page").forEach((section) => section.classList.toggle("active", section.id === `page-${page}`));
    $$(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.page === page));
    $("#sidebar").classList.remove("open");
    window.location.hash = page;
    document.title = `${$("#page-" + page)?.dataset.title || "RideSync"} — RideSync`;
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (page === "browse") loadBrowse();
    if (page === "booking") { loadActor(); loadVehicleOptions(); }
    if (page === "audit") loadAudit();
    if (page === "analytics") loadAnalytics();
    if (page === "map") setTimeout(() => { initMap(); loadMap(); }, 50);
    if (page === "reviews") { loadReviews(); loadCatalog(); }
}

async function checkHealth() {
    const status = $("#systemStatus");
    const dot = $("#systemDot");
    status.textContent = "Checking services…";
    dot.className = "status-dot";
    try {
        const data = await api("/api/health");
        const available = [data.postgres && "PostgreSQL", data.mongo && "MongoDB"].filter(Boolean);
        status.textContent = data.status === "ok" ? "PostgreSQL and MongoDB are online." : `${available.join(" and ") || "No data services"} online.`;
        dot.classList.add(data.status === "ok" ? "ok" : "bad");
    } catch (err) {
        status.textContent = err.message;
        dot.classList.add("bad");
    }
}

async function setActor(id, quiet = false) {
    const parsed = Number(id);
    if (!Number.isInteger(parsed) || parsed < 1) {
        if (!quiet) toast("Enter a valid rider ID.", "error");
        return;
    }
    state.actorId = parsed;
    $("#actorInput").value = parsed;
    $("#bookingRider").value = parsed;
    $("#catalogVehicle").value ||= 1;
    await loadActor(quiet);
    if (state.page === "audit") loadAudit();
}

async function loadActor(quiet = false) {
    const name = $("#actorName");
    name.textContent = "Loading rider…";
    try {
        state.actor = await api(`/api/riders/${state.actorId}`);
        name.textContent = state.actor.name;
        $("#walletRider").textContent = `${state.actor.name} · #${state.actor.id}`;
        $("#walletBalance").textContent = money(state.actor.wallet_balance);
        $("#auditActor").textContent = `${state.actor.name} · #${state.actor.id}`;
        renderActiveTrip();
    } catch (err) {
        state.actor = null;
        name.textContent = `Rider #${state.actorId} unavailable`;
        $("#walletRider").textContent = `Rider #${state.actorId}`;
        $("#walletBalance").textContent = "₹—";
        $("#activeTrip").innerHTML = errorState(err.message);
        if (!quiet) toast(err.message, "error");
    }
}

function renderActiveTrip() {
    const host = $("#activeTrip");
    const trip = state.actor?.recent_trips?.find((item) => item.status !== "COMPLETED");
    if (!trip) {
        host.innerHTML = empty("No active trip", "This rider is ready to make a booking.");
        return;
    }
    const nextButton = trip.status === "REQUESTED"
        ? `<button class="button secondary trip-status" data-id="${trip.id}" data-status="IN TRANSIT">Start trip</button>` : "";
    host.innerHTML = `<div class="trip-card">
    <div class="trip-card-top"><div><span class="mono">TRIP #${trip.id}</span><h3>${escapeHtml(trip.license_plate)}</h3></div>${statusBadge(trip.status)}</div>
    <div class="muted">${money(trip.fare_amount)} · ${dateTime(trip.created_at)}</div>
    <div class="trip-actions">${nextButton}<button class="button primary trip-status" data-id="${trip.id}" data-status="COMPLETED">Complete trip</button></div>
  </div>`;
    $$(".trip-status", host).forEach((button) => button.addEventListener("click", () => changeTripStatus(button)));
}

async function changeTripStatus(button) {
    setButtonBusy(button, true, "Updating…");
    try {
        await api(`/api/trips/${button.dataset.id}/status`, {
            method: "PATCH", body: JSON.stringify({ status: button.dataset.status }),
        });
        toast(`Trip moved to ${button.dataset.status}.`);
        await loadActor(true);
        if (state.entity === "trips") loadBrowse();
    } catch (err) {
        toast(err.message, "error");
    } finally { setButtonBusy(button, false); }
}

function browseUrl() {
    const params = new URLSearchParams({ page: state.browsePage, page_size: 15 });
    const search = $("#browseSearch").value.trim();
    if (search && state.entity !== "trips") params.set("search", search);
    if (state.entity === "trips" && $("#browseStatus").value) params.set("status", $("#browseStatus").value);
    if (state.entity === "trips" && /^\d+$/.test(search)) params.set("rider_id", search);
    return `/api/${state.entity}?${params}`;
}

async function loadBrowse() {
    const host = $("#browseContent");
    host.innerHTML = loading(`Loading ${state.entity}…`);
    $("#browseStatusWrap").classList.toggle("hidden", state.entity !== "trips");
    $("#browseSearch").placeholder = state.entity === "riders" ? "Rider name or ID" : state.entity === "vehicles" ? "Plate or vehicle ID" : "Rider ID";
    try {
        const data = await api(browseUrl());
        renderBrowseTable(data.items);
        renderPagination(data);
    } catch (err) {
        host.innerHTML = errorState(err.message);
        $("#browsePagination").innerHTML = "";
    }
}

function renderBrowseTable(items) {
    const host = $("#browseContent");
    if (!items.length) { host.innerHTML = empty(`No ${state.entity} found`); return; }
    const configs = {
        riders: {
            headers: ["Rider", "Name", "Wallet", "Trips", "Active", "Action"],
            row: (r) => `<tr data-id="${r.id}"><td class="mono">#${r.id}</td><td><b>${escapeHtml(r.name)}</b></td><td class="amount">${money(r.wallet_balance)}</td><td>${number(r.trip_count)}</td><td>${Number(r.active_trip_count) ? statusBadge("ACTIVE") : '<span class="muted">—</span>'}</td><td class="row-action"><button class="table-delete delete-row" data-entity="riders" data-id="${r.id}" type="button">Delete</button></td></tr>`,
        },
        vehicles: {
            headers: ["Vehicle", "License plate", "Class", "Availability", "Action"],
            row: (v) => `<tr data-id="${v.id}"><td class="mono">#${v.id}</td><td><b>${escapeHtml(v.license_plate)}</b></td><td>${escapeHtml(v.class)}</td><td>${v.is_active ? statusBadge("ACTIVE") : '<span class="badge">INACTIVE</span>'}</td><td class="row-action"><button class="table-delete delete-row" data-entity="vehicles" data-id="${v.id}" type="button">Delete</button></td></tr>`,
        },
        trips: {
            headers: ["Trip", "Rider", "Vehicle", "Fare", "Status", "Created"],
            row: (t) => `<tr data-id="${t.id}"><td class="mono">#${t.id}</td><td><b>${escapeHtml(t.rider_name)}</b><br><small class="muted">#${t.rider_id}</small></td><td>${escapeHtml(t.license_plate)}<br><small class="muted">#${t.vehicle_id}</small></td><td class="amount">${money(t.fare_amount)}</td><td>${statusBadge(t.status)}</td><td>${dateTime(t.created_at)}</td></tr>`,
        },
    };
    const config = configs[state.entity];
    host.innerHTML = `<table class="data-table"><thead><tr>${config.headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${items.map(config.row).join("")}</tbody></table>`;
    $$("tbody tr", host).forEach((row) => row.addEventListener("click", (event) => {
        if (event.target.closest(".delete-row")) return;
        openDetail(state.entity, row.dataset.id);
    }));
    $$(".delete-row", host).forEach((button) => button.addEventListener("click", (event) => {
        event.stopPropagation();
        deleteRecord(button.dataset.entity, button.dataset.id);
    }));
}

function renderPagination(data) {
    const host = $("#browsePagination");
    host.innerHTML = `<span>${number(data.total)} records · Page ${data.page} of ${Math.max(data.pages, 1)}</span><div><button data-page="${data.page - 1}" ${data.page <= 1 ? "disabled" : ""}>←</button><button data-page="${data.page + 1}" ${data.page >= data.pages ? "disabled" : ""}>→</button></div>`;
    $$('button:not([disabled])', host).forEach((button) => button.addEventListener("click", () => {
        state.browsePage = Number(button.dataset.page); loadBrowse();
    }));
}

async function openDetail(entity, id) {
    const drawer = $("#detailDrawer");
    const backdrop = $("#drawerBackdrop");
    drawer.classList.add("open"); backdrop.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
    $("#drawerContent").innerHTML = loading("Loading record…");
    try {
        const item = await api(`/api/${entity}/${id}`);
        $("#drawerContent").innerHTML = detailHtml(entity, item);
        bindDetailActions();
        const use = $("#useRider", drawer);
        if (use) use.addEventListener("click", async () => { await setActor(id); closeDrawer(); navigate("booking"); });
    } catch (err) { $("#drawerContent").innerHTML = errorState(err.message); }
}

function tripTimeline(trips = []) {
    if (!trips.length) return empty("No trips yet");
    return `<div class="timeline">${trips.map((t) => `<div class="timeline-row"><b>Trip #${t.id} · ${statusBadge(t.status)}</b><small>${dateTime(t.created_at)} · ${money(t.fare_amount)}</small></div>`).join("")}</div>`;
}

function detailHtml(entity, item) {
    if (entity === "riders") return `<div class="drawer-hero"><span class="eyebrow">Rider #${item.id}</span><h2>${escapeHtml(item.name)}</h2><p class="muted">Wallet and recent activity</p></div><div class="drawer-meta"><div><small>Wallet balance</small><strong>${money(item.wallet_balance)}</strong></div><div><small>Recent trips</small><strong>${number(item.recent_trips?.length)}</strong></div></div><button class="button primary wide" id="useRider">Use as demo rider <b>→</b></button><button class="button danger wide delete-record" data-entity="riders" data-id="${item.id}">Delete rider</button><div class="drawer-section"><h3>Trip timeline</h3>${tripTimeline(item.recent_trips)}</div>`;
    if (entity === "vehicles") {
        const features = item.metadata?.features || {};
        return `<div class="drawer-hero"><span class="eyebrow">Vehicle #${item.id}</span><h2>${escapeHtml(item.license_plate)}</h2>${statusBadge(item.is_active ? "ACTIVE" : "INACTIVE")}</div><div class="drawer-meta"><div><small>Class</small><strong>${escapeHtml(item.class)}</strong></div><div><small>Inspections</small><strong>${number(item.metadata?.inspections?.length)}</strong></div></div><button class="button danger wide delete-record" data-entity="vehicles" data-id="${item.id}">Delete vehicle</button><div class="drawer-section"><h3>Flexible features</h3><div class="chip-list">${Object.entries(features).map(([k, v]) => `<span class="chip">${escapeHtml(k.replaceAll("_", " "))}: ${escapeHtml(Array.isArray(v) ? v.join(", ") : v)}</span>`).join("") || '<span class="muted">No metadata available</span>'}</div></div><div class="drawer-section"><h3>Recent trips</h3>${tripTimeline(item.recent_trips)}</div>`;
    }
    return `<div class="drawer-hero"><span class="eyebrow">Trip #${item.id}</span><h2>${escapeHtml(item.rider_name)} → ${escapeHtml(item.license_plate)}</h2>${statusBadge(item.status)}</div><div class="drawer-meta"><div><small>Fare</small><strong>${money(item.fare_amount)}</strong></div><div><small>Created</small><strong>${shortDate(item.created_at)}</strong></div><div><small>Rider</small><strong>#${item.rider_id}</strong></div><div><small>Vehicle</small><strong>#${item.vehicle_id} · ${escapeHtml(item.vehicle_class)}</strong></div></div>`;
}

function closeDrawer() {
    $("#detailDrawer").classList.remove("open"); $("#drawerBackdrop").classList.remove("open");
    $("#detailDrawer").setAttribute("aria-hidden", "true");
}

async function loadVehicleOptions() {
    const select = $("#bookingVehicle");
    try {
        const data = await api("/api/vehicles?page_size=100&active_only=true");
        select.innerHTML = '<option value="">Choose a vehicle</option>' + data.items.map((v) => `<option value="${v.id}">#${v.id} · ${escapeHtml(v.license_plate)} · ${escapeHtml(v.class)}</option>`).join("");
    } catch (err) { select.innerHTML = `<option value="">${escapeHtml(err.message)}</option>`; }
}

async function submitBooking(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $('button[type="submit"]', form);
    const values = Object.fromEntries(new FormData(form));
    values.rider_id = Number(values.rider_id); values.vehicle_id = Number(values.vehicle_id); values.fare_amount = Number(values.fare_amount);
    setButtonBusy(button, true, "Booking atomically…");
    $("#bookingMessage").innerHTML = "";
    try {
        const result = await api("/api/bookings", { method: "POST", body: JSON.stringify(values) });
        $("#bookingMessage").innerHTML = `<div class="result-card"><h3>Trip #${result.trip.id} booked</h3><p>The wallet debit and trip were committed together. Audit log #${result.audit_entry.id} confirms the trigger fired.</p><div class="result-ledger"><div><small>Before</small>${money(result.balance_before)}</div><span>→</span><div><small>After</small>${money(result.balance_after)}</div></div></div>`;
        await setActor(values.rider_id, true);
        form.elements.fare_amount.value = "";
    } catch (err) {
        $("#bookingMessage").innerHTML = `<div class="result-card error"><h3>Booking not completed</h3><p>${escapeHtml(err.message)}</p></div>`;
    } finally { setButtonBusy(button, false); }
}

async function loadAudit() {
    const host = $("#auditContent");
    host.innerHTML = loading("Loading immutable ledger…");
    const params = new URLSearchParams();
    if ($("#auditFrom").value) params.set("date_from", $("#auditFrom").value);
    if ($("#auditTo").value) params.set("date_to", $("#auditTo").value);
    try {
        const data = await api(`/api/riders/${state.actorId}/audit?${params}`);
        $("#auditActor").textContent = `${data.rider.name} · #${data.rider.id}`;
        if (!data.entries.length) { host.innerHTML = empty("No ledger entries", "No wallet changes match this date range."); return; }
        host.innerHTML = `<table class="data-table"><thead><tr><th>Entry</th><th>Timestamp</th><th>Fare</th><th>Balance after</th></tr></thead><tbody>${data.entries.map((entry) => `<tr><td class="mono">#${entry.id}</td><td>${dateTime(entry.created_at)}</td><td class="amount ${Number(entry.amount_changed) >= 0 ? "positive" : "negative"}">${Number(entry.amount_changed) >= 0 ? "+" : ""}${money(entry.amount_changed)}</td><td class="amount"><b>${money(entry.balance_after)}</b></td></tr>`).join("")}</tbody></table>`;
    } catch (err) { host.innerHTML = errorState(err.message); }
}

async function loadAnalytics() {
    const chart = $("#revenueChart");
    const ranks = $("#rankingContent");
    chart.innerHTML = loading("Calculating window functions…"); ranks.innerHTML = loading();
    const params = new URLSearchParams({ days: $("#analyticsDays").value });
    if ($("#analyticsVehicle").value) params.set("vehicle_id", $("#analyticsVehicle").value);
    try {
        const [data, summary] = await Promise.all([api(`/api/analytics/revenue?${params}`), api("/api/analytics/summary?limit=10")]);
        renderAnalyticsMetrics(data, summary);
        renderRevenueChart(data.series);
        renderRankings(data.latest_rankings);
        renderSummary(summary);
    } catch (err) {
        chart.innerHTML = errorState(err.message); ranks.innerHTML = errorState(err.message);
        $("#analyticsMetrics").innerHTML = ""; $("#summaryContent").innerHTML = errorState(err.message);
    }
}

function renderAnalyticsMetrics(data, summary) {
    const latest = data.series.at(-1);
    const total = summary.vehicles.reduce((sum, row) => sum + Number(row.lifetime_earnings), 0);
    $("#analyticsMetrics").innerHTML = `<article class="metric-card"><span>Latest 7-day average</span><strong>${latest ? money(latest.moving_avg_7d) : "—"}</strong><small>${latest ? escapeHtml(latest.license_plate) : "No completed trips"}</small></article><article class="metric-card"><span>Points returned</span><strong>${number(data.series.length)}</strong><small>${data.days}-day query window</small></article><article class="metric-card"><span>Top 10 lifetime revenue</span><strong>${money(total)}</strong><small>Materialized summary</small></article>`;
}

function renderRevenueChart(series) {
    const host = $("#revenueChart");
    if (!series.length) { host.innerHTML = empty("No completed-trip revenue", "Choose another vehicle or period."); return; }
    let points = series;
    if (!$("#analyticsVehicle").value) {
        const counts = new Map();
        series.forEach((row) => counts.set(row.vehicle_id, (counts.get(row.vehicle_id) || 0) + 1));
        const selected = [...counts].sort((a, b) => b[1] - a[1])[0][0];
        points = series.filter((row) => row.vehicle_id === selected);
    }
    const width = 760, height = 290, left = 58, right = 18, top = 15, bottom = 35;
    const values = points.map((p) => Number(p.moving_avg_7d));
    const max = Math.max(...values, 1), min = Math.min(...values, 0);
    const x = (index) => left + (index / Math.max(points.length - 1, 1)) * (width - left - right);
    const y = (value) => top + (1 - (value - min) / Math.max(max - min, 1)) * (height - top - bottom);
    const coords = points.map((p, index) => `${x(index)},${y(Number(p.moving_avg_7d))}`);
    const area = `${left},${height - bottom} ${coords.join(" ")} ${x(points.length - 1)},${height - bottom}`;
    const grid = [0, .25, .5, .75, 1].map((ratio) => {
        const gy = top + ratio * (height - top - bottom); const label = max - ratio * (max - min);
        return `<line class="chart-grid" x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}"/><text class="chart-label" x="0" y="${gy + 3}">₹${number(label)}</text>`;
    }).join("");
    const labels = points.filter((_, i) => i === 0 || i === points.length - 1 || (points.length > 8 && i === Math.floor(points.length / 2))).map((p) => `<text class="chart-label" text-anchor="middle" x="${x(points.indexOf(p))}" y="${height - 8}">${shortDate(p.revenue_date)}</text>`).join("");
    const dots = points.map((p, i) => `<circle class="chart-point" cx="${x(i)}" cy="${y(Number(p.moving_avg_7d))}" r="4"><title>${shortDate(p.revenue_date)} · ${money(p.moving_avg_7d)}</title></circle>`).join("");
    host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Seven day revenue moving average"><defs><linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#cbf26a" stop-opacity=".55"/><stop offset="100%" stop-color="#cbf26a" stop-opacity=".03"/></linearGradient></defs>${grid}<polygon class="chart-area" points="${area}"/><polyline class="chart-line" points="${coords.join(" ")}"/>${dots}${labels}</svg>`;
}

function renderRankings(rows) {
    const host = $("#rankingContent");
    if (!rows.length) { host.innerHTML = empty("No rankings yet"); return; }
    host.innerHTML = `<div class="rank-list">${rows.slice(0, 10).map((row) => `<div class="rank-row"><span class="rank-number">${row.rank_vehicle_per_day}</span><div><b>${escapeHtml(row.license_plate)}</b><small>Vehicle #${row.vehicle_id} · ${shortDate(row.revenue_date)}</small></div><strong>${money(row.moving_avg_7d)}</strong></div>`).join("")}</div>`;
}

function renderSummary(data) {
    $("#refreshTime").textContent = `Last refreshed ${dateTime(data.last_refreshed)}`;
    const host = $("#summaryContent");
    if (!data.vehicles.length) { host.innerHTML = empty("No summary data"); return; }
    host.innerHTML = `<table class="data-table"><thead><tr><th>Vehicle</th><th>Class</th><th>Completed trips</th><th>Lifetime earnings</th></tr></thead><tbody>${data.vehicles.map((v) => `<tr data-id="${v.vehicle_id}"><td><b>${escapeHtml(v.license_plate)}</b><br><small class="muted">#${v.vehicle_id}</small></td><td>${escapeHtml(v.class)}</td><td>${number(v.lifetime_trip_count)}</td><td class="amount"><b>${money(v.lifetime_earnings)}</b></td></tr>`).join("")}</tbody></table>`;
}

async function refreshSummary() {
    const button = $("#refreshSummary"); setButtonBusy(button, true, "Refreshing view…");
    try { await api("/api/analytics/refresh", { method: "POST" }); toast("Lifetime earnings refreshed."); await loadAnalytics(); }
    catch (err) { toast(err.message, "error"); }
    finally { setButtonBusy(button, false); }
}

function initMap() {
    if (state.map || !window.L) {
        if (!window.L) $("#vehicleMap").innerHTML = errorState("The map library could not load. The sorted result list is still available.");
        return;
    }
    state.map = L.map("vehicleMap", { zoomControl: true }).setView([17.4454, 78.3488], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(state.map);
}

function clearMapLayers() {
    if (!state.map) return;
    state.mapLayers.forEach((layer) => state.map.removeLayer(layer)); state.mapLayers = [];
}

async function loadMap() {
    const host = $("#mapResults"); host.innerHTML = loading("Reading live pings…");
    const lat = Number($("#mapLat").value), lon = Number($("#mapLon").value), radius = Number($("#mapRadius").value);
    try {
        const data = await api(`/api/map/nearby?lat=${lat}&lon=${lon}&radius_m=${radius}&limit=5000`);
        renderMap(data);
    } catch (err) { host.innerHTML = errorState(err.message); $("#mapStamp").textContent = "Telemetry unavailable"; }
}

function renderMap(data) {
    const host = $("#mapResults");
    $("#mapStamp").textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString("en-IN")} · ${(data.radius_m / 1000).toFixed(0)} km radius`;
    if (!data.vehicles.length) host.innerHTML = empty("No available vehicles", "Try a wider radius or another city.");
    else host.innerHTML = `<div class="map-result-summary"><b>${number(data.vehicles.length)}</b><span>vehicles within ${(data.radius_m / 1000).toFixed(0)} km · nearest first</span></div>` + data.vehicles.map((v, index) => `<button type="button" class="vehicle-result" data-vehicle-index="${index}"><span class="vehicle-pin">#${v.vehicle_id}</span><div><b>Vehicle ${v.vehicle_id}</b><small>${number(v.speed_kmph, 1)} km/h · Driver #${v.driver_id ?? "—"}</small></div><strong>${v.distance_m < 1000 ? `${number(v.distance_m)} m` : `${number(v.distance_m / 1000, 1)} km`}</strong></button>`).join("");
    if (!state.map) return;
    clearMapLayers();
    state.map.setView([data.origin.lat, data.origin.lon], data.radius_m > 6000 ? 12 : 13);
    state.mapLayers.push(L.circle([data.origin.lat, data.origin.lon], { radius: data.radius_m, color: "#476c31", weight: 1, fillColor: "#cbf26a", fillOpacity: .12 }).addTo(state.map));
    state.mapLayers.push(L.circleMarker([data.origin.lat, data.origin.lon], { radius: 7, color: "#fff", weight: 3, fillColor: "#ff765c", fillOpacity: 1 }).bindPopup("Search origin").addTo(state.map));
    const vehicleMarkers = [];
    data.vehicles.forEach((v) => {
        const [vehicleLon, vehicleLat] = v.location.coordinates;
        const icon = L.divIcon({ className: "vehicle-map-icon", html: `<span>${v.vehicle_id}</span>`, iconSize: [28, 28], iconAnchor: [14, 28] });
        const marker = L.marker([vehicleLat, vehicleLon], { icon }).bindPopup(`<b>Vehicle #${v.vehicle_id}</b><br>${number(v.distance_m)} m away`);
        vehicleMarkers.push(marker);
        state.mapLayers.push(marker.addTo(state.map));
    });
    $$(".vehicle-result", host).forEach((button) => {
        button.addEventListener("click", () => {
            const marker = vehicleMarkers[Number(button.dataset.vehicleIndex)];
            if (marker) { marker.openPopup(); state.map.panTo(marker.getLatLng()); }
        });
    });
}

async function loadReviews() {
    $("#ratingChart").innerHTML = loading(); $("#tagChart").innerHTML = loading();
    try {
        const params = new URLSearchParams({ city: $("#reviewCity").value, days: $("#reviewDays").value });
        const data = await api(`/api/reviews/analytics?${params}`);
        $("#reviewAverage").textContent = data.average_rating ?? "—";
        $("#reviewCount").textContent = `${number(data.total_reviews)} reviews · ${data.city} · ${data.days} days`;
        renderRatings(data.rating_distribution);
        renderTags(data.top_feedback_tags);
    } catch (err) {
        $("#reviewAverage").textContent = "—"; $("#reviewCount").textContent = err.message;
        $("#ratingChart").innerHTML = errorState(err.message); $("#tagChart").innerHTML = errorState(err.message);
    }
}

function renderRatings(rows) {
    const host = $("#ratingChart");
    if (!rows.length) { host.innerHTML = empty("No reviews found"); return; }
    const values = new Map(rows.map((r) => [r.rating, r.count])); const max = Math.max(...values.values(), 1);
    host.innerHTML = [5, 4, 3, 2, 1].map((rating) => { const count = values.get(rating) || 0; return `<div class="bar-row"><span>${rating}★</span><div class="bar-track"><span class="bar-fill" style="width:${count / max * 100}%"></span></div><strong>${number(count)}</strong></div>`; }).join("");
}

function renderTags(rows) {
    const host = $("#tagChart");
    if (!rows.length) { host.innerHTML = empty("No feedback tags found"); return; }
    const max = Math.max(...rows.map((r) => r.count), 1);
    host.innerHTML = rows.map((row) => `<div class="tag-row"><div class="tag-label"><span>${escapeHtml(row.tag.replaceAll("_", " "))}</span><b>${number(row.count)}</b></div><div class="tag-track"><div class="tag-fill" style="width:${row.count / max * 100}%"></div></div></div>`).join("");
}

async function loadCatalog() {
    const host = $("#catalogContent"); host.innerHTML = loading("Loading flexible document…");
    const id = Number($("#catalogVehicle").value);
    if (!id) { host.innerHTML = errorState("Enter a vehicle ID."); return; }
    try {
        const data = await api(`/api/catalog/vehicles/${id}`);
        const features = Object.entries(data.features || {});
        host.innerHTML = `<div class="catalog-grid"><article class="catalog-block"><h3>Flexible features</h3><ul class="feature-list">${features.map(([key, value]) => `<li><span>${escapeHtml(key.replaceAll("_", " "))}</span><b>${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</b></li>`).join("") || "<li>No features</li>"}</ul></article><article class="catalog-block"><h3>Certifications</h3><div class="chip-list">${(data.certifications || []).map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("") || '<span class="muted">None recorded</span>'}</div></article><article class="catalog-block"><h3>Inspection history</h3>${(data.inspections || []).slice(0, 4).map((inspection) => `<div class="inspection"><b>${escapeHtml(inspection.result)} · ${number(inspection.odometer_km)} km</b><small>${shortDate(inspection.inspected_on)} · ${escapeHtml(inspection.centre || "Unknown centre")}</small></div>`).join("") || '<span class="muted">No inspections recorded</span>'}</article></div>`;
    } catch (err) { host.innerHTML = errorState(err.message); }
}

async function submitAddRider(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("button[type=submit]", form);
    const values = Object.fromEntries(new FormData(form));
    values.wallet_balance = Number(values.wallet_balance);
    setButtonBusy(button, true, "Adding…");
    try {
        const rider = await api("/api/riders", { method: "POST", body: JSON.stringify(values) });
        toast(`Rider #${rider.id} added successfully.`);
        form.reset();
        closeManagementModal();
        selectEntity("riders");
        $("#browseSearch").value = rider.name;
        state.browsePage = 1;
        await loadBrowse();
        await setActor(rider.id, true);
    } catch (err) {
        $("#managementMessage").innerHTML = `<div class="result-card error"><h3>Rider not added</h3><p>${escapeHtml(err.message)}</p></div>`;
    } finally { setButtonBusy(button, false); }
}

async function submitAddVehicle(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("button[type=submit]", form);
    const values = Object.fromEntries(new FormData(form));
    setButtonBusy(button, true, "Adding…");
    try {
        const vehicle = await api("/api/vehicles", { method: "POST", body: JSON.stringify(values) });
        toast(`Vehicle #${vehicle.id} added successfully.`);
        form.reset();
        closeManagementModal();
        selectEntity("vehicles");
        $("#browseSearch").value = vehicle.license_plate;
        state.browsePage = 1;
        await loadBrowse();
        if (state.page === "booking") loadVehicleOptions();
    } catch (err) {
        $("#managementMessage").innerHTML = `<div class="result-card error"><h3>Vehicle not added</h3><p>${escapeHtml(err.message)}</p></div>`;
    } finally { setButtonBusy(button, false); }
}

async function deleteRecord(entity, id) {
    const label = entity === "riders" ? "rider" : "vehicle";
    if (!window.confirm(`Attempt to delete ${label} #${id}? Historical records may prevent deletion.`)) return;
    try {
        await api(`/api/${entity}/${id}`, { method: "DELETE" });
        toast(`${label} #${id} deleted.`);
        closeDrawer();
        if (state.actorId === Number(id) && entity === "riders") await setActor(1, true);
        await loadBrowse();
    } catch (err) {
        toast(err.message, "error");
        const message = $("#managementMessage");
        if (message) message.innerHTML = `<div class="result-card error"><h3>Deletion blocked</h3><p>${escapeHtml(err.message)}</p></div>`;
    }
}

function bindDetailActions() {
    const button = $(".delete-record");
    if (button) button.addEventListener("click", () => deleteRecord(button.dataset.entity, button.dataset.id));
}

function selectEntity(entity) {
    state.entity = entity;
    state.browsePage = 1;
    $$(".entity-tabs button").forEach((item) => item.classList.toggle("active", item.dataset.entity === entity));
    $("#browseStatusWrap").classList.toggle("hidden", entity !== "trips");
    $("#browseSearch").placeholder = entity === "riders" ? "Rider name or ID" : entity === "vehicles" ? "Plate or vehicle ID" : "Rider ID";
}

function openManagementModal(type) {
    const rider = type === "rider";
    $("#managementModalTitle").textContent = rider ? "Add rider" : "Add vehicle";
    $("#managementModalKicker").textContent = rider ? "Rider management" : "Fleet management";
    $("#managementModalDescription").textContent = rider ? "Create a new rider and starting wallet balance." : "Create a vehicle and make it available for the fleet.";
    $("#addRiderForm").classList.toggle("hidden", !rider);
    $("#addVehicleForm").classList.toggle("hidden", rider);
    $("#managementMessage").innerHTML = "";
    $("#managementModal").classList.add("open");
    $("#managementModalBackdrop").classList.add("open");
    $("#managementModal").setAttribute("aria-hidden", "false");
    $("#managementModalBackdrop").setAttribute("aria-hidden", "false");
    const field = rider ? $("#addRiderForm input[name=name]") : $("#addVehicleForm input[name=license_plate]");
    setTimeout(() => field.focus(), 50);
}

function closeManagementModal() {
    $("#managementModal").classList.remove("open");
    $("#managementModalBackdrop").classList.remove("open");
    $("#managementModal").setAttribute("aria-hidden", "true");
    $("#managementModalBackdrop").setAttribute("aria-hidden", "true");
}

function bindEvents() {
    $$(".nav-link").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.page)));
    $("#mobileMenu").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
    $("#setActor").addEventListener("click", () => setActor($("#actorInput").value));
    $("#actorInput").addEventListener("keydown", (event) => { if (event.key === "Enter") setActor(event.currentTarget.value); });
    $("#retryHealth").addEventListener("click", checkHealth);
    $$(".entity-tabs button").forEach((button) => button.addEventListener("click", () => {
        selectEntity(button.dataset.entity);
        $("#browseSearch").value = "";
        loadBrowse();
    }));
    let searchTimer;
    $("#browseSearch").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.browsePage = 1; loadBrowse(); }, 350); });
    $("#browseStatus").addEventListener("change", () => { state.browsePage = 1; loadBrowse(); });
    $("#browseReload").addEventListener("click", loadBrowse);
    $("#addRiderButton").addEventListener("click", () => openManagementModal("rider"));
    $("#addVehicleButton").addEventListener("click", () => openManagementModal("vehicle"));
    $("#managementModalClose").addEventListener("click", closeManagementModal);
    $("#managementModalBackdrop").addEventListener("click", closeManagementModal);
    $("#addRiderForm").addEventListener("submit", submitAddRider);
    $("#addVehicleForm").addEventListener("submit", submitAddVehicle);
    $("#drawerClose").addEventListener("click", closeDrawer); $("#drawerBackdrop").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeDrawer(); closeManagementModal(); } });
    $("#bookingForm").addEventListener("submit", submitBooking);
    $("#bookingRider").addEventListener("change", (event) => setActor(event.currentTarget.value, true));
    $("#refreshActiveTrip").addEventListener("click", () => loadActor());
    $("#loadAudit").addEventListener("click", loadAudit);
    $("#loadAnalytics").addEventListener("click", loadAnalytics); $("#refreshSummary").addEventListener("click", refreshSummary);
    $("#mapPreset").addEventListener("change", (event) => { const [lat, lon] = event.currentTarget.value.split(","); $("#mapLat").value = lat; $("#mapLon").value = lon; loadMap(); });
    $("#searchMap").addEventListener("click", loadMap);
    $("#mapPolling").addEventListener("change", setupMapPolling);
    $("#loadReviews").addEventListener("click", loadReviews); $("#loadCatalog").addEventListener("click", loadCatalog);
}

function setupMapPolling() {
    clearInterval(state.mapTimer); state.mapTimer = null;
    if ($("#mapPolling").checked) state.mapTimer = setInterval(() => { if (state.page === "map") loadMap(); }, 15000);
}

function startClock() {
    const update = () => { $("#clock").textContent = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date()); };
    update(); setInterval(update, 30000);
}

async function boot() {
    bindEvents(); startClock(); setupMapPolling(); checkHealth();
    $("#bookingRider").value = state.actorId;
    const requested = window.location.hash.slice(1);
    navigate(["browse", "booking", "audit", "analytics", "map", "reviews"].includes(requested) ? requested : "browse");
    await loadActor(true);
}

document.addEventListener("DOMContentLoaded", boot);