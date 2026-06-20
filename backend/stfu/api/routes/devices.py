from fastapi import APIRouter
from stfu.audio.devices import list_devices

router = APIRouter()


@router.get("/devices")
def get_devices():
    return [vars(d) for d in list_devices()]
