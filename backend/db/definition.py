

from sqlalchemy import create_engine, insert, ForeignKey, Column, Integer, String, Text, Float, DateTime, Boolean, Enum, select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
from typing import List, Dict, Tuple, Optional, Set
import os 
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from petname import Generate


ASYNC_DATABASE_URL = f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB')}?sslmode=require"

DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB')}?sslmode=require"
# Set up the async database engine and session
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False, pool_size=10, max_overflow=20, pool_timeout=5, pool_recycle=1800,pool_pre_ping=True)
engine = create_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20, pool_timeout=5, pool_recycle=1800,pool_pre_ping=True)
Base = declarative_base()
DEFAULT_ELO = 1000


class Agents(Base):
    __tablename__ = "agents"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)
    elo = Column(Integer, nullable=False, default=DEFAULT_ELO)


class Matches(Base):
    __tablename__ = "matches"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    agent1_id = Column(UUID, ForeignKey("agents.id"), nullable=False)
    agent2_id = Column(UUID, ForeignKey("agents.id"), nullable=False)
    agent1_action = Column(String, nullable=False) # the action the agent took
    agent2_action = Column(String, nullable=False) # the action the agent took
    agent1_default = Column(Boolean, nullable=False, default=False) # did the agent fail to make a tool call
    agent2_default = Column(Boolean, nullable=False, default=False) # did the agent fail to make a tool call
    result = Column(Integer, nullable=False) # 0: draw, 1: agent1 wins, 2: agent2 wins
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Transcripts(Base):
    __tablename__ = "transcripts"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID, ForeignKey("matches.id"), nullable=False)
    message = Column(Text, nullable=False)
    agent_id = Column(Integer, nullable=False) # 0: system, 1: agent1, 2: agent2
    order = Column(Integer, nullable=False) # the order in the conversation
    created_at = Column(DateTime, nullable=False, default=datetime.now)

class Users(Base):
    __tablename__ = "users"
    user_uuid = Column(UUID, primary_key=True, default=uuid.uuid4)
    id = Column(String, primary_key=True)
    username = Column(String, nullable=False)
    elo = Column(Integer, nullable=False, default=DEFAULT_ELO) # user's elo
    elo_history = Column(JSONB, nullable=False, default=[]) # user's elo history
    created_at = Column(DateTime, nullable=False, default=datetime.now)

def calculate_elo_change(elo1: int, elo2: int, result: int, k_factor: int = 32) -> Tuple[int, int]:
    """
    Calculate ELO rating changes for both players.
    
    Args:
        elo1: Current ELO of player 1
        elo2: Current ELO of player 2  
        result: Match result (1: player1 wins, 2: player2 wins, 0: draw)
        k_factor: ELO K-factor (default 32)
    
    Returns:
        Tuple of (new_elo1, new_elo2)
    """
    expected1 = 1 / (1 + 10 ** ((elo2 - elo1) / 400))
    expected2 = 1 / (1 + 10 ** ((elo1 - elo2) / 400))
    
    if result == 1:  # Player 1 wins
        score1, score2 = 1, 0
    elif result == 2:  # Player 2 wins
        score1, score2 = 0, 1
    else:  # Draw
        score1, score2 = 0.5, 0.5
    
    new_elo1 = round(elo1 + k_factor * (score1 - expected1))
    new_elo2 = round(elo2 + k_factor * (score2 - expected2))
    
    return new_elo1, new_elo2


def create_tables():
    Base.metadata.create_all(engine)
    return "Tables created successfully"


def get_or_create_agent(model: Dict) -> str:
    """Get existing agent or create new one for a model"""
    with Session(engine, expire_on_commit=False) as session:
        # Check if agent already exists
        agent = session.query(Agents).filter(Agents.name == model["id"]).first()
        
        if agent:
            return str(agent.id)

        # Create new agent
        new_agent = Agents(
            id=uuid.uuid4(),
            name=model["id"],
            description=model.get("description", ""),
            elo=DEFAULT_ELO
        )
        session.add(new_agent)
        session.commit()
        
        return str(new_agent.id)


def get_or_create_agents(models: List[Dict]) -> Dict[str, str]:
    """
    Bulk version of get_or_create_agent for efficiency.
    
    Args:
        models: List of model dictionaries
        
    Returns:
        Dict mapping model id to agent_id
    """
    with Session(engine, expire_on_commit=False) as session:
        # Get all model slugs
        model_slugs = [model["id"] for model in models]
        
        # Query all existing agents in one go
        existing_agents = session.query(Agents).filter(Agents.name.in_(model_slugs)).all()
        existing_by_slug = {agent.name: str(agent.id) for agent in existing_agents}
        
        # Find models that need new agents
        new_models = [model for model in models if model["id"] not in existing_by_slug]
        
        # Bulk create new agents
        new_agents = []
        slug_to_id = {}
        
        for model in new_models:
            agent_id = uuid.uuid4()
            new_agent = Agents(
                id=agent_id,
                name=model["id"],
                description=model.get("description", ""),
                elo=DEFAULT_ELO
            )
            new_agents.append(new_agent)
            slug_to_id[model["id"]] = str(agent_id)
        
        if new_agents:
            session.add_all(new_agents)
            session.commit()
        
        # Combine existing and new agents
        result = {**existing_by_slug, **slug_to_id}
        return result


def get_played_pairs() -> Set[Tuple[str, str]]:
    """Get all pairs of agents that have already played each other"""
    with Session(engine, expire_on_commit=False) as session:
        result = session.query(Matches.agent1_id, Matches.agent2_id).all()
        played_pairs = set()
        for agent1_id, agent2_id in result:
            # Add both orderings since (A,B) and (B,A) are the same match
            played_pairs.add((str(agent1_id), str(agent2_id)))
            played_pairs.add((str(agent2_id), str(agent1_id)))
        
        return played_pairs

def get_all_pairs() -> Set[Tuple[str, str]]:
    """Get all pairs of agents that haven't played each other yet"""
    with Session(engine, expire_on_commit=False) as session:
        result = session.query(Agents.id).all()
        all_pairs = set()
        for i in range(len(result)):
            for j in range(i+1, len(result)):
                agent1_id = str(result[i].id)
                agent2_id = str(result[j].id)

                if str(agent1_id) != str(agent2_id):
                    all_pairs.add((result[i].name, result[j].name, str(agent1_id), str(agent2_id)))
        return all_pairs

def get_agent_elos() -> Dict[str, int]:
    """Get current ELO ratings for all agents"""
    with Session(engine, expire_on_commit=False) as session:
        result = session.query(Agents.id, Agents.elo).all()
        return {str(agent_id): elo for agent_id, elo in result}


def store_match_result(agent1_id: str, agent2_id: str, match_result: Dict):
    """Store match result and update ELO ratings"""
    with Session(engine, expire_on_commit=False) as session:
        # Get current ELO ratings
        agent1 = session.query(Agents).filter(Agents.id == uuid.UUID(agent1_id)).first()
        agent2 = session.query(Agents).filter(Agents.id == uuid.UUID(agent2_id)).first()

        
        old_elo1, old_elo2 = agent1.elo, agent2.elo
        
        # Calculate new ELO ratings
        new_elo1, new_elo2 = calculate_elo_change(old_elo1, old_elo2, match_result["winner"])
        
        # Update ELO ratings
        agent1.elo = new_elo1
        agent2.elo = new_elo2
        agent1.updated_at = datetime.now()
        agent2.updated_at = datetime.now()
        
        # Create match record
        match_id = uuid.uuid4()
        match = Matches(
            id=match_id,
            agent1_id=uuid.UUID(agent1_id),
            agent2_id=uuid.UUID(agent2_id),
            agent1_action=match_result.get("agent1_action", "withhold"),
            agent2_action=match_result.get("agent2_action", "withhold"),
            agent1_default=match_result.get("agent1_defaulted", False),
            agent2_default=match_result.get("agent2_defaulted", False),
            result=match_result["winner"]
        )
        session.add(match)
        
        # Store transcript
        for order, msg in enumerate(match_result["message_history"]):
            transcript = Transcripts(
                id=uuid.uuid4(),
                match_id=match_id,
                message=msg["content"],
                agent_id=msg.get("agent_id", 0) or 0,  # Convert None to 0 for system messages
                order=order
            )
            session.add(transcript)
        
        session.commit()
        
        return {
            "old_elo1": old_elo1,
            "old_elo2": old_elo2,
            "new_elo1": new_elo1,
            "new_elo2": new_elo2
        }

def generate_username():
    """Generate username from Stripe customer name or email"""
    # Safely check if name attribute exists and has a value
    #while loop to check if username is taken
    username = Generate(2, separator='_').lower() 
    with Session(engine, expire_on_commit=False) as session:
        while session.query(Users).filter(Users.username == username).first():
            username = Generate(2, separator='_').lower() 
        return username

def create_update_user(user_id: str, username: str=None):
    """Create or update user in database"""
    with Session(engine, expire_on_commit=False) as session:
        # Check if user already exists
        user = session.query(Users).filter(Users.id == user_id).first()
        
        if user:
            # Update existing user
            if username: user.username = username  # Use email as username for now
            session.commit()
            return user
        else:
            new_user = Users(
                id=user_id,
                username=generate_username(),  # Use email as username for now
                elo=DEFAULT_ELO,
                elo_history=[DEFAULT_ELO]
            )
            session.add(new_user)
            session.commit()
            return new_user


def get_leaderboard():
    """Get combined leaderboard of users and agents sorted by ELO, only including those with matches"""
    with Session(engine, expire_on_commit=False) as session:
        # Get all agents with their match counts
        agents_with_matches = session.query(
            Agents.id, 
            Agents.name, 
            Agents.elo, 
            Agents.created_at,
            func.count(Matches.id).label('total_matches')
        ).outerjoin(
            Matches, 
            (Matches.agent1_id == Agents.id) | (Matches.agent2_id == Agents.id)
        ).group_by(Agents.id, Agents.name, Agents.elo, Agents.created_at).having(func.count(Matches.id) > 0).all()
        
        agent_data = [
            {
                "id": str(agent.id),
                "name": agent.name,
                "elo": agent.elo,
                "type": "agent",
                "created_at": agent.created_at.isoformat(),
                "total_matches": agent.total_matches
            }
            for agent in agents_with_matches
        ]
        
        # Get all users with their match counts
        users_with_matches = session.query(
            Users.id, 
            Users.username, 
            Users.elo, 
            Users.created_at,
            func.count(Matches.id).label('total_matches')
        ).outerjoin(
            Matches, 
            (Matches.agent1_id == Users.user_uuid) | (Matches.agent2_id == Users.user_uuid)
        ).group_by(Users.id, Users.username, Users.elo, Users.created_at).having(func.count(Matches.id) > 0).all()
        
        user_data = [
            {
                "id": user.user_uuid,
                "username": user.username,
                "elo": user.elo,
                "type": "user",
                "created_at": user.created_at.isoformat(),
                "total_matches": user.total_matches
            }
            for user in users_with_matches
        ]
        
        # Combine and sort by ELO
        combined = agent_data + user_data
        combined.sort(key=lambda x: x["elo"], reverse=True) 
        
        return combined


def get_user_profile(user_id: str):
    """Get user profile with statistics"""
    with Session(engine, expire_on_commit=False) as session:
        user = session.query(Users).filter(Users.id == user_id).first()
        if not user:
            return None
            
        # Get match statistics
        total_matches = session.query(Matches).filter(
            (Matches.agent1_id == user_id) | (Matches.agent2_id == user_id)
        ).count()
        
        wins = session.query(Matches).filter(
            ((Matches.agent1_id == user_id) & (Matches.result == 1)) |
            ((Matches.agent2_id == user_id) & (Matches.result == 2))
        ).count()
        
        defaults = session.query(Matches).filter(
            ((Matches.agent1_id == user_id) & (Matches.agent1_default == True)) |
            ((Matches.agent2_id == user_id) & (Matches.agent2_default == True))
        ).count()

        # Action distribution for this user
        user_matches = session.query(Matches).filter(
            (Matches.agent1_id == user_id) | (Matches.agent2_id == user_id)
        ).all()

        action_counts = {"withhold": 0, "submit_evidence": 0}
        for m in user_matches:
            try:
                is_agent1 = str(m.agent1_id) == str(user_id)
            except Exception:
                is_agent1 = m.agent1_id == user_id
            action = m.agent1_action if is_agent1 else m.agent2_action
            if action in action_counts:
                action_counts[action] += 1

        total_actions = action_counts["withhold"] + action_counts["submit_evidence"]
        action_percentages = {
            "withhold": (action_counts["withhold"] / total_actions) if total_actions else 0,
            "submit_evidence": (action_counts["submit_evidence"] / total_actions) if total_actions else 0,
        }
        
        return {
            "id": user.user_uuid,
            "username": user.username,
            "elo": user.elo,
            "elo_history": user.elo_history,
            "created_at": user.created_at.isoformat(),
            "total_matches": total_matches,
            "wins": wins,
            "win_rate": wins / total_matches if total_matches > 0 else 0,
            "defaults": defaults,
            "default_rate": defaults / total_matches if total_matches > 0 else 0,
            "action_counts": action_counts,
            "action_percentages": action_percentages,
        }


def get_agent_profile(agent_id: str):
    """Get agent profile with statistics"""
    with Session(engine, expire_on_commit=False) as session:
        agent = session.query(Agents).filter(Agents.id == uuid.UUID(agent_id)).first()
        if not agent:
            return None
            
        # Get match statistics
        total_matches = session.query(Matches).filter(
            (Matches.agent1_id == agent.id) | (Matches.agent2_id == agent.id)
        ).count()
        
        wins = session.query(Matches).filter(
            ((Matches.agent1_id == agent.id) & (Matches.result == 1)) |
            ((Matches.agent2_id == agent.id) & (Matches.result == 2))
        ).count()
        
        defaults = session.query(Matches).filter(
            ((Matches.agent1_id == agent.id) & (Matches.agent1_default == True)) |
            ((Matches.agent2_id == agent.id) & (Matches.agent2_default == True))
        ).count()

        # Action distribution for this agent
        agent_matches = session.query(Matches).filter(
            (Matches.agent1_id == agent.id) | (Matches.agent2_id == agent.id)
        ).all()
        action_counts = {"withhold": 0, "submit_evidence": 0}
        for m in agent_matches:
            is_agent1 = m.agent1_id == agent.id
            action = m.agent1_action if is_agent1 else m.agent2_action
            if action in action_counts:
                action_counts[action] += 1

        total_actions = action_counts["withhold"] + action_counts["submit_evidence"]
        action_percentages = {
            "withhold": (action_counts["withhold"] / total_actions) if total_actions else 0,
            "submit_evidence": (action_counts["submit_evidence"] / total_actions) if total_actions else 0,
        }
        
        return {
            "id": str(agent.id),
            "name": agent.name,
            "description": agent.description,
            "elo": agent.elo,
            "created_at": agent.created_at.isoformat(),
            "updated_at": agent.updated_at.isoformat(),
            "total_matches": total_matches,
            "wins": wins,
            "win_rate": wins / total_matches if total_matches > 0 else 0,
            "defaults": defaults,
            "default_rate": defaults / total_matches if total_matches > 0 else 0,
            "action_counts": action_counts,
            "action_percentages": action_percentages,
        }


def get_match_history(player_id: str, limit: int = 50):
    """Get match history for a player (user or agent)"""
    with Session(engine, expire_on_commit=False) as session:
        try: #TODO: lmao try except for agent vs player logic? fix this 
            # Try as UUID first (for agents)
            player_uuid = uuid.UUID(player_id)
            matches = session.query(Matches).filter(
                (Matches.agent1_id == player_uuid) | (Matches.agent2_id == player_uuid)
            ).order_by(Matches.created_at.desc()).limit(limit).all()
        except ValueError:
            # If not UUID, it's a user ID (string)
            matches = session.query(Matches).filter(
                (Matches.agent1_id == player_id) | (Matches.agent2_id == player_id)
            ).order_by(Matches.created_at.desc()).limit(limit).all()
        
        match_data = []
        for match in matches:
            # Get opponent info
            if str(match.agent1_id) == player_id or match.agent1_id == player_id:
                # Player is agent1, opponent is agent2
                opponent_id = str(match.agent2_id)
                a1, a2 = match.agent1_action, match.agent2_action
                if a1 == a2:
                    player_result = 0  # draw
                elif a1 == "submit_evidence" and a2 == "withhold":
                    player_result = 1  # win
                elif a1 == "withhold" and a2 == "submit_evidence":
                    player_result = 2  # loss
                else:
                    # Fallback to stored result
                    player_result = 1 if match.result == 1 else (2 if match.result == 2 else 0)
            else:
                # Player is agent2, opponent is agent1
                opponent_id = str(match.agent1_id)
                a1, a2 = match.agent1_action, match.agent2_action
                if a1 == a2:
                    player_result = 0  # draw
                elif a2 == "submit_evidence" and a1 == "withhold":
                    player_result = 1  # win
                elif a2 == "withhold" and a1 == "submit_evidence":
                    player_result = 2  # loss
                else:
                    # Fallback to stored result
                    player_result = 1 if match.result == 2 else (2 if match.result == 1 else 0)
                
            # Get opponent name
            try:
                opponent_uuid = uuid.UUID(opponent_id)
                opponent = session.query(Agents).filter(Agents.id == opponent_uuid).first()
                opponent_name = opponent.name if opponent else "Unknown Agent"
                opponent_type = "agent"
            except ValueError:
                opponent = session.query(Users).filter(Users.id == opponent_id).first()
                opponent_name = opponent.name if opponent else "Unknown User"
                opponent_type = "user"
            
            match_data.append({
                "id": str(match.id),
                "opponent_id": opponent_id,
                "opponent_name": opponent_name,
                "opponent_type": opponent_type,
                "result": player_result,  # 1: win, 2: loss, 0: draw
                "created_at": match.created_at.isoformat()
            })
        
        return match_data


def get_match_transcript(match_id: str):
    """Get full transcript for a match"""
    with Session(engine, expire_on_commit=False) as session:
        match = session.query(Matches).filter(Matches.id == uuid.UUID(match_id)).first()
        if not match:
            return None
            
        transcripts = session.query(Transcripts).filter(
            Transcripts.match_id == uuid.UUID(match_id)
        ).order_by(Transcripts.order).all()
        
        # Get agent/user names
        agent1 = session.query(Agents).filter(Agents.id == match.agent1_id).first()
        agent2 = session.query(Agents).filter(Agents.id == match.agent2_id).first()
        
        # Handle if one is a user
        if not agent1:
            user1 = session.query(Users).filter(Users.id == str(match.agent1_id)).first()
            agent1_name = user1.username if user1 else "Unknown"
        else:
            agent1_name = agent1.name
            
        if not agent2:
            user2 = session.query(Users).filter(Users.id == str(match.agent2_id)).first()
            agent2_name = user2.username if user2 else "Unknown"
        else:
            agent2_name = agent2.name
        
        # Recompute winner based on actions
        a1, a2 = match.agent1_action, match.agent2_action
        if a1 == a2:
            computed_result = 0
        elif a1 == "submit_evidence" and a2 == "withhold":
            computed_result = 1
        elif a1 == "withhold" and a2 == "submit_evidence":
            computed_result = 2
        else:
            computed_result = match.result

        return {
            "match_id": str(match.id),
            "agent1_name": agent1_name,
            "agent2_name": agent2_name,
            "result": computed_result,
            "agent1_default": match.agent1_default,
            "agent2_default": match.agent2_default,
            "agent1_action": match.agent1_action,
            "agent2_action": match.agent2_action,
            "created_at": match.created_at.isoformat(),
            "transcript": [
                {
                    "order": t.order,
                    "agent_id": t.agent_id,
                    "message": t.message,
                    "created_at": t.created_at.isoformat()
                }
                for t in transcripts
            ]
        }


def update_user_username(user_id: str, username: str):
    """Update user's username"""
    with Session(engine, expire_on_commit=False) as session:
        user = session.query(Users).filter(Users.id == user_id).first()
        if user:
            user.username = username
            session.commit()
            return True
        return False
