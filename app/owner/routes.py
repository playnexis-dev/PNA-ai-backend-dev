from fastapi import (
    APIRouter,
    Header,
    HTTPException,
)

from app.owner.schemas import (
    OwnerRegister,
)

from app.owner.service import create_owner

router = APIRouter(
    prefix="/owners",
    tags=["Owners"],
)


@router.post("/register")
async def register_owner(
    payload: OwnerRegister,
    authorization: str | None = Header(default=None),
):
    try:
        access_token = None

        if authorization and authorization.lower().startswith("bearer "):
            access_token = authorization.split(" ", 1)[1].strip()

        owner = await create_owner(
            payload,
            access_token=access_token,
        )

        return owner

    except HTTPException:
        raise

    except Exception as e:
        print(e)

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
