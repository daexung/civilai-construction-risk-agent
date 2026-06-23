import math
from typing import NamedTuple


class GridResult(NamedTuple):
    nx: int
    ny: int
    in_bounds: bool


_RE = 6371.00877
_GRID = 5.0
_SLAT1 = 30.0
_SLAT2 = 60.0
_OLON = 126.0
_OLAT = 38.0
_XO = 43.0
_YO = 136.0

_NX_MIN, _NX_MAX = 1, 149
_NY_MIN, _NY_MAX = 1, 253

_n = math.log(
    math.cos(math.radians(_SLAT1)) / math.cos(math.radians(_SLAT2))
) / math.log(
    math.tan(math.pi / 4 + math.radians(_SLAT2) / 2)
    / math.tan(math.pi / 4 + math.radians(_SLAT1) / 2)
)
_F = (
    math.cos(math.radians(_SLAT1))
    * math.pow(math.tan(math.pi / 4 + math.radians(_SLAT1) / 2), _n)
    / _n
)
_RO = (_RE / _GRID) * _F / math.pow(
    math.tan(math.pi / 4 + math.radians(_OLAT) / 2), _n
)


def latlon_to_grid(latitude: float, longitude: float) -> GridResult:
    if latitude > 90 or latitude < -90:
        raise ValueError(
            f"latitude must be in [-90, 90], got {latitude}"
        )
    if longitude > 180 or longitude < -180:
        raise ValueError(
            f"longitude must be in [-180, 180], got {longitude}"
        )

    if latitude == 90 or latitude == -90:
        raise ValueError(
            f"latitude must not be exactly ±90 (pole singularity), got {latitude}"
        )

    theta = _n * math.radians(longitude - _OLON)
    ra = (_RE / _GRID) * _F / math.pow(
        math.tan(math.pi / 4 + math.radians(latitude) / 2), _n
    )
    x = ra * math.sin(theta) + _XO
    y = _RO - ra * math.cos(theta) + _YO

    nx = int(x + 0.5)
    ny = int(y + 0.5)

    in_bounds = _NX_MIN <= nx <= _NX_MAX and _NY_MIN <= ny <= _NY_MAX

    return GridResult(nx=nx, ny=ny, in_bounds=in_bounds)
