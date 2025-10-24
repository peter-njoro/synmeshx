from fastapi import APIRouter

router = APIRouter()

@router.post("/test")
def auth_test():
    return {"message": "Authroute is working"}