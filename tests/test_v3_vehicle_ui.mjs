import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const panelLabels = JSON.parse(
  fs.readFileSync(
    "custom_components/audiconnect/v3/frontend/vehicle_labels.json",
    "utf8",
  ),
);
let Panel;
class FakeElement {
  attachShadow() {
    this.shadowRoot = { addEventListener() {}, innerHTML: "" };
    return this.shadowRoot;
  }
  dispatchEvent(event) {
    this.event = event;
  }
}
vm.runInNewContext(
  fs.readFileSync(
    "custom_components/audiconnect/v3/frontend/vehicle.js",
    "utf8",
  ),
  {
    HTMLElement: FakeElement,
    URL,
    window: { confirm: () => true },
    CustomEvent: class {
      constructor(name, options) {
        this.type = name;
        this.detail = options.detail;
      }
    },
    customElements: {
      define(name, klass) {
        assert.equal(name, "audiconnect-vehicle-panel");
        Panel = klass;
      },
    },
  },
);
const lock = {
  key: "lock.lock",
  entity_id: "lock.audi",
  name: "Lock",
  control: true,
};
const target = {
  key: "number.target_state_of_charge",
  entity_id: "number.audi",
  name: "Charge target",
  control: true,
};
const model = {
  key: "sensor.model",
  entity_id: "sensor.model",
  name: "Model",
  control: false,
};
function fixture() {
  const panel = new Panel();
  panel.labels = panelLabels;
  const calls = [];
  panel.vehicles = [
    {
      device_id: "device",
      name: "Audi <script>",
      entities: [lock, target, model],
    },
  ];
  panel.selected = "device";
  panel.loaded = true;
  panel._hass = {
    user: { is_admin: false },
    states: {
      "lock.audi": {
        state: "locked",
        attributes: {
          unlock_enabled: true,
          lock_enabled: false,
          state_source: "last_known_vehicle",
        },
      },
      "number.audi": {
        state: "80",
        attributes: { min: 50, max: 100, step: 5, unit_of_measurement: "%" },
      },
      "sensor.model": { state: "Q8", attributes: { vehicle_type: "phev" } },
    },
    callService: async (...args) => calls.push(args),
    callWS: async (args) => {
      calls.push(args);
      return { vehicles: panel.vehicles };
    },
  };
  return { panel, calls };
}
test("consumer tabs are capability-adaptive and navigation never dispatches", () => {
  const { panel, calls } = fixture();
  panel.render();
  assert.match(panel.shadowRoot.innerHTML, /Audi &lt;script&gt;/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML, /data-tab="Climate"/);
  assert.match(panel.shadowRoot.innerHTML, /data-tab="Charging"/);
  assert.match(
    panel.shadowRoot.innerHTML,
    /data-tab="Vehicle &amp; Documents"/,
  );
  assert.doesNotMatch(panel.shadowRoot.innerHTML, /data-page=/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML, /Engineering Workbench/);
  panel.click({
    target: { closest: () => ({ dataset: { tab: "Charging" } }) },
  });
  assert.match(panel.shadowRoot.innerHTML, /data-save/);
  assert.equal(calls.length, 0);
});
test("native explicit lock operation checks availability and never reports physical success", async () => {
  const { panel, calls } = fixture();
  await panel.run(lock, "unlock");
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "lock");
  assert.equal(calls[0][1], "unlock");
  assert.equal(calls[0][2].entity_id, "lock.audi");
  assert.match(panel.message, /physical execution is not confirmed/);
  await panel.run(lock, "lock");
  await panel.run({ ...lock, control: false }, "unlock");
  assert.equal(calls.length, 1);
});
test("inline configuration sends actual native number service and rejects out-of-range values", async () => {
  const { panel, calls } = fixture();
  panel.drafts.set(target.entity_id, "90");
  await panel.save(target);
  assert.equal(calls[0][0], "number");
  assert.equal(calls[0][1], "set_value");
  assert.equal(calls[0][2].value, 90);
  assert.equal(panel._hass.states[target.entity_id].state, "80");
  panel.drafts.set(target.entity_id, "120");
  await panel.save(target);
  assert.equal(calls.length, 1);
});

test("direct vehicle tabs and overview actions reach settings without extra navigation or requests", () => {
  const { panel, calls } = fixture();
  panel.render();
  assert.match(panel.shadowRoot.innerHTML, /Quick actions/);
  panel.click({
    target: { closest: () => ({ dataset: { tab: "Charging" } }) },
  });
  assert.equal(panel.tab, "Charging");
  assert.match(panel.shadowRoot.innerHTML, /data-save/);
  panel.click({
    target: { closest: () => ({ dataset: { tab: "Vehicle & Documents" } }) },
  });
  assert.equal(panel.tab, "Vehicle & Documents");
  assert.match(panel.shadowRoot.innerHTML, /Owner&#39;s Manual/);
  assert.equal(calls.length, 0);
});
test("climate has direct supported actions and native temperature configuration", async () => {
  const { panel, calls } = fixture();
  const climate = {
    key: "climate.climatisation",
    entity_id: "climate.audi",
    name: "Climate",
    control: true,
  };
  panel.current().entities.push(climate);
  panel._hass.states[climate.entity_id] = {
    state: "off",
    attributes: {
      start_enabled: true,
      stop_enabled: true,
      supported_features: 1,
      temperature: 20,
      min_temp: 15,
      max_temp: 30,
    },
  };
  panel.click({ target: { closest: () => ({ dataset: { tab: "Climate" } }) } });
  assert.match(panel.shadowRoot.innerHTML, /Start climate/);
  assert.match(panel.shadowRoot.innerHTML, /Target temperature/);
  panel.drafts.set(climate.entity_id, "21");
  await panel.save(climate);
  assert.equal(calls[0][0], "climate");
  assert.equal(calls[0][1], "set_temperature");
  assert.equal(calls[0][2].temperature, 21);
  await panel.run(climate, "turn_on");
  assert.equal(calls[1][1], "turn_on");
  panel.drafts.set(climate.entity_id, "50");
  await panel.save(climate);
  assert.equal(calls.length, 2);
});

test("trip chart uses only actual nonnegative distances and preserves zero", () => {
  const { panel } = fixture();
  const result = panel.tripChart([
    { timestamp: "2026-11-27T10:00:00Z", mileage: 12 },
    { timestamp: "2026-11-26T10:00:00Z", mileage: 0 },
    { timestamp: "2026-11-25T10:00:00Z", mileage: null },
  ]);
  assert.match(result, /12 km/);
  assert.match(result, /0 km/);
  assert.doesNotMatch(result, /null km/);
});
test("service edits call the scoped local settings API only for admin", async () => {
  const { panel, calls } = fixture();
  panel.current().entities.push({
    key: "sensor.local_dealer",
    entity_id: "sensor.dealer",
    name: "Dealer",
    control: false,
  });
  await panel.serviceDetails();
  assert.equal(calls.length, 0);
  panel._hass.user.is_admin = true;
  panel._hass.callWS = async (msg) => {
    calls.push(msg);
    return { settings: { dealer_name: "Audi" } };
  };
  await panel.serviceDetails();
  assert.equal(calls[0].entity_id, "sensor.dealer");
  assert.equal(panel.serviceDraft.dealer_name, "Audi");
  panel.serviceDraft.dealer_name = "New dealer";
  await panel.serviceDetails(true);
  assert.equal(calls[1].updates.dealer_name, "New dealer");
  assert.match(panel.message, /saved in Home Assistant/);
});

test("charging and climate timers consume the native structured item envelope, not a guessed array", () => {
  const { panel } = fixture();
  panel.current().entities.push({
    key: "sensor.charging_timer_enabled_count",
    entity_id: "sensor.timers",
    name: "Timers",
    control: false,
  });
  panel._hass.states["sensor.timers"] = {
    state: "1",
    attributes: {
      charging_timers: {
        data: {
          items: [{ enabled: true, target_time_local: "07:30" }],
          received_count: 1,
          normalized_count: 1,
        },
        vehicle_freshness: "stale_last_known",
      },
    },
  };
  panel.tab = "Charging";
  panel.render();
  assert.match(panel.shadowRoot.innerHTML, /07:30/);
  assert.match(panel.shadowRoot.innerHTML, /Read-only vehicle schedule/);
  assert.match(panel.shadowRoot.innerHTML, /Last known/);
});
test("fuel-only car does not advertise charging from a generic range sensor", () => {
  const { panel } = fixture();
  panel.current().entities = [
    model,
    {
      key: "sensor.range",
      entity_id: "sensor.range",
      name: "Range",
      control: false,
    },
  ];
  panel._hass.states["sensor.range"] = {
    state: "500",
    attributes: { unit_of_measurement: "km" },
  };
  panel.render();
  assert.doesNotMatch(panel.shadowRoot.innerHTML, /data-tab="Charging"/);
  assert.match(panel.shadowRoot.innerHTML, /500 km/);
});
test("reported tyre evidence and connected service expiration are surfaced without false clearance", () => {
  const { panel } = fixture();
  panel.current().entities.push({
    key: "sensor.service_overview",
    entity_id: "sensor.service",
    name: "Service",
    control: false,
  });
  panel._hass.states["sensor.service"] = {
    state: "unknown",
    attributes: {
      health_warning_evidence: {
        data: {
          tyre_warning_reported: true,
          warnings: { items: [{ text: "Check tyre pressure" }] },
          campaigns: { items: [] },
        },
      },
    },
  };
  assert.match(panel.healthHTML(), /Tyre warning reported/);
  panel._hass.states["sensor.model"].attributes.connected_services = {
    data: { items: [{ id: "connect", expiration_date: "2027-11-01" }] },
  };
  assert.match(panel.ownershipHTML(), /2027-11-01/);
  panel._hass.states["sensor.service"].attributes.health_warning_evidence.data =
    {};
  assert.match(panel.healthHTML(), /does not establish/);
});

test("configuration opens the correct authorized Audi account and native translated entity names are reused", () => {
  const { panel } = fixture();
  panel.current().configuration_entry = "account-2";
  assert.match(panel.configurationURL(), /#config_entry=account-2$/);
  panel._hass.localize = (key) =>
    key.endsWith(".v3_model.name") ? "Voertuigmodel" : "";
  assert.equal(
    panel.entityLabel({ ...model, translation_key: "v3_model" }),
    "Voertuigmodel",
  );
  assert.equal(panel.entityLabel(model), "Model");
});
test("unknown HVAC mode still allows a supported native target preference without inventing HVAC state", async () => {
  const { panel, calls } = fixture();
  const climate = {
    key: "climate.climatisation",
    entity_id: "climate.audi",
    name: "Climate",
    control: true,
  };
  panel.current().entities.push(climate);
  panel._hass.states[climate.entity_id] = {
    state: "unknown",
    attributes: {
      supported_features: 1,
      min_temp: 15,
      max_temp: 30,
      temperature: 21,
      target_temperature_source: "local_pending",
    },
  };
  assert.match(panel.climatePanel(climate), /Local preference/);
  assert.match(panel.editor(climate, panel.state(climate)), /data-save/);
  panel.drafts.set(climate.entity_id, "22");
  await panel.save(climate);
  assert.equal(calls[0][1], "set_temperature");
  assert.equal(panel._hass.states[climate.entity_id].state, "unknown");
});

test("consumer navigation and native state labels follow the signed-in user's language", () => {
  const { panel } = fixture();
  for (const [language, overview, charge] of [
    ["nl", "Overzicht", "Laden"],
    ["fr", "Vue d’ensemble", "Recharge"],
    ["de", "Übersicht", "Laden"],
    ["es", "Overview", "Charging"],
  ]) {
    panel._hass.language = language;
    panel.render();
    assert.match(
      panel.shadowRoot.innerHTML,
      new RegExp(">" + overview + "</button>"),
    );
    assert.match(
      panel.shadowRoot.innerHTML,
      new RegExp(">" + charge + "</button>"),
    );
  }
  panel._hass.language = "nl";
  panel._hass.formatEntityState = () => "Vergrendeld";
  assert.equal(panel.display(panel._hass.states["lock.audi"]), "Vergrendeld");
});

test("stale UI rows cannot execute after native control permission changes", async () => {
  const { panel, calls } = fixture();
  panel.current().entities = [{ ...lock, control: false }, target, model];
  await panel.run(lock, "unlock");
  assert.equal(calls.length, 0);
  panel.current().entities = [lock, { ...target, control: false }, model];
  panel.drafts.set(target.entity_id, "90");
  await panel.save(target);
  assert.equal(calls.length, 0);
});

test("registry change conceals prior data until native scope is checked and clears denied data", async () => {
  const { panel, calls } = fixture();
  panel.archive = { total: 1, trips: [{ mileage: 12 }] };
  panel.serviceDraft = { dealer_name: "Private" };
  panel.drafts.set(target.entity_id, "90");
  let complete;
  panel._hass.callWS = (msg) => {
    calls.push(msg);
    return new Promise((resolve) => {
      complete = resolve;
    });
  };
  panel.hass = { ...panel._hass, entities: {} };
  assert.equal(panel.current(), undefined);
  assert.doesNotMatch(panel.shadowRoot.innerHTML, /Private/);
  await panel.run(lock, "unlock");
  assert.equal(calls.length, 1);
  complete({ vehicles: [], labels: panelLabels });
  // The panel executes in a separate VM realm; wait for its actual promise continuation.
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(panel.vehicles.length, 0);
  assert.equal(panel.archive, null);
  assert.equal(panel.serviceDraft, null);
  assert.equal(panel.drafts.size, 0);
});

test("specialized charging preserves independent native direction and actual command journal status", () => {
  const { panel } = fixture();
  const charging = {
    key: "switch.charging",
    entity_id: "switch.charge",
    name: "Charging",
    control: true,
  };
  const stop = {
    key: "button.stop_charging_modern",
    entity_id: "button.stop",
    name: "Stop",
    control: true,
  };
  panel.current().entities.push(charging, stop);
  panel._hass.states["switch.charge"] = {
    state: "off",
    attributes: {
      on_enabled: true,
      off_enabled: false,
      command_status: "verified",
      command_requested_at: "2026-11-27T08:00:00Z",
    },
  };
  panel._hass.states["button.stop"] = {
    state: "2026-11-27T09:00:00Z",
    attributes: {
      command_status: "readback_mismatch",
      command_requested_at: "2026-11-27T09:00:00Z",
    },
  };
  const html = panel.chargingPanel();
  assert.match(html, /data-entity="switch.charge" data-service="turn_on"/);
  assert.match(html, /data-entity="button.stop" data-service="press"/);
  assert.match(html, /Vehicle reported a different state/);
  assert.doesNotMatch(html, /Matching vehicle observation/);
});

test("manual language and dealer contact use official link and authorized local state only", () => {
  const { panel } = fixture();
  panel._hass.language = "nl-BE";
  assert.equal(panel.manualURL(), "https://ownersmanual.audi.com/home/nl_NL");
  panel._hass.language = "fr-BE";
  assert.equal(panel.manualURL(), "https://ownersmanual.audi.com/home/fr_FR");
  panel._hass.language = "en";
  panel.current().entities.push({
    key: "sensor.local_dealer",
    entity_id: "sensor.dealer",
    name: "Dealer",
    control: false,
  });
  panel._hass.states["sensor.dealer"] = {
    state: "Audi",
    attributes: {
      configured: true,
      dealer_city: "Brussels",
      dealer_address: "<address>",
      next_service_date: "2027-01-01",
    },
  };
  assert.match(panel.dealerHTML(), /Brussels/);
  assert.match(panel.dealerHTML(), /&lt;address&gt;/);
  assert.match(panel.dealerHTML(), /2027-01-01/);
  panel.current().entities = panel
    .current()
    .entities.filter((row) => row.key !== "sensor.local_dealer");
  assert.equal(panel.dealerHTML(), "");
});

test("trip chart shows independent recorded consumption values and omits missing metrics", () => {
  const { panel } = fixture();
  const graph = panel.tripChart([
    {
      timestamp: "2026-11-27T10:00:00Z",
      mileage: 12,
      totalElectricConsumption: 0,
      totalFuelConsumption: 1.4,
    },
  ]);
  assert.match(graph, /12 km/);
  assert.match(graph, /0 kWh/);
  assert.match(graph, /1.4 L/);
  assert.doesNotMatch(
    panel.tripChart([{ timestamp: "2026-11-27T10:00:00Z", mileage: 12 }]),
    /kWh/,
  );
});

test("unrelated registry update preserves authorized drafts and archive after revalidation", async () => {
  const { panel, calls } = fixture();
  panel.drafts.set(target.entity_id, "90");
  const archive = { total: 1, trips: [{ mileage: 12 }] };
  panel.archive = archive;
  panel.hass = { ...panel._hass, entities: {} };
  assert.equal(panel.current(), undefined);
  await panel.run(lock, "unlock");
  await Promise.resolve();
  assert.equal(calls.length, 1);
  assert.equal(panel.drafts.get(target.entity_id), "90");
  assert.equal(panel.archive, archive);
  assert.equal(panel.current().device_id, "device");
});

test("reported timer variants from native alternate entities are visible without writes", () => {
  const { panel, calls } = fixture();
  panel.current().entities.push({
    key: "sensor.charging_state",
    entity_id: "sensor.charge",
    name: "Charging",
    control: false,
  });
  panel._hass.states["sensor.charge"] = {
    state: "ready",
    attributes: {
      charging_timers: {
        data: {
          items: [
            {
              enabled: true,
              departure_time_local: "08:00",
              repetition_days: ["monday", "friday"],
              climatisation: true,
              preferred_charging_times: {
                items: [
                  {
                    start_time_local: "01:00",
                    end_time_local: "05:00",
                    enabled: false,
                  },
                ],
                received_count: 2,
                normalized_count: 1,
                truncated: false,
                all_items_recognized: false,
              },
            },
          ],
          received_count: 1,
        },
        vehicle_freshness: "stale_last_known",
      },
    },
  };
  panel.tab = "Charging";
  const html = panel.timersHTML();
  for (const value of [
    "08:00",
    "Monday, Friday",
    "Climate on departure",
    "Preferred charging window",
    "01:00",
    "05:00",
    "Disabled",
    "Last known",
    "Some schedule details could not be interpreted.",
  ])
    assert.ok(html.includes(value), value);
  assert.equal(calls.length, 0);
  panel.current().entities.push({
    key: "sensor.climatisation_timer_enabled_count",
    entity_id: "sensor.climate_timers",
    name: "Timers",
    control: false,
  });
  panel._hass.states["sensor.climate_timers"] = {
    state: "1",
    attributes: {
      climate_timers: {
        data: { items: [{ target_time_local: "06:30", enabled: true }] },
      },
    },
  };
  panel.tab = "Climate";
  assert.match(panel.timersHTML(), /06:30/);
});

test("cached identity and individual measurement capture appear in overview", () => {
  const { panel } = fixture();
  panel._hass.states["sensor.model"].attributes.presentation_source =
    "ha_registry_last_known";
  panel._hass.states["sensor.model"].attributes.identity_restored = true;
  panel._hass.states["lock.audi"].attributes.vehicle_captured =
    "2026-11-27T08:00:00Z";
  panel.render();
  assert.match(panel.shadowRoot.innerHTML, /Last known registry identity/);
  assert.match(panel.shadowRoot.innerHTML, /Newest vehicle measurement/);
  assert.ok(
    panel.observationLabel(panel._hass.states["lock.audi"]).includes("2026"),
  );
});

test("maintenance and native integration health expose actual reported quality", () => {
  const { panel } = fixture();
  panel.current().entities.push(
    {
      key: "sensor.service_overview",
      entity_id: "sensor.service",
      name: "Service",
      control: false,
    },
    {
      key: "binary_sensor.integration_problem",
      entity_id: "binary_sensor.problem",
      name: "Integration problem",
      control: false,
    },
  );
  panel._hass.states["sensor.service"] = {
    state: "due_soon",
    attributes: { vehicle_freshness: "stale_last_known" },
  };
  panel._hass.states["binary_sensor.problem"] = { state: "on", attributes: {} };
  assert.match(panel.statusRows(), /Last known/);
  assert.match(panel.statusRows(), /Integration status/);
});

test("registry reconciliation keeps other authorized edits but discards revoked control", async () => {
  const { panel } = fixture();
  panel.drafts.set(target.entity_id, "90");
  panel.drafts.set(lock.entity_id, "locked");
  const changed = {
    ...panel.current(),
    entities: [{ ...lock, control: false }, target, model],
  };
  panel._hass.callWS = async () => ({
    vehicles: [changed],
    labels: panelLabels,
  });
  panel.hass = { ...panel._hass, entities: {} };
  assert.equal(panel.current(), undefined);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(panel.current().device_id, "device");
  assert.equal(panel.drafts.get(target.entity_id), "90");
  assert.equal(panel.drafts.has(lock.entity_id), false);
});

test("access groups native door and window status without duplicate generic cards", () => {
  const { panel } = fixture();
  for (const [key, id, name, state] of [
    [
      "binary_sensor.left_front_door_open",
      "binary_sensor.door",
      "Left front door",
      "on",
    ],
    [
      "binary_sensor.right_rear_window_open",
      "binary_sensor.window",
      "Right rear window",
      "unknown",
    ],
    ["binary_sensor.trunk_open", "binary_sensor.trunk", "Trunk", "off"],
  ]) {
    panel.current().entities.push({ key, entity_id: id, name, control: false });
    panel._hass.states[id] = {
      state,
      attributes: { vehicle_freshness: "stale_last_known" },
    };
  }
  panel.tab = "Access & Security";
  panel.render();
  const html = panel.shadowRoot.innerHTML;
  assert.match(html, /Left front door/);
  assert.match(html, /Right rear window/);
  assert.match(html, /Other openings and security/);
  assert.equal(
    (html.match(/data-entity="binary_sensor.door"/g) || []).length,
    1,
  );
  assert.match(html, /Last known/);
});

test("period query scopes archive and exports preserve zero, missing and fixed CSV columns", async () => {
  const { panel, calls } = fixture();
  panel.current().entities.push({
    key: "sensor.trip_history",
    entity_id: "sensor.archive",
    name: "Archive",
    control: false,
  });
  panel._hass.callWS = async (msg) => {
    calls.push(msg);
    return {
      total: 2,
      offset: msg.offset,
      trips: [],
      start_date: msg.start_date,
      end_date: msg.end_date,
      metrics: {
        mileage: { sum: 42, reported_count: 2 },
        totalFuelConsumption: { sum: 0, reported_count: 1 },
      },
    };
  };
  panel.tripPeriod = { start_date: "2026-11-01", end_date: "2026-12-01" };
  await panel.trips();
  assert.equal(calls[0].start_date, "2026-11-01");
  assert.equal(calls[0].end_date, "2026-12-01");
  assert.match(panel.archiveHTML(), /1 \/ 2 reported/);
  assert.match(panel.archiveHTML(), /0 L/);
  assert.match(panel.archiveHTML(), /Export CSV/);
  assert.match(
    panel.tripCSV([
      {
        timestamp: "2026-11-01T00:00:00Z",
        mileage: 0,
        totalFuelConsumption: 1.2,
      },
    ]),
    /2026-11-01T00:00:00Z,0,,1.2,,,/,
  );
  assert.doesNotMatch(
    panel.tripCSV([{ timestamp: "=malicious()", mileage: 1 }]),
    /malicious/,
  );
  panel.tripPeriod = { start_date: "2026-12-01", end_date: "2026-11-01" };
  await panel.trips();
  assert.equal(calls.length, 1);
});

test("offline scope immediately hides state and rejects command and restores only after revalidation", async () => {
  const { panel, calls } = fixture();
  panel.hass = { ...panel._hass, connected: false };
  assert.equal(panel.current(), undefined);
  assert.match(panel.shadowRoot.innerHTML, /Connection lost/);
  await panel.run(lock, "unlock");
  assert.equal(calls.length, 0);
  panel.hass = { ...panel._hass, connected: true };
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(panel.current());
  assert.equal(calls.length, 1);
});

test("refresh actions are distinct from view refresh and remain native", async () => {
  const { panel, calls } = fixture();
  for (const [key, id] of [
    ["button.v3_refresh_cloud", "button.cloud"],
    ["button.refresh_vehicle_data", "button.vehicle"],
    ["button.wake_vehicle_modern", "button.wake"],
  ]) {
    panel
      .current()
      .entities.push({ key, entity_id: id, name: key, control: true });
    panel._hass.states[id] = { state: "unknown", attributes: {} };
  }
  panel.render();
  assert.match(
    panel.shadowRoot.innerHTML,
    /Refreshing this view does not contact Audi/,
  );
  for (const key of ["button.cloud", "button.vehicle", "button.wake"])
    assert.ok(panel.shadowRoot.innerHTML.includes('data-entity="' + key + '"'));
  assert.equal(calls.length, 0);
  await panel.run(panel.row("button.refresh_vehicle_data"), "press");
  assert.equal(calls.length, 1);
  assert.equal(calls[0][2].entity_id, "button.vehicle");
});

test("service settings save only changed fields, retaining native concurrent changes", async () => {
  const { panel, calls } = fixture();
  panel._hass.user.is_admin = true;
  panel.current().entities.push({
    key: "sensor.local_dealer",
    entity_id: "sensor.dealer",
    name: "Dealer",
    control: false,
  });
  panel._hass.callWS = async (msg) => {
    calls.push(msg);
    return {
      settings: {
        dealer_name: msg.updates?.dealer_name || "Old",
        dealer_city: "Updated elsewhere",
      },
    };
  };
  await panel.serviceDetails();
  panel.serviceDraft.dealer_name = "New";
  await panel.serviceDetails(true);
  assert.deepEqual(Object.keys(calls[1].updates), ["dealer_name"]);
  assert.equal(panel.serviceDraft.dealer_city, "Updated elsewhere");
});

test("climate alias fills only missing native direction", () => {
  const { panel } = fixture();
  const climate = {
    key: "climate.climatisation",
    entity_id: "climate.cabin",
    name: "Cabin",
    control: true,
  };
  const alias = {
    key: "switch.climate_quick_control",
    entity_id: "switch.quick",
    name: "Climate power",
    control: true,
  };
  panel.current().entities.push(climate, alias);
  panel._hass.states[climate.entity_id] = {
    state: "off",
    attributes: { start_enabled: true, stop_enabled: false },
  };
  panel._hass.states[alias.entity_id] = {
    state: "off",
    attributes: { control_actions: { start: true, stop: true } },
  };
  const choices = panel.climateActions(climate);
  assert.equal(choices.length, 2);
  assert.equal(choices[0].row.entity_id, climate.entity_id);
  assert.equal(choices[1].row.entity_id, alias.entity_id);
});

test("offline user switch cannot restore another user's private drafts", async () => {
  const { panel } = fixture();
  panel.drafts.set(target.entity_id, "95");
  panel.tripPeriod = { start_date: "2026-11-01" };
  panel.hass = { ...panel._hass, connected: false };
  panel.hass = { ...panel._hass, user: { id: "different", is_admin: false } };
  assert.equal(panel.drafts.size, 0);
  assert.equal(Object.keys(panel.tripPeriod).length, 0);
  assert.equal(panel.vehicles.length, 0);
});

test("archive pagination back to first page uses applied period not pending edits", async () => {
  const { panel, calls } = fixture();
  panel.current().entities.push({
    key: "sensor.trip_history",
    entity_id: "sensor.archive",
    name: "Archive",
    control: false,
  });
  panel.archive = {
    total: 60,
    offset: 25,
    start_date: "2026-11-01",
    end_date: "2026-12-01",
    trips: [],
  };
  panel.tripPeriod = { start_date: "2026-10-01" };
  panel._hass.callWS = async (msg) => {
    calls.push(msg);
    return {
      total: 60,
      offset: msg.offset,
      start_date: msg.start_date,
      end_date: msg.end_date,
      trips: [],
    };
  };
  await panel.trips(0, false, false, true);
  assert.equal(calls[0].start_date, "2026-11-01");
  assert.equal(calls[0].end_date, "2026-12-01");
});

test("charging groups native profile and settings in the same domain without duplicate controls or requests", () => {
  const { panel, calls } = fixture();
  panel.current().entities.push(
    {
      key: "sensor.active_charging_profile_name",
      entity_id: "sensor.profile",
      name: "Active charging profile",
      control: false,
    },
    {
      key: "sensor.charging_current_limit_a",
      entity_id: "sensor.current",
      name: "Charging current",
      control: false,
    },
  );
  panel._hass.states["sensor.profile"] = {
    state: "Home",
    attributes: { vehicle_freshness: "stale_last_known" },
  };
  panel._hass.states["sensor.current"] = {
    state: "unknown",
    attributes: {},
  };
  panel.tab = "Charging";
  panel.render();
  const html = panel.shadowRoot.innerHTML;
  assert.match(html, /class="charge-settings"/);
  assert.match(html, /Active charging profile/);
  assert.match(html, /Home/);
  assert.match(html, /Last known/);
  assert.match(html, /Charging current/);
  assert.equal(
    (html.match(/data-entity="number.audi" data-save/g) || []).length,
    1,
  );
  assert.equal((html.match(/class="charge-settings"/g) || []).length, 1);
  assert.equal(calls.length, 0);
});

test("domain presentation formats recorded consumption without changing raw data", () => {
  const { panel } = fixture();
  panel._hass.language = "en";
  const trip = {
    timestamp: "2026-11-27T10:00:00Z",
    totalElectricConsumption: 4.469999999999995,
  };
  const html = panel.tripChart([trip]);
  assert.match(html, /4.47 kWh/);
  assert.doesNotMatch(html, /999999/);
  assert.equal(trip.totalElectricConsumption, 4.469999999999995);
});

test("historical request is not presented as a currently awaiting operation", () => {
  const { panel } = fixture();
  panel._hass.states["number.audi"].attributes.command_status =
    "accepted_unconfirmed";
  panel._hass.states["number.audi"].attributes.command_requested_at =
    "2026-11-19T18:00:00Z";
  const html = panel.domainRows("Settings", [target], true);
  assert.match(html, /Last request/);
  assert.match(html, /vehicle result unconfirmed/);
  assert.doesNotMatch(html, /awaiting vehicle/);
  assert.equal((html.match(/data-save/g) || []).length, 1);
});

test("journey groups place inspection and oil change in their own maintenance context", () => {
  const { panel, calls } = fixture();
  for (const [key, id, name] of [
    ["sensor.service_inspection_time", "sensor.inspection", "Inspection time"],
    ["sensor.oil_change_distance", "sensor.oil", "Oil distance"],
  ]) {
    panel.current().entities.push({ key, entity_id: id, name, control: false });
    panel._hass.states[id] = { state: "227", attributes: {} };
  }
  panel.tab = "Service & Health";
  panel.render();
  const html = panel.shadowRoot.innerHTML;
  assert.match(html, /<h2>Inspection<\/h2>/);
  assert.match(html, /<h2>Oil change<\/h2>/);
  assert.equal(
    (html.match(/data-entity="sensor.inspection"/g) || []).length,
    1,
  );
  assert.equal(calls.length, 0);
});
