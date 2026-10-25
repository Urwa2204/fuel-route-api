import requests
from django.shortcuts import render
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .planner import NoFuelStopError
from .services import RoutingError, build_plan


class RouteInput(serializers.Serializer):
    start = serializers.CharField(max_length=200)
    finish = serializers.CharField(max_length=200)


class RouteView(APIView):
    def get(self, request):
        return self._run(request.query_params)

    def post(self, request):
        return self._run(request.data)

    def _run(self, data):
        ser = RouteInput(data=data)
        ser.is_valid(raise_exception=True)
        try:
            result = build_plan(ser.validated_data["start"], ser.validated_data["finish"])
        except (RoutingError, NoFuelStopError) as e:
            return Response({"error": str(e)}, status=400)
        except requests.RequestException:
            return Response({"error": "Routing service unavailable"}, status=502)
        return Response(result)


def map_page(request):
    return render(request, "routing/map.html")