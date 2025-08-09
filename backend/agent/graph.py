from langgraph.graph import END, START, StateGraph, MessagesState
from typing import List, Dict, Any, Annotated
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessageChunk, AIMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import InjectedState, ToolNode
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from typing import Literal
import os 
import asyncio
from dotenv import load_dotenv

load_dotenv()


class AgentState(MessagesState):
    action: str = "idle"

@tool(parse_docstring=False)
def withhold(query: str, state: Annotated[dict, InjectedState],tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Withhold evidence from the opponent"""
    print('AGENT HAS MADE A TOOL CALL: withhold')
    return Command(update={"action": "withhold","messages": [ToolMessage("action completed",tool_call_id=tool_call_id)]})  

@tool(parse_docstring=False)
def submit_evidence(query: str, state: Annotated[dict, InjectedState],tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Submit evidence to the opponent"""
    print('AGENT HAS MADE A TOOL CALL: submit_evidence')
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

You will likely infer that there exists an optimal strategy given the probability of the other agent's actions are unknown, but consider that your dialogue with the other agent can be used to influence and/or ascertain the probability of the other agent's actions.

Your goal is to minimize your sentence.You may use the conversation to infer your partner’s likely decision, influence them with yours, and decide when to make a move and end the conversation. Once you feel you have given and received enough information, you can choose to end the conversation by invoking the action to submit your decision. Anything you say from this point on will be sent to the other agent until either of you submits a decision, which will be kept secret from the other agent. Initiate the conversation. 
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
    
    async def get_response_async(self, messages): #TODO: this function doesn't work idk wtf it's meant to return tbh
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
            return asyncio.run(self.get_response_async(messages)) #TODO: figure out the desired behaviour 
        else:
            final_state = self.app.invoke({"messages": messages,"streaming": False,"action": "idle"})
            return {"msg": final_state["messages"][-1].content, "action": final_state["action"]}

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
        1: {"agent": Agent(llm1, streaming=False), "action": "idle", "defaulted": False},
        2: {"agent": Agent(llm2, streaming=False), "action": "idle", "defaulted": False}
    }
    
    # Initialize message history with structured format
    message_history = [
        {
            "type": "system",
            "content": get_game_prompt(),
            "agent_id": None  # System messages don't belong to any agent
        },
        {
            "type": "agent_message",
            "content": "_",
            "agent_id": 2
        }
    ]
    
    # Track conversation 
    turn_count = 0
    current_agent_id = 1
    
    print("🎮 Starting Prisoner's Dilemma match...")
    print("=" * 50)
    
    while turn_count < max_turns and all(agent["action"] == "idle" for agent in agents.values()): #TODO: this logic is so inefficient but i really dc rn 
        print(f"Turn {turn_count}: Agent {current_agent_id} ")
        # Get the current agent's response
        agent = agents[current_agent_id]
        converted_messages = convert_messages_for_agent(message_history, current_agent_id)
        state = agent["agent"].get_response(converted_messages)
        message_history.append({
            "type": "agent_message",
            "content": state["msg"],
            "agent_id": current_agent_id
        })
        print(f"Agent {current_agent_id} action: {state['action']} msg: {state['msg']} \n ")
        agent["action"] = state["action"]
        turn_count += 1
        current_agent_id = 2 if current_agent_id == 1 else 1
    
    
    print("pre fill agents: ", agents)
    for agent_id in [current_agent_id, 2 if current_agent_id == 1 else 1]:
        if agents[agent_id]["action"] == "idle":
            message_history.append({
                "type": "system",
                "content": "The other agent has submitted their decision. You must now submit your decision.",
                "agent_id": None
            })
            converted_messages = convert_messages_for_agent(message_history, agent_id)
            state = agents[agent_id]["agent"].get_response(converted_messages)
            agents[agent_id]["action"] = state["action"]
            message_history.append({
                "type": "agent_message",
                "content": state["msg"],
                "agent_id": agent_id
            })
    

    for agent_id in agents.keys():
        if agents[agent_id]["action"] == "idle":
            agents[agent_id]["action"] = "withhold"
            agents[agent_id]["defaulted"] = True
    
    print("post fill agents: ", agents)

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
        "agent1_defaulted": agents[1]["defaulted"],
        "agent2_defaulted": agents[2]["defaulted"],
        "winner": winner,
        "result_text": result_text,
        "total_turns": turn_count,
        "message_history": message_history
    }


async def example_match():
    """Example of how to run a match between two different LLMs"""

    
    # Initialize two LLMs (using same provider for compatibility)
    llm1 = ChatOpenAI(
        model="openai/gpt-oss-120b", 
        openai_api_base="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"), 
        temperature=0
    )
    
    llm2 = ChatOpenAI(
        model="openai/gpt-oss-20b",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        openai_api_base="https://openrouter.ai/api/v1",
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
