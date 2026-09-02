from django.contrib.gis.db import models as gis_models
from django.db import models


class DepotBay(models.Model):
    name = models.CharField(max_length=64, unique=True)
    # geography=True: distances/areas are computed on the spheroid (real
    # meters), not on a flat plane. See Q8 -- this is the tradeoff
    # GEOMETRY vs GEOGRAPHY makes explicit.
    location = gis_models.PointField(geography=True, srid=4326)

    def __str__(self) -> str:
        return self.name


class VehiclePosition(models.Model):
    """
    Deliberately NOT indexed on `status` at the model level -- the index
    is added and dropped at runtime by demo_postgres_indexing (Q7) so the
    before/after EXPLAIN output is real, not asserted.
    """

    vehicle_id = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    location = gis_models.PointField(geography=True, srid=4326)
    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.vehicle_id}@{self.recorded_at}"
