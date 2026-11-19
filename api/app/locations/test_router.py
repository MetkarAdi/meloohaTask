import asyncio

from app.locations.router import suggest_locations


class FakeResponse:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, params):
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def factory_for(responses, calls):
    def factory(**_kwargs):
        return FakeClient(responses, calls)
    return factory


def test_open_meteo_prefix_matches_and_does_not_use_photon_when_results_exist():
    calls = []
    response = FakeResponse({"results": [
        {"name": "Pune", "admin1": "Maharashtra", "country": "India", "latitude": 18.52, "longitude": 73.85},
        {"name": "Pune City", "country": "India", "latitude": 18.5, "longitude": 73.8},
        {"name": "Mumbai", "country": "India", "latitude": 19.07, "longitude": 72.87},
    ]})

    found = asyncio.run(suggest_locations("pu", client_factory=factory_for([response], calls)))

    assert [item.name for item in found] == ["Pune", "Pune City"]
    assert found[0].label == "Pune, Maharashtra, India"
    assert len(calls) == 1
    assert calls[0][1]["name"] == "pu"


def test_photon_is_used_when_primary_geocoder_cannot_suggest():
    calls = []
    primary = FakeResponse({"results": []})
    photon = FakeResponse({"features": [{
        "properties": {"name": "Dhule", "state": "Maharashtra", "country": "India"},
        "geometry": {"coordinates": [74.77, 20.9]},
    }]})

    found = asyncio.run(suggest_locations("dh", client_factory=factory_for([primary, photon], calls)))

    assert len(found) == 1
    assert found[0].label == "Dhule, Maharashtra, India"
    assert (found[0].latitude, found[0].longitude) == (20.9, 74.77)
    assert len(calls) == 2
    assert "photon.komoot.io" in calls[1][0]


def test_short_query_returns_without_network_request():
    calls = []
    found = asyncio.run(suggest_locations("P", client_factory=factory_for([], calls)))
    assert found == []
    assert calls == []
