import logging

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .serializers import HeatmapRequestSerializer, PlanRequestSerializer
from .services import geocoding, heatmap, planner
from .services.http import UpstreamError

log = logging.getLogger(__name__)


class GeocodeThrottle(AnonRateThrottle):
    rate = "120/min"  # autocomplete fires on keystrokes (debounced client-side)


def _upstream_error(exc: UpstreamError) -> Response:
    log.warning("upstream failure: %s", exc)
    return Response({"detail": f"{exc.service}: {exc.message}"}, status=exc.status)


@api_view(["GET"])
def health(_request: Request) -> Response:
    return Response({"status": "ok"})


@api_view(["GET"])
@throttle_classes([GeocodeThrottle])
def geocode(request: Request) -> Response:
    query = request.query_params.get("q", "")[:200]
    if len(query.strip()) < 2:
        return Response({"results": []})
    try:
        return Response({"results": geocoding.search(query)})
    except UpstreamError as exc:
        return _upstream_error(exc)


@api_view(["POST"])
def plan(request: Request) -> Response:
    serializer = PlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    req = planner.PlanRequest(
        origin=(data["origin"]["lon"], data["origin"]["lat"]),
        destination=(data["destination"]["lon"], data["destination"]["lat"]),
        origin_label=data["origin"]["label"],
        destination_label=data["destination"]["label"],
        departure=data["departure"],
        load_lbs=data["load_lbs"],
        interval_mi=int(data["interval_mi"]),
        hos=data["hos"],
    )
    try:
        return Response(planner.build_plan(req))
    except UpstreamError as exc:
        return _upstream_error(exc)


@api_view(["POST"])
def heatmap_view(request: Request) -> Response:
    serializer = HeatmapRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        return Response(heatmap.build_heatmap(data["paths"], data["departure"].timestamp(), data["load_lbs"]))
    except UpstreamError as exc:
        return _upstream_error(exc)
