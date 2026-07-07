from jan_setu.pipeline.dedup import haversine_m

# Two points in Pune roughly 300m apart (offset along latitude).
_PUNE_LAT = 18.5204
_PUNE_LON = 73.8567
_METERS_PER_DEGREE_LAT = 111_194.9
_OFFSET_DEGREES = 300 / _METERS_PER_DEGREE_LAT


def test_haversine_m_known_distance_between_two_pune_points():
    lat2 = _PUNE_LAT + _OFFSET_DEGREES

    distance = haversine_m(_PUNE_LAT, _PUNE_LON, lat2, _PUNE_LON)

    assert abs(distance - 300) < 1.0


def test_haversine_m_same_point_returns_approximately_zero():
    distance = haversine_m(_PUNE_LAT, _PUNE_LON, _PUNE_LAT, _PUNE_LON)

    assert abs(distance) < 1e-6


def test_haversine_m_is_symmetric():
    lat2 = _PUNE_LAT + _OFFSET_DEGREES
    lon2 = _PUNE_LON + _OFFSET_DEGREES

    forward = haversine_m(_PUNE_LAT, _PUNE_LON, lat2, lon2)
    backward = haversine_m(lat2, lon2, _PUNE_LAT, _PUNE_LON)

    assert forward == backward
