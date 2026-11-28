/* Audi Connect — normal user vehicle experience. Native HA state and actions only. */
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const title = (value) => String(value ?? "").replace(/_/g, " ");
const available = (state) =>
  !!state && !["unavailable", "unknown"].includes(state.state);
const TABS = [
  "Overview",
  "Charging",
  "Climate",
  "Access & Security",
  "Location",
  "Trips & Consumption",
  "Service & Health",
  "Vehicle & Documents",
  "Settings",
  "Engineering",
];
const TAB_LABEL = {
  "Access & Security": "Access",
  "Trips & Consumption": "Trips",
  "Service & Health": "Service",
  "Vehicle & Documents": "Vehicle",
};
// Presentation groups describe user journeys, not runtime data ownership.
const JOURNEY_GROUPS = {
  Climate: [
    [
      "Cabin climate",
      [
        "climate.climatisation",
        "sensor.climatisation_state",
        "sensor.outdoor_temperature",
        "sensor.next_climatisation_timer_local",
        "sensor.remaining_climatisation_time",
      ],
    ],
  ],
  "Access & Security": [["Central locking", ["lock.lock"]]],
  Location: [
    [
      "Last reported parking position",
      [
        "sensor.parked_in",
        "sensor.parking_address",
        "sensor.park_time",
        "sensor.position_last_updated",
        "device_tracker.position",
      ],
    ],
  ],
  "Trips & Consumption": [
    [
      "Last trip",
      [
        "sensor.last_trip_distance",
        "sensor.last_trip_duration",
        "sensor.last_trip_average_fuel_consumption",
        "sensor.last_trip_average_electric_consumption",
        "sensor.last_trip_fuel_consumption",
        "sensor.last_trip_electric_consumption",
      ],
    ],
    ["Short-term statistics", /^sensor\.shortterm_trip_/],
    ["Long-term statistics", /^sensor\.longterm_trip_/],
  ],
  "Service & Health": [
    ["Maintenance", ["sensor.service_overview", "sensor.mileage"]],
    [
      "Inspection",
      ["sensor.service_inspection_time", "sensor.service_inspection_distance"],
    ],
    ["Oil change", ["sensor.oil_change_time", "sensor.oil_change_distance"]],
    ["Service contact", ["sensor.local_dealer"]],
  ],
  "Vehicle & Documents": [
    ["Vehicle identity", ["sensor.car_type", "sensor.mileage"]],
    [
      "Powertrain",
      ["sensor.primary_engine_type", "sensor.secondary_engine_type"],
    ],
  ],
};
const OVERVIEW = [
  "sensor.state_of_charge",
  "sensor.tank_level",
  "sensor.range",
  "sensor.vehicle_data_freshness",
  "sensor.vehicle_data_age",
  "sensor.charging_state",
  "sensor.climatisation_state",
  "sensor.door_status",
  "sensor.window_status",
  "sensor.parked_in",
  "sensor.mileage",
  "sensor.service_overview",
  "binary_sensor.integration_problem",
];
const GROUPS = {
  Charging:
    /^(sensor\.(state_of_charge|range|hybrid_range|primary_engine_range|secondary_engine_range|charging_|charge_power_|energy_flow|external_power|max_charge_current|actual_charge_rate|plug_led|remaining_charging|target_state_of_charge|active_charging_profile|preferred_charging|charging_timer_|charging_current_|charging_plug_auto_unlock)|binary_sensor\.plug_|number\.|select\.|switch\.charging$|button\.(start_charging|stop_charging))/,
  Climate:
    /^(climate\.|sensor\.(climatisation_|outdoor_temperature|remaining_climatisation|next_climatisation|preheater_)|switch\.(climate|climatisation|preheater|window_heating)|binary_sensor\.glass_surface_heating|button\.(start_window|stop_window))/,
  "Access & Security":
    /^(lock\.|sensor\.(door|window)|binary_sensor\.(safelock|any_window|any_door|trunk|hood|left_|right_|sun_roof|roof_cover|parking_light)|button\.(flash_lights|start_engine|stop_engine))/,
  Location:
    /^(device_tracker\.|sensor\.(park|position_last_updated)|binary_sensor\.is_moving)/,
  "Trips & Consumption":
    /^sensor\.(last_trip|shortterm_|longterm_|trip_history)/,
  "Service & Health":
    /^(sensor\.(service_|oil_|local_dealer|mileage)|binary_sensor\.(oil_level|braking_status))/,
  "Vehicle & Documents":
    /^(sensor\.(model|car_type|primary_engine_type|secondary_engine_type|vehicle_reported_|vehicle_data_|last_update_time|mileage|cloud_last_successful_poll|integration_status|data_act_status|last_error)|binary_sensor\.integration_problem)/,
};
const QUICK = [
  "switch.charging",
  "switch.climate_quick_control",
  "lock.lock",
  "button.flash_lights",
  "button.start_charging_modern",
  "button.stop_charging_modern",
  "climate.climatisation",
  "button.v3_refresh_cloud",
  "button.refresh_vehicle_data",
  "button.wake_vehicle_modern",
];
const DOCS = [
  ["Owner's Manual", "https://ownersmanual.audi.com/"],
  ["myAudi", "https://my.audi.com/"],
  ["EU Data Act", "https://eu-data-act.vwgroup-datahub.com/"],
];
function imageURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      url.hostname === "mediaservice.audi.com" &&
      !url.username &&
      !url.password &&
      !url.port &&
      !url.hash
      ? url.href
      : "";
  } catch {
    return "";
  }
}
function quality(state) {
  if (!state) return "Unavailable";
  const a = state.attributes || {};
  if (a.state_is_optimistic) return "Requested — awaiting vehicle";
  if (
    a.state_source === "last_known_vehicle" ||
    String(a.vehicle_freshness).startsWith("stale")
  )
    return "Last known";
  if (a.vehicle_freshness === "unknown" || a.state_source === "unknown")
    return "Current state unknown";
  if (!available(state))
    return state.state === "unknown" ? "Unknown" : "Unavailable";
  return a.vehicle_freshness === "fresh" ? "Fresh" : "";
}
function valueText(state) {
  if (!available(state))
    return state?.state === "unknown" ? "Unknown" : "Unavailable";
  if (state.attributes?.state_is_optimistic)
    return "Requested: " + title(state.state);
  return (
    title(state.state) +
    (state.attributes?.unit_of_measurement
      ? " " + state.attributes.unit_of_measurement
      : "")
  );
}
function actionsFor(row, state) {
  if (!row.control || !state || state.state === "unavailable") return [];
  const a = state.attributes || {};
  const domain = row.key.split(".")[0];
  if (domain === "button") return [{ service: "press", label: row.name }];
  if (domain === "lock")
    return [
      a.lock_enabled && { service: "lock", label: "Lock" },
      a.unlock_enabled && { service: "unlock", label: "Unlock" },
    ].filter(Boolean);
  if (domain === "climate")
    return [
      a.start_enabled && { service: "turn_on", label: "Start climate" },
      a.stop_enabled && { service: "turn_off", label: "Stop climate" },
    ].filter(Boolean);
  if (domain === "switch")
    return [
      (a.on_enabled ??
        a.control_actions?.start ??
        a.control_actions?.enable) === true && {
        service: "turn_on",
        label:
          row.key === "switch.charging"
            ? "Start charging"
            : row.key === "switch.climate_quick_control"
              ? "Start climate"
              : "Turn on",
      },
      (a.off_enabled ??
        a.control_actions?.stop ??
        a.control_actions?.disable) === true && {
        service: "turn_off",
        label:
          row.key === "switch.charging"
            ? "Stop charging"
            : row.key === "switch.climate_quick_control"
              ? "Stop climate"
              : "Turn off",
      },
    ].filter(Boolean);
  return [];
}
const PRESENTATION_URL =
  typeof document !== "undefined" && document.currentScript?.src
    ? new URL("presentation.css", document.currentScript.src).href
    : "/audiconnect_v3/presentation.css";
const PANEL_STYLE = `
@import url("${PRESENTATION_URL}");
:host{display:block;color:var(--primary-text-color);background:var(--primary-background-color);min-height:100%;font-family:var(--paper-font-body1_-_font-family,inherit)}
*{box-sizing:border-box}
main{max-width:1240px;margin:auto;padding:clamp(12px,3vw,32px)}
header{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px}
header strong{font-size:1.35rem}
button,select,a,input{font:inherit;min-height:42px;border:1px solid var(--divider-color);border-radius:10px;padding:9px 13px;color:var(--primary-text-color);background:var(--card-background-color)}
button,select,a{cursor:pointer}a{display:inline-flex;align-items:center;text-decoration:none}
 button:disabled{opacity:.5;cursor:default}
section{margin:12px 0 24px;min-width:0}h2{font-size:1.15rem;margin:0 0 12px}
.muted,small,.label{color:var(--secondary-text-color)}.label{font-size:.86rem}
.hero{display:grid;gap:12px;padding:18px;border:1px solid var(--divider-color);border-radius:20px;background:var(--card-background-color)}
.hero-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;min-width:0}
.hero-head>div{min-width:0}.hero-head h1{font-size:clamp(1.4rem,3vw,2rem);margin:4px 0;overflow-wrap:anywhere}
.hero-head p{margin:5px 0;color:var(--secondary-text-color)}.hero-head select{max-width:45%;min-width:0}.hero-status{font-size:.9rem}
.hero-footer{display:flex;align-items:center;justify-content:space-between;font-size:.85rem;color:var(--secondary-text-color);gap:8px}.hero-footer button{border:0;padding:5px;min-height:36px}
.vehicle-picture{border-radius:14px;overflow:hidden;display:flex;align-items:center;justify-content:center;background:var(--secondary-background-color);height:clamp(180px,34vw,300px)}
.vehicle-picture img{width:100%;height:100%;object-fit:contain}
nav{display:flex;gap:8px;overflow:auto;padding:0 0 14px;scrollbar-width:thin}
nav button{white-space:nowrap;flex:0 0 auto;font-weight:600;border:0;border-radius:24px;background:transparent}
nav button[aria-pressed=true]{background:var(--primary-text-color);color:var(--primary-background-color)}
.settings-button{border:0;background:transparent}
.overview-layout{display:grid;gap:18px;align-items:start}.overview-layout>div{min-width:0}.overview-layout>div>section:first-child{margin-top:0}
.energy-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,140px),1fr))}
.energy,.status-card{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:16px;padding:16px;min-width:0;overflow-wrap:anywhere}
.energy{display:flex;flex-direction:column;gap:9px}.energy strong{font-size:1.8rem}.energy ha-icon{--mdc-icon-size:18px}
.status-row{display:flex;align-items:center;gap:10px;width:100%;border:0;border-bottom:1px solid var(--divider-color);border-radius:0;text-align:left;padding:11px 0;background:transparent}
.status-row:last-child{border:0}.status-value{margin-left:auto;text-align:right;overflow-wrap:anywhere;min-width:0}.status-value small{display:block}
.total-range{color:var(--secondary-text-color);font-size:.9rem}
.shortcuts{display:flex;flex-wrap:wrap;gap:8px}.shortcuts button{flex:1 1 70px;min-width:0}
.shortcuts button{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;padding:14px 8px;border:1px solid var(--divider-color);background:var(--card-background-color);overflow-wrap:anywhere}
.shortcuts ha-icon{--mdc-icon-size:26px}
.disclosure{width:100%;text-align:left}.action{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}
.actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:auto}.editor{display:flex;gap:6px;align-items:center}.editor input,.editor select{min-width:0;flex:1;width:auto}
.meter{height:7px;background:var(--divider-color);border-radius:7px;overflow:hidden}.meter span{display:block;height:100%;background:var(--primary-color);border-radius:7px}
.electric .meter span{background:#64c99b}.fuel .meter span{background:#7da7d9}
.message{padding:12px;border-left:3px solid var(--primary-color);background:var(--card-background-color)}
.table{overflow:auto}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid var(--divider-color);text-align:left}
.service-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:12px}.service-form label{display:flex;flex-direction:column;gap:6px}.service-form input{width:100%;min-width:0;max-width:100%}
.trip-chart{display:grid;gap:9px;margin:20px 0}.trip-chart>div{display:grid;grid-template-columns:minmax(0,90px) minmax(0,1fr) minmax(0,90px);align-items:center;gap:8px}.trip-chart>div>span{text-align:right;overflow-wrap:anywhere}.trip-chart>div>small{overflow-wrap:anywhere}.trip-chart h3{margin:4px 0;font-size:.95rem}
#parking-map{margin:12px auto;max-width:640px}#parking-map>*{display:block;width:100%}.command-feedback{margin:10px 0}
.climate-panel{text-align:center}.climate-panel svg{display:block;width:min(100%,260px);margin:0 auto}.climate-panel .actions,.climate-panel .editor{justify-content:center;margin:12px auto;max-width:360px}.climate-related{text-align:left;margin-top:20px;border-top:1px solid var(--divider-color)}.climate-related .actions,.climate-related .editor{margin:0;max-width:100%}
.charge-level{display:grid;gap:8px;margin:14px 0}.charge-level strong{font-size:2.4rem}.charge-panel .actions{margin-top:16px}
.charge-settings{border-top:1px solid var(--divider-color);margin-top:20px;padding-top:12px}.charge-settings h3{font-size:1rem;margin:0 0 8px}
.editor button{flex-shrink:0;white-space:nowrap}
.domain-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:12px 0;border-bottom:1px solid var(--divider-color)}.domain-row:last-child{border:0}.domain-row>div:first-child{flex:1 1 170px;min-width:0}.domain-row p{margin:4px 0;color:var(--secondary-text-color);overflow-wrap:anywhere}.domain-row .actions{margin:0;min-width:0;max-width:100%}.domain-row .editor{max-width:100%}.domain-row .command-feedback{flex-basis:100%;margin:0}.domain-row>button{margin-left:auto}
.domain-section h2{margin-bottom:4px}.status-card details summary{cursor:pointer;padding:10px 0;font-weight:600}
.attention{font-weight:600;color:var(--warning-color,var(--primary-text-color))}
@media(min-width:900px){.overview-layout{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.hero:has(.vehicle-picture){grid-template-columns:minmax(0,1fr) minmax(0,1.35fr);align-items:center}.hero:has(.vehicle-picture) .hero-head{flex-direction:column}.hero:has(.vehicle-picture) .hero-head select{max-width:100%}.hero-footer{grid-column:1/-1}}
@media(max-width:600px){.status-row .action{max-width:100%}.editor{flex-wrap:wrap}.editor button{width:100%}}
`;
class AudiVehiclePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.vehicles = [];
    this.labels = {};
    this.selected = "";
    this.tab = "Overview";
    this.loading = false;
    this.loaded = false;
    this.reloadPending = false;
    this.revalidating = false;
    this.scopeVersion = 0;
    this.busy = new Set();
    this.drafts = new Map();
    this.message = "";
    this.archive = null;
    this.tripPeriod = {};
    this.archiveLoading = false;
    this.expanded = new Set();
    this.serviceDraft = null;
    this.serviceOriginal = null;
    this.serviceBusy = false;
    this.myaudiBusy = false;
    this.mapCard = null;
    this.mapKey = "";
    this.mapLoading = false;
    this.shadowRoot.addEventListener("click", (event) => this.click(event));
    this.shadowRoot.addEventListener("input", (event) => {
      if (event.target.dataset.serviceField && this.serviceDraft)
        this.serviceDraft[event.target.dataset.serviceField] =
          event.target.value;
      if (event.target.dataset.editEntity)
        this.drafts.set(event.target.dataset.editEntity, event.target.value);
      if (event.target.dataset.tripDate)
        this.tripPeriod[event.target.dataset.tripDate] = event.target.value;
    });
    this.shadowRoot.addEventListener("change", (event) => {
      if (event.target.dataset.editEntity) {
        this.drafts.set(event.target.dataset.editEntity, event.target.value);
      }
      if (event.target.dataset.tripDate)
        this.tripPeriod[event.target.dataset.tripDate] = event.target.value;
      if (event.target.id === "vehicle-select") {
        this.selected = event.target.value;
        this.resetVehicleView();
        this.render();
        if (
          this.tab === "Trips & Consumption" &&
          this.row("sensor.trip_history")
        )
          void this.trips();
      }
    });
  }
  resetVehicleView() {
    this.engineeringElement = null;
    this.engineeringKey = "";
    this.scopeVersion++;
    this.drafts.clear();
    this.archive = null;
    this.tripPeriod = {};
    this.expanded.clear();
    this.serviceDraft = null;
    this.serviceOriginal = null;
    this.mapCard = null;
    this.mapKey = "";
    this.message = "";
  }
  connectedCallback() {
    if (this._hass && !this.loaded) void this.load();
  }
  disconnectedCallback() {
    this.loaded = false;
    this.resetVehicleView();
    this.vehicles = [];
    this.revalidating = false;
    if (this.loading) this.reloadPending = true;
  }
  set panel(value) {
    this._panel = value;
  }
  engineeringContext() {
    if (
      !this._hass?.user?.is_admin ||
      this.revalidating ||
      this._hass.connected === false
    )
      return null;
    return this.current()?.engineering_context || null;
  }
  async mountEngineering() {
    const context = this.tab === "Engineering" && this.engineeringContext();
    const host = this.shadowRoot.querySelector?.("#engineering-workspace");
    if (!context || !host) {
      this.engineeringElement = null;
      this.engineeringKey = "";
      return;
    }
    const key = JSON.stringify(context);
    if (this.engineeringKey !== key) {
      this.engineeringElement = null;
      this.engineeringKey = key;
    }
    try {
      if (!customElements.get("audiconnect-v3-panel")) {
        const url =
          this._panel?.config?.workbench_module_url ||
          "/audiconnect_v3/panel.js";
        await import(url);
      }
      if (
        this.tab !== "Engineering" ||
        JSON.stringify(this.engineeringContext()) !== key ||
        this.shadowRoot.querySelector?.("#engineering-workspace") !== host
      )
        return;
      if (!this.engineeringElement) {
        this.engineeringElement = document.createElement(
          "audiconnect-v3-panel",
        );
        this.engineeringElement.applicationContext = context;
      }
      if (this.engineeringElement.parentNode !== host)
        host.replaceChildren(this.engineeringElement);
      this.engineeringElement.hass = this._hass;
    } catch {
      if (this.shadowRoot.querySelector?.("#engineering-workspace") === host)
        host.textContent = this.tr("Engineering workspace unavailable");
    }
  }
  set hass(hass) {
    const before = this._hass;
    this._hass = hass;
    const userChanged =
      before &&
      (before.user?.id !== hass.user?.id ||
        before.user?.is_admin !== hass.user?.is_admin);
    if (hass.connected === false) {
      if (before?.connected !== false || userChanged) {
        if (userChanged) {
          this.resetVehicleView();
          this.vehicles = [];
        } else this.scopeVersion++;
        this.revalidating = true;
        this.reloadPending = this.loading;
        this.render();
      }
      return;
    }
    if (
      hass.language !== before?.language &&
      typeof hass.loadBackendTranslation === "function"
    ) {
      void hass
        .loadBackendTranslation("entity", "audiconnect")
        .then(() => this.render())
        .catch(() => {});
    }
    if (!this.loaded && !this.loading) {
      void this.load();
      return;
    }
    const rows = this.current()?.entities || [];
    const registryChanged =
      before &&
      (before.entities !== hass.entities ||
        before.devices !== hass.devices ||
        (before.connected === false && hass.connected === true) ||
        rows.some(
          (row) =>
            Boolean(before.states[row.entity_id]) !==
            Boolean(hass.states[row.entity_id]),
        ));
    if (userChanged || registryChanged) {
      if (userChanged) {
        this.resetVehicleView();
        this.vehicles = [];
      } else {
        // Suspend display and dispatch while checking the native scope.
        // Keep drafts private until the same scope has been authorized again.
        this.scopeVersion++;
      }
      this.revalidating = true;
      if (this.loading) this.reloadPending = true;
      else void this.load();
      this.render();
      return;
    }
    if (
      !before ||
      before.language !== hass.language ||
      rows.some((r) => before.states[r.entity_id] !== hass.states[r.entity_id])
    ) {
      this.render();
    } else if (this.tab === "Engineering") {
      void this.mountEngineering();
    }
  }
  tr(label) {
    const lang = String(this._hass?.language || "en")
      .split("-")[0]
      .toLowerCase();
    const index = ["nl", "fr", "de"].indexOf(lang);
    return index >= 0 ? this.labels[label]?.[index] || label : label;
  }
  qualityLabel(state) {
    return this.tr(quality(state));
  }
  observationLabel(state) {
    const q = this.qualityLabel(state);
    const stamp = Date.parse(state?.attributes?.vehicle_captured);
    return [
      q,
      Number.isFinite(stamp)
        ? new Date(stamp).toLocaleString(this._hass?.language)
        : "",
    ]
      .filter(Boolean)
      .join(" · ");
  }
  identityLabel(state) {
    const a = state?.attributes || {};
    if (!available(state)) return this.tr("Identity not confirmed");
    return this.tr(
      a.presentation_source === "ha_registry_last_known"
        ? "Last known registry identity"
        : a.identity_restored
          ? "Last known manufacturer identity"
          : "Manufacturer information when reported",
    );
  }
  display(state) {
    if (!available(state)) return this.tr(valueText(state));
    const value =
      this._hass?.formatEntityState?.(state) ||
      valueText({
        ...state,
        attributes: { ...state.attributes, state_is_optimistic: false },
      });
    return (
      (state.attributes?.state_is_optimistic ? this.tr("Requested: ") : "") +
      value
    );
  }
  entityLabel(row) {
    const key = row.translation_key;
    const domain = row.key.split(".")[0];
    return (
      (key &&
        this._hass?.localize?.(
          "component.audiconnect.entity." + domain + "." + key + ".name",
        )) ||
      row.name
    );
  }
  current() {
    return this.revalidating
      ? undefined
      : this.vehicles.find((v) => v.device_id === this.selected);
  }
  state(row) {
    return this._hass?.states?.[row.entity_id];
  }
  row(key) {
    return this.current()?.entities.find((r) => r.key === key);
  }
  async load() {
    if (!this._hass || this._hass.connected === false || this.loading) return;
    this.loading = true;
    this.render();
    try {
      const result = await this._hass.callWS({
        type: "audiconnect/vehicle/list",
      });
      if (this.reloadPending || this._hass.connected === false) return;
      const previous = this.vehicles.find((v) => v.device_id === this.selected);
      this.vehicles = result.vehicles || [];
      this.labels = result.labels || this.labels;
      this.revalidating = false;
      if (!this.current()) this.selected = this.vehicles[0]?.device_id || "";
      const current = this.current();
      if (
        previous?.device_id !== current?.device_id ||
        previous?.configuration_entry !== current?.configuration_entry
      )
        this.resetVehicleView();
      else if (
        JSON.stringify(previous?.entities) !== JSON.stringify(current?.entities)
      ) {
        // Keep only edits and views belonging to unchanged, authorized native entities.
        this.scopeVersion++;
        const same = (id, control = false) => {
          const old = previous?.entities.find((row) => row.entity_id === id);
          return (
            old &&
            current?.entities.some(
              (row) =>
                row.entity_id === id &&
                row.key === old.key &&
                (!control || row.control),
            )
          );
        };
        for (const id of this.drafts.keys())
          if (!same(id, true)) this.drafts.delete(id);
        const archive = previous?.entities.find(
          (row) => row.key === "sensor.trip_history",
        );
        if (!archive || !same(archive.entity_id)) this.archive = null;
        const dealer = previous?.entities.find(
          (row) => row.key === "sensor.local_dealer",
        );
        if (!dealer || !same(dealer.entity_id) || !this._hass?.user?.is_admin)
          this.serviceDraft = this.serviceOriginal = null;
        this.mapCard = null;
        this.mapKey = "";
      }
      this.message = "";
    } catch {
      this.vehicles = [];
      this.selected = "";
      this.resetVehicleView();
      this.message = "Vehicle list unavailable. Refresh to try again.";
    } finally {
      this.loaded = true;
      this.loading = false;
      if (!this.reloadPending && this._hass?.connected !== false)
        this.revalidating = false;
      this.render();
      if (this.reloadPending) {
        this.reloadPending = false;
        if (this.isConnected !== false && this._hass?.connected !== false)
          void this.load();
        else this.loaded = false;
      } else if (
        this.tab === "Trips & Consumption" &&
        !this.archive &&
        this.row("sensor.trip_history")
      )
        void this.trips();
    }
  }
  permittedControl(row) {
    return (
      row.control &&
      !this.loading &&
      this._hass?.connected !== false &&
      this.current()?.entities.some(
        (current) =>
          current.entity_id === row.entity_id &&
          current.key === row.key &&
          current.control,
      )
    );
  }
  async run(row, service) {
    const state = this.state(row);
    if (
      !this.permittedControl(row) ||
      !actionsFor(row, state).some((a) => a.service === service) ||
      this.busy.has(row.entity_id)
    )
      return;
    const action = actionsFor(row, state).find(
      (candidate) => candidate.service === service,
    );
    const confirmation = this.tr("Send {action} to {vehicle} ({control})?")
      .replace(
        "{action}",
        action?.label === row.name
          ? this.entityLabel(row)
          : this.tr(action?.label || title(service)),
      )
      .replace("{vehicle}", this.current().name)
      .replace("{control}", this.entityLabel(row));
    if (!window.confirm(confirmation)) return;
    this.busy.add(row.entity_id);
    const selected = this.scopeVersion;
    this.message = "Sending request…";
    this.render();
    try {
      await this._hass.callService(row.key.split(".")[0], service, {
        entity_id: row.entity_id,
      });
      if (this.scopeVersion === selected)
        this.message =
          "Request returned. Check the reported vehicle state; physical execution is not confirmed.";
    } catch {
      if (this.scopeVersion === selected)
        this.message =
          "Request failed or outcome is uncertain. Check vehicle status before trying again.";
    } finally {
      this.busy.delete(row.entity_id);
      this.render();
    }
  }
  async save(row) {
    const s = this.state(row);
    if (
      !this.permittedControl(row) ||
      !s ||
      s.state === "unavailable" ||
      this.busy.has(row.entity_id) ||
      (!available(s) && !row.key.startsWith("climate."))
    )
      return;
    const raw = this.drafts.get(row.entity_id);
    const domain = row.key.split(".")[0];
    const attrs = s.attributes || {};
    let service, payload;
    if (domain === "number") {
      if (raw == null || raw === "" || !Number.isFinite(Number(raw))) return;
      const value = Number(raw);
      if (
        !Number.isFinite(attrs.min) ||
        !Number.isFinite(attrs.max) ||
        value < attrs.min ||
        value > attrs.max
      ) {
        this.message = "Choose a value within the available range.";
        this.render();
        return;
      }
      service = "set_value";
      payload = { value };
    } else if (
      domain === "climate" &&
      Number(attrs.supported_features) & 1 &&
      raw != null &&
      raw !== "" &&
      Number.isFinite(Number(raw)) &&
      Number.isFinite(attrs.min_temp) &&
      Number.isFinite(attrs.max_temp) &&
      Number(raw) >= attrs.min_temp &&
      Number(raw) <= attrs.max_temp
    ) {
      service = "set_temperature";
      payload = { temperature: Number(raw) };
    } else if (
      domain === "select" &&
      Array.isArray(attrs.options) &&
      attrs.options.includes(raw)
    ) {
      service = "select_option";
      payload = { option: raw };
    } else return;
    if (
      !window.confirm(
        this.tr("Apply {control} to {vehicle}?")
          .replace("{control}", this.entityLabel(row))
          .replace("{vehicle}", this.current().name),
      )
    )
      return;
    this.busy.add(row.entity_id);
    const selected = this.scopeVersion;
    this.render();
    try {
      await this._hass.callService(domain, service, {
        entity_id: row.entity_id,
        ...payload,
      });
      if (this.scopeVersion === selected) {
        this.drafts.delete(row.entity_id);
        this.message =
          "Settings request returned. Check the reported value before relying on the change.";
      }
    } catch {
      if (this.scopeVersion === selected)
        this.message =
          "Settings request failed or is uncertain. Your edit is retained.";
    } finally {
      this.busy.delete(row.entity_id);
      this.render();
    }
  }
  tripCSV(trips) {
    const columns = [
      ["timestamp", "timestamp_utc"],
      ["mileage", "distance_km"],
      ["totalElectricConsumption", "electric_kwh"],
      ["totalFuelConsumption", "fuel_l"],
      ["traveltime", "duration_min"],
      ["averageElectricEngineConsumption", "electric_kwh_per_100km"],
      ["averageFuelConsumption", "fuel_l_per_100km"],
    ];
    return [
      columns.map(([, label]) => label).join(","),
      ...trips.map((trip) =>
        columns
          .map(([key]) => {
            const value = trip[key];
            if (key === "timestamp")
              return typeof value === "string" &&
                /^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(value)
                ? value
                : "";
            return typeof value === "number" && Number.isFinite(value)
              ? String(value)
              : "";
          })
          .join(","),
      ),
    ].join("\r\n");
  }
  async trips(offset = 0, exportAll = false, csv = false, paginate = false) {
    const row = this.row("sensor.trip_history");
    if (!row || this.loading || this.archiveLoading) return;
    const selected = this.scopeVersion;
    // Pagination always belongs to the applied period, not unsaved date edits.
    const period =
      (paginate || exportAll) && this.archive ? this.archive : this.tripPeriod;
    const start = period.start_date || "";
    const end = period.end_date || "";
    if (start && end && start >= end) {
      this.message = "Start date must precede end date.";
      this.render();
      return;
    }
    this.archiveLoading = true;
    this.render();
    try {
      const result = await this._hass.callWS({
        type: "audiconnect/vehicle/trips",
        entity_id: row.entity_id,
        offset,
        limit: 25,
        export: exportAll,
        ...(start ? { start_date: start } : {}),
        ...(end ? { end_date: end } : {}),
      });
      if (this.scopeVersion !== selected) return;
      if (exportAll) {
        const url = URL.createObjectURL(
          new Blob(
            [
              csv
                ? this.tripCSV(result.trips || [])
                : JSON.stringify(result, null, 2),
            ],
            {
              type: csv ? "text/csv;charset=utf-8" : "application/json",
            },
          ),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = csv
          ? "audi-trip-history.csv"
          : "audi-trip-history.json";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } else this.archive = result;
    } catch {
      if (this.scopeVersion === selected)
        this.message = "Trip archive unavailable.";
    } finally {
      this.archiveLoading = false;
      this.render();
      if (
        this.scopeVersion !== selected &&
        this.tab === "Trips & Consumption" &&
        !this.archive
      )
        void this.trips();
    }
  }
  click(event) {
    const button = event.target.closest?.("button");
    if (!button || button.disabled) return;
    const data = button.dataset;
    if (data.expand !== undefined) {
      if (this.expanded.has(this.tab)) this.expanded.delete(this.tab);
      else this.expanded.add(this.tab);
      this.render();
      return;
    }
    if (data.tab && TABS.includes(data.tab) && this.hasTab(data.tab)) {
      this.tab = data.tab;
      this.message = "";
      this.render();
      if (
        this.tab === "Trips & Consumption" &&
        !this.archive &&
        this.row("sensor.trip_history")
      )
        void this.trips();
      return;
    }
    if (data.myaudiRefresh !== undefined) {
      void this.refreshMyAudi();
      return;
    }
    if (data.serviceEdit !== undefined) {
      void this.serviceDetails();
      return;
    }
    if (data.serviceSave !== undefined) {
      void this.serviceDetails(true);
      return;
    }
    if (data.serviceCancel !== undefined) {
      this.serviceDraft = this.serviceOriginal = null;
      this.render();
      return;
    }
    if (data.refresh !== undefined) {
      void this.load();
      return;
    }
    if (data.trips !== undefined) {
      void this.trips(
        Number(data.trips),
        false,
        false,
        data.page !== undefined,
      );
      return;
    }
    if (data.tripClear !== undefined) {
      this.tripPeriod = {};
      void this.trips();
      return;
    }
    if (data.export !== undefined) {
      void this.trips(0, true, data.export === "csv");
      return;
    }
    const row = this.current()?.entities.find(
      (r) => r.entity_id === data.entity,
    );
    if (!row) return;
    if (data.service) {
      void this.run(row, data.service);
      return;
    }
    if (data.save !== undefined) {
      void this.save(row);
      return;
    }
    if (data.details !== undefined)
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId: row.entity_id },
          bubbles: true,
          composed: true,
        }),
      );
  }
  hasTab(tab) {
    if (tab === "Engineering") return Boolean(this.engineeringContext());
    if (tab === "Charging")
      return (this.current()?.entities || []).some(
        (row) =>
          GROUPS.Charging.test(row.key) &&
          ![
            "sensor.range",
            "sensor.hybrid_range",
            "sensor.primary_engine_range",
            "sensor.secondary_engine_range",
            "sensor.primary_engine_range_percent",
            "sensor.secondary_engine_range_percent",
          ].includes(row.key),
      );
    return (
      ["Overview", "Vehicle & Documents", "Settings"].includes(tab) ||
      (this.current()?.entities || []).some((row) => GROUPS[tab]?.test(row.key))
    );
  }
  ordered(rows, keys) {
    return keys.flatMap((key) => rows.filter((row) => row.key === key));
  }
  domainRow(row, controls = false) {
    const state = this.state(row);
    const evidence = this.observationLabel(state);
    const actions = controls ? actionsFor(row, state) : [];
    const value = row.key.startsWith("button.")
      ? this.tr(actions.length ? "Available" : "Unavailable")
      : ["sensor.door_status", "sensor.window_status"].includes(row.key) &&
          state?.state === "stale"
        ? this.tr("Current state unknown")
        : this.display(state);
    const detail =
      evidence && evidence !== value
        ? "<small>" + esc(evidence) + "</small>"
        : "";
    const writable = controls && row.control;
    const id = esc(row.entity_id);
    const localService =
      row.key === "sensor.service_overview" && !this.hasConfiguredDealer()
        ? ["next_appointment_local", "warranty_expiry_local"]
            .filter((key) => state?.attributes?.[key])
            .map(
              (key) =>
                "<small>" +
                esc(
                  this.tr(
                    key === "next_appointment_local"
                      ? "Next appointment (local)"
                      : "Warranty expiry (local)",
                  ),
                ) +
                ": " +
                esc(state.attributes[key]) +
                "</small>",
            )
            .join("")
        : "";
    if (!writable && !actions.length)
      return (
        '<button class="status-row" data-entity="' +
        id +
        '" data-details><span>' +
        esc(this.entityLabel(row)) +
        '</span><span class="status-value">' +
        esc(value) +
        detail +
        localService +
        '</span><ha-icon icon="mdi:chevron-right"></ha-icon></button>'
      );
    const edit = writable ? this.editor(row, state) : "";
    const buttons = actions
      .map((action) => this.actionHTML(row, action))
      .join("");
    return (
      '<div class="domain-row"><div><strong>' +
      esc(this.entityLabel(row)) +
      "</strong><p>" +
      esc(value) +
      "</p>" +
      detail +
      "</div>" +
      (buttons || edit
        ? '<div class="actions">' + buttons + edit + "</div>"
        : "") +
      '<button data-entity="' +
      id +
      '" data-details>' +
      esc(this.tr(writable ? "Control / edit" : "Details")) +
      "</button>" +
      this.commandFeedback([row]) +
      "</div>"
    );
  }
  domainRows(label, rows, controls = false) {
    return rows.length
      ? '<section class="status-card domain-section"><h2>' +
          esc(this.tr(label)) +
          "</h2>" +
          rows.map((row) => this.domainRow(row, controls)).join("") +
          "</section>"
      : "";
  }
  journeyGroups(rows, used) {
    return (JOURNEY_GROUPS[this.tab] || [])
      .map(([label, selection]) => {
        const remaining = rows.filter((row) => !used.has(row.entity_id));
        const members = Array.isArray(selection)
          ? this.ordered(remaining, selection)
          : remaining.filter((row) => selection.test(row.key));
        for (const row of members) used.add(row.entity_id);
        return this.domainRows(label, members, true);
      })
      .join("");
  }
  reading(key) {
    const row = this.row(key);
    return row ? this.state(row) : undefined;
  }
  roleRange(role) {
    const fuels = ["gasoline", "diesel", "petrol", "cng", "lpg"];
    const slots = ["primary", "secondary"].filter((slot) => {
      const type = this.reading("sensor." + slot + "_engine_type");
      return (
        available(type) &&
        (role === "electric"
          ? type.state === "electric"
          : fuels.includes(type.state))
      );
    });
    if (slots.length !== 1) return undefined;
    const range = this.reading("sensor." + slots[0] + "_engine_range");
    return available(range) ? range : undefined;
  }
  energyCards() {
    const cards = [
      ["sensor.state_of_charge", "Battery", "electric", "mdi:battery-charging"],
      ["sensor.tank_level", "Fuel", "fuel", "mdi:gas-station"],
    ];
    const html = cards
      .filter(([key]) => this.row(key))
      .map(([key, label, role, icon]) => {
        const state = this.reading(key);
        const range = this.roleRange(role);
        const n = Number(state?.state);
        const pct =
          available(state) &&
          state.attributes?.unit_of_measurement === "%" &&
          Number.isFinite(n) &&
          n >= 0 &&
          n <= 100;
        return (
          '<article class="energy ' +
          role +
          '"><span class="label"><ha-icon icon="' +
          icon +
          '"></ha-icon> ' +
          esc(this.tr(label)) +
          "</span><strong>" +
          esc(this.display(state)) +
          "</strong>" +
          (pct
            ? '<div class="meter"><span style="width:' + n + '%"></span></div>'
            : "") +
          (range
            ? "<small>" +
              esc(this.display(range)) +
              " " +
              esc(this.tr(role + " range")) +
              (this.observationLabel(range)
                ? " · " + esc(this.observationLabel(range))
                : "") +
              "</small>"
            : "") +
          (this.observationLabel(state)
            ? "<small>" + esc(this.observationLabel(state)) + "</small>"
            : "") +
          "</article>"
        );
      })
      .join("");
    const range = this.reading("sensor.range");
    return (
      (html ? '<div class="energy-grid">' + html + "</div>" : "") +
      (available(range)
        ? '<p class="total-range">' +
          esc(this.tr("Total range")) +
          " · " +
          esc(this.display(range)) +
          (this.observationLabel(range)
            ? " · " + esc(this.observationLabel(range))
            : "") +
          "</p>"
        : "")
    );
  }
  actionHTML(row, action, icon = "") {
    if (!row || !action) return "";
    return (
      '<button class="action" data-entity="' +
      esc(row.entity_id) +
      '" data-service="' +
      esc(action.service) +
      '" ' +
      (this.loading || this.busy.has(row.entity_id) ? "disabled" : "") +
      ">" +
      (icon ? '<ha-icon icon="' + esc(icon) + '"></ha-icon>' : "") +
      esc(
        action.label === row.name
          ? this.entityLabel(row)
          : this.tr(action.label),
      ) +
      "</button>"
    );
  }
  homeActions() {
    const link = (tab, label, icon) =>
      this.hasTab(tab)
        ? '<button data-tab="' +
          esc(tab) +
          '"><ha-icon icon="' +
          icon +
          '"></ha-icon>' +
          esc(this.tr(label)) +
          "</button>"
        : "";
    const button = (row, action, icon, label) =>
      row && action ? this.actionHTML(row, { ...action, label }, icon) : "";
    const lock = this.row("lock.lock");
    const state = lock && this.state(lock);
    const lockAction =
      lock &&
      available(state) &&
      !state.attributes?.state_is_optimistic &&
      state.attributes?.state_source === "vehicle"
        ? actionsFor(lock, state).find(
            (action) =>
              action.service ===
              (state.state === "locked"
                ? "unlock"
                : state.state === "unlocked"
                  ? "lock"
                  : ""),
          )
        : undefined;
    const flash = this.row("button.flash_lights");
    const flashAction =
      flash &&
      actionsFor(flash, this.state(flash)).find(
        (action) => action.service === "press",
      );
    const content =
      link("Charging", "Charge", "mdi:ev-plug-type2") +
      link("Climate", "Climate", "mdi:fan") +
      (lockAction
        ? button(lock, lockAction, "mdi:lock-outline", lockAction.label)
        : link("Access & Security", "Access", "mdi:lock-outline")) +
      button(flash, flashAction, "mdi:lightbulb-outline", "Flash");
    return content
      ? "<section><h2>" +
          esc(this.tr("Quick actions")) +
          '</h2><div class="shortcuts">' +
          content +
          "</div></section>"
      : "";
  }
  refreshPanel() {
    const rows = [
      "button.v3_refresh_cloud",
      "button.refresh_vehicle_data",
      "button.wake_vehicle_modern",
    ]
      .map((key) => this.row(key))
      .filter(Boolean);
    if (!rows.length) return "";
    const descriptions = {
      "button.v3_refresh_cloud":
        "Refresh account data without waking the vehicle.",
      "button.refresh_vehicle_data":
        "Request newer vehicle data, if supported.",
      "button.wake_vehicle_modern": "Wake the vehicle only when needed.",
    };
    return (
      '<section class="status-card"><h2>' +
      esc(this.tr("Update vehicle data")) +
      '</h2><p class="muted">' +
      esc(this.tr("Refreshing this view does not contact Audi.")) +
      "</p>" +
      rows
        .map((row) => {
          const actions = actionsFor(row, this.state(row));
          return (
            '<div class="status-row"><span>' +
            esc(this.tr(descriptions[row.key])) +
            '</span><span class="status-value">' +
            (actions.length
              ? this.actionHTML(row, actions[0])
              : esc(this.tr("Unavailable"))) +
            this.commandFeedback([row]) +
            "</span></div>"
          );
        })
        .join("") +
      "</section>"
    );
  }
  statusRows() {
    const entries = [
      [
        this.row("binary_sensor.any_door_open")
          ? "binary_sensor.any_door_open"
          : "sensor.door_status",
        "Doors",
        "mdi:car-door",
        "Access & Security",
      ],
      [
        this.row("binary_sensor.any_window_open")
          ? "binary_sensor.any_window_open"
          : "sensor.window_status",
        "Windows",
        "mdi:car-door",
        "Access & Security",
      ],
      ["lock.lock", "Lock", "mdi:lock-outline", "Access & Security"],
      ["sensor.charging_state", "Charging", "mdi:ev-plug-type2", "Charging"],
      ["sensor.climatisation_state", "Climate", "mdi:fan", "Climate"],
      ["sensor.parked_in", "Location", "mdi:map-marker-outline", "Location"],
      ["sensor.mileage", "Odometer", "mdi:gauge", "Vehicle & Documents"],
      [
        "binary_sensor.integration_problem",
        "Integration status",
        "mdi:cloud-alert",
        "Vehicle & Documents",
      ],
    ];
    const rows = entries
      .filter(([key]) => this.row(key))
      .map(([key, label, icon, tab]) => {
        const state = this.reading(key);
        return (
          '<button class="status-row" data-tab="' +
          esc(tab) +
          '"><ha-icon icon="' +
          icon +
          '"></ha-icon><span>' +
          esc(this.tr(label)) +
          '</span><span class="status-value">' +
          esc(
            ["sensor.door_status", "sensor.window_status"].includes(key) &&
              state?.state === "stale"
              ? this.tr("Current state unknown")
              : this.display(state),
          ) +
          (this.observationLabel(state)
            ? "<small>" + esc(this.observationLabel(state)) + "</small>"
            : "") +
          '</span><ha-icon icon="mdi:chevron-right"></ha-icon></button>'
        );
      })
      .join("");
    const service = this.reading("sensor.service_overview");
    const serviceHtml = this.row("sensor.service_overview")
      ? '<section class="status-card"><h2>' +
        esc(this.tr("Service & maintenance")) +
        '</h2><button class="status-row" data-tab="Service &amp; Health"><ha-icon icon="mdi:wrench-outline"></ha-icon><span>' +
        esc(this.tr("Maintenance")) +
        '</span><span class="status-value">' +
        esc(this.display(service)) +
        (this.observationLabel(service)
          ? "<small>" + esc(this.observationLabel(service)) + "</small>"
          : "") +
        '</span><ha-icon icon="mdi:chevron-right"></ha-icon></button></section>'
      : "";
    return (
      (rows
        ? '<section class="status-card"><h2>' +
          esc(this.tr("Vehicle status")) +
          "</h2>" +
          rows +
          "</section>"
        : "") + serviceHtml
    );
  }
  accessStatus(rows) {
    const groups = [
      [
        "Doors",
        /^(sensor\.door|binary_sensor\.(any_door|(?:left|right)_(?:front|rear)_door))/,
      ],
      [
        "Windows",
        /^(sensor\.window|binary_sensor\.(any_window|(?:left|right)_(?:front|rear)_window))/,
      ],
      [
        "Other openings and security",
        /^binary_sensor\.(trunk|hood|sun_roof|roof_cover|safelock|parking_light)/,
      ],
    ];
    const used = new Set();
    const html = groups
      .map(([label, pattern]) => {
        const members = rows.filter((row) => pattern.test(row.key));
        if (!members.length) return "";
        for (const row of members) used.add(row.entity_id);
        const aggregate = members.filter((row) =>
          /^binary_sensor\.any_/.test(row.key),
        );
        const individual = members.filter((row) => !aggregate.includes(row));
        const primary = aggregate.length ? aggregate : members;
        const details = aggregate.length ? individual : [];
        return (
          '<section class="status-card"><h2>' +
          esc(this.tr(label)) +
          "</h2>" +
          primary.map((row) => this.domainRow(row)).join("") +
          (details.length
            ? '<details data-disclosure="' +
              esc(label) +
              '"><summary>' +
              esc(this.tr("Details")) +
              "</summary>" +
              details.map((row) => this.domainRow(row)).join("") +
              "</details>"
            : "") +
          "</section>"
        );
      })
      .join("");
    return { html, used };
  }
  editor(row, s) {
    if (
      !row.control ||
      !s ||
      s.state === "unavailable" ||
      (!available(s) && !row.key.startsWith("climate."))
    )
      return "";
    const attrs = s.attributes || {};
    const value =
      this.drafts.get(row.entity_id) ??
      (row.key.startsWith("climate.") ? (attrs.temperature ?? "") : s.state);
    const id = esc(row.entity_id);
    const disabled = this.busy.has(row.entity_id) ? "disabled" : "";
    let field = "";
    if (
      row.key.startsWith("number.") &&
      Number.isFinite(attrs.min) &&
      Number.isFinite(attrs.max)
    ) {
      field =
        '<input type="number" aria-label="' +
        esc(this.entityLabel(row)) +
        '" data-edit-entity="' +
        id +
        '" min="' +
        esc(attrs.min) +
        '" max="' +
        esc(attrs.max) +
        '" step="' +
        esc(attrs.step ?? "any") +
        '" value="' +
        esc(value) +
        '" ' +
        disabled +
        ">";
    } else if (
      row.key.startsWith("climate.") &&
      Number(attrs.supported_features) & 1 &&
      Number.isFinite(attrs.min_temp) &&
      Number.isFinite(attrs.max_temp)
    ) {
      field =
        '<input type="number" aria-label="' +
        esc(this.tr("Target temperature")) +
        '" data-edit-entity="' +
        id +
        '" min="' +
        esc(attrs.min_temp) +
        '" max="' +
        esc(attrs.max_temp) +
        '" step="' +
        esc(attrs.target_temp_step ?? "any") +
        '" value="' +
        esc(value) +
        '" ' +
        disabled +
        ">";
    } else if (
      row.key.startsWith("select.") &&
      Array.isArray(attrs.options) &&
      attrs.options.length
    ) {
      field =
        '<select aria-label="' +
        esc(this.entityLabel(row)) +
        '" data-edit-entity="' +
        id +
        '" ' +
        disabled +
        ">" +
        attrs.options
          .map(
            (o) =>
              '<option value="' +
              esc(o) +
              '" ' +
              (o === value ? "selected" : "") +
              ">" +
              esc(
                this._hass?.formatEntityState?.({ ...s, state: o }) ||
                  this.tr(title(o)),
              ) +
              "</option>",
          )
          .join("") +
        "</select>";
    }
    return field
      ? '<div class="editor">' +
          field +
          '<button data-entity="' +
          id +
          '" data-save ' +
          disabled +
          (">" + esc(this.tr("Apply")) + "</button></div>")
      : "";
  }
  commandFeedback(rows) {
    const records = rows
      .map((row) => this.state(row)?.attributes)
      .filter((a) => a?.command_status);
    const timed = records.filter((a) =>
      Number.isFinite(Date.parse(a.command_requested_at)),
    );
    const latest =
      timed.sort(
        (a, b) =>
          Date.parse(b.command_requested_at) -
          Date.parse(a.command_requested_at),
      )[0] || (records.length === 1 ? records[0] : null);
    if (!latest) return "";
    const message =
      {
        pending: "Request recorded as pending",
        accepted_unconfirmed: "Request accepted · vehicle result unconfirmed",
        backend_completed: "Audi reports completion · check vehicle",
        verified: "Matching vehicle observation",
        rejected: "Request rejected",
        uncertain: "Outcome uncertain · check before retrying",
        reviewed: "Request reviewed",
        physical_failed: "Physical action failed",
        readback_mismatch: "Vehicle reported a different state",
      }[latest.command_status] || "Check request status";
    const time = Date.parse(latest.command_requested_at);
    return (
      '<div class="command-feedback" role="status"><small>' +
      esc(this.tr("Last request")) +
      " · " +
      esc(this.tr(message)) +
      (Number.isFinite(time)
        ? " · " + esc(new Date(time).toLocaleString(this._hass?.language))
        : "") +
      "</small></div>"
    );
  }
  async refreshMyAudi() {
    const current = this.current();
    const row = current?.entities[0];
    if (
      !row ||
      !current.myaudi_configured ||
      !this._hass?.user?.is_admin ||
      this.myaudiBusy
    )
      return;
    const scope = this.scopeVersion;
    this.myaudiBusy = true;
    this.render();
    try {
      const result = await this._hass.callWS({
        type: "audiconnect/vehicle/myaudi",
        entity_id: row.entity_id,
      });
      if (this.scopeVersion === scope && this.current() === current)
        current.myaudi_dossier = result;
    } catch {
      if (this.scopeVersion === scope)
        this.message =
          "myAudi unavailable. Check the connection in Additional data sources.";
    } finally {
      this.myaudiBusy = false;
      this.render();
    }
  }
  myaudiHTML() {
    const car = this.current();
    if (!this._hass?.user?.is_admin || !car?.myaudi_configured) return "";
    const d = car.myaudi_dossier;
    const line = (name, value) =>
      value == null || value === ""
        ? ""
        : "<div><small>" +
          esc(this.tr(name)) +
          "</small> · " +
          esc(String(value)) +
          "</div>";
    const list = (name, rows, render) =>
      "<h3>" +
      esc(this.tr(name)) +
      "</h3>" +
      (Array.isArray(rows)
        ? rows.length
          ? rows.map(render).join("")
          : "<small>" + esc(this.tr("No entries returned")) + "</small>"
        : "<small>" + esc(this.tr("Unavailable")) + "</small>");
    let detail = "";
    if (d) {
      if (this.tab === "Vehicle & Documents") {
        const identity = d.identity || {};
        detail +=
          line("Model", identity.model) +
          line("Model year", identity.model_year) +
          line("Model coding", identity.model_coding) +
          line("Powertrain", identity.powertrain) +
          line("Exterior", identity.exteriorColor) +
          line("Interior", identity.interiorColor);
        if (d.image)
          detail +=
            '<img alt="Audi vehicle" style="max-width:100%" src="' +
            esc(d.image) +
            '">';
        detail +=
          "<details><summary>" +
          esc(this.tr("Connected services")) +
          "</summary>" +
          list("Connected services", d.services, (r) =>
            line(
              r.id || "Service",
              [r.status, r.expirationDate].filter(Boolean).join(" · "),
            ),
          ) +
          "</details>";
      } else {
        detail += list("Digital service record", d.service, (r) =>
          line(r.serviceDate || "Service", r.serviceDescription),
        );
        detail +=
          "<h3>" +
          esc(this.tr("Warranty")) +
          "</h3>" +
          (d.warranty
            ? line("Start", d.warranty.startDate) +
              line("Expiry", d.warranty.expirationDate) +
              line(
                "Odometer limit",
                [d.warranty.odometerLimit, d.warranty.odometerUnit]
                  .filter((v) => v != null)
                  .join(" "),
              )
            : "<small>" + esc(this.tr("Unavailable")) + "</small>");
        detail += list("Oil specification", d.oil?.norms, (r) =>
          line(
            r.oilNorm || "Oil",
            [r.amount, d.oil.unit].filter((v) => v != null).join(" "),
          ),
        );
      }
      detail += line(
        "Retrieved from myAudi",
        new Date(d.observed_at).toLocaleString(),
      );
    } else detail = "<p>" + esc(this.tr("No dossier retrieved yet.")) + "</p>";
    return (
      '<section class="status-card"><h2>myAudi</h2><button data-myaudi-refresh ' +
      (this.myaudiBusy ? "disabled" : "") +
      ">" +
      esc(this.tr("Refresh myAudi dossier")) +
      "</button>" +
      detail +
      "</section>"
    );
  }
  async serviceDetails(save = false) {
    const row = this.row("sensor.local_dealer");
    if (
      !row ||
      !this._hass?.user?.is_admin ||
      this.loading ||
      this.serviceBusy ||
      (save && !this.serviceDraft)
    )
      return;
    const selected = this.scopeVersion;
    this.serviceBusy = true;
    this.render();
    try {
      const result = await this._hass.callWS({
        type: "audiconnect/vehicle/service_details",
        entity_id: row.entity_id,
        ...(save
          ? {
              updates: Object.fromEntries(
                Object.entries(this.serviceDraft).filter(
                  ([key, value]) =>
                    value !== (this.serviceOriginal?.[key] || ""),
                ),
              ),
            }
          : {}),
      });
      if (this.scopeVersion !== selected) return;
      this.serviceDraft = { ...result.settings };
      this.serviceOriginal = { ...result.settings };
      if (save) this.message = "Service details saved in Home Assistant.";
    } catch {
      if (this.scopeVersion === selected)
        this.message =
          "Service details could not be saved or loaded. Check the entries and access.";
    } finally {
      this.serviceBusy = false;
      this.render();
    }
  }
  identityDetails(state, used) {
    const row = this.row("sensor.model");
    if (!row || !available(state)) return "";
    used.add(row.entity_id);
    const a = state.attributes || {};
    const stamp = (value) => {
      const parsed = Date.parse(value);
      return Number.isFinite(parsed)
        ? new Date(parsed).toLocaleString(this._hass?.language)
        : this.tr("Capture time unknown");
    };
    const details = [
      [
        this.entityLabel(row),
        this.display(state),
        [
          this.identityLabel(state),
          a.presentation_source === "manufacturer"
            ? stamp(a.identity_observed_at)
            : "",
        ]
          .filter(Boolean)
          .join(" · "),
      ],
      [
        this.tr("Model year"),
        a.model_year || this.tr("Model year unknown"),
        a.model_year ? stamp(a.year_observed_at) : "",
      ],
    ];
    return (
      '<section class="status-card"><h2>' +
      esc(this.tr("Manufacturer identity")) +
      "</h2>" +
      details
        .map(
          ([label, value, evidence]) =>
            '<div class="status-row"><span>' +
            esc(label) +
            '</span><span class="status-value">' +
            esc(value) +
            (evidence ? "<small>" + esc(evidence) + "</small>" : "") +
            "</span></div>",
        )
        .join("") +
      '<button data-entity="' +
      esc(row.entity_id) +
      '" data-details>' +
      esc(this.tr("More details")) +
      "</button></section>"
    );
  }
  officialDocuments(maintenance = false) {
    const links = maintenance
      ? [
          ["Owner's Manual", this.manualURL()],
          ["myAudi", "https://my.audi.com/"],
        ]
      : DOCS.map(([label, url]) => [
          label,
          label === "Owner's Manual" ? this.manualURL() : url,
        ]);
    return (
      "<section><h2>" +
      esc(
        this.tr(
          maintenance
            ? "Manufacturer maintenance information"
            : "Official documents & information",
        ),
      ) +
      '</h2><p class="muted">' +
      esc(
        this.tr(
          maintenance
            ? "Use the official manual for maintenance instructions and myAudi for available service records. These are external services, not synchronized maintenance history."
            : "Open the official Audi services. Select your vehicle in the external service; availability depends on your market and account.",
        ),
      ) +
      '</p><div class="actions">' +
      links
        .map(
          ([label, url]) =>
            '<a href="' +
            esc(url) +
            '" target="_blank" rel="noopener noreferrer">' +
            esc(this.tr(label)) +
            " ↗</a>",
        )
        .join("") +
      "</div></section>"
    );
  }
  manualURL() {
    const language = String(this._hass?.language || "en")
      .toLowerCase()
      .replace("_", "-");
    const locale = {
      nl: "nl_NL",
      "nl-nl": "nl_NL",
      "nl-be": "nl_NL",
      fr: "fr_FR",
      "fr-fr": "fr_FR",
      "fr-be": "fr_FR",
      de: "de_DE",
      "de-de": "de_DE",
      "de-at": "de_DE",
      en: "en_GB",
      "en-gb": "en_GB",
    }[language];
    return "https://ownersmanual.audi.com/" + (locale ? "home/" + locale : "");
  }
  hasConfiguredDealer() {
    const state = this.reading("sensor.local_dealer");
    return available(state) && state.attributes?.configured === true;
  }
  configurationURL() {
    const entry = this.current()?.configuration_entry;
    return (
      "/config/integrations/integration/audiconnect" +
      (typeof entry === "string" && entry
        ? "#config_entry=" + encodeURIComponent(entry)
        : "")
    );
  }
  serviceHTML() {
    const row = this.row("sensor.local_dealer");
    const admin = this._hass?.user?.is_admin;
    if (!row && !admin) return "";
    const state = row && this.state(row);
    const fields = [
      ["dealer_name", "Dealer"],
      ["dealer_city", "City"],
      ["dealer_address", "Address"],
      ["dealer_phone", "Phone"],
      ["dealer_website", "Website"],
      ["next_service_date", "Next appointment"],
      ["warranty_expiry", "Warranty expiry"],
    ];
    const editing = admin && row && this.serviceDraft;
    let content = "";
    if (editing) {
      content =
        '<div class="service-form">' +
        fields
          .map(
            ([key, label]) =>
              "<label>" +
              esc(this.tr(label)) +
              '<input maxlength="255" type="' +
              (key.endsWith("_date") || key === "warranty_expiry"
                ? "date"
                : "text") +
              '" data-service-field="' +
              key +
              '" value="' +
              esc(this.serviceDraft[key] || "") +
              '"></label>',
          )
          .join("") +
        '</div><div class="actions"><button class="action" data-service-save ' +
        (this.serviceBusy ? "disabled" : "") +
        (">" +
          esc(this.tr("Save details")) +
          "</button><button data-service-cancel ") +
        (this.serviceBusy ? "disabled" : "") +
        (">" + esc(this.tr("Close")) + "</button></div>");
    } else if (this.hasConfiguredDealer()) {
      content = fields
        .map(([key, label]) => [
          label,
          key === "dealer_name" ? state.state : state.attributes[key],
        ])
        .filter(([, value]) => typeof value === "string" && value)
        .map(
          ([label, value]) =>
            '<div class="status-row"><span>' +
            esc(this.tr(label)) +
            '</span><span class="status-value">' +
            esc(value) +
            "</span></div>",
        )
        .join("");
    } else if (row) {
      content = this.domainRow(row);
    }
    const actions = admin
      ? '<div class="actions">' +
        (row && !editing
          ? "<button data-service-edit " +
            (this.serviceBusy ? "disabled" : "") +
            (">" + esc(this.tr("Edit service details")) + "</button>")
          : "") +
        '<a href="' +
        esc(this.configurationURL()) +
        '">' +
        esc(this.tr("Open Audi Connect configuration")) +
        "</a></div>"
      : "";
    return (
      '<section class="status-card"><h2>' +
      esc(this.tr("Service contact")) +
      '</h2><p class="muted">' +
      esc(this.tr("Your local information, not manufacturer records.")) +
      "</p>" +
      content +
      actions +
      "</section>"
    );
  }
  climateActions(row) {
    const alias = this.row("switch.climate_quick_control");
    const rows = [row, alias].filter(Boolean);
    return ["turn_on", "turn_off"].flatMap((service) => {
      for (const candidate of rows) {
        const action = actionsFor(candidate, this.state(candidate)).find(
          (a) => a.service === service,
        );
        if (action) return [{ row: candidate, action }];
      }
      return [];
    });
  }
  climatePanel(row, rows = [], used = new Set()) {
    const state = this.state(row);
    const a = state?.attributes || {};
    const temp =
      typeof a.temperature === "number" && Number.isFinite(a.temperature)
        ? a.temperature
        : null;
    const unit =
      a.temperature_unit ||
      this._hass?.config?.unit_system?.temperature ||
      "°C";
    const targetSource =
      a.target_temperature_source === "local_pending"
        ? "Local preference · applied on next start"
        : a.target_temperature_source === "optimistic"
          ? "Requested temperature · awaiting vehicle"
          : a.target_temperature_source === "last_known_vehicle"
            ? "Last reported target"
            : "";
    const source = a.state_is_optimistic
      ? "Requested · awaiting vehicle"
      : this.observationLabel(state);
    const actions = this.climateActions(row);
    const related = rows.filter(
      (item) =>
        item.entity_id !== row.entity_id &&
        item.key !== "switch.climate_quick_control" &&
        (/^(button|switch)\./.test(item.key) ||
          [
            "sensor.outdoor_temperature",
            "sensor.remaining_climatisation_time",
            "sensor.next_climatisation_timer_local",
          ].includes(item.key)),
    );
    for (const item of related) used.add(item.entity_id);
    const id = esc(row.entity_id);
    const dial =
      temp !== null &&
      Number.isFinite(a.min_temp) &&
      Number.isFinite(a.max_temp) &&
      a.max_temp > a.min_temp
        ? '<svg viewBox="0 0 200 130" role="img" aria-label="' +
          esc(this.tr("Target temperature")) +
          '"><path d="M24 113 A80 80 0 1 1 176 113" fill="none" stroke="var(--divider-color)" stroke-width="10" stroke-linecap="round"/><path d="M24 113 A80 80 0 1 1 176 113" fill="none" stroke="var(--primary-color)" stroke-width="10" stroke-linecap="round" pathLength="100" stroke-dasharray="' +
          Math.max(
            0,
            Math.min(
              100,
              (100 * (temp - a.min_temp)) / (a.max_temp - a.min_temp),
            ),
          ) +
          ' 100"/><text x="100" y="82" text-anchor="middle" fill="currentColor" font-size="32" font-weight="600">' +
          esc(temp) +
          '°</text><text x="100" y="104" text-anchor="middle" fill="currentColor" font-size="11">' +
          esc(unit) +
          "</text></svg>"
        : '<strong class="climate-unknown">' +
          esc(this.tr("Target temperature unavailable")) +
          "</strong>";
    return (
      '<section class="status-card climate-panel"><h2>' +
      esc(this.tr("Cabin climate")) +
      "</h2>" +
      dial +
      (targetSource
        ? '<p class="muted">' + esc(this.tr(targetSource)) + "</p>"
        : "") +
      "<p>" +
      esc(this.display(state)) +
      (source ? " · " + esc(this.tr(source)) : "") +
      "</p>" +
      '<div class="actions">' +
      actions.map(({ row, action }) => this.actionHTML(row, action)).join("") +
      "</div>" +
      this.editor(row, state) +
      this.commandFeedback(
        [row, this.row("switch.climate_quick_control")].filter(Boolean),
      ) +
      '<button data-entity="' +
      id +
      ('" data-details>' + esc(this.tr("Climate details")) + "</button>") +
      (related.length
        ? '<div class="climate-related">' +
          related.map((item) => this.domainRow(item, true)).join("") +
          "</div>"
        : "") +
      "</section>"
    );
  }
  chargingPanel(rows = [], used = new Set()) {
    const battery = this.reading("sensor.state_of_charge");
    const state = this.reading("sensor.charging_state");
    const plug = this.reading("binary_sensor.plug_state");
    const power = this.reading("sensor.charging_power");
    const eta = this.reading("sensor.remaining_charging_time");
    const complete = this.reading("sensor.charging_complete_time");
    const control = this.row("switch.charging");
    const switchActions = control
      ? actionsFor(control, this.state(control))
      : [];
    const choices = [
      ["turn_on", "button.start_charging_modern", "Start charging"],
      ["turn_off", "button.stop_charging_modern", "Stop charging"],
    ].flatMap(([service, fallbackKey, label]) => {
      const direct = switchActions.find((action) => action.service === service);
      if (direct) return [{ row: control, service, label }];
      const row = this.row(fallbackKey);
      return row &&
        actionsFor(row, this.state(row)).some(
          (action) => action.service === "press",
        )
        ? [{ row, service: "press", label }]
        : [];
    });
    const actions = choices
      .map(({ row, service, label }) =>
        this.actionHTML(row, { service, label }),
      )
      .join("");
    const n = Number(battery?.state);
    const pct =
      available(battery) &&
      battery.attributes?.unit_of_measurement === "%" &&
      Number.isFinite(n) &&
      n >= 0 &&
      n <= 100;
    const fields = [
      ["Charging status", state],
      ["Plug", plug],
      ["Charging power", power],
      ["Time remaining", eta],
      ["Estimated completion", complete],
    ].filter(([, s]) => s);
    const details = this.ordered(rows, [
      "sensor.active_charging_profile_name",
      "sensor.charging_mode",
      "sensor.charging_current_limit_a",
      "sensor.charging_current_limit_mode",
      "sensor.max_charge_current",
      "sensor.actual_charge_rate",
      "sensor.charge_power_limitation_reason",
      "sensor.target_state_of_charge",
      "sensor.active_charging_profile_target_soc",
      "sensor.active_charging_profile_min_soc",
    ]);
    const settings = rows.filter((row) => /^(number|select)\./.test(row.key));
    for (const row of [...details, ...settings]) used.add(row.entity_id);
    const range = this.roleRange("electric");
    return (
      '<section class="status-card charge-panel"><h2>' +
      esc(this.tr("Charging")) +
      "</h2>" +
      (battery
        ? '<div class="charge-level"><strong>' +
          esc(this.display(battery)) +
          "</strong>" +
          (this.observationLabel(battery)
            ? "<small>" + esc(this.observationLabel(battery)) + "</small>"
            : "") +
          (pct
            ? '<div class="meter"><span style="width:' + n + '%"></span></div>'
            : "") +
          "</div>"
        : "") +
      (range
        ? '<p class="total-range">' +
          esc(this.tr("electric range")) +
          " · " +
          esc(this.display(range)) +
          (this.observationLabel(range)
            ? " · " + esc(this.observationLabel(range))
            : "") +
          "</p>"
        : "") +
      [
        ...fields,
        ...details.map((row) => [this.entityLabel(row), this.state(row)]),
      ]
        .map(
          ([label, s]) =>
            '<div class="status-row"><span>' +
            esc(this.tr(label)) +
            '</span><span class="status-value">' +
            esc(this.display(s)) +
            (this.observationLabel(s)
              ? "<small>" + esc(this.observationLabel(s)) + "</small>"
              : "") +
            "</span></div>",
        )
        .join("") +
      (actions ? '<div class="actions">' + actions + "</div>" : "") +
      this.commandFeedback(
        [
          control,
          this.row("button.start_charging_modern"),
          this.row("button.stop_charging_modern"),
        ].filter(Boolean),
      ) +
      (settings.length
        ? '<div class="charge-settings"><h3>' +
          esc(this.tr("Settings")) +
          "</h3>" +
          settings.map((row) => this.domainRow(row, true)).join("") +
          "</div>"
        : "") +
      "</section>"
    );
  }
  ownershipHTML() {
    const model = this.reading("sensor.model");
    const classification = this.reading("sensor.car_type");
    const envelope =
      model?.attributes?.connected_services ||
      classification?.attributes?.connected_services;
    const list = envelope?.data?.items;
    if (!Array.isArray(list)) return "";
    return (
      '<section class="status-card"><h2>' +
      esc(this.tr("Connected services")) +
      '</h2><p class="muted">' +
      esc(this.tr("Reported by Audi")) +
      " · " +
      "" +
      esc(
        this.observationLabel({ state: "reported", attributes: envelope }) ||
          this.tr("Capture time unknown"),
      ) +
      '</p><details data-disclosure="connected-services"><summary>' +
      esc(this.tr("Details")) +
      " · " +
      list.length +
      "</summary>" +
      list
        .map(
          (service) =>
            '<div class="status-row"><span>' +
            esc(title(service.id)) +
            '</span><span class="status-value">' +
            (service.expiration_date
              ? esc(this.tr("Expires")) +
                " " +
                esc(service.expiration_date.slice(0, 10))
              : esc(this.tr("Expiry not reported"))) +
            "</span></div>",
        )
        .join("") +
      (list.length
        ? ""
        : "<p>" + esc(this.tr("No service records returned.")) + "</p>") +
      "</details></section>"
    );
  }
  healthHTML() {
    const envelope = this.reading("sensor.service_overview")?.attributes
      ?.health_warning_evidence;
    if (!envelope?.data) return "";
    const data = envelope.data;
    const warningRows = Array.isArray(data.warnings?.items)
      ? data.warnings.items
      : [];
    const campaigns = Array.isArray(data.campaigns?.items)
      ? data.campaigns.items
      : [];
    const rows = [...warningRows, ...campaigns]
      .map(
        (row) =>
          '<div class="status-row"><span>' +
          esc(
            row.text ||
              title(row.type || row.category || "Reported vehicle notice"),
          ) +
          '</span><span class="status-value">' +
          esc(row.occurred_at || "") +
          "</span></div>",
      )
      .join("");
    return (
      '<section class="status-card"><h2>' +
      esc(this.tr("Vehicle health & notices")) +
      '</h2><p class="muted">' +
      esc(
        this.qualityLabel({ state: "reported", attributes: envelope }) ||
          this.tr("Capture time unknown"),
      ) +
      "</p>" +
      (data.tyre_warning_reported === true
        ? '<p class="attention">' +
          esc(this.tr("Tyre warning reported by Audi.")) +
          "</p>"
        : "") +
      (rows ||
        "<p>" +
          esc(
            this.tr(
              "No specific warning was returned. This does not establish that the vehicle has no faults or recalls.",
            ),
          ) +
          "</p>") +
      "</section>"
    );
  }
  timersHTML() {
    const groups =
      this.tab === "Charging"
        ? [
            [
              [
                "sensor.charging_timer_enabled_count",
                "sensor.charging_state",
                "sensor.charging_mode",
              ],
              "charging_timers",
              "Charging schedules",
            ],
            [
              [
                "sensor.charging_state",
                "sensor.charging_timer_enabled_count",
                "sensor.charging_mode",
              ],
              "departure_charging_timers",
              "Departure schedules",
            ],
          ]
        : [
            [
              [
                "climate.climatisation",
                "sensor.climatisation_timer_enabled_count",
              ],
              "climate_timers",
              "Climate schedules",
            ],
            [
              ["climate.climatisation"],
              "departure_climate_timers",
              "Departure schedules",
            ],
            [
              [
                "climate.climatisation",
                "sensor.climatisation_timer_enabled_count",
              ],
              "ventilation_timers",
              "Ventilation schedules",
            ],
          ];
    const enabled = (v) =>
      this.tr(v === true ? "Enabled" : v === false ? "Disabled" : "Unknown");
    return groups
      .map(([keys, detail, label]) => {
        // These native entities project the same canonical detail, not separate sources.
        const envelope = keys
          .map((key) => this.reading(key)?.attributes?.[detail])
          .find((value) => Array.isArray(value?.data?.items));
        if (!envelope) return "";
        const content = envelope.data.items
          .map((timer) => {
            const time =
              timer.departure_datetime_local ||
              timer.target_datetime_local ||
              timer.start_datetime_local ||
              timer.departure_time_local ||
              timer.target_time_local ||
              timer.start_time_local ||
              timer.target_datetime ||
              timer.start_datetime;
            const days =
              timer.recurring_on &&
              Object.keys(timer.recurring_on).filter(
                (day) => timer.recurring_on[day] === true,
              );
            const recurrence = days?.length
              ? days
              : Array.isArray(timer.repetition_days)
                ? timer.repetition_days
                : [];
            const windowEnvelope = timer.preferred_charging_times;
            const windows = Array.isArray(windowEnvelope?.items)
              ? windowEnvelope.items
              : [];
            return (
              '<div class="status-row"><span>' +
              esc(time || this.tr("Time not reported")) +
              (recurrence.length
                ? "<small>" +
                  esc(this.tr("Reported recurrence")) +
                  ": " +
                  esc(
                    recurrence
                      .map((day) => {
                        const token = String(day);
                        const weekday = token.toLowerCase().replace(/s$/, "");
                        const label = [
                          "monday",
                          "tuesday",
                          "wednesday",
                          "thursday",
                          "friday",
                          "saturday",
                          "sunday",
                        ].includes(weekday)
                          ? weekday[0].toUpperCase() + weekday.slice(1)
                          : token;
                        return this.tr(label);
                      })
                      .join(", "),
                  ) +
                  "</small>"
                : "") +
              (typeof timer.climatisation === "boolean"
                ? "<small>" +
                  esc(this.tr("Climate on departure")) +
                  ": " +
                  esc(enabled(timer.climatisation)) +
                  "</small>"
                : "") +
              windows
                .map(
                  (window) =>
                    "<small>" +
                    esc(this.tr("Preferred charging window")) +
                    ": " +
                    esc(
                      window.start_time_local || this.tr("Time not reported"),
                    ) +
                    " – " +
                    esc(window.end_time_local || this.tr("Time not reported")) +
                    " · " +
                    esc(enabled(window.enabled)) +
                    "</small>",
                )
                .join("") +
              (windowEnvelope?.all_items_recognized === false
                ? "<small>" +
                  esc(
                    this.tr("Some schedule details could not be interpreted."),
                  ) +
                  "</small>"
                : "") +
              '</span><span class="status-value">' +
              esc(enabled(timer.enabled)) +
              "</span></div>"
            );
          })
          .join("");
        return (
          '<section class="status-card"><h2>' +
          esc(this.tr(label)) +
          '</h2><p class="muted">' +
          esc(
            this.observationLabel({
              state: "reported",
              attributes: envelope,
            }) || this.tr("Reported schedule"),
          ) +
          " · " +
          esc(this.tr("Read-only vehicle schedule")) +
          "</p>" +
          (content ||
            "<p>" +
              esc(
                this.tr(
                  envelope.data.received_count > 0
                    ? "Schedules were returned but could not be interpreted."
                    : "No schedules reported in this response.",
                ),
              ) +
              "</p>") +
          (content && envelope.data.all_items_recognized === false
            ? '<p class="muted">' +
              esc(this.tr("Some schedule details could not be interpreted.")) +
              "</p>"
            : "") +
          "</section>"
        );
      })
      .join("");
  }
  locationHTML(rows = [], used = new Set()) {
    const row = this.row("device_tracker.position");
    if (!row) return "";
    const state = this.state(row);
    const coordinates = state?.attributes;
    const fields = this.ordered(rows, [
      "sensor.parked_in",
      "sensor.parking_address",
      "sensor.park_time",
      "sensor.position_last_updated",
    ]);
    for (const field of fields) used.add(field.entity_id);
    used.add(row.entity_id);
    const valid =
      available(state) &&
      typeof coordinates?.latitude === "number" &&
      Number.isFinite(coordinates.latitude) &&
      Math.abs(coordinates.latitude) <= 90 &&
      typeof coordinates.longitude === "number" &&
      Number.isFinite(coordinates.longitude) &&
      Math.abs(coordinates.longitude) <= 180;
    return (
      '<section class="status-card"><h2>' +
      esc(this.tr("Last reported parking position")) +
      "</h2>" +
      '<p class="muted">' +
      esc(this.tr("Not live driving GPS.")) +
      " " +
      esc(this.observationLabel(state)) +
      "</p>" +
      fields.map((field) => this.domainRow(field)).join("") +
      (valid
        ? '<div id="parking-map"></div><button data-entity="' +
          esc(row.entity_id) +
          ('" data-details>' + esc(this.tr("Open parking map")) + "</button>")
        : "<p>" + esc(this.tr("Parking position unavailable.")) + "</p>") +
      "</section>"
    );
  }
  async mountMap() {
    const host = this.shadowRoot.getElementById?.("parking-map");
    const row = this.row("device_tracker.position");
    if (
      !host ||
      !row ||
      this.tab !== "Location" ||
      typeof window.loadCardHelpers !== "function"
    )
      return;
    const key = row.entity_id;
    const scope = this.scopeVersion;
    if (this.mapCard && this.mapKey === key) {
      this.mapCard.hass = this._hass;
      host.append(this.mapCard);
      return;
    }
    if (this.mapLoading) return;
    this.mapLoading = true;
    try {
      const helpers = await window.loadCardHelpers();
      if (
        this.scopeVersion !== scope ||
        this.tab !== "Location" ||
        this.row("device_tracker.position")?.entity_id !== key
      )
        return;
      const card = helpers.createCardElement({
        type: "map",
        entities: [key],
        hours_to_show: 0,
        default_zoom: 15,
      });
      card.hass = this._hass;
      this.mapCard = card;
      this.mapKey = key;
      this.shadowRoot.getElementById?.("parking-map")?.append(card);
    } catch {
      // Native more-info remains available; do not send coordinates to another provider.
    } finally {
      this.mapLoading = false;
      if (
        this.scopeVersion !== scope &&
        this.tab === "Location" &&
        this.current()
      )
        void this.mountMap();
    }
  }
  formatMeasurement(value) {
    return value.toLocaleString(this._hass?.language, {
      maximumFractionDigits: 3,
    });
  }
  tripChart(trips) {
    const metrics = [
      ["mileage", "Distance", "km", "distance"],
      ["totalElectricConsumption", "Electric", "kWh", "electric"],
      ["totalFuelConsumption", "Fuel", "L", "fuel"],
    ];
    const records = trips.slice(0, 12).reverse();
    return metrics
      .map(([key, label, unit, style]) => {
        const values = records.filter(
          (trip) =>
            typeof trip[key] === "number" &&
            Number.isFinite(trip[key]) &&
            trip[key] >= 0,
        );
        if (!values.length) return "";
        const max = Math.max(1, ...values.map((trip) => trip[key]));
        return (
          '<div class="trip-chart ' +
          style +
          '" aria-label="' +
          esc(this.tr(label)) +
          '"><h3>' +
          esc(this.tr(label)) +
          " · " +
          esc(unit) +
          "</h3>" +
          values
            .map(
              (trip) =>
                "<div><small>" +
                esc(
                  new Date(trip.timestamp).toLocaleDateString(
                    this._hass?.language,
                  ),
                ) +
                '</small><div class="meter"><span style="width:' +
                (100 * trip[key]) / max +
                '%"></span></div><span>' +
                esc(this.formatMeasurement(trip[key])) +
                " " +
                esc(unit) +
                "</span></div>",
            )
            .join("") +
          "</div>"
        );
      })
      .join("");
  }
  archiveTotals(data) {
    if (!data.metrics || !data.total) return "";
    const rows = [
      ["mileage", "Distance", "km"],
      ["totalElectricConsumption", "Electric", "kWh"],
      ["totalFuelConsumption", "Fuel", "L"],
      ["traveltime", "Duration", "min"],
    ];
    return (
      '<section class="status-card"><h2>' +
      esc(this.tr("Observed period totals")) +
      "</h2>" +
      rows
        .map(([key, label, unit]) => {
          const metric = data.metrics[key];
          if (!metric || metric.sum == null) return "";
          return (
            '<div class="status-row"><span>' +
            esc(this.tr(label)) +
            '</span><span class="status-value">' +
            esc(
              Number(metric.sum).toLocaleString(this._hass?.language, {
                maximumFractionDigits: 2,
              }),
            ) +
            " " +
            unit +
            "<small>" +
            esc(
              metric.reported_count +
                " / " +
                data.total +
                " " +
                this.tr("reported"),
            ) +
            "</small></span></div>"
          );
        })
        .join("") +
      "</section>"
    );
  }
  archiveHTML() {
    const row = this.row("sensor.trip_history");
    if (!row) return "";
    const data = this.archive;
    let html =
      "<section><h2>" +
      esc(this.tr("Observed trip archive")) +
      '</h2><p class="muted">' +
      esc(this.tr("Recorded trips only; not a complete lifetime history.")) +
      '</p><div class="service-form">' +
      [
        ["start_date", "From date (UTC)"],
        ["end_date", "Before date (UTC)"],
      ]
        .map(
          ([key, label]) =>
            "<label>" +
            esc(this.tr(label)) +
            '<input type="date" data-trip-date="' +
            key +
            '" value="' +
            esc(this.tripPeriod[key] || "") +
            '"' +
            (this.archiveLoading ? " disabled" : "") +
            "></label>",
        )
        .join("") +
      '</div><div class="actions">' +
      '<button data-trips="0" ' +
      (this.archiveLoading ? "disabled" : "") +
      (">" + esc(this.tr("Apply period")) + "</button>") +
      "<button data-trip-clear " +
      (this.archiveLoading ? "disabled" : "") +
      ">" +
      esc(this.tr("Clear period")) +
      "</button>" +
      "<button data-export " +
      (this.archiveLoading ? "disabled" : "") +
      (">" + esc(this.tr("Export JSON")) + "</button>") +
      '<button data-export="csv" ' +
      (this.archiveLoading ? "disabled" : "") +
      ">" +
      esc(this.tr("Export CSV")) +
      "</button></div>";
    if (data) {
      html +=
        "<p>" +
        esc(data.total) +
        " " +
        esc(this.tr("archived records")) +
        "</p>" +
        (data.start_date || data.end_date
          ? '<p class="muted">' +
            esc(this.tr("Applied period (UTC)")) +
            ": " +
            esc(data.start_date || "—") +
            " / " +
            esc(data.end_date || "—") +
            "</p>"
          : "") +
        this.archiveTotals(data) +
        '<p class="muted">' +
        esc(this.tr("Recent trips on this page")) +
        "</p>" +
        this.tripChart(data.trips || []) +
        ('<div class="table"><table><thead><tr><th>' +
          esc(this.tr("Date")) +
          "</th><th>" +
          esc(this.tr("Distance")) +
          "</th><th>" +
          esc(this.tr("Electric")) +
          "</th><th>" +
          esc(this.tr("Fuel")) +
          "</th></tr></thead><tbody>");
      for (const trip of data.trips || [])
        html +=
          "<tr><td>" +
          esc(new Date(trip.timestamp).toLocaleString(this._hass?.language)) +
          "</td><td>" +
          esc(trip.mileage == null ? "—" : trip.mileage + " km") +
          "</td><td>" +
          esc(
            trip.totalElectricConsumption == null
              ? "—"
              : trip.totalElectricConsumption + " kWh",
          ) +
          "</td><td>" +
          esc(
            trip.totalFuelConsumption == null
              ? "—"
              : trip.totalFuelConsumption + " L",
          ) +
          "</td></tr>";
      html +=
        '</tbody></table></div><div class="actions">' +
        (data.offset > 0
          ? '<button data-page data-trips="' +
            Math.max(0, data.offset - 25) +
            ('">' + esc(this.tr("Previous")) + "</button>")
          : "") +
        (data.offset + 25 < data.total
          ? '<button data-page data-trips="' +
            (data.offset + 25) +
            ('">' + esc(this.tr("Next")) + "</button>")
          : "") +
        "</div>";
    }
    return html + "</section>";
  }
  render() {
    if (!this.shadowRoot) return;
    const vehicle = this.current();
    const all = vehicle?.entities || [];
    const model = this.row("sensor.model");
    const modelState = model && this.state(model);
    const attrs = modelState?.attributes || {};
    const image = available(modelState)
      ? imageURL(attrs.vehicle_image_url)
      : "";
    const freshness = this.row("sensor.vehicle_data_freshness");
    const age = this.row("sensor.vehicle_data_age");
    if (
      vehicle &&
      !["Overview", "Vehicle & Documents", "Settings"].includes(this.tab) &&
      !this.hasTab(this.tab)
    )
      this.tab = "Overview";
    const rows =
      this.tab === "Overview"
        ? all.filter((r) => OVERVIEW.includes(r.key) || QUICK.includes(r.key))
        : all.filter((r) => GROUPS[this.tab]?.test(r.key));
    const nav = TABS.filter((tab) => tab !== "Settings" && this.hasTab(tab))
      .map(
        (tab) =>
          '<button data-tab="' +
          esc(tab) +
          '" aria-pressed="' +
          (tab === this.tab) +
          '">' +
          esc(this.tr(TAB_LABEL[tab] || tab)) +
          "</button>",
      )
      .join("");
    const selector =
      '<select id="vehicle-select" aria-label="' +
      esc(this.tr("Vehicle")) +
      '">' +
      this.vehicles
        .map(
          (v) =>
            '<option value="' +
            esc(v.device_id) +
            '" ' +
            (v.device_id === this.selected ? "selected" : "") +
            ">" +
            esc(v.name) +
            "</option>",
        )
        .join("") +
      "</select>";
    let body = "";
    if (vehicle) {
      const lockState = this.reading("lock.lock");
      const moving = this.reading("binary_sensor.is_moving");
      const lockLabel = available(lockState) ? this.display(lockState) : "";
      const movingLabel =
        available(moving) &&
        moving.attributes?.vehicle_freshness === "fresh" &&
        moving.state === "off"
          ? this.tr("Parked")
          : "";
      const status = [movingLabel, lockLabel].filter(Boolean).join(" · ");
      body =
        '<section class="hero"><div class="hero-head"><div><h1>' +
        esc(available(modelState) ? this.display(modelState) : vehicle.name) +
        "</h1><p>" +
        esc(
          [attrs.model_year, attrs.vehicle_type && title(attrs.vehicle_type)]
            .filter(Boolean)
            .join(" · "),
        ) +
        '</p><p class="muted">' +
        esc(this.identityLabel(modelState)) +
        "</p>" +
        (status
          ? '<p class="hero-status">' +
            esc(status) +
            (lockLabel && this.observationLabel(lockState)
              ? " · " + esc(this.observationLabel(lockState))
              : "") +
            "</p>"
          : "") +
        "</div>" +
        selector +
        "</div>" +
        (this.tab === "Overview" && image
          ? '<div class="vehicle-picture"><img referrerpolicy="no-referrer" alt="' +
            esc(this.tr("Manufacturer vehicle image")) +
            '" src="' +
            esc(image) +
            '"></div>'
          : "") +
        '<div class="hero-footer"><span>' +
        esc(this.tr("Newest vehicle measurement")) +
        " · " +
        esc(
          freshness
            ? this.display(this.state(freshness))
            : this.tr("Freshness unknown"),
        ) +
        (age && available(this.state(age))
          ? " · " + esc(this.display(this.state(age)))
          : "") +
        ('</span><button data-refresh aria-label="' +
          esc(this.tr("Refresh view")) +
          '" title="' +
          esc(this.tr("Refresh view")) +
          '" ') +
        (this.loading ? "disabled" : "") +
        '><ha-icon icon="mdi:refresh"></ha-icon></button></div></section>' +
        ('<nav aria-label="' + esc(this.tr("Vehicle functions")) + '">') +
        nav +
        "</nav>";
      const used = new Set();
      if (this.tab === "Engineering") {
        body +=
          '<section id="engineering-workspace" aria-label="' +
          esc(this.tr("Engineering")) +
          '"></section>';
      } else if (this.tab === "Overview") {
        body +=
          '<div class="overview-layout"><div>' +
          this.energyCards() +
          this.homeActions() +
          this.refreshPanel() +
          "</div><div>" +
          this.statusRows() +
          "</div></div>";
        used.clear();
        for (const row of rows)
          if (
            [
              "sensor.state_of_charge",
              "sensor.tank_level",
              "sensor.range",
              "sensor.door_status",
              "sensor.window_status",
              "sensor.charging_state",
              "sensor.climatisation_state",
              "sensor.parked_in",
              "sensor.mileage",
              "sensor.service_overview",
              "sensor.vehicle_data_freshness",
              "sensor.vehicle_data_age",
              "binary_sensor.integration_problem",
              "button.v3_refresh_cloud",
              "button.refresh_vehicle_data",
              "button.wake_vehicle_modern",
            ].includes(row.key)
          )
            used.add(row.entity_id);
      } else {
        if (this.tab === "Charging") {
          body += this.chargingPanel(rows, used);
          for (const row of rows)
            if (
              [
                "sensor.state_of_charge",
                "sensor.charging_state",
                "binary_sensor.plug_state",
                "sensor.charging_power",
                "sensor.remaining_charging_time",
                "sensor.charging_complete_time",
                "switch.charging",
                "button.start_charging_modern",
                "button.stop_charging_modern",
              ].includes(row.key)
            )
              used.add(row.entity_id);
        }
        if (this.tab === "Climate" && this.row("climate.climatisation")) {
          const climate = this.row("climate.climatisation");
          body += this.climatePanel(climate, rows, used);
          used.add(climate.entity_id);
          const alias = this.row("switch.climate_quick_control");
          if (alias) used.add(alias.entity_id);
        }
        const access =
          this.tab === "Access & Security" ? this.accessStatus(rows) : null;
        if (access) for (const id of access.used) used.add(id);
        if (this.tab === "Location" && this.row("device_tracker.position"))
          body += this.locationHTML(rows, used);
        if (this.tab === "Service & Health") {
          const dealer = this.row("sensor.local_dealer");
          if (dealer) used.add(dealer.entity_id);
        }
        if (this.tab === "Vehicle & Documents")
          body += this.identityDetails(modelState, used);
        body += this.journeyGroups(rows, used);
        if (access) body += access.html;
        const controls = rows.filter(
          (row) =>
            !used.has(row.entity_id) &&
            /^(button|switch|lock|climate|number|select)\./.test(row.key),
        );
        const settings = controls.filter(
          (row) =>
            /^(number|select)\./.test(row.key) ||
            /^switch\.climatisation_/.test(row.key),
        );
        body += this.domainRows(
          "Actions",
          controls.filter((row) => !settings.includes(row)),
          true,
        );
        body += this.domainRows("Settings", settings, true);
        for (const row of controls) used.add(row.entity_id);
      }
      if (this.tab === "Trips & Consumption") body += this.archiveHTML();
      if (this.tab === "Charging" || this.tab === "Climate")
        body += this.timersHTML();
      if (this.tab === "Service & Health")
        body +=
          this.healthHTML() +
          this.serviceHTML() +
          this.myaudiHTML() +
          this.officialDocuments(true);
      if (this.tab === "Vehicle & Documents") body += this.ownershipHTML();
      const remaining = rows.filter((row) => !used.has(row.entity_id));
      let additional = "";
      if (remaining.length) {
        const expanded = this.expanded.has(this.tab);
        additional =
          '<section><button class="disclosure" data-expand aria-expanded="' +
          expanded +
          '">' +
          esc(this.tr(expanded ? "Hide details" : "More details")) +
          "</button>" +
          (expanded
            ? this.domainRows("Additional information", remaining, true)
            : "") +
          "</section>";
      }
      if (this.tab === "Vehicle & Documents")
        body += this.myaudiHTML() + this.officialDocuments();
      if (this.tab === "Settings") {
        const shortcuts = [
          ["Charging", "Charging"],
          ["Climate", "Climate"],
          ["Access & Security", "Access"],
          ["Service & Health", "Service"],
        ].filter(([tab]) => this.hasTab(tab));
        body +=
          '<section class="status-card"><h2>' +
          esc(this.tr("Vehicle preferences")) +
          '</h2><div class="actions">' +
          shortcuts
            .map(
              ([tab, label]) =>
                '<button data-tab="' +
                esc(tab) +
                '">' +
                esc(this.tr(label)) +
                "</button>",
            )
            .join("") +
          "</div></section>";
        body += this.refreshPanel();
        body +=
          "<section><h2>" +
          esc(this.tr("Configuration")) +
          "</h2>" +
          (this._hass?.user?.is_admin
            ? "<p>" +
              esc(
                this.tr(
                  "Manage your account, vehicle preferences, service details and connected data sources.",
                ),
              ) +
              '</p><div class="actions"><a href="' +
              esc(this.configurationURL()) +
              ('">' +
                esc(this.tr("Manage account & preferences")) +
                '</a><a href="/config/devices/device/') +
              esc(vehicle.device_id) +
              ('">' + esc(this.tr("Vehicle device & entities")) + "</a></div>")
            : "<p>" +
              esc(
                this.tr(
                  "Account configuration requires a Home Assistant administrator. You can manage permitted vehicle controls on the function tabs.",
                ),
              ) +
              "</p>") +
          "</section>";
      }
      body += additional;
    } else
      body =
        "<section><h2>" +
        esc(
          this.tr(
            this._hass?.connected === false
              ? "Connection lost"
              : this.loading
                ? "Loading vehicles…"
                : "No accessible Audi vehicles",
          ),
        ) +
        ("</h2><p>" +
          esc(
            this.tr(
              "Check that your Audi account is connected and that you have access to a vehicle.",
            ),
          ) +
          "</p></section>");
    const html =
      "<style>" +
      PANEL_STYLE +
      ('</style><main><header><div style="flex:1"><strong>Audi Connect</strong><div class="muted">' +
        esc(this.tr("My garage")) +
        "</div></div>") +
      (vehicle
        ? '<button class="settings-button" data-tab="Settings" aria-label="' +
          esc(this.tr("Settings")) +
          '" title="' +
          esc(this.tr("Settings")) +
          '"><ha-icon icon="mdi:cog-outline"></ha-icon></button>'
        : "<button data-refresh " +
          (this.loading ? "disabled" : "") +
          (">" + esc(this.tr("Refresh view")) + "</button>")) +
      "</header>" +
      (this.message
        ? '<p class="message" role="status">' +
          esc(this.tr(this.message)) +
          "</p>"
        : "") +
      body +
      "</main>";
    this.updateView(html);
  }
  updateView(html) {
    // Avoid replacing unchanged markup and preserve focus through actual state updates.
    const root = this.shadowRoot;
    if (html !== this._renderedHTML) {
      const active = root.activeElement;
      const key =
        active && this.current()
          ? [active.tagName, active.id, JSON.stringify(active.dataset)]
          : null;
      const selection =
        active?.selectionStart == null
          ? null
          : [active.selectionStart, active.selectionEnd];
      const navScroll = root.querySelector?.("nav")?.scrollLeft || 0;
      const context = this.current() ? this.selected + ":" + this.tab : "";
      const disclosures = new Map(
        this._disclosureContext === context
          ? [
              ...(root.querySelectorAll?.("details[data-disclosure]") || []),
            ].map((detail) => [detail.dataset.disclosure, detail.open])
          : [],
      );
      this._disclosureContext = context;
      root.innerHTML = html;
      for (const detail of root.querySelectorAll?.(
        "details[data-disclosure]",
      ) || [])
        if (disclosures.has(detail.dataset.disclosure))
          detail.open = disclosures.get(detail.dataset.disclosure);
      this._renderedHTML = html;
      const nav = root.querySelector?.("nav");
      if (nav) nav.scrollLeft = navScroll;
      if (key) {
        const next = [
          ...(root.querySelectorAll?.("button,input,select,a") || []),
        ].find(
          (el) =>
            el.tagName === key[0] &&
            el.id === key[1] &&
            JSON.stringify(el.dataset) === key[2] &&
            !el.disabled,
        );
        if (next && (key[1] || key[2] !== "{}")) {
          next.focus({ preventScroll: true });
          if (selection && next.setSelectionRange) {
            try {
              next.setSelectionRange(...selection);
            } catch {
              /* unsupported input type */
            }
          }
        }
      }
    }
    if (this.tab === "Location") void this.mountMap();
    void this.mountEngineering();
  }
}
customElements.define("audiconnect-vehicle-panel", AudiVehiclePanel);
