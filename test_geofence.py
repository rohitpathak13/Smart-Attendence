"""
Unit Tests for Phase 17: College Location-Based Attendance (Geofencing).
Tests Haversine distance, boundary conditions, poor accuracy, invalid coordinates,
multi-campus handling, and different configured radii (30m default vs 50m).
"""
import unittest
from core.geofence import haversine_distance, validate_coordinates, verify_student_location

class TestGeofence(unittest.TestCase):
    def setUp(self):
        # Sample campus coordinates (Main Campus)
        self.campus_lat = 28.535500
        self.campus_lon = 77.391000

        self.campus_30m = [{
            "id": 1,
            "name": "Engineering Campus",
            "latitude": self.campus_lat,
            "longitude": self.campus_lon,
            "radius_meters": 30.0,
            "is_active": 1
        }]

        self.campus_50m = [{
            "id": 1,
            "name": "Engineering Campus",
            "latitude": self.campus_lat,
            "longitude": self.campus_lon,
            "radius_meters": 50.0,
            "is_active": 1
        }]

    # 1. Haversine Math Verification
    def test_haversine_distance_calculation(self):
        # Exact same point should be 0.0m
        dist_zero = haversine_distance(self.campus_lat, self.campus_lon, self.campus_lat, self.campus_lon)
        self.assertAlmostEqual(dist_zero, 0.0, places=4)

        # 0.0001 deg latitude is approximately 11.12 meters
        dist = haversine_distance(self.campus_lat, self.campus_lon, self.campus_lat + 0.0001, self.campus_lon)
        self.assertGreater(dist, 10.0)
        self.assertLess(dist, 12.0)

    # 2. Student Clearly Inside Radius
    def test_student_clearly_inside_radius(self):
        # Point ~10 meters away from campus (inside 30m default)
        inside_lat = self.campus_lat + 0.00008
        inside_lon = self.campus_lon

        is_ok, msg, details = verify_student_location(
            student_lat=inside_lat,
            student_lon=inside_lon,
            accuracy_meters=10.0,
            campuses=self.campus_30m,
            accuracy_threshold_meters=50.0
        )
        self.assertTrue(is_ok)
        self.assertIn("verified", msg.lower())
        self.assertLessEqual(details["distance_meters"], 30.0)
        self.assertEqual(details["allowed_radius_meters"], 30.0)

    # 3. Student Clearly Outside Radius
    def test_student_clearly_outside_radius(self):
        # Point ~200 meters away (outside 30m default)
        outside_lat = self.campus_lat + 0.002
        outside_lon = self.campus_lon

        is_ok, msg, details = verify_student_location(
            student_lat=outside_lat,
            student_lon=outside_lon,
            accuracy_meters=15.0,
            campuses=self.campus_30m,
            accuracy_threshold_meters=50.0
        )
        self.assertFalse(is_ok)
        # Requirement: "Show a clear message such as: 'Attendance is allowed only within the authorized college campus area.'"
        self.assertEqual(msg, "Attendance is allowed only within the authorized college campus area.")
        self.assertGreater(details["distance_meters"], 30.0)

    # 4. Student at Configured Boundary
    def test_student_at_configured_boundary(self):
        # Calculate offset that equals ~30.0m
        # Using haversine, find coordinate at ~30 meters
        lat_step = 0.00027  # ~30.0 meters
        dist = haversine_distance(self.campus_lat, self.campus_lon, self.campus_lat + lat_step, self.campus_lon)
        
        campus_boundary = [{
            "id": 1,
            "name": "Boundary Campus",
            "latitude": self.campus_lat,
            "longitude": self.campus_lon,
            "radius_meters": round(dist, 2),
            "is_active": 1
        }]

        is_ok, _, details = verify_student_location(
            student_lat=self.campus_lat + lat_step,
            student_lon=self.campus_lon,
            accuracy_meters=5.0,
            campuses=campus_boundary
        )
        self.assertTrue(is_ok)
        self.assertAlmostEqual(details["distance_meters"], round(dist, 2), delta=0.5)

    # 5. Invalid Coordinates
    def test_invalid_coordinates(self):
        invalid_cases = [
            (95.0, 77.0),    # Latitude > 90
            (-95.0, 77.0),   # Latitude < -90
            (28.0, 185.0),   # Longitude > 180
            (28.0, -185.0),  # Longitude < -180
            ("invalid", 77), # String
            (float("nan"), 77.0) # NaN
        ]
        for lat, lon in invalid_cases:
            is_ok, msg, details = verify_student_location(
                student_lat=lat,
                student_lon=lon,
                accuracy_meters=10.0,
                campuses=self.campus_30m
            )
            self.assertFalse(is_ok, f"Expected ({lat}, {lon}) to be rejected.")
            self.assertEqual(details["error_type"], "INVALID_COORDINATES")

    # 6. Missing Coordinates
    def test_missing_coordinates(self):
        is_ok, msg, details = verify_student_location(
            student_lat=None,
            student_lon=None,
            accuracy_meters=None,
            campuses=self.campus_30m
        )
        self.assertFalse(is_ok)
        self.assertIn("missing", msg.lower())
        self.assertEqual(details["error_type"], "INVALID_COORDINATES")

    # 7. Poor Location Accuracy Requirement
    def test_poor_location_accuracy_rejected(self):
        # Student coordinate is inside (0m), but GPS error is 90m (exceeds threshold of 50m)
        is_ok, msg, details = verify_student_location(
            student_lat=self.campus_lat,
            student_lon=self.campus_lon,
            accuracy_meters=90.0,
            campuses=self.campus_30m,
            accuracy_threshold_meters=50.0
        )
        self.assertFalse(is_ok)
        self.assertEqual(details["error_type"], "POOR_ACCURACY")
        self.assertIn("accuracy is too low", msg.lower())

    # 8. Multi-Campus Handling
    def test_multiple_authorized_campuses(self):
        campuses = [
            {
                "id": 1,
                "name": "North Campus",
                "latitude": 28.7000,
                "longitude": 77.1000,
                "radius_meters": 30.0,
                "is_active": 1
            },
            {
                "id": 2,
                "name": "South Campus",
                "latitude": 28.4000,
                "longitude": 77.3000,
                "radius_meters": 30.0,
                "is_active": 1
            }
        ]

        # Student is at South Campus (~5m from South Campus, far from North Campus)
        is_ok, msg, details = verify_student_location(
            student_lat=28.40004,
            student_lon=77.3000,
            accuracy_meters=10.0,
            campuses=campuses
        )
        self.assertTrue(is_ok)
        self.assertEqual(details["campus_name"], "South Campus")

    # 9. Different Configured Radii (30m vs 50m)
    def test_different_configured_radii(self):
        # Point ~40 meters from campus:
        # Distance is 40m -> should FAIL on 30m default radius, but PASS on 50m radius!
        lat_40m = self.campus_lat + 0.00036
        dist = haversine_distance(self.campus_lat, self.campus_lon, lat_40m, self.campus_lon)
        self.assertGreater(dist, 32.0)
        self.assertLess(dist, 48.0)

        # On 30m radius configuration -> Must be REJECTED
        ok_30m, msg_30m, _ = verify_student_location(
            student_lat=lat_40m,
            student_lon=self.campus_lon,
            accuracy_meters=10.0,
            campuses=self.campus_30m
        )
        self.assertFalse(ok_30m)
        self.assertEqual(msg_30m, "Attendance is allowed only within the authorized college campus area.")

        # On 50m radius configuration -> Must be ACCEPTED
        ok_50m, msg_50m, _ = verify_student_location(
            student_lat=lat_40m,
            student_lon=self.campus_lon,
            accuracy_meters=10.0,
            campuses=self.campus_50m
        )
        self.assertTrue(ok_50m)

if __name__ == "__main__":
    unittest.main()
