import pytest
from unittest.mock import patch, MagicMock
from requests.exceptions import RequestException

from src.services.routing import MapboxDirectionsClient, recalculate_itinerary_routes

@pytest.fixture
def mock_requests_get():
    with patch("src.services.routing.requests.get") as mock_get:
        yield mock_get

@pytest.fixture
def mock_settings():
    with patch("src.services.routing.get_settings") as mock_set:
        mock_set.return_value.mapbox_access_token = "fake_token"
        yield mock_set

def test_get_route_info_batch_success(mock_requests_get, mock_settings):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "code": "Ok",
        "routes": [
            {
                "legs": [
                    {
                        "distance": 12500.5,
                        "duration": 1500.5,
                        "steps": [
                            {"geometry": {"type": "LineString", "coordinates": [[106.660172, 10.762622], [106.671234, 10.771234]]}}
                        ]
                    }
                ]
            }
        ]
    }
    mock_requests_get.return_value = mock_response
    
    # Coordinates: (lat, lon)
    coords = [(10.762622, 106.660172), (10.771234, 106.671234)]
    profile = "driving-traffic"
    
    result = MapboxDirectionsClient.get_route_info_batch(coords, profile)
    
    assert result is not None
    assert len(result) == 1
    assert result[0]["distance_km"] == 12.5
    assert result[0]["duration_mins"] == 25.0
    assert result[0]["profile"] == profile
    assert result[0]["polyline"] != ""
    
    expected_url = f"https://api.mapbox.com/directions/v5/mapbox/{profile}/106.660172,10.762622;106.671234,10.771234"
    mock_requests_get.assert_called_once_with(expected_url, params={"overview": "false", "steps": "true", "geometries": "geojson", "access_token": "fake_token"}, timeout=10)

def test_get_route_info_batch_api_error(mock_requests_get, mock_settings):
    mock_requests_get.side_effect = RequestException("API down")
    result = MapboxDirectionsClient.get_route_info_batch([(10.0, 106.0), (10.1, 106.1)], "driving-traffic")
    assert result is None

def test_parse_coordinates():
    from src.services.routing import parse_coordinates
    assert parse_coordinates("10.5, 106.5") == (10.5, 106.5)
    assert parse_coordinates((10.5, 106.5)) == (10.5, 106.5)
    assert parse_coordinates([10.5, 106.5]) == (10.5, 106.5)
    assert parse_coordinates("invalid") is None

@patch("src.services.routing.MapboxDirectionsClient.get_route_info_batch")
def test_recalculate_itinerary_routes_batching(mock_batch_api):
    # Mock the driving response
    mock_batch_api.side_effect = [
        # First call (driving-traffic) - 3 legs
        [
            {"distance_km": 5.0, "duration_mins": 10.0, "polyline": "d1", "profile": "driving-traffic"},
            {"distance_km": 0.5, "duration_mins": 1.0, "polyline": "d2", "profile": "driving-traffic"},
            {"distance_km": 6.0, "duration_mins": 12.0, "polyline": "d3", "profile": "driving-traffic"}
        ],
        # Second call (walking) - 3 legs
        [
            {"distance_km": 5.0, "duration_mins": 50.0, "polyline": "w1", "profile": "walking"},
            {"distance_km": 0.5, "duration_mins": 5.0, "polyline": "w2", "profile": "walking"},
            {"distance_km": 6.0, "duration_mins": 60.0, "polyline": "w3", "profile": "walking"}
        ]
    ]

    trip_data = {
        "hotel": {"coordinates": "10.0, 106.0"},
        "itinerary_items": [
            # Leg 1: (10.0, 106.0) to (10.1, 106.1) - Distance ~15km, should use driving
            {"day_number": 1, "order_index": 1, "coordinates": "10.1, 106.1"},
            # Leg 2: (10.1, 106.1) to (10.105, 106.1) - Distance ~0.55km, should use walking
            {"day_number": 1, "order_index": 2, "coordinates": "10.105, 106.1"},
            # Leg 3: (10.105, 106.1) to (10.0, 106.0) - Hotel - Distance ~15km, should use driving
        ]
    }

    updated = recalculate_itinerary_routes(trip_data)
    items = updated["itinerary_items"]
    
    # 2 API calls should be made (driving, then walking because of the short leg)
    assert mock_batch_api.call_count == 2
    
    # Hotel -> Item 1 (Driving)
    assert items[0]["route_from_hotel"]["profile"] == "driving-traffic"
    assert items[0]["route_from_hotel"]["polyline"] == "d1"

    # Item 1 -> Item 2 (Walking, < 1.2km)
    assert items[0]["route_to_next"]["profile"] == "walking"
    assert items[0]["route_to_next"]["polyline"] == "w2"

    # Item 2 (last item) -> Hotel (Driving)
    assert items[1]["route_to_next"]["profile"] == "driving-traffic"
    assert items[1]["route_to_next"]["polyline"] == "d3"

def test_encode_polyline():
    from src.services.routing import encode_polyline
    coords = [(10.76262, 106.66017), (10.77123, 106.67123)]
    result = encode_polyline(coords)
    assert len(result) > 0
    assert type(result) == str
