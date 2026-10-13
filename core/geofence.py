"""
Geofencing and Campus Location Verification Engine.
Uses the Haversine formula to calculate the great-circle distance between
reported student coordinates and administrator-configured authorized college campus(es).

Security Notes:
- Frontend calculations are never trusted; verification occurs strictly server-side.
- Browser geolocation is an indicator of proximity, not absolute physical presence proof.
  GPS readings can be spoofed or degraded indoors.
"""
import math
from typing import Tuple, List, Dict, Optional, Any

EARTH_RADIUS_METERS = 6371000.0  # WGS-84 mean Earth radius in meters

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the great-circle distance between two points on the Earth's surface
    specified in decimal degrees using the Haversine formula.

    Returns:
        Distance in meters.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    
    # Clamp to [0, 1] to avoid domain error in sqrt due to floating point inaccuracies
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return EARTH_RADIUS_METERS * c

def validate_coordinates(lat: Any, lon: Any) -> Tuple[bool, Optional[float], Optional[float], str]:
    """
    Validates that latitude and longitude are valid numeric coordinates.
    Latitude must be between -90 and 90.
    Longitude must be between -180 and 180.
    """
    if lat is None or lon is None:
        return False, None, None, "Geographic coordinates (latitude and longitude) are missing."

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return False, None, None, "Invalid coordinate format: Latitude and longitude must be numbers."

    if math.isnan(lat_f) or math.isnan(lon_f) or math.isinf(lat_f) or math.isinf(lon_f):
        return False, None, None, "Coordinates cannot be NaN or Infinite."

    if not (-90.0 <= lat_f <= 90.0):
        return False, None, None, f"Latitude {lat_f} is out of bounds (must be between -90 and 90 degrees)."

    if not (-180.0 <= lon_f <= 180.0):
        return False, None, None, f"Longitude {lon_f} is out of bounds (must be between -180 and 180 degrees)."

    return True, lat_f, lon_f, "Coordinates are valid."

def verify_student_location(
    student_lat: Optional[float],
    student_lon: Optional[float],
    accuracy_meters: Optional[float],
    campuses: List[Dict[str, Any]],
    accuracy_threshold_meters: float = 50.0,
    geofence_enabled: bool = True
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates reported student coordinates against registered college campuses.

    Args:
        student_lat: Reported student latitude.
        student_lon: Reported student longitude.
        accuracy_meters: Reported GPS accuracy radius in meters (from Geolocation API).
        campuses: List of active campus configurations. Each must have:
                  'id', 'name', 'latitude', 'longitude', 'radius_meters'.
        accuracy_threshold_meters: Max acceptable GPS accuracy error (default 50.0m).
        geofence_enabled: Global or institutional toggle for geofencing.

    Returns:
        (is_verified, message, audit_details)
    """
    if not geofence_enabled:
        return True, "Geofencing verification is disabled.", {
            "geofence_enabled": False,
            "verified": True
        }

    # 1. Coordinate presence and validity check
    is_valid, lat_f, lon_f, coord_msg = validate_coordinates(student_lat, student_lon)
    if not is_valid:
        return False, coord_msg, {
            "geofence_enabled": True,
            "verified": False,
            "error_type": "INVALID_COORDINATES",
            "message": coord_msg
        }

    # 2. GPS accuracy check
    if accuracy_meters is not None:
        try:
            acc_f = float(accuracy_meters)
            if acc_f > accuracy_threshold_meters:
                msg = (
                    f"Location accuracy is too low (±{acc_f:.1f}m > allowable ±{accuracy_threshold_meters:.1f}m). "
                    "Please wait for a better GPS signal or move to an open area."
                )
                return False, msg, {
                    "geofence_enabled": True,
                    "verified": False,
                    "error_type": "POOR_ACCURACY",
                    "reported_accuracy_meters": round(acc_f, 1),
                    "required_accuracy_meters": round(accuracy_threshold_meters, 1)
                }
        except (ValueError, TypeError):
            pass

    # 3. Check registered campuses
    active_campuses = [c for c in campuses if c.get("is_active", 1)]
    if not active_campuses:
        return False, "No active campus location is configured. Please contact administrator.", {
            "geofence_enabled": True,
            "verified": False,
            "error_type": "NO_ACTIVE_CAMPUS"
        }

    # 4. Haversine distance evaluation across all active campuses
    closest_campus = None
    min_distance = float("inf")
    matched_campus = None

    for campus in active_campuses:
        c_lat = campus["latitude"]
        c_lon = campus["longitude"]
        radius = float(campus.get("radius_meters", 30.0))

        dist = haversine_distance(lat_f, lon_f, c_lat, c_lon)
        if dist < min_distance:
            min_distance = dist
            closest_campus = campus

        # If student is within the campus radius
        # Note: rounding to 2 decimal places to handle boundary floating point precision
        if round(dist, 2) <= round(radius, 2):
            matched_campus = campus
            break

    if matched_campus:
        return True, f"Location verified within {matched_campus['name']} area.", {
            "geofence_enabled": True,
            "verified": True,
            "campus_id": matched_campus.get("id"),
            "campus_name": matched_campus["name"],
            "distance_meters": round(min_distance, 2),
            "allowed_radius_meters": float(matched_campus.get("radius_meters", 30.0)),
            "accuracy_meters": round(float(accuracy_meters), 1) if accuracy_meters is not None else None
        }

    # Outside radius
    allowed_radius = float(closest_campus.get("radius_meters", 30.0)) if closest_campus else 30.0
    return False, "Attendance is allowed only within the authorized college campus area.", {
        "geofence_enabled": True,
        "verified": False,
        "error_type": "OUTSIDE_GEOFENCE",
        "closest_campus": closest_campus.get("name") if closest_campus else "Unknown",
        "distance_meters": round(min_distance, 2),
        "allowed_radius_meters": allowed_radius
    }
