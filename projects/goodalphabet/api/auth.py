from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.api_route('/login', methods=['GET', 'POST'])
@router.api_route('/register', methods=['GET', 'POST'])
async def auth_disabled():
    raise HTTPException(
        status_code=410,
        detail='本地登录/注册接口已下线，请改用 Next.js + Auth0 登录流程（/auth/login）。',
    )
