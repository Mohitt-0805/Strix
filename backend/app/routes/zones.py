"""ATM zone listing endpoint."""

from fastapi import APIRouter, Depends

from backend.app.deps import get_current_user
from backend.app.models import User
from backend.app.schemas import ZoneOut
from backend.app.services.zones import load_atm_zones

router = APIRouter(tags=["zones"])


@router.get("/zones", response_model=list[ZoneOut])
def list_zones(_current_user: User = Depends(get_current_user)) -> list[ZoneOut]:
    """Return configured ATM standing zones sorted by id."""
    return [ZoneOut(**item) for item in load_atm_zones()]
