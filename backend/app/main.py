from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import auth, projects, sync

app = FastAPI(title=settings.PROJECT_NAME)

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix=settings.API_V1_STR + "/auth", tags=["Auth"])
app.include_router(projects.router, prefix=settings.API_V1_STR + "/projects", tags=["Projects"])
app.include_router(sync.router, prefix=settings.API_V1_STR + "/sync", tags=["sync"])


@app.get("/")
def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}
