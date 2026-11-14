from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from custom_components.audiconnect.v3.integration_health import IntegrationHealth
from custom_components.audiconnect.v3.access_summary import access_summary
from custom_components.audiconnect.v3.vehicle import V3Vehicle

VIN = "wauzzz4m0md123456"


def test_partial_errors_recover_only_on_matching_job_and_keep_safe_history():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    health = IntegrationHealth()
    engine = NS(transport=NS(remaining_calls=None), last_cloud_poll_succeeded=True)
    op = "cariad.discovery.readiness"
    response = NS(
        status=207,
        data={
            "readiness": {
                "readinessStatus": {
                    "error": {"code": 4112, "retry": True, "info": "private-data"}
                }
            }
        },
    )
    health.observe(VIN, op, "GET", response, {})
    row = health.snapshot(engine, car)
    assert row["status"] == "degraded" and row["problem"]
    assert row["last_error"]["oem_error_code"] == 4112
    assert "private-data" not in str(row)
    assert row["quota_remaining"] is None
    health.observe(VIN, op, "GET", NS(status=207, data={"charging": {"value": 1}}), {})
    assert health.snapshot(engine, car)["problem"]
    health.observe(
        VIN,
        op,
        "GET",
        NS(
            status=200,
            data={"readiness": {"readinessStatus": {"value": {"online": True}}}},
        ),
        {},
    )
    row = health.snapshot(engine, car)
    assert row["status"] == "operational" and not row["problem"]
    assert row["last_error"]["active"] is False and len(row["error_history"]) == 2


def test_poll_failure_and_quota_are_not_successful_connectivity():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    health = IntegrationHealth()
    engine = NS(transport=NS(remaining_calls=0), last_cloud_poll_succeeded=False)
    assert health.snapshot(engine, car)["status"] == "rate_limited"
    health.poll_error = "authentication_required"
    assert health.snapshot(engine, car)["status"] == "authentication_required"


def test_access_status_partial_unknown_and_stale_never_closed():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    stamp = datetime.now(UTC)
    car.readings["window_detail"] = {
        "captured": stamp.isoformat(),
        "value": {
            "items": [
                {"name": "frontLeft", "status": ["closed"]},
                {"name": "frontRight", "status": ["unsupported"]},
                {"name": "rearLeft", "status": ["closed"]},
                {"name": "rearRight", "status": ["closed"]},
            ]
        },
    }
    state, attrs = access_summary(car, "window")
    assert state == "unknown" and not attrs["complete"]
    car.readings["window_detail"]["value"]["items"][1]["status"] = ["open"]
    assert access_summary(car, "window")[0] == "open"
    car.readings["window_detail"]["captured"] = (stamp - timedelta(hours=2)).isoformat()
    state, attrs = access_summary(car, "window")
    assert state == "stale" and attrs["last_reported_aggregate"] == "open"
    assert attrs["components"]["frontRight"] == "open"
    assert access_summary(car, "door")[0] == "unknown"


def test_access_duplicate_window_does_not_become_safe():
    car = V3Vehicle(VIN, "Audi", "Audi Q8", "q8", "DE")
    rows = [
        {"name": name, "status": ["closed"]}
        for name in ("frontLeft", "frontRight", "rearLeft", "rearRight")
    ]
    rows.append({"name": "frontLeft", "status": ["open"]})
    car.readings["window_detail"] = {
        "captured": datetime.now(UTC).isoformat(),
        "value": {"items": rows},
    }
    assert access_summary(car, "window")[0] == "unknown"


def test_health_snapshot_is_read_only():
    car = V3Vehicle(VIN, "Audi", "", "", "DE")
    health = IntegrationHealth()
    engine = NS(transport=NS(remaining_calls=50), last_cloud_poll_succeeded=True)
    health.observe_inventory(engine, car)
    before = health.snapshot(engine, car)
    assert before["active_error_count"] == 1
    car.model = "Audi Q8"
    health.snapshot(engine, car)
    assert health.findings[car.vin.lower()]
    health.observe_inventory(engine, car)
    assert health.snapshot(engine, car)["active_error_count"] == 0
