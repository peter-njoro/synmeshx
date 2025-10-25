from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .api.routes import auth, projects, sync

app = FastAPI(title=settings.project_name, debug=settings.debug)    

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix=settings.api_v1_str + "/auth", tags=["Auth"])
# app.include_router(projects.router, prefix=settings.api_v1_str + "/projects", tags=["Projects"])
# app.include_router(sync.router, prefix=settings.api_v1_str + "/sync", tags=["sync"])


@app.get("/")
def root():
    return {"message": f"Welcome to {settings.project_name} API"}
