from dotenv import load_dotenv
import copy
import os
import json
import asyncio
from typing import Dict, Any, List, Optional
import random
import uuid as uuid_module
from langchain_openai import ChatOpenAI
from agent.graph import play_match, get_game_prompt

load_dotenv('.env')

from fastapi import FastAPI, Security, WebSocket, WebSocketDisconnect, Request, UploadFile, File, HTTPException, status, Depends, Header
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import db.definition as db_method
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from auth import VerifyToken, _request_ctx_var, ui_client_validation 


limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"],enabled=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


auth = VerifyToken()

state = {
    "waiting_players": [],  # List of users waiting for matches
    "active_games": {},     # Dictionary of active game sessions
    "available_agents": []  # List of available LLM agents
} 
@asynccontextmanager
async def lifespan(app: FastAPI):
    response = db_method.create_tables()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    try:
        request_ctx = _request_ctx_var.set(request)
        response = await call_next(request)
        _request_ctx_var.reset(request_ctx)
        return response
    except Exception as e:
        raise e
    

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.post("/api/test-ui-only-endpoint") # this is an endpoint that is accessible to the UI client 
async def test_endpoint(request: Request,ui_client_validation: str = Security(ui_client_validation)):
    return JSONResponse(content={"response": "Hello World"}, status_code=200)

@app.post("/api/test-ui-auth-endpoint") # this is an endpoint that is accessible only from UI client and for logged in users
async def test_endpoint(request: Request,auth_result: str = Security(auth.verify),ui_client_validation: str = Security(ui_client_validation)):
    return JSONResponse(content={"response": "Hello World"}, status_code=200)

@app.get("/api/system-prompt")
async def get_system_prompt_endpoint(ui_client_validation: str = Security(ui_client_validation)):
    """Expose the current system prompt used for games"""
    prompt = get_game_prompt()
    return JSONResponse(content={"system_prompt": prompt}, status_code=200)

# Leaderboard endpoint
@app.get("/api/leaderboard")
async def get_leaderboard_endpoint(ui_client_validation: str = Security(ui_client_validation)):
    """Get the leaderboard of all users and agents"""
    leaderboard = db_method.get_leaderboard()
    return JSONResponse(content={"leaderboard": leaderboard}, status_code=200)

# User profile endpoints
@app.get("/api/users/{user_id}")
async def get_user_profile_endpoint(user_id: str, ui_client_validation: str = Security(ui_client_validation)):
    """Get user profile information"""
    profile = db_method.get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return JSONResponse(content=profile, status_code=200)

@app.put("/api/users/{user_id}/username")
async def update_username_endpoint(
    user_id: str, 
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Update user's username"""
    # Ensure user can only update their own profile
    if auth_result['sub'] != user_id:
        raise HTTPException(status_code=403, detail="Can only update own profile")
    
    body = await request.json()
    username = body.get('username')
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    
    success = db_method.update_user_username(user_id, username)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    
    return JSONResponse(content={"message": "Username updated successfully"}, status_code=200)

# Agent profile endpoint
@app.get("/api/agents/{agent_id}")
async def get_agent_profile_endpoint(agent_id: str, ui_client_validation: str = Security(ui_client_validation)):
    """Get agent profile information"""
    profile = db_method.get_agent_profile(agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    return JSONResponse(content=profile, status_code=200)

# Match history endpoint
@app.get("/api/matches/history/{player_id}")
async def get_match_history_endpoint(
    player_id: str, 
    limit: int = 50, 
    ui_client_validation: str = Security(ui_client_validation)
):
    """Get match history for a player"""
    matches = db_method.get_match_history(player_id, limit)
    return JSONResponse(content={"matches": matches}, status_code=200)

# Match transcript endpoint
@app.get("/api/matches/{match_id}/transcript")
async def get_match_transcript_endpoint(match_id: str, ui_client_validation: str = Security(ui_client_validation)):
    """Get match transcript"""
    transcript = db_method.get_match_transcript(match_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Match not found")
    return JSONResponse(content=transcript, status_code=200)

# Current user endpoint
@app.get("/api/me")
async def get_current_user_endpoint(
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Get current authenticated user's profile"""
    user_id = auth_result['sub']
    profile = db_method.get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    return JSONResponse(content=profile, status_code=200)

# Game matching endpoints
@app.post("/api/matchmaking/queue")
async def join_matchmaking_queue(
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Join the matchmaking queue"""
    user_id = auth_result['sub']
    
    # Check if user is already in queue
    if any(player['user_id'] == user_id for player in state["waiting_players"]):
        raise HTTPException(status_code=400, detail="Already in queue")
    
    # Add user to waiting queue
    player_info = {
        "user_id": user_id,
        "name": auth_result.get('name', 'Unknown'),
        "joined_at": asyncio.get_event_loop().time()
    }
    state["waiting_players"].append(player_info)
    
    return JSONResponse(content={"message": "Added to matchmaking queue", "queue_position": len(state["waiting_players"])}, status_code=200)

@app.delete("/api/matchmaking/queue")
async def leave_matchmaking_queue(
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Leave the matchmaking queue"""
    user_id = auth_result['sub']
    
    # Remove user from queue if present
    state["waiting_players"] = [p for p in state["waiting_players"] if p['user_id'] != user_id]
    
    return JSONResponse(content={"message": "Removed from matchmaking queue"}, status_code=200)

@app.get("/api/matchmaking/status")
async def get_matchmaking_status(
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Get matchmaking status for current user"""
    user_id = auth_result['sub']
    
    # Check if user is in queue
    in_queue = any(player['user_id'] == user_id for player in state["waiting_players"])
    queue_size = len(state["waiting_players"])
    
    # Check if user has an active game
    active_game = None
    for game_id, game in state["active_games"].items():
        if game.get('player1_id') == user_id or game.get('player2_id') == user_id:
            active_game = game_id
            break
    
    return JSONResponse(content={
        "in_queue": in_queue,
        "queue_size": queue_size,
        "active_game": active_game
    }, status_code=200)

@app.post("/api/games/vs-llm")
async def start_game_vs_llm(
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Start a game against a random LLM"""
    user_id = auth_result['sub']
    
    # Get random agent
    agents = db_method.get_agent_elos()
    if not agents:
        raise HTTPException(status_code=503, detail="No LLM agents available")
    
    agent_ids = list(agents.keys())
    selected_agent_id = random.choice(agent_ids)
    
    # Create game session
    game_id = str(uuid_module.uuid4())
    game_session = {
        "game_id": game_id,
        "player1_id": user_id,
        "player1_type": "user",
        "player2_id": selected_agent_id,
        "player2_type": "agent",
        "status": "waiting_for_players",
        "created_at": asyncio.get_event_loop().time()
    }
    
    state["active_games"][game_id] = game_session
    
    return JSONResponse(content={
        "game_id": game_id,
        "message": "Game created against LLM",
        "opponent_type": "agent"
    }, status_code=200)

@app.get("/api/games/{game_id}")
async def get_game_status(
    game_id: str,
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Get game status"""
    user_id = auth_result['sub']
    
    game = state["active_games"].get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Check if user is part of this game
    if game['player1_id'] != user_id and game['player2_id'] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to view this game")
    
    return JSONResponse(content=game, status_code=200)

@app.post("/api/games/{game_id}/action")
async def submit_game_action(
    game_id: str,
    request: Request,
    auth_result: str = Security(auth.verify),
    ui_client_validation: str = Security(ui_client_validation)
):
    """Submit an action for a game"""
    user_id = auth_result['sub']
    body = await request.json()
    action = body.get('action')  # 'cooperate' or 'defect'
    
    if action not in ['cooperate', 'defect']:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    game = state["active_games"].get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Check if user is part of this game
    if game['player1_id'] != user_id and game['player2_id'] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this game")
    
    # Store user's action
    if game['player1_id'] == user_id:
        game['player1_action'] = action
    else:
        game['player2_action'] = action
    
    return JSONResponse(content={"message": "Action submitted successfully"}, status_code=200)