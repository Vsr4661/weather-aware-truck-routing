from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

# Open-Meteo forecasts run 16 days out; leave room for multi-day trips plus the
# 24 h departure scan and the 48 h heatmap.
MAX_DEPARTURE_AHEAD = timedelta(days=7)
MAX_DEPARTURE_PAST = timedelta(hours=2)


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField()
    load_lbs = serializers.FloatField(min_value=0, max_value=200_000)
    interval_mi = serializers.ChoiceField(choices=[10, 25, 50])
    hos = serializers.BooleanField(default=True)

    def validate_departure(self, value):
        now = timezone.now()
        if value < now - MAX_DEPARTURE_PAST:
            raise serializers.ValidationError("Departure can't be in the past (forecasts only).")
        if value > now + MAX_DEPARTURE_AHEAD:
            raise serializers.ValidationError("Departure must be within the next 7 days (forecast range).")
        return value

    def validate(self, attrs):
        o, d = attrs["origin"], attrs["destination"]
        if abs(o["lat"] - d["lat"]) < 1e-4 and abs(o["lon"] - d["lon"]) < 1e-4:
            raise serializers.ValidationError("Origin and destination are the same place.")
        return attrs


class HeatmapRequestSerializer(serializers.Serializer):
    """Stateless: the client sends back the route paths from its plan response,
    so any server instance can answer (no shared cache needed)."""

    paths = serializers.ListField(
        child=serializers.ListField(
            child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
            min_length=2,
            max_length=20_000,
        ),
        min_length=1,
        max_length=3,
    )
    departure = serializers.DateTimeField()
    load_lbs = serializers.FloatField(min_value=0, max_value=200_000)

    def validate_paths(self, paths):
        for path in paths:
            for lon, lat in path:
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise serializers.ValidationError("Coordinates out of range.")
        return paths
