import pytest
from unittest.mock import patch, MagicMock
from requests.exceptions import RequestException

from src.services.routing import OSRMClient, get_route_to_next

@pytest.fixture
def mock_requests_get():
    with patch("src.services.routing.requests.get") as mock_get:
        yield mock_get

def test_get_route_info_success(mock_requests_get):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "code": "Ok",
        "routes": [
            {
                "distance": 12500.5, # 12.5 km
                "duration": 1500.5,  # 25.0 mins
                "geometry": "encoded_polyline_here"
            }
        ]
    }
    mock_requests_get.return_value = mock_response
    
    # Coordinates: (lat, lon)
    origin = (10.762622, 106.660172)
    dest = (10.771234, 106.671234)
    
    # Need to clear cache for testing since we're using lru_cache
    OSRMClient.get_route_info.cache_clear()
    
    result = OSRMClient.get_route_info(origin, dest)
    
    assert result is not None
    assert result["distance_km"] == 12.5
    assert result["duration_mins"] == 25.0
    assert result["polyline"] == "encoded_polyline_here"
    
    # Verify the URL format: {lon},{lat}
    expected_url = "http://router.project-osrm.org/route/v1/driving/106.660172,10.762622;106.671234,10.771234?overview=full"
    mock_requests_get.assert_called_once_with(expected_url, timeout=5)

def test_get_route_info_api_error(mock_requests_get):
    mock_requests_get.side_effect = RequestException("API down")
    
    OSRMClient.get_route_info.cache_clear()
    result = OSRMClient.get_route_info((10.0, 106.0), (10.1, 106.1))
    
    assert result is None

def test_get_route_info_no_routes(mock_requests_get):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "code": "NoRoute"
    }
    mock_requests_get.return_value = mock_response
    
    OSRMClient.get_route_info.cache_clear()
    result = OSRMClient.get_route_info((10.0, 106.0), (10.1, 106.1))
    
    assert result is None

def test_get_route_to_next_none_coords():
    assert get_route_to_next(None, (10.0, 106.0)) is None
    assert get_route_to_next((10.0, 106.0), None) is None
    assert get_route_to_next(None, None) is None

def test_get_route_to_next_same_coords():
    result = get_route_to_next((10.0, 106.0), (10.0, 106.0))
    assert result is not None
    assert result["distance_km"] == 0.0
    assert result["duration_mins"] == 0.0
    assert result["polyline"] == ""

def test_parse_coordinates():
    from src.services.routing import parse_coordinates
    assert parse_coordinates("10.5, 106.5") == (10.5, 106.5)
    assert parse_coordinates((10.5, 106.5)) == (10.5, 106.5)
    assert parse_coordinates([10.5, 106.5]) == (10.5, 106.5)
    assert parse_coordinates("invalid") is None

def test_recalculate_itinerary_routes(mock_requests_get):
    from src.services.routing import recalculate_itinerary_routes
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "code": "Ok",
        "routes": [{"distance": 5000.0, "duration": 600.0, "geometry": "poly"}]
    }
    mock_requests_get.return_value = mock_response
    OSRMClient.get_route_info.cache_clear()

    trip_data = {
        "hotel": {"coordinates": "10.0, 106.0"},
        "itinerary_items": [
            {"day_number": 1, "order_index": 1, "coordinates": "10.1, 106.1"},
            {"day_number": 1, "order_index": 2, "coordinates": "10.2, 106.2"},
        ]
    }

    updated = recalculate_itinerary_routes(trip_data)
    items = updated["itinerary_items"]
    
    # Hotel -> Item 1
    assert "route_from_hotel" in items[0]
    assert items[0]["route_from_hotel"]["distance_km"] == 5.0

    # Item 1 -> Item 2
    assert "route_to_next" in items[0]
    assert items[0]["route_to_next"]["distance_km"] == 5.0

    # Item 2 (last item) -> Hotel
    assert "route_to_next" in items[1]
    assert items[1]["route_to_next"]["distance_km"] == 5.0

