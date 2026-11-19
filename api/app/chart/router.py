from fastapi import APIRouter, HTTPException
from geopy.exc import GeocoderServiceError
from kerykeion import KerykeionException

from .calculator import calculate_chart
from .models import ChartRequest, ChartResponse

router = APIRouter(prefix="/chart", tags=["chart"])


@router.post("/calculate", response_model=ChartResponse)
def calculate(request: ChartRequest) -> ChartResponse:
    try:
        return calculate_chart(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GeocoderServiceError as exc:
        raise HTTPException(status_code=503, detail="Birthplace lookup is unavailable; retry or provide coordinates.") from exc
    except KerykeionException as exc:
        raise HTTPException(status_code=422, detail=f"Could not calculate chart: {exc}") from exc
