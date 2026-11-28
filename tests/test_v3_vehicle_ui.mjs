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

test("registry change immediately drops the previous vehicle's archive and reloads native scope", async () => {
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
  assert.equal(panel.archive, null);
  assert.equal(panel.serviceDraft, null);
  assert.equal(panel.drafts.size, 0);
  assert.equal(panel.current(), undefined);
  await panel.run(lock, "unlock");
  assert.equal(calls.length, 1);
  complete({ vehicles: [], labels: panelLabels });
  await Promise.resolve();
  assert.equal(panel.vehicles.length, 0);
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
