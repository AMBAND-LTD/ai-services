# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from ai_services_api.controllers.chatbot_router import api_router as chatbot_router
from ai_services_api.controllers.sentiment_router import api_router as sentiment_router



# Create the FastAPI app instance
app = FastAPI(title="Gemini Vision API", version="0.0.1")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins; consider limiting this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="ai_services_api/services/chatbot/static"), name="static")

# Include the chatbot API router
# Example usage
app.include_router(chatbot_router)
app.include_router(sentiment_router)


@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("ai_services_api/services/chatbot/templates/index.html") as f:
        return f.read()
    
@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("ai_services_api/services/sentiment/templates/index.html") as f:
        return f.read()

# Health check endpoint
@app.get("/health")
def hello() -> str:
    return "Hello World!"

# Include the chatbot API router
# Example usage
app.include_router(chatbot_router)
app.include_router(sentiment_router)
