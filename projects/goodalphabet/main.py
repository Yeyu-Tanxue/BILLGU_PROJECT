import os, traceback
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from wordbook_catalog import register_catalog
from api.auth import router as auth_router
from api.plan import router as plan_router
from api.learn import router as learn_router
from api.review import router as review_router
from api.billing import router as billing_router
from api.admin import router as admin_router
from api.xhs_admin import router as xhs_admin_router

app = FastAPI()
GENERATED_DIR = os.environ.get("XHS_GENERATED_DIR") or ("/tmp/generated" if os.environ.get("VERCEL") else "static/generated")
os.makedirs(GENERATED_DIR, exist_ok=True)
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")

FRONTEND_MODE = os.environ.get("FRONTEND_MODE", "static").lower()
NEXT_DEV_SERVER = os.environ.get("NEXT_DEV_SERVER", "http://localhost:3000").rstrip("/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"error": str(exc)})
app.include_router(auth_router, prefix="/api")
app.include_router(plan_router, prefix="/api")
app.include_router(learn_router, prefix="/api")
app.include_router(review_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(xhs_admin_router, prefix="/api")

@app.get("/")
async def index():
    if FRONTEND_MODE == "next":
        return RedirectResponse(url=NEXT_DEV_SERVER)
    return FileResponse("static/index.html")


@app.get("/login")
async def login_page():
    if FRONTEND_MODE == "next":
        return RedirectResponse(url=f"{NEXT_DEV_SERVER}/auth/login")
    return RedirectResponse(url="/")


@app.get("/frontend-info")
async def frontend_info():
    return {
        "frontend_mode": FRONTEND_MODE,
        "next_dev_server": NEXT_DEV_SERVER,
        "static_index": "/",
        "login_entry": f"{NEXT_DEV_SERVER}/auth/login" if FRONTEND_MODE == "next" else "/",
        "api_base": "/api",
    }


@app.on_event("startup")
async def startup():
    init_db()
    register_catalog()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
