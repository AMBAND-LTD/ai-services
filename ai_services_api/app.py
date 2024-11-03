from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from ai_services_api.controllers.chatbot_router import api_router as chatbot_router
from ai_services_api.controllers.recommendation_router import api_router as recommendation_router
# Create the FastAPI app instance
app = FastAPI(title="AI Services Platform", version="0.0.1")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the chatbot API router
app.include_router(chatbot_router, prefix="/chatbot")
app.include_router(recommendation_router, prefix="/recommendation")
# Serve static files if needed
# app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("ai_services_api/templates/index.html") as f:
        return f.read()

@app.get("/chatbot", response_class=HTMLResponse)
async def read_chatbot():
    with open("ai_services_api/services/chatbot/templates/index.html") as f:
        return f.read()

@app.get("/recommendation", response_class=HTMLResponse)
async def read_recommendation():
    with open("ai_services_api/templates/recommendations.html") as f:
        return f.read()

# Health check endpoint
@app.get("/health")
def health_check() -> str:
    return "Service is healthy!"