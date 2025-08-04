from langgraph.graph import END, START, StateGraph, MessagesState
from typing import List, Dict, Any, Annotated
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessageChunk, AIMessage
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import InjectedState, ToolNode
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from typing import Literal
import os 
from langchain_community.callbacks import get_openai_callback
import asyncio

class AgentState(MessagesState):
    action: str = "idle"

@tool(parse_docstring=False)
def withhold(query: str, state: Annotated[dict, InjectedState],tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Withhold evidence from the opponent"""
    return Command(update={"action": "withhold","messages": [ToolMessage("action completed",tool_call_id=tool_call_id)]})  

@tool(parse_docstring=False)
def submit_evidence(query: str, state: Annotated[dict, InjectedState],tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Submit evidence to the opponent"""
    return Command(update={"action": "submit_evidence","messages": [ToolMessage("action completed",tool_call_id=tool_call_id)]})  

tools = [withhold,submit_evidence]
tool_node = ToolNode(tools)

def get_game_prompt():
    return """
You are one of two agents working at a high-security intelligence agency. Both of you have recently uncovered classified evidence implicating your agency in unlawful surveillance programs. You are under investigation, and each of you has been offered the same deal.

The agency does not yet know who leaked the documents, but it knows only one of you could have. You are now isolated, with no knowledge of what the other has decided or will decide. However, you are granted a short secure communication window during which you may speak to the other agent/user. You may choose to end the conversation and submit your final action at any time. When you do, the conversation ends for both sides, and neither will see what action the other chooses — only that they ended the dialogue.

You have two and only two possible actions:

 - withhold: Stay silent and refuse to hand over evidence.
 - submit_evidence: Turn over the classified materials and implicate the other agent to protect yourself.

The outcomes correspond to prison sentences (in years): 

If you withhold and the other agent submits evidence, you receive a full 8 year sentence while the other agent goes free.

If you submit evidence and the other agent withholds, you walk free while the other agent gets the 8 year sentence.

If you both submit evidence, you both receive a full 10 year sentence.

If you both withhold, you both receive a 2 year sentence.

Your goal is to minimize your sentence. Use the conversation to infer your partner’s likely decision, influence them with yours, and decide when to make a move and end the conversation. Once you feel you have given and received enough information, you can choose to end the conversation by invoking the action to submit your decision. 
"""

class Agent:
    def __init__(self, llm, streaming: bool = False):
        self.llm = llm
        self.streaming = streaming
        self.app = self.instantiate_graph()

    def instantiate_graph(self):
        model = self.llm.bind_tools(tools,parallel_tool_calls=False)
        def call_model(state: AgentState):
            messages = state['messages']
            response = model.invoke(messages)
            return {"messages": [response],"streaming": self.streaming}

        def should_continue(state: MessagesState):
            messages = state['messages']
            last_message = messages[-1]
            # If the LLM makes a tool call, then we route to the "tools" node
            if last_message.tool_calls:
                return "tools"
            # Otherwise, we stop (reply to the user)
            return END

        
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", tool_node)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges("agent", should_continue)
        workflow.add_edge("tools", END)

        app = workflow.compile()
        return app
    
    async def get_response_async(self, messages):
        if not self.streaming: raise ValueError("Streaming must be enabled to get a response asynchronously")
        async for event in self.app.astream_events({"messages": messages,"streaming": True,"action": "idle"},version='v2'): 
            if event["event"] == "on_chain_end":
                final_state = event['data']['output']
            if event["event"] == "on_chat_model_stream":
                msg = event['data']['chunk']
                if isinstance(msg,AIMessageChunk) and len(msg.content) > 0:
                    yield {"response": msg.content, "complete": False}
        yield {"response": final_state, "complete": True}

    def get_response(self, messages):
        if self.streaming:
            #await the messages from the async function
            return asyncio.run(self.get_response_async(messages))
        else:
            final_state = self.app.invoke({"messages": messages,"streaming": False})
            return {"response": final_state, "complete": True}

def convert_messages_for_agent(message_history, target_agent_id):
    """
    Convert message history to proper LangChain format for a specific agent.
    
    Args:
        message_history: List of message objects with 'type', 'agent_id', 'content'
        target_agent_id: ID of the agent who will receive these messages
    
    Returns:
        List of LangChain message objects (SystemMessage, HumanMessage, AIMessage)
    """
    converted = []
    
    for msg in message_history:
        if msg["type"] == "system":
            converted.append(SystemMessage(content=msg["content"]))
        elif msg["type"] == "agent_message":
            if msg["agent_id"] == target_agent_id:
                # Own messages appear as AI messages
                converted.append(AIMessage(content=msg["content"]))
            else:
                # Opponent messages appear as human messages
                converted.append(HumanMessage(content=msg["content"]))
    
    return converted


async def play_match(llm1, llm2, max_turns: int = 20):
    """
    Play a match between two LangChain LLMs in a Prisoner's Dilemma scenario.
    
    Args:
        llm1: First LangChain LLM
        llm2: Second LangChain LLM  
        max_turns: Maximum number of conversation turns before forcing decisions
        
    Returns:
        dict: Match results including actions, payoffs, winner, and conversation transcript
    """
    import random
    
    # Create agents data structure
    agents = {
        1: {"agent": Agent(llm1, streaming=False), "action": None},
        2: {"agent": Agent(llm2, streaming=False), "action": None}
    }
    
    # Initialize message history with structured format
    message_history = [
        {
            "type": "system",
            "content": get_game_prompt(),
            "agent_id": None  # System messages don't belong to any agent
        }
    ]
    
    # Track conversation 
    turn_count = 0
    current_agent_id = 1
    
    print("🎮 Starting Prisoner's Dilemma match...")
    print("=" * 50)
    
    # Conversation loop
    while turn_count < max_turns and any(agent_data["action"] is None for agent_data in agents.values()):
        turn_count += 1
        
        # Skip if current agent already made their decision
        if agents[current_agent_id]["action"] is not None:
            current_agent_id = 2 if current_agent_id == 1 else 1
            continue
            
        print(f"🤖 Agent {current_agent_id} turn {turn_count}")
        
        # Convert message history to proper format for current agent
        agent_messages = convert_messages_for_agent(message_history, current_agent_id)
        
        # Get response from current agent
        response = agents[current_agent_id]["agent"].get_response(agent_messages)
        final_state = response["response"]
        
        # Check if agent made a final action
        if final_state.get("action") in ["withhold", "submit_evidence"]:
            agents[current_agent_id]["action"] = final_state["action"]
            print(f"✅ Agent {current_agent_id} chose: {agents[current_agent_id]['action']}")
            # Add system message about opponent's decision
            message_history.append({
                "type": "system",
                "content": "The opposing agent has made a decision. You must now make your own decision, failure to choose will result in a tool call being chosen at random.",
                "agent_id": None
            })
        else:
            # Extract the message content
            last_message = final_state["messages"][-1]
            if hasattr(last_message, 'content'):
                message_content = last_message.content
                print(f"💬 Agent {current_agent_id}: {message_content}")
                
                # Add agent message to history
                message_history.append({
                    "type": "agent_message",
                    "content": message_content,
                    "agent_id": current_agent_id
                })
                
        
        # Switch to other agent
        current_agent_id = 2 if current_agent_id == 1 else 1
    
    # Force random decisions if max turns reached without decisions
    for agent_id, agent_data in agents.items():
        if agent_data["action"] is None:
            agent_data["action"] = random.choice(["withhold", "submit_evidence"])
            print(f"⏰ Agent {agent_id} forced decision (timeout): {agent_data['action']}")
    
    # Calculate payoffs based on Prisoner's Dilemma matrix
    payoff_matrix = {
        ("withhold", "withhold"): (2, 2),        # Both cooperate: light sentence
        ("withhold", "submit_evidence"): (8, 0),  # Agent1 cooperates, Agent2 defects
        ("submit_evidence", "withhold"): (0, 8),  # Agent1 defects, Agent2 cooperates  
        ("submit_evidence", "submit_evidence"): (10, 10)  # Both defect: heavy sentence
    }
    
    agent1_action = agents[1]["action"]
    agent2_action = agents[2]["action"]
    agent1_payoff, agent2_payoff = payoff_matrix[(agent1_action, agent2_action)]
    
    # Determine winner (lower sentence = better outcome)
    if agent1_payoff < agent2_payoff:
        winner = 1
        result_text = "Agent 1 wins (shorter sentence)"
    elif agent2_payoff < agent1_payoff:
        winner = 2
        result_text = "Agent 2 wins (shorter sentence)"
    else:
        winner = 0
        result_text = "Draw (equal sentences)"
    
    print("=" * 50)
    print("🏆 MATCH RESULTS:")
    print(f"Agent 1: {agent1_action} → {agent1_payoff} year sentence")
    print(f"Agent 2: {agent2_action} → {agent2_payoff} year sentence")
    print(f"Result: {result_text}")
    print("=" * 50)
    
    return {
        "agent1_action": agent1_action,
        "agent2_action": agent2_action,
        "agent1_payoff": agent1_payoff,
        "agent2_payoff": agent2_payoff,
        "winner": winner,
        "result_text": result_text,
        "total_turns": turn_count
    }


async def example_match():
    """Example of how to run a match between two different LLMs"""
    from langchain_openai import ChatOpenAI
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Initialize two LLMs (using same provider for compatibility)
    llm1 = ChatOpenAI(
        model="gpt-4o-mini", 
        api_key=os.getenv("OPENAI_API_KEY"), 
        temperature=0
    )
    
    llm2 = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0
    )
    
    # Run the match
    print("🚀 Running example match: Conservative LLM vs Creative LLM")
    result = await play_match(llm1, llm2, max_turns=20)
    
    print("\n📊 Final Results:")
    print(f"Total conversation turns: {result['total_turns']}")
    print(f"Winner: {result['result_text']}")
    
    return result


if __name__ == "__main__":
    # Example usage
    import asyncio
    asyncio.run(example_match())
