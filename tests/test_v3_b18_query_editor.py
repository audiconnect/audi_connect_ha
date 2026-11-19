import pytest
from custom_components.audiconnect.v3.transport import validate_identity_query


@pytest.mark.parametrize(
    "query",
    [
        "query vehicleList { userVehicles { vin vehicle { media { longName } } } }",
        "{ userVehicles { vin vehicle { core { modelYear } newField } } }",
    ],
)
def test_read_only_query_editor_accepts_selection(query):
    validate_identity_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "mutation { userVehicles { vin } }",
        "{ userVehicles { vehicle { core { modelYear } } } }",
        "{ userVehicles { vin alias: vehicle { core { modelYear } } } }",
        "{ userVehicles { vin } } { userVehicles { vin } }",
        "{ userVehicles { vin __schema } }",
        "{ userVehicles { vin vehicle(arg: 1) { core } } }",
        "{ userVehicles { vin @skip(if: true) } }",
        "{ userVehicles { vin } account { email } }",
    ],
)
def test_read_only_query_editor_rejects_unscoped_or_nonselection(query):
    with pytest.raises(ValueError):
        validate_identity_query(query)


def test_har_ordered_query_is_exact_fixed_read_only_body():
    from types import SimpleNamespace
    from custom_components.audiconnect.v3.transport import (
        WEB_ORDERED_OPERATION,
        identity_request_body,
        is_reviewed_identity_body,
    )
    from custom_components.audiconnect.v3.family_executors import GraphQLExecutor

    body = identity_request_body(WEB_ORDERED_OPERATION)
    assert body["variables"] == {"orderBy": "FAVORITE_AND_REGISTRATION"}
    assert body["operationName"] == "GET_USER_VEHICLES_ORDERED_BY"
    assert is_reviewed_identity_body(body)
    auth = SimpleNamespace(country="BE", access_token=lambda family: "fake-test-token")
    executor = GraphQLExecutor()
    plan = executor.plan(auth, "POST", "/vgql/v1/graphql", body, explicit_action=True)
    assert plan.url == "https://app-api.live-my.audi.com/vgql/v1/graphql"
    assert (
        plan.body == body and plan.headers["Authorization"] == "Bearer fake-test-token"
    )
    assert "Cookie" not in plan.headers and "x-csrf-token" not in plan.headers
    for modified in (
        {"query": body["query"]},
        {**body, "operationName": "other"},
        {**body, "variables": {"orderBy": "other"}},
        {**body, "query": "mutation { userVehicles { vin } }"},
    ):
        assert not is_reviewed_identity_body(modified)
        with pytest.raises(ValueError):
            executor.plan(
                auth, "POST", "/vgql/v1/graphql", modified, explicit_action=True
            )


def test_runtime_identity_query_can_edit_har_fields_and_variables():
    from types import SimpleNamespace
    from custom_components.audiconnect.v3.transport import validate_identity_body
    from custom_components.audiconnect.v3.family_executors import GraphQLExecutor

    query = """query Explore($orderBy: VehicleSortOrder!) {
      userVehicles(orderBy: $orderBy) {
        vin vehicle { core { modelYear } renderPictures(mediaTypes: ["MYAPN8NB"]) { url __typename } }
      }
    }"""
    body = {"query": query, "variables": {"orderBy": "FAVORITE_AND_REGISTRATION"}}
    validate_identity_body(body)
    auth = SimpleNamespace(country="DE", access_token=lambda family: "test")
    plan = GraphQLExecutor().plan(
        auth, "POST", "/vgql/v1/graphql", body, explicit_action=True
    )
    assert plan.body == body
    for bad in (
        {**body, "variables": {"orderBy": "secret bearer"}},
        {**body, "variables": {"orderBy": "VALID", "token": "secret"}},
        {**body, "query": query.replace("mediaTypes", "unknownArg")},
        {
            **body,
            "query": query.replace("userVehicles(orderBy: $orderBy)", "userVehicles"),
        },
        {**body, "query": query.replace("MYAPN8NB", "https://example.org")},
        {**body, "operationName": "Other"},
        {**body, "query": query + " mutation { userVehicles { vin } }"},
    ):
        with pytest.raises(ValueError):
            validate_identity_body(bad)
    with pytest.raises(ValueError):
        GraphQLExecutor().plan(auth, "POST", "/vgql/v1/graphql", body)


def test_retired_after_garage_is_evidence_only():
    from custom_components.audiconnect.v3.transport import (
        POST_GARAGE_OPERATION,
        IDENTITY_OPERATIONS,
        IDENTITY_QUERIES,
        identity_request_body,
    )

    assert POST_GARAGE_OPERATION in IDENTITY_OPERATIONS
    assert POST_GARAGE_OPERATION not in IDENTITY_QUERIES
    with pytest.raises(KeyError):
        identity_request_body(POST_GARAGE_OPERATION)
