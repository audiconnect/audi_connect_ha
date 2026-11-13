import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
let Panel;
let clipboard = [];
class FakeElement {
  attachShadow() {
    this.shadowRoot = {
      addEventListener() {},
      innerHTML: "",
      getElementById() {
        return null;
      },
    };
    return this.shadowRoot;
  }
}
vm.runInNewContext(
  fs.readFileSync("custom_components/audiconnect/v3/frontend/panel.js", "utf8"),
  {
    HTMLElement: FakeElement,
    navigator: {
      clipboard: {
        writeText: async (value) => {
          clipboard.push(value);
        },
      },
    },
    customElements: {
      define(name, klass) {
        assert.equal(name, "audiconnect-v3-panel");
        Panel = klass;
      },
    },
  },
);
test("Read candidate survives route selection and rerender without the obsolete climate wizard", async () => {
  const panel = new Panel();
  panel.selected = "entry";
  panel.vin = "TESTVIN";
  panel.attribute = "stateOfCharge";
  panel.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "TESTVIN", name: "Test Audi", model: "Q8" }],
    },
  ];
  const routes = [
    {
      id: "cariad.selectivestatus.batch",
      family: "cariad",
      method: "GET",
      path: "/a",
    },
    {
      id: "cariad.selectivestatus.targeted",
      family: "cariad",
      method: "GET",
      path: "/b",
    },
  ];
  let saved = null;
  const calls = [];
  panel.api = async (name, data) => {
    calls.push(name);
    if (name === "attribute_routes")
      return { routes, draft: saved, active: routes[0].id };
    if (name === "attribute_save") {
      saved = data.operation;
      return { saved, activated: false };
    }
    if (name === "status") return { counts: {}, rows: [] };
    if (name === "list") return { integrations: panel.entries };
    throw Error("Unexpected WS operation " + name);
  };
  await panel._readRoutes();
  await panel._change({ target: { id: "read-route", value: routes[1].id } });
  panel.render();
  assert.equal(panel.readChoice, routes[1].id);
  await panel._click({
    target: { closest: () => ({ dataset: { action: "read-save" } }) },
  });
  assert.equal(saved, routes[1].id);
  assert.equal(panel.readChoice, routes[1].id);
  assert.equal(calls.includes("routes"), false);
  assert.equal(calls.includes("attribute_activate"), false);
});

test("Workbench keeps engineering views and V2 backlog separate from verified attributes", async () => {
  const panel = new Panel();
  panel.step = 1;
  panel.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "TESTVIN", name: "Audi", model: "Q8" }],
    },
  ];
  panel.selected = "entry";
  panel.vin = "TESTVIN";
  panel.capabilityStatus = {
    counts: {
      v2_attribute_inventory: 109,
      v2_control_inventory: 21,
      v3_verified_attributes: 1,
    },
    rows: [
      {
        capability: "charging",
        aspect: "status",
        attribute: "stateOfCharge",
        entity_key: "state_of_charge",
        status: "verified",
        source: "v3_live_evidence",
        api_family: "cariad",
        path: "charging.batteryStatus.value.currentSOC_pct",
      },
      {
        capability: "remote",
        aspect: "control",
        attribute: "lock",
        status: "migration_pending",
        source: "v2_control_reference",
      },
    ],
  };
  panel.render();
  assert.match(panel.shadowRoot.innerHTML, /Overview/);
  assert.match(panel.shadowRoot.innerHTML, /Capabilities/);
  assert.match(panel.shadowRoot.innerHTML, /Configure & test/);
  assert.match(panel.shadowRoot.innerHTML, /109/);
  assert.match(panel.shadowRoot.innerHTML, /21/);
  assert.match(panel.shadowRoot.innerHTML, /1 fresh/);
  await panel._click({
    target: { closest: () => ({ dataset: { action: "step-2" } }) },
  });
  assert.equal(panel.step, 2);
  assert.match(panel.shadowRoot.innerHTML, /state of charge/);
  panel.api = async (name, data) => {
    assert.equal(name, "attribute_routes");
    assert.equal(data.attribute, "stateOfCharge");
    return {
      routes: [
        {
          id: "cariad.selectivestatus.batch",
          family: "cariad",
          method: "GET",
          kind: "shared_batch",
          result: "verified",
          path: "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs={JOBS}",
        },
      ],
      active: "cariad.selectivestatus.batch",
    };
  };
  await panel._click({
    target: {
      closest: () => ({
        dataset: {
          action: "select-attribute",
          capability: "charging",
          attribute: "stateOfCharge",
        },
      }),
    },
  });
  assert.equal(panel.step, 3);
  assert.equal(panel.attribute, "stateOfCharge");
  assert.match(panel.shadowRoot.innerHTML, /Activate for polling/);
  assert.match(
    panel.shadowRoot.innerHTML,
    /Advanced · define another API path/,
  );
});

test("HA-native Workbench groups by the vehicle's API family", () => {
  const panel = new Panel();
  panel.selected = "sample";
  panel.vin = "VIN1";
  panel.entries = [
    {
      entry_id: "sample",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  panel.capabilityStatus = {
    counts: {
      catalog_jobs: 23,
      not_scanned_jobs: 0,
      observed_jobs: 2,
      not_observed_jobs: 21,
    },
    rows: [
      {
        api_family: "cariad",
        capability: "charging",
        attribute: "stateOfCharge",
        entity_key: "state_of_charge",
        status: "verified",
        source: "v3_live_evidence",
      },
      {
        api_family: "mbb",
        capability: "charging",
        attribute: "stateOfCharge",
        entity_key: "state_of_charge",
        status: "not_tested",
        source: "v2_attribute_reference",
      },
    ],
  };
  panel.render();
  assert.match(panel.shadowRoot.innerHTML, /ha-font-family-body/);
  assert.match(panel.shadowRoot.innerHTML, /Audi Engineering Dashboard/);
  assert.match(panel.shadowRoot.innerHTML, /1 readable/);
  assert.match(panel.shadowRoot.innerHTML, /1 readable/);
  panel.apiFamily = "all";
  panel.render();
  assert.match(panel.shadowRoot.innerHTML, /\/ 2 readable/);
});

test("Wake, lock and climate are independently selectable for guarded physical testing", async () => {
  const p = new Panel();
  p.selected = "test";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "test",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  p.step = 2;
  p.category = "remote";
  p.capabilityStatus = {
    counts: {},
    rows: [],
    control_actions: [
      {
        capability: "remote",
        action: "wake",
        api_family: "cariad",
        candidate_count: 1,
        status: "not_tested",
      },
      {
        capability: "access",
        action: "lock",
        api_family: "cariad",
        candidate_count: 1,
        status: "not_tested",
      },
      {
        capability: "climate",
        action: "start",
        api_family: "cariad",
        candidate_count: 1,
        status: "not_tested",
      },
    ],
  };
  p.render();
  assert.match(p.shadowRoot.innerHTML, /Wake vehicle/);
  assert.match(p.shadowRoot.innerHTML, /Inspect & test/);
  p.api = async (name, args) => {
    assert.equal(name, "control_routes");
    assert.equal(args.capability, "remote");
    assert.equal(args.action, "wake");
    return {
      routes: [
        {
          id: "cariad.remote.wake",
          family: "cariad",
          status: "not_tested",
          path: "/vehicle/v1/vehicles/{VIN}/vehiclewakeuptrigger",
        },
      ],
      requires: "Physical verification",
    };
  };
  await p._click({
    target: {
      closest: () => ({
        dataset: {
          action: "select-control",
          capability: "remote",
          control: "wake",
        },
      }),
    },
  });
  assert.equal(p.controlAction, "wake");
  assert.equal(p.step, 3);
  assert.match(p.shadowRoot.innerHTML, /Send one test command/);
  assert.match(p.shadowRoot.innerHTML, /Physical verification/);
});

test("API evidence shows scan options and restricted historical executions", () => {
  const p = new Panel();
  p.step = 4;
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  p.apiHistory = [
    {
      operation: "cariad.discovery.full",
      family: "cariad",
      method: "GET",
      at: "2026-11-11T20:00:00+00:00",
      http_status: 200,
      result: "http_ok",
      preview: { soc: 97 },
    },
  ];
  p.render();
  assert.match(p.shadowRoot.innerHTML, /Quick scan/);
  assert.match(p.shadowRoot.innerHTML, /Full read-only scan/);
  assert.match(p.shadowRoot.innerHTML, /Last result and response by API route/);
  assert.match(p.shadowRoot.innerHTML, /2026-11-11T20:00:00/);
  assert.doesNotMatch(p.shadowRoot.innerHTML, /Climate \(guided controls\)/);
  assert.doesNotMatch(p.shadowRoot.innerHTML, /Control migration pending/);
});

test("Manual scan sends GET-family command only", async () => {
  const p = new Panel();
  p.step = 3;
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  const commands = [];
  p.api = async (name, data) => {
    commands.push(name);
    if (name === "test_family_reads") {
      assert.equal(data.family, "cariad");
      return { family: "cariad", request_count: 1 };
    }
    if (name === "routes") return { routes: [], history: [] };
    if (name === "status") return { counts: {}, rows: [] };
    if (name === "list") return { integrations: p.entries };
    if (name === "api_results") return { records: [] };
    throw Error("Unexpected command " + name);
  };
  await p._click({
    target: { closest: () => ({ dataset: { action: "family-test" } }) },
  });
  assert.deepEqual(
    commands.filter((x) => x.includes("test")),
    ["test_family_reads"],
  );
});

test("Alternative access command template exposes only reserved runtime placeholders", () => {
  const p = new Panel();
  p.step = 3;
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", api_family: "cariad", name: "Audi", model: "Q8" },
      ],
    },
  ];
  p.controlCapability = "access";
  p.controlAction = "unlock";
  p.controlRoutes = [
    {
      id: "cariad.access.unlock",
      family: "cariad",
      path: "/vehicle/v1/vehicles/{VIN}/access/unlock",
      status: "not_tested",
    },
  ];
  p.controlChoice = "cariad.access.unlock";
  const template = JSON.parse(p.initialControlRoute);
  assert.equal(template.path, "/vehicle/v1/vehicles/{VIN}/access/unlock");
  assert.deepEqual(JSON.parse(JSON.stringify(template.body)), {
    spin: "{SPIN}",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(template.variables)), {});
  p.render();
  assert.match(
    p.shadowRoot.innerHTML,
    /Advanced · Add an alternative command template/,
  );
  assert.match(p.shadowRoot.innerHTML, /Do not enter or save a real S-PIN/);
  assert.doesNotMatch(p.shadowRoot.innerHTML, /9876/);
});

test("Saving an access command template does not send a POST or require PIN input", async () => {
  const p = new Panel();
  p.step = 3;
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", api_family: "cariad", name: "Audi", model: "Q8" },
      ],
    },
  ];
  p.controlCapability = "access";
  p.controlAction = "lock";
  const data = p.initialControlRoute;
  const calls = [];
  assert.match(p.definitionFields("control", data), /data-field="path"/);
  p.api = async (name, args) => {
    calls.push(name);
    if (name === "add_route") {
      assert.equal(args.route.body.spin, "{SPIN}");
      assert.equal(args.route.path, "/vehicle/v1/vehicles/{VIN}/access/lock");
      return { operation: "user.access.lock.alternative" };
    }
    if (name === "routes") return { routes: [], history: [] };
    if (name === "status") return { counts: {}, rows: [] };
    if (name === "attribute_routes") return { routes: [] };
    if (name === "control_routes")
      return {
        routes: [
          {
            id: "user.access.lock.alternative",
            family: "cariad",
            method: "POST",
            path: "/vehicle/v1/vehicles/{VIN}/access/lock",
            status: "not_tested",
          },
        ],
      };
    if (name === "list") return { integrations: p.entries };
    throw Error("Unexpected command " + name);
  };
  await p._click({
    target: { closest: () => ({ dataset: { action: "control-add" } }) },
  });
  assert.deepEqual(
    calls.filter((x) => /test|control_test/.test(x)),
    [],
  );
  assert.equal(p.controlChoice, "user.access.lock.alternative");
});

test("Discovery modes do not send commands; exact approval is required", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  p.capabilityStatus = {
    counts: {},
    rows: [],
    control_actions: [
      {
        capability: "remote",
        action: "wake",
        api_family: "cariad",
        candidate_count: 1,
        approval_groups: ["non_spin"],
      },
      {
        capability: "access",
        action: "unlock",
        api_family: "cariad",
        candidate_count: 1,
        approval_groups: ["spin"],
      },
    ],
  };
  const calls = [];
  p.api = async (name, args) => {
    calls.push({ name, args });
    if (name === "control_test") return { sequence: 1 };
    if (name === "routes") return { routes: [], history: [] };
    if (name === "status") return p.capabilityStatus;
    if (name === "control_routes")
      return { routes: p.controlRoutes, spin_configured: true };
    if (name === "api_results") return { records: [] };
    if (name === "list") return { integrations: p.entries };
    throw Error(name);
  };
  const click = (action, group) =>
    p._click({ target: { closest: () => ({ dataset: { action, group } }) } });
  await click("discovery-group", "spin");
  assert.equal(p.discoveryGroup, "spin");
  assert.equal(calls.length, 0);
  p.controlCapability = "access";
  p.controlAction = "unlock";
  p.step = 3;
  p.controlChoice = "cariad.access.unlock";
  p.controlRoutes = [
    { id: p.controlChoice, family: "cariad", approval_group: "spin" },
  ];
  p.spinConfigured = true;
  await click("control-test");
  assert.equal(calls.filter((x) => x.name === "control_test").length, 0);
  p.shadowRoot.getElementById = (id) =>
    id === "control-approval" ? { checked: true } : null;
  await click("control-test");
  const sent = calls.filter((x) => x.name === "control_test");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].args.approval, "spin");
  assert.equal(sent[0].args.operation, "cariad.access.unlock");
});

test("cockpit separates tested operations, active bindings and physical evidence", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        {
          vin: "VIN1",
          name: "Audi",
          model: "Q8",
          api_family: "cariad",
          start_enabled: true,
        },
      ],
    },
  ];
  p.capabilityStatus = {
    counts: {},
    rows: [],
    operations: [
      {
        operation: "test.read",
        family: "cariad",
        method: "GET",
        tested: true,
        active: true,
        schema: "valid",
        fields: [
          {
            path: "oil.level",
            type: "boolean",
            quality: "valid",
            mapping: "unmapped",
          },
        ],
      },
      {
        operation: "test.command",
        family: "cariad",
        method: "POST",
        tested: true,
        active: false,
        physical: "unknown",
        attention: ["needs physical proof"],
      },
      {
        operation: "test.pending",
        family: "cariad",
        method: "GET",
        tested: false,
      },
    ],
    findings: [
      {
        severity: "warning",
        reason: "needs physical proof",
        capability: "climate",
      },
    ],
  };
  p.render();
  assert.match(p.shadowRoot.innerHTML, /Enabled controls/);
  assert.match(p.shadowRoot.innerHTML, /oil.level/);
  assert.match(p.shadowRoot.innerHTML, /test.pending/);
  await p._change({ target: { id: "operation-filter", value: "attention" } });
  assert.match(p.shadowRoot.innerHTML, /test.command/);
  assert.doesNotMatch(p.shadowRoot.innerHTML, /test.pending/);
});

test("controls filter never leaks another capability and vehicle changes clear selection", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.step = 2;
  p.category = "climate";
  p.discoveryGroup = "non_spin";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  p.capabilityStatus = {
    rows: [],
    control_actions: [
      {
        capability: "climate",
        action: "start",
        api_family: "cariad",
        candidate_count: 1,
        approval_groups: ["non_spin"],
      },
      {
        capability: "charging",
        action: "set_target_soc",
        api_family: "cariad",
        candidate_count: 1,
        approval_groups: ["non_spin"],
      },
    ],
  };
  p.render();
  assert.match(p.shadowRoot.innerHTML, /data-control="start"/);
  assert.doesNotMatch(p.shadowRoot.innerHTML, /data-control="set_target_soc"/);
  p.controlAction = "start";
  p.pending = { sequence: 1 };
  p.apiHistory = [{}];
  p._resetVehicleSelection();
  assert.equal(p.controlAction, "");
  assert.equal(p.pending, null);
  assert.equal(p.apiHistory.length, 0);
  assert.equal(p.step, 1);
});

test("failed route lookup clears old action and prevents stale dispatch", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.controlChoice = "old.route";
  p.controlRoutes = [{ id: "old.route", approval_group: "non_spin" }];
  p.api = async () => {
    throw Error("lookup failed");
  };
  await p._click({
    target: {
      closest: () => ({
        dataset: {
          action: "select-control",
          capability: "climate",
          control: "stop",
        },
      }),
    },
  });
  assert.equal(p.controlChoice, "");
  assert.equal(p.controlRoutes.length, 0);
  assert.match(p.error, /lookup failed/);
});
test("review finding opens only the affected evidence without sending vehicle commands", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.capabilityStatus = {
    rows: [],
    findings: [{ operation: "cariad.test", reason: "http_error" }],
  };
  p.api = async () => {
    throw Error("No request expected");
  };
  await p._click({
    target: {
      closest: () => ({ dataset: { action: "inspect-finding", index: "0" } }),
    },
  });
  assert.equal(p.step, 4);
  assert.equal(p.focusOperation, "cariad.test");
});

test("loading historical evidence is local, escapes payload HTML and resets on vehicle change", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  p.step = 4;
  const calls = [];
  p.api = async (name, data) => {
    calls.push([name, data]);
    return {
      records: [],
      engineering_history: [
        {
          operation: "test.read",
          family: "cariad",
          method: "GET",
          at: "now",
          http_status: 207,
          payload: { vin: "{VIN}", target: 15.5, detail: "<script>" },
        },
      ],
    };
  };
  await p._apiResults();
  p.render();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "api_results");
  assert.match(p.shadowRoot.innerHTML, /15\.5/);
  assert.match(p.shadowRoot.innerHTML, /\{VIN\}/);
  assert.match(p.shadowRoot.innerHTML, /&lt;script&gt;/);
  p._resetVehicleSelection();
  assert.equal(p.engineeringHistory.length, 0);
});

test("selected test and historical execution show request and response without another click", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.step = 4;
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  p.api = async (name, data) => {
    assert.equal(name, "api_results");
    assert.equal(data.include_engineering, true);
    return {
      records: [],
      engineering_history: [
        {
          operation: "test.read",
          family: "cariad",
          method: "GET",
          at: "now",
          http_status: 207,
          request: { payload: { method: "GET", url: "/vehicles/{VIN}" } },
          payload: { value: 15.5 },
        },
      ],
    };
  };
  await p._apiResults();
  p.render();
  assert.match(p.shadowRoot.innerHTML, /Request sent/);
  assert.match(p.shadowRoot.innerHTML, /Response received/);
  assert.match(p.shadowRoot.innerHTML, /15\.5/);
  assert.match(p.shadowRoot.innerHTML, /<details class="record" open>/);
});

test("HAR identity template exposes fixed variables without browser credentials", () => {
  const p = new Panel();
  p.step = 3;
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  const op = "graphql.inventory.webOrdered";
  p.apiFamily = "all";
  p.capabilityStatus = {
    counts: {},
    rows: [],
    operations: [
      {
        operation: op,
        method: "POST",
        path: "/vgql/v1/graphql",
        family: "graphql",
        read_only: true,
        capabilities: ["vehicle_identity"],
        mappings: [],
      },
    ],
    identity_templates: { [op]: "query GET_USER_VEHICLES_ORDERED_BY" },
    identity_fixed_parameters: {
      [op]: {
        operationName: "GET_USER_VEHICLES_ORDERED_BY",
        variables: { orderBy: "FAVORITE_AND_REGISTRATION" },
      },
    },
  };
  p.openIdentityEditor(op);
  assert.match(p.shadowRoot.innerHTML, /FAVORITE_AND_REGISTRATION/);
  assert.match(p.shadowRoot.innerHTML, /data-field="variables"/);
  assert.doesNotMatch(
    p.shadowRoot.innerHTML,
    /<textarea [^>]*data-field="query"[^>]*readonly/,
  );
  assert.match(p.shadowRoot.innerHTML, /not a web session replay/);
});

test("uncertain vehicle command identifies blocker and leaves read-only workbench accessible", () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  p.capabilityStatus = {
    counts: {},
    rows: [],
    normal_command: {
      operation: "cariad.climate.window_heating_start",
      capability: "climate",
      command_id: "cmd1",
      state: "uncertain",
      started_at: 1794500000,
    },
  };
  p.render();
  assert.match(p.shadowRoot.innerHTML, /last command outcome uncertain/i);
  assert.equal(p.capabilityBlocked("climate"), false);
  assert.equal(p.capabilityBlocked("access"), false);
  assert.match(p.shadowRoot.innerHTML, /cariad.climate.window_heating_start/);
  assert.match(p.shadowRoot.innerHTML, /No review required/);
  assert.match(
    p.shadowRoot.innerHTML,
    /Read-only polling and query experiments remain available/,
  );
});

test("identity draft loads per template and reset restores built-in definition", () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  const op = "graphql.inventory.vehicleList";
  p.capabilityStatus = {
    counts: {},
    rows: [],
    operations: [
      {
        operation: op,
        method: "POST",
        path: "/vgql/v1/graphql",
        family: "graphql",
        read_only: true,
        capabilities: ["vehicle_identity"],
        mappings: [],
      },
    ],
    identity_templates: { [op]: "{ userVehicles { vin } }" },
    identity_drafts: {
      [op]: {
        query: "query Probe { userVehicles { vin nickname } }",
        variables: {},
      },
    },
  };
  p.openIdentityEditor(op);
  assert.match(
    p.definitionValue("identity", p.identityDefinition).query,
    /Probe/,
  );
  assert.match(p.shadowRoot.innerHTML, /Save local draft/);
  p.openIdentityEditor(op, true);
  assert.equal(
    p.definitionValue("identity", p.identityDefinition).query,
    "{ userVehicles { vin } }",
  );
});

test("template field edits survive rerender and invalid JSON without cross-vehicle drift", () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  const template = JSON.stringify({
    path: "/original",
    body: { action: "start" },
  });
  const key = p.definitionKey("control", template);
  p.definitionEdits.set(key + ":path", "/changed");
  p.definitionEdits.set(key + ":body", '{"action":"stop"}');
  assert.match(p.definitionFields("control", template), /\/changed/);
  assert.equal(p.definitionValue("control", template).body.action, "stop");
  p.definitionEdits.set(key + ":body", "{");
  assert.throws(
    () => p.definitionValue("control", template),
    /Invalid JSON in body/,
  );
  assert.match(p.definitionFields("control", template), /data-field="body"/);
  p.vin = "VIN2";
  assert.equal(p.definitionValue("control", template).path, "/original");
});

test("read editor seeds from selected backend mapping not unrelated charging defaults", () => {
  const p = new Panel();
  p.attribute = "doorLockStatus";
  p.readChoice = "cariad.selectivestatus.batch";
  p.readRoutes = [
    {
      id: p.readChoice,
      kind: "shared_batch",
      family: "cariad",
      path: "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs={JOBS}",
      response_paths: ["access.lock"],
    },
    {
      id: "targeted",
      kind: "targeted_job",
      family: "cariad",
      path: "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=access",
      response_paths: ["access.lock"],
    },
  ];
  const template = JSON.parse(p.initialReadRoute);
  assert.equal(template.response_path, "access.lock");
  assert.match(template.path, /jobs=access$/);
});

test("save and test read template executes only GET test and keeps new route selected", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.step = 3;
  p.attribute = "stateOfCharge";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  p.readRoutes = [
    {
      id: "target",
      kind: "targeted_job",
      family: "cariad",
      path: "/vehicle/v1/vehicles/{VIN}/selectivestatus?jobs=charging",
      response_paths: ["charging.soc"],
    },
  ];
  p.readChoice = "target";
  const template = p.initialReadRoute;
  p.definitionEdits.set(
    p.definitionKey("read", template) + ":response_path",
    "charging.changed",
  );
  const calls = [];
  p.api = async (name, args) => {
    calls.push(name);
    if (name === "attribute_add") {
      assert.equal(args.definition.response_path, "charging.changed");
      return { saved: "user.read.stateofcharge_mapping", activated: false };
    }
    if (name === "attribute_test") {
      assert.equal(args.operation, "user.read.stateofcharge_mapping");
      return { route: args.operation, result: "verified" };
    }
    if (name === "routes") return { routes: [], history: [] };
    if (name === "status") return { counts: {}, rows: [] };
    if (name === "attribute_routes")
      return {
        routes: [
          ...p.readRoutes,
          {
            id: "user.read.stateofcharge_mapping",
            family: "cariad",
            kind: "custom",
            path: "/new",
            response_paths: ["charging.changed"],
          },
        ],
        active: "target",
      };
    if (name === "api_results") return { records: [] };
    if (name === "list") return { integrations: p.entries };
    throw Error(name);
  };
  await p._click({
    target: { closest: () => ({ dataset: { action: "read-add-test" } }) },
  });
  assert.equal(p.error, "");
  assert.equal(p.readChoice, "user.read.stateofcharge_mapping");
  assert.deepEqual(
    calls.filter((n) => /attribute_(add|test|activate)/.test(n)),
    ["attribute_add", "attribute_test"],
  );
});

test("typed command parameters use backend schema without JSON editing", () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  const route = {
    id: "cariad.charging.mode",
    parameter_schema: {
      value: { type: "string", enum: ["manual", "timer"], required: true },
    },
  };
  assert.match(p.parameterFields(route), /<select/);
  assert.throws(() => p.parameterValues(route, "{}"), /Required parameter/);
  const key = p.definitionKey(
    "parameters",
    JSON.stringify([route.id, route.parameter_schema]),
  );
  p.definitionEdits.set(key + ":value", "timer");
  assert.equal(p.parameterValues(route, "{}").value, "timer");
});

test("repeated template editing proposes another identifier without changing active route", () => {
  const p = new Panel();
  p.attribute = "stateOfCharge";
  p.readRoutes = [
    {
      id: "user.read.stateofcharge_mapping",
      kind: "custom",
      family: "cariad",
      path: "/new",
      response_paths: ["charging.soc"],
    },
  ];
  p.readChoice = p.readRoutes[0].id;
  const template = JSON.parse(p.initialReadRoute);
  assert.equal(template.id, "user.read.stateofcharge_mapping_2");
  assert.equal(template.path, "/new");
  p.controlCapability = "charging";
  p.controlAction = "start";
  p.controlRoutes = [
    {
      id: "user.charging.start.alternative",
      family: "cariad",
      method: "POST",
      path: "/start",
      request_body: {},
    },
  ];
  p.controlChoice = p.controlRoutes[0].id;
  assert.equal(
    JSON.parse(p.initialControlRoute).id,
    "user.charging.start.alternative_2",
  );
});

test("disabled inventory is global and permits inspection without candidates", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.step = 2;
  p.category = "climate";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [
        { vin: "VIN1", name: "Audi", model: "Q8", api_family: "cariad" },
      ],
    },
  ];
  p.apiFamily = "cariad";
  p.functionMode = "controls";
  p.discoveryGroup = "spin";
  p.searchText = "unrelated";
  p.capabilityStatus = {
    rows: [],
    control_actions: [
      {
        capability: "charging",
        action: "set_target_soc",
        api_family: "mbb",
        candidate_count: 0,
        binding_status: "user_disabled",
        approval_groups: [],
      },
    ],
  };
  await p._change({ target: { id: "inventory-filter", value: "disabled" } });
  assert.equal(p.apiFamily, "all");
  assert.equal(p.functionMode, "all");
  assert.equal(p.discoveryGroup, "read_only");
  assert.match(
    p.shadowRoot.innerHTML,
    /data-control="set_target_soc"\s*>Inspect/,
  );
});

test("Execution history combines capability, entity, method, outcome, time and payload filters", () => {
  const p = new Panel();
  const operations = [
    { operation: "charge", capabilities: ["charging"] },
    { operation: "climate", capabilities: ["climate"] },
  ];
  p.engineeringHistory = [
    {
      operation: "charge",
      family: "cariad",
      method: "GET",
      at: "2026-11-12T10:00:00Z",
      http_status: 200,
      payload: { soc: 80 },
    },
    {
      operation: "charge",
      family: "cariad",
      method: "GET",
      at: "2026-11-11T10:00:00Z",
      http_status: 500,
      payload: { soc: "error" },
    },
    {
      operation: "climate",
      family: "cariad",
      method: "POST",
      at: "2026-11-12T10:00:00Z",
      http_status: 200,
      payload: { soc: 80 },
    },
  ];
  p.capabilityFilter = "charging";
  p.operationMethod = "GET";
  p.logOutcome = "success";
  p.logFrom = "2026-11-12";
  p.logTo = "2026-11-12";
  p.searchText = "soc";
  const records = [{ ...p.engineeringHistory[0], preview: "duplicate" }];
  const rows = p.executionRows(operations, records, "cariad", {
    operations: ["charge"],
  });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].record.operation, "charge");
  assert.equal(rows[0].detail.payload.soc, 80);
  assert.equal(p.executionRows(operations, records, "mbb", null).length, 0);
  p._resetVehicleSelection();
  assert.equal(p.capabilityFilter, "");
  assert.equal(p.logFrom, "");
  assert.equal(p.searchText, "");
});

test("Missing entity trace and actual HA state use existing links without a request", async () => {
  const p = new Panel();
  p._hass = {
    states: {
      "sensor.audi_soc": {
        state: "80",
        attributes: { unit_of_measurement: "%" },
      },
    },
  };
  p.capabilityStatus = {
    rows: [
      {
        attribute: "stateOfCharge",
        entity_keys: ["sensor.state_of_charge"],
        status: "verified",
        normalized_value: 80,
        path: "charging.soc",
      },
    ],
    entity_links: [
      {
        contract_key: "sensor.state_of_charge",
        entity_ids: ["sensor.audi_soc"],
        capabilities: ["charging"],
        operations: ["cariad.status.charging"],
      },
    ],
  };
  p.entityFilter = "sensor.audi_soc";
  assert.match(p.entityInspector(p.selectedEntityLink()), /80 %/);
  assert.match(p.entityInspector(p.selectedEntityLink()), /charging.soc/);
  p.api = async () => {
    throw Error("Entity trace must not execute API");
  };
  await p._click({
    target: {
      closest: () => ({
        dataset: {
          action: "open-operation",
          operation: "cariad.status.charging",
        },
      }),
    },
  });
  assert.equal(p.step, 4);
  assert.equal(p.focusOperation, "cariad.status.charging");
  p.capabilityStatus.entity_links[0].entity_ids = [];
  p.entityFilter = "sensor.state_of_charge";
  assert.match(
    p.entityInspector(p.selectedEntityLink()),
    /Entity not registered/,
  );
});

test("Shared capability and operation filters survive navigation and search", async () => {
  const p = new Panel();
  p.capabilityFilter = "charging";
  p.focusOperation = "cariad.status.charging";
  p.apiFamily = "cariad";
  await p._change({ target: { id: "global-search", value: "soc" } });
  await p._click({
    target: { closest: () => ({ dataset: { action: "step-4" } }) },
  });
  assert.equal(p.capabilityFilter, "charging");
  assert.equal(p.focusOperation, "cariad.status.charging");
  assert.equal(p.apiFamily, "cariad");
  assert.equal(p.searchText, "soc");
  await p._click({
    target: { closest: () => ({ dataset: { action: "clear-operation" } }) },
  });
  assert.equal(p.focusOperation, "");
  assert.equal(p.capabilityFilter, "charging");
});

test("Execution review edits retained evidence without vehicle calls", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.step = 4;
  p.entries = [
    { entry_id: "entry", vehicles: [{ vin: "VIN1", api_family: "cariad" }] },
  ];
  p.apiHistory = [
    {
      operation: "test.read",
      family: "cariad",
      method: "GET",
      at: "2026-11-12T10:00:00Z",
      http_status: 200,
    },
  ];
  p.shadowRoot.getElementById = (id) =>
    id === "review-outcome-0"
      ? { value: "worked" }
      : id === "review-comment-0"
        ? { value: "Compared against myAudi" }
        : null;
  const calls = [];
  p.api = async (name, args) => {
    calls.push(name);
    if (name === "review_execution") {
      assert.equal(args.operation, "test.read");
      assert.equal(args.outcome, "worked");
      assert.equal(args.comment, "Compared against myAudi");
      return { saved: true };
    }
    if (name === "api_results")
      return {
        records: p.apiHistory,
        execution_reviews: [
          {
            operation: "test.read",
            at: p.apiHistory[0].at,
            outcome: "worked",
            comment: "Compared against myAudi",
          },
        ],
      };
    if (name === "status") return { counts: {}, rows: [] };
    if (name === "list") return { integrations: p.entries };
    throw Error("Unexpected operation " + name);
  };
  await p._click({
    target: {
      closest: () => ({
        dataset: {
          action: "execution-review",
          index: "0",
          operation: "test.read",
          at: p.apiHistory[0].at,
        },
      }),
    },
  });
  assert.equal(p.error, "");
  assert.equal(calls.filter((name) => name === "review_execution").length, 1);
  assert.equal(
    calls.some((name) => name.includes("test") || name.includes("activate")),
    false,
  );
  assert.match(p.shadowRoot.innerHTML, /Compared against myAudi/);
});

test("GraphQL uses common definition editing and preserves invalid variables without dispatch", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.capabilityStatus = {
    rows: [],
    identity_templates: {
      "graphql.inventory.vehicleList": "{ userVehicles { vin } }",
    },
  };
  p.openIdentityEditor("graphql.inventory.vehicleList");
  const key = p.definitionKey("identity", p.identityDefinition);
  p.definitionEdits.set(key + ":variables", "{invalid");
  p.api = async () => {
    throw Error("Unexpected API call");
  };
  await p._click({
    target: { closest: () => ({ dataset: { action: "identity-submit" } }) },
  });
  assert.match(p.error, /Invalid JSON in variables/);
  assert.equal(p.definitionEdits.get(key + ":variables"), "{invalid");
  p.openIdentityEditor("graphql.inventory.vehicleList", true);
  assert.equal(
    p.definitionValue("identity", p.identityDefinition).query,
    "{ userVehicles { vin } }",
  );
});

test("Identical GraphQL templates keep edits separate by operation", () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  const query = "{ userVehicles { vin } }";
  p.capabilityStatus = {
    rows: [],
    identity_templates: { "graphql.one": query, "graphql.two": query },
  };
  p.openIdentityEditor("graphql.one");
  p.definitionEdits.set(
    p.definitionKey("identity", p.identityDefinition) + ":query",
    "{ userVehicles { vin role } }",
  );
  p.openIdentityEditor("graphql.two");
  assert.equal(
    p.definitionValue("identity", p.identityDefinition).query,
    query,
  );
  p.openIdentityEditor("graphql.one");
  assert.match(
    p.definitionValue("identity", p.identityDefinition).query,
    /role/,
  );
});

test("Portable definition JSON reuses editor and never executes a request", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.attribute = "stateOfCharge";
  const template = p.initialReadRoute;
  const value = {
    ...JSON.parse(template),
    id: "user.read.imported",
    response_path: "charging.value",
    capture_path: "charging.time",
  };
  p.shadowRoot.getElementById = (id) =>
    id === "definition-json-read" ? { value: JSON.stringify(value) } : null;
  p.api = async () => {
    throw Error("Import must not call API");
  };
  await p._click({
    target: {
      closest: () => ({
        dataset: { action: "definition-json", editor: "read" },
      }),
    },
  });
  assert.equal(p.error, "");
  assert.equal(p.definitionValue("read", template).id, "user.read.imported");
  assert.equal(
    p.definitionValue("read", template).capture_path,
    "charging.time",
  );
  assert.throws(
    () =>
      p.loadDefinitionJSON(
        "read",
        template,
        JSON.stringify({ ...value, credentials: "forbidden" }),
      ),
    /Unknown definition fields/,
  );
  assert.throws(
    () =>
      p.loadDefinitionJSON(
        "read",
        template,
        JSON.stringify({ ...value, attribute: "different" }),
      ),
    /matching attribute/,
  );
  assert.throws(
    () =>
      p.loadDefinitionJSON(
        "read",
        template,
        JSON.stringify({
          ...value,
          id: "user.read.changed",
          capture_path: 123,
        }),
      ),
    /Expected text/,
  );
  assert.equal(p.definitionValue("read", template).id, "user.read.imported");
});

test("End-user discovery advances on No and only Yes sends the displayed action", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  const first = {
    label: "Start cabin climate",
    capability: "climate",
    action: "start",
    operation: "cariad.climate.start.stored",
    approval_group: "non_spin",
  };
  const second = {
    label: "Stop cabin climate",
    capability: "climate",
    action: "stop",
    operation: "cariad.climate.stop",
    approval_group: "non_spin",
  };
  p.capabilityStatus = {
    rows: [],
    end_user_progress: {
      read_assessed: 22,
      read_total: 28,
      read_assessment_percent: 78.6,
      controls: [],
    },
    end_user_candidates: [first, second],
    end_user_timing: { poll_interval_seconds: 900 },
  };
  const calls = [];
  p.api = async (name, args) => {
    calls.push([name, args]);
    if (name === "status") return p.capabilityStatus;
    if (name === "api_results") return { records: [] };
    if (name === "control_test") return { sequence: 1 };
    throw Error(name);
  };
  const click = async (action, c = {}) =>
    p._click({
      target: {
        closest: () => ({
          dataset: {
            action,
            operation: c.operation,
            capability: c.capability,
            control: c.action,
          },
        }),
      },
    });
  await click("step-5");
  assert.equal(calls.length, 0);
  assert.match(p.shadowRoot.innerHTML, /22\/28 assessed/);
  assert.match(p.shadowRoot.innerHTML, /Discover Start cabin climate/);
  await click("end-user-no", first);
  assert.equal(calls.length, 0);
  assert.match(p.shadowRoot.innerHTML, /Discover Stop cabin climate/);
  await click("end-user-yes", first);
  assert.equal(calls.length, 0);
  await click("end-user-yes", second);
  const sent = calls.filter(([name]) => name === "control_test");
  assert.equal(sent.length, 1);
  assert.equal(sent[0][1].operation, second.operation);
  assert.equal(sent[0][1].end_user, true);
  p._resetVehicleSelection();
  assert.equal(p.skippedControls.size, 0);
});

test("Expert mode tests selected action out of order and opens failed route for editing", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  const first = {
    label: "Start climate",
    capability: "climate",
    action: "start",
    operation: "cariad.climate.start.stored",
    approval_group: "non_spin",
  };
  const second = {
    label: "Stop charging",
    capability: "charging",
    action: "stop",
    operation: "cariad.charging.stop",
    approval_group: "non_spin",
  };
  p.capabilityStatus = {
    rows: [],
    end_user_progress: {
      controls: [
        {
          capability: "charging",
          action: "stop",
          eligible: true,
          status: "catalog_matched",
          physical: "failed",
        },
      ],
    },
    end_user_candidates: [first],
    expert_candidates: [first, second],
    command_journal: [
      {
        capability: "charging",
        action: "stop",
        operation: second.operation,
        state: "physical_failed",
      },
    ],
  };
  const calls = [];
  p.api = async (name, args) => {
    calls.push([name, args]);
    if (name === "status") return p.capabilityStatus;
    if (name === "api_results") return { records: [] };
    if (name === "control_test") return { sequence: 1 };
    if (name === "control_routes")
      return {
        routes: [
          {
            id: second.operation,
            family: "cariad",
            method: "POST",
            path: "/vehicle/v1/vehicles/{VIN}/charging/stop",
            approval_group: "non_spin",
            status: "failed",
          },
        ],
      };
    throw Error(name);
  };
  const click = (action, attrs = {}) =>
    p._click({
      target: { closest: () => ({ dataset: { action, ...attrs } }) },
    });
  await click("step-5");
  await click("discovery-mode", { mode: "expert" });
  assert.match(p.shadowRoot.innerHTML, /Edit failed API/);
  assert.equal(calls.length, 0);
  await click("end-user-yes", {
    capability: "charging",
    control: "stop",
    operation: second.operation,
  });
  assert.equal(calls[0][0], "control_test");
  assert.equal(calls[0][1].operation, second.operation);
  assert.equal(calls[0][1].expert, true);
  await click("select-control", {
    capability: "charging",
    control: "stop",
    operation: second.operation,
  });
  assert.equal(p.step, 3);
  assert.equal(p.controlChoice, second.operation);
  assert.equal(
    JSON.parse(p.initialControlRoute).path,
    "/vehicle/v1/vehicles/{VIN}/charging/stop",
  );
  assert.notEqual(JSON.parse(p.initialControlRoute).id, second.operation);
});

test("End-user validation includes real native entity state and refreshes only from local diagnostics", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.step = 5;
  p._loaded = true;
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  p.capabilityStatus = {
    rows: [],
    end_user_progress: { controls: [] },
    entity_links: [
      {
        contract_key: "sensor.discovery_coverage",
        entity_ids: ["sensor.audi_discovery"],
        operations: [],
        capabilities: [],
        attributes: [],
      },
      {
        contract_key: "sensor.state_of_charge",
        entity_ids: ["sensor.audi_soc"],
        operations: [],
        capabilities: ["charging"],
        attributes: [],
      },
    ],
  };
  const states = {
    "sensor.audi_discovery": { state: "80" },
    "sensor.audi_soc": { state: "65" },
  };
  p._hass = { states };
  p.render();
  assert.match(p.shadowRoot.innerHTML, /2 entities with an available HA state/);
  assert.match(p.shadowRoot.innerHTML, /sensor.audi_soc/);
  const calls = [];
  p.api = async (name) => {
    calls.push(name);
    return p.capabilityStatus;
  };
  p.hass = { states: { ...states, "sensor.other": { state: "on" } } };
  assert.equal(calls.length, 0);
  p.hass = { states: { ...states, "sensor.audi_discovery": { state: "100" } } };
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(calls, ["status"]);
});

test("Overview prioritizes current actions without deleting historical findings", async () => {
  const p = new Panel();
  p.selected = "entry";
  p.vin = "VIN1";
  p.entries = [
    {
      entry_id: "entry",
      vehicles: [{ vin: "VIN1", name: "Audi", api_family: "cariad" }],
    },
  ];
  const old = {
    id: "attribute:oil",
    reason: "boolean_oil_level_use_binary",
    capability: "vehicle_status",
  };
  const missing = {
    id: "vehicle:manufacturer_model",
    reason: "manufacturer_identity_missing",
    capability: "vehicle_identity",
    operation: "graphql.inventory.vehicleList",
  };
  p.capabilityStatus = {
    rows: [],
    findings: [old, missing],
    next_actions: [missing],
    identity_summary: {
      manufacturer_model: false,
      model_year: false,
      oem_drivetrain: true,
    },
    operations: [
      {
        operation: missing.operation,
        family: "graphql",
        read_only: true,
        capabilities: ["vehicle_identity"],
        mappings: [],
      },
    ],
  };
  p.render();
  const overview = p.shadowRoot.innerHTML
    .split('data-view="overview"')[1]
    .split('data-view="evidence"')[0];
  assert.match(overview, /Manufacturer identity missing/);
  assert.match(overview, /3 identity fields/);
  assert.doesNotMatch(overview, /Oil level is a warning/);
  assert.match(p.shadowRoot.innerHTML, /Oil level is a warning/);
  await p._click({
    target: {
      closest: () => ({ dataset: { action: "inspect-finding", index: "1" } }),
    },
  });
  assert.equal(p.category, "vehicle_identity");
  assert.equal(p.step, 2);
});

test("Copy API evidence uses displayed masked JSON only and never calls Audi", async () => {
  const p = new Panel();
  const detail = {
    operation: "graphql.inventory.webOrdered",
    http_status: 401,
    at: "2026-11-12T21:42:49Z",
    request: { payload: { url: "/graphql", vin: "{VIN}" } },
    payload: { errors: [{ reason: "token_exchange_denied" }] },
  };
  const html = p.responseInspector(detail.operation, detail);
  assert.match(html, /Copy request &amp; response/);
  assert.match(html, /Copy request/);
  assert.match(html, /Copy response/);
  const req = JSON.stringify(detail.request.payload, null, 2),
    res = JSON.stringify(detail.payload, null, 2);
  const nodes = {
    'pre[data-evidence="request"]': { textContent: req },
    'pre[data-evidence="response"]': { textContent: res },
    "[data-evidence-status]": { textContent: "HTTP 401" },
    "[data-evidence-note]": { textContent: "Masked JSON" },
  };
  p.api = async () => {
    throw Error("Copy must not call backend");
  };
  clipboard = [];
  for (const kind of ["request", "response", "all"]) {
    const button = {
      dataset: { action: "copy-evidence", copy: kind },
      closest: () => ({ querySelector: (key) => nodes[key] }),
    };
    await p._click({ target: { closest: () => button } });
    assert.equal(button.textContent, "Copied");
  }
  assert.equal(clipboard[0], req);
  assert.equal(clipboard[1], res);
  assert.equal(
    clipboard[2],
    [
      "HTTP 401",
      "Request sent\n\n" + req,
      "Response received\n\n" + res,
      "Masked JSON",
    ].join("\n\n"),
  );
  p.apiHistory = [{ operation: "old", preview: { code: 401 } }];
  assert.match(p.responseInspector("old"), /Copy response/);
  assert.doesNotMatch(p.responseInspector("old"), /Copy request/);
});

test("Share saved route copies backend-approved definition without execution", async () => {
  const panel = new Panel();
  panel.selected = "entry";
  panel.vin = "TESTVIN";
  const definition = { id: "user.read.example", method: "GET" };
  const calls = [];
  panel.api = async (name, data) => {
    calls.push(name);
    assert.equal(data.operation, definition.id);
    return definition;
  };
  await panel._click({
    target: {
      closest: () => ({
        dataset: { action: "share-definition", operation: definition.id },
      }),
    },
  });
  assert.deepEqual(calls, ["share_definition"]);
  assert.deepEqual(JSON.parse(clipboard.at(-1)), definition);
});

test("Backend portable local definition imports into the new attribute editor", () => {
  const p = new Panel();
  const shared = JSON.parse(
    fs.readFileSync("tests/fixtures/v3_shared_read.json", "utf8"),
  );
  const template = p.initialNewAttribute;
  p.loadDefinitionJSON("new-attribute", template, JSON.stringify(shared));
  assert.deepEqual(
    JSON.parse(JSON.stringify(p.definitionValue("new-attribute", template))),
    shared,
  );
});
