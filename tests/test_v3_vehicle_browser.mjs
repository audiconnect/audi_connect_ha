import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const panelScript = pathToFileURL(
  path.resolve("custom_components/audiconnect/v3/frontend/vehicle.js"),
).href;

function browserJourney() {
  const panel = document.querySelector("audiconnect-vehicle-panel");
  const calls = [];
  const assert = (value, msg) => {
    if (!value) throw new Error(msg);
  };
  const tick = async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  };
  const read = (state, attributes = {}) => ({ state, attributes });
  const rows = [
    ["sensor.model", "sensor.model", "Model"],
    ["sensor.state_of_charge", "sensor.battery", "Battery"],
    ["sensor.tank_level", "sensor.fuel", "Fuel"],
    ["sensor.charging_state", "sensor.charge_state", "Charging state"],
    ["number.target_state_of_charge", "number.target", "Charge limit", true],
    ["climate.climatisation", "climate.cabin", "Cabin", true],
    ["lock.lock", "lock.car", "Lock", true],
    ["device_tracker.position", "device_tracker.car", "Parking position"],
    ["sensor.trip_history", "sensor.archive", "Trips"],
    ["sensor.service_overview", "sensor.service", "Service"],
    ["sensor.local_dealer", "sensor.dealer", "Dealer"],
    ["sensor.vehicle_data_freshness", "sensor.freshness", "Freshness"],
  ].map(([key, entity_id, name, control = false]) => ({
    key,
    entity_id,
    name,
    control,
  }));
  const fixture = {
    device_id: "test-car",
    name: "Audi test vehicle",
    configuration_entry: "test-account",
    entities: rows,
  };
  const restricted = {
    device_id: "test-car",
    name: "Audi test vehicle",
    entities: [rows[0], { ...rows[6], control: false }],
  };
  let isAdmin = true;
  let mapConfig;
  window.loadCardHelpers = async () => ({
    createCardElement: (config) => {
      mapConfig = config;
      return document.createElement("div");
    },
  });
  const hass = {
    language: "en",
    user: { id: "admin", is_admin: true },
    states: {
      "sensor.model": read("Q8 test model", {
        model_year: 2025,
        vehicle_type: "phev",
      }),
      "sensor.battery": read("78", {
        unit_of_measurement: "%",
        vehicle_freshness: "fresh",
      }),
      "sensor.fuel": read("64", {
        unit_of_measurement: "%",
        vehicle_freshness: "fresh",
      }),
      "sensor.charge_state": read("ready", { vehicle_freshness: "fresh" }),
      "number.target": read("80", {
        min: 50,
        max: 100,
        step: 5,
        unit_of_measurement: "%",
      }),
      "climate.cabin": read("off", {
        supported_features: 1,
        start_enabled: true,
        stop_enabled: true,
        temperature: 21,
        min_temp: 15,
        max_temp: 30,
      }),
      "lock.car": read("locked", {
        lock_enabled: false,
        unlock_enabled: true,
        state_source: "last_known_vehicle",
      }),
      "device_tracker.car": read("not_home", {
        latitude: 50,
        longitude: 4,
        vehicle_freshness: "stale_last_known",
      }),
      "sensor.archive": read("1"),
      "sensor.service": read("scheduled"),
      "sensor.dealer": read("Audi", {
        configured: true,
        dealer_city: "Test city",
      }),
      "sensor.freshness": read("fresh"),
    },
    callWS: async (msg) => {
      calls.push(msg);
      if (msg.type === "audiconnect/vehicle/list")
        return { vehicles: [isAdmin ? fixture : restricted] };
      if (msg.type === "audiconnect/vehicle/service_details")
        return { settings: msg.updates || { dealer_name: "Audi" } };
      if (msg.type === "audiconnect/vehicle/trips")
        return {
          total: 1,
          offset: 0,
          limit: 25,
          trips: [
            {
              timestamp: "2026-11-27T10:00:00Z",
              mileage: 12,
              totalElectricConsumption: 0,
              totalFuelConsumption: 1.4,
            },
          ],
        };
      throw new Error("Unexpected websocket");
    },
    callService: async (domain, service, data) => {
      calls.push({ domain, service, data });
    },
  };
  window.confirm = () => true;
  async function verify() {
    panel.hass = hass;
    await tick();
    const root = panel.shadowRoot;
    const overflow = () =>
      root.querySelector("main").scrollWidth <=
      root.querySelector("main").clientWidth + 1;
    const tab = (key) => {
      root.querySelector("nav button[data-tab='" + key + "']").click();
      assert(overflow(), key + " overflow");
    };
    assert(root.querySelector(".hero"), "Vehicle hero");
    assert(
      root.querySelectorAll(".energy-grid .energy").length === 2,
      "Battery and fuel",
    );
    assert(root.querySelector(".shortcuts"), "Quick actions");
    const layout = root.querySelector(".overview-layout");
    assert(
      layout && getComputedStyle(layout).display === "grid",
      "Responsive overview grid",
    );
    const columns =
      getComputedStyle(layout).gridTemplateColumns.split(" ").length;
    assert(
      columns === (window.innerWidth >= 900 ? 2 : 1),
      "Responsive overview columns",
    );
    assert(root.querySelector("button[data-tab='Settings']"), "Settings gear");
    assert(overflow(), "Overview overflow");
    assert(
      !root.querySelector(".shortcuts button[data-service='unlock']"),
      "Stale lock must not choose direct unlock",
    );
    const start = calls.length;
    tab("Charging");
    assert(root.querySelector(".charge-panel"), "Specialized charging");
    assert(calls.length === start, "Navigation must not dispatch");
    const input = root.querySelector("input[data-edit-entity='number.target']");
    assert(input, "Charge limit editor");
    input.focus();
    input.value = "90";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    panel.hass = {
      ...hass,
      states: {
        ...hass.states,
        "sensor.charge_state": read("charging", { vehicle_freshness: "fresh" }),
      },
    };
    assert(
      root.activeElement?.dataset.editEntity === "number.target",
      "Focus survives relevant HA update",
    );
    assert(
      root.activeElement.value === "90",
      "Draft survives relevant HA update",
    );
    assert(
      root.textContent.includes("charging"),
      "New status visible while editing",
    );
    root
      .querySelector("button[data-entity='number.target'][data-save]")
      .click();
    await tick();
    assert(
      calls.length === start + 1 &&
        calls.at(-1).service === "set_value" &&
        calls.at(-1).data.value === 90,
      "Native configuration dispatch",
    );
    assert(
      hass.states["number.target"].state === "80",
      "No fabricated readback",
    );
    tab("Climate");
    assert(root.querySelector(".climate-panel svg"), "Climate gauge");
    root.querySelector(".climate-panel button[data-service='turn_on']").click();
    await tick();
    assert(
      calls.at(-1).service === "turn_on" &&
        calls.at(-1).data.entity_id === "climate.cabin",
      "Native climate action",
    );
    tab("Access & Security");
    assert(
      root.querySelector(
        "button[data-entity='lock.car'][data-service='unlock']",
      ),
      "Explicit access action",
    );
    assert(root.textContent.includes("Last known"), "Access freshness");
    tab("Location");
    await tick();
    assert(
      mapConfig?.type === "map" &&
        mapConfig.entities[0] === "device_tracker.car",
      "Native map uses only selected entity",
    );
    assert(root.textContent.includes("Not live driving GPS"), "Parking truth");
    tab("Trips & Consumption");
    await tick();
    assert(
      root.querySelectorAll(".trip-chart").length === 3,
      "Distance, electric and fuel charts",
    );
    assert(root.textContent.includes("0 kWh"), "Recorded zero preserved");
    const from = root.querySelector("input[data-trip-date='start_date']");
    from.value = "2026-11-01";
    from.dispatchEvent(new Event("input", { bubbles: true }));
    root.querySelector("button[data-trips='0']").click();
    await tick();
    assert(
      calls.at(-1).start_date === "2026-11-01",
      "Trip filter uses scoped archive",
    );
    assert(
      root.querySelector("button[data-export='csv']"),
      "CSV export available",
    );
    tab("Service & Health");
    assert(root.textContent.includes("Test city"), "Local service contact");
    root.querySelector("button[data-service-edit]").click();
    await tick();
    const dealer = root.querySelector(
      "input[data-service-field='dealer_name']",
    );
    assert(dealer && dealer.value === "Audi", "Service editor loaded");
    dealer.value = "New dealer";
    dealer.dispatchEvent(new Event("input", { bubbles: true }));
    root.querySelector("button[data-service-save]").click();
    await tick();
    assert(
      calls.at(-1).updates.dealer_name === "New dealer",
      "Scoped service save",
    );
    tab("Vehicle & Documents");
    assert(
      root.querySelector("a[href='https://ownersmanual.audi.com/home/en_GB']"),
      "Official manual",
    );
    root.querySelector("button[data-tab='Settings']").click();
    assert(
      root.querySelector("a[href$='#config_entry=test-account']"),
      "Correct account settings",
    );
    tab("Overview");
    assert(overflow(), "Overview overflow after actions");
    isAdmin = false;
    panel.hass = {
      ...hass,
      user: { id: "resident", is_admin: false },
      entities: {},
    };
    assert(!panel.current(), "Old account view cleared");
    await tick();
    assert(
      !root.querySelector("nav button[data-tab='Trips & Consumption']"),
      "Archive denied",
    );
    assert(
      !root.querySelector("nav button[data-tab='Charging']"),
      "Charging denied",
    );
    tab("Access & Security");
    assert(
      !root.querySelector("button[data-service='unlock']"),
      "Read-only resident cannot dispatch lock",
    );
    root.querySelector("button[data-tab='Settings']").click();
    assert(
      !root.querySelector("a[href*='config_entry=']"),
      "Account admin link denied",
    );
    document.body.dataset.result = "PASS";
  }
  verify().catch((err) => {
    document.body.dataset.result = "FAIL";
    const out = document.createElement("pre");
    out.textContent = err.stack;
    document.body.append(out);
  });
}

const browserScript = "(" + browserJourney.toString() + ")();";

function fixture(width, theme) {
  return (
    '<!doctype html><html><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    "<style>html,body{margin:0;font:16px sans-serif}body{width:" +
    width +
    "px;max-width:100vw;" +
    (theme === "light"
      ? "--primary-text-color:#13171b;--secondary-text-color:#4b5563;--primary-background-color:#f5f6f7;--secondary-background-color:#ffffff;--card-background-color:#ffffff;--divider-color:#d4d8de;--primary-color:#285b89;--text-primary-color:#ffffff;background:#f5f6f7"
      : "--primary-text-color:#f4f4f4;--secondary-text-color:#b9c2cc;--primary-background-color:#13171b;--secondary-background-color:#20262c;--card-background-color:#20262c;--divider-color:#3d4650;--primary-color:#729fcf;--text-primary-color:#10161c;background:#13171b") +
    "}</style></head>" +
    '<body data-result="PENDING"><audiconnect-vehicle-panel></audiconnect-vehicle-panel>' +
    '<script src="' +
    panelScript +
    '"></script><script>' +
    browserScript +
    "</script></body></html>"
  );
}

for (const width of [390, 768, 1280])
  for (const theme of ["dark", "light"]) {
    test(
      "consumer panel in Chromium at " + width + "px (" + theme + ")",
      () => {
        const directory = fs.mkdtempSync(
          path.join(os.tmpdir(), "audi-browser-"),
        );
        try {
          const file = path.join(directory, "fixture.html");
          fs.writeFileSync(file, fixture(width, theme));
          const result = spawnSync(
            process.env.AUDICONNECT_BROWSER || "google-chrome",
            [
              "--headless",
              "--no-sandbox",
              "--disable-dev-shm-usage",
              "--disable-background-networking",
              "--no-first-run",
              "--window-size=" + width + ",900",
              "--virtual-time-budget=3000",
              "--dump-dom",
              pathToFileURL(file).href,
            ],
            { encoding: "utf8", timeout: 30000 },
          );
          assert.ifError(result.error);
          assert.equal(result.status, 0, result.stderr);
          const body = result.stdout.match(/<body[^>]*data-result="([^"]+)"/);
          assert.equal(
            body?.[1],
            "PASS",
            result.stdout.match(/<pre>[\s\S]*?<\/pre>/)?.[0] ||
              "Browser result unavailable",
          );
        } finally {
          fs.rmSync(directory, { recursive: true, force: true });
        }
      },
    );
  }
