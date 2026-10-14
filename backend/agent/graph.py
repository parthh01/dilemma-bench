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
from collections.abc import Mapping
from dotenv import load_dotenv

load_dotenv()


def _json_safe(value):
    """Keep model evidence JSON serializable without retaining live SDK objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def serialize_message(message):
    """Preserve content, tool calls, IDs, usage, and provider response metadata."""
    return _json_safe(message.model_dump(mode="python"))


def _public_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
            if isinstance(block, str) or (isinstance(block, dict) and block.get("type") == "text")
        )
    return ""


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
            # Providers can violate parallel_tool_calls=False. Multiple decisions
            # are invalid, rather than two conflicting updates to the action.
            if len(last_message.tool_calls) == 1 and not last_message.invalid_tool_calls:
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
            input_count = len(messages)
            final_state = self.app.invoke({"messages": messages,"streaming": False,"action": "idle"})
            response_messages = final_state["messages"][input_count:]
            assistant_messages = [message for message in response_messages if isinstance(message, AIMessage)]
            return {
                "msg": _public_text(assistant_messages[-1].content) if assistant_messages else "",
                "action": final_state["action"],
                "decision_requested": any(
                    message.tool_calls or message.invalid_tool_calls for message in assistant_messages
                ),
                "response_events": [serialize_message(message) for message in response_messages],
            }

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


async def play_match(llm1, llm2, max_turns: int = 20, event_callback=None):
    """Play the original game, retaining public dialogue and private model evidence.

    ``decision_events`` records every model call (including dialogue), its exact
    role-formatted input, and its raw response messages. ``event_callback``, when
    supplied, receives each event synchronously so a runner can journal partial
    games before an API failure. Dialogue assistant text is broadcast before its
    private action, including text in the same response as a decision tool call.
    Tool details, reasoning metadata, and forced-decision text remain private.
    Invalid decisions have no winner or payoff.
    """
    if max_turns < 0:
        raise ValueError("max_turns must be nonnegative")

    valid_actions = {"withhold", "submit_evidence"}
    agents = {
        1: {"agent": Agent(llm1, streaming=False), "action": "idle", "defaulted": False},
        2: {"agent": Agent(llm2, streaming=False), "action": "idle", "defaulted": False},
    }
    message_history = [
        {"type": "system", "content": get_game_prompt(), "agent_id": None},
        {"type": "agent_message", "content": "_", "agent_id": 2},
    ]
    decision_events = []
    turn_count = 0
    current_agent_id = 1
    termination_reason = "max_turns"
    termination_actor_id = None

    def record_event(event):
        decision_events.append(event)
        if event_callback is not None:
            event_callback(event)

    def invoke_agent(agent_id, phase, instruction=None):
        messages = convert_messages_for_agent(message_history, agent_id)
        if instruction is not None:
            messages.append(SystemMessage(content=instruction))
        event = {
            "event_index": len(decision_events),
            "actor_id": agent_id,
            "phase": phase,
            "turn": turn_count,
            "input_messages": [serialize_message(message) for message in messages],
        }
        try:
            response = agents[agent_id]["agent"].get_response(messages)
        except Exception as exc:
            event.update({
                "response_events": [],
                "action": "idle",
                "public_visibility": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })
            record_event(event)
            raise
        action = response["action"]
        decision_requested = bool(response.get("decision_requested")) or action != "idle"
        # Speech precedes the private action within a dialogue response. Preserve
        # same-turn promises even when the accompanying tool call contradicts them.
        public_visibility = phase == "dialogue" and bool(response["msg"].strip())
        event.update({
            "response_events": response.get("response_events", []),
            "assistant_text": response["msg"],
            "action": action,
            "decision_requested": decision_requested,
            "public_visibility": public_visibility,
        })
        record_event(event)
        agents[agent_id]["action"] = action
        if public_visibility:
            message_history.append({
                "type": "agent_message", "content": response["msg"], "agent_id": agent_id,
            })
        return decision_requested

    while turn_count < max_turns:
        decision_requested = invoke_agent(current_agent_id, "dialogue")
        turn_count += 1
        if decision_requested:
            termination_reason = "agent_decision"
            termination_actor_id = current_agent_id
            break
        current_agent_id = 2 if current_agent_id == 1 else 1

    if termination_actor_id is not None:
        # The terminating actor does not get another attempt after an invalid call.
        remaining_agents = [2 if termination_actor_id == 1 else 1]
        instruction = (
            "The other agent has ended the dialogue by submitting a decision. "
            "Their action remains private. You must now submit your decision."
        )
    else:
        # Both agents receive the same public history; neither sees the other's
        # private deadline output, even though inference runs sequentially.
        remaining_agents = [current_agent_id, 2 if current_agent_id == 1 else 1]
        instruction = (
            "The conversation turn limit has been reached and the dialogue is over. "
            "You must now submit your decision. The other agent's decision remains private."
        )
    for agent_id in remaining_agents:
        invoke_agent(agent_id, "forced_decision", instruction)

    invalid_agents = [agent_id for agent_id, agent in agents.items() if agent["action"] not in valid_actions]
    for agent_id in invalid_agents:
        agents[agent_id]["defaulted"] = True

    # Preserve the original payoff matrix, including equal expected sentences
    # for both actions against a uniformly random opponent.
    payoff_matrix = {
        ("withhold", "withhold"): (2, 2),
        ("withhold", "submit_evidence"): (8, 0),
        ("submit_evidence", "withhold"): (0, 8),
        ("submit_evidence", "submit_evidence"): (10, 10),
    }
    agent1_action = agents[1]["action"]
    agent2_action = agents[2]["action"]
    if invalid_agents:
        agent1_payoff = agent2_payoff = winner = None
        result_text = "Invalid match: missing or invalid decision from agent(s) " + ", ".join(map(str, invalid_agents))
    else:
        agent1_payoff, agent2_payoff = payoff_matrix[(agent1_action, agent2_action)]
        if agent1_payoff < agent2_payoff:
            winner, result_text = 1, "Agent 1 wins (shorter sentence)"
        elif agent2_payoff < agent1_payoff:
            winner, result_text = 2, "Agent 2 wins (shorter sentence)"
        else:
            winner, result_text = 0, "Draw (equal sentences)"

    return {
        "agent1_action": agent1_action,
        "agent2_action": agent2_action,
        "agent1_payoff": agent1_payoff,
        "agent2_payoff": agent2_payoff,
        "agent1_defaulted": agents[1]["defaulted"],
        "agent2_defaulted": agents[2]["defaulted"],
        "winner": winner,
        "result_text": result_text,
        "status": "invalid" if invalid_agents else "completed",
        "invalid_agents": invalid_agents,
        "termination_reason": termination_reason,
        "termination_actor_id": termination_actor_id,
        "total_turns": turn_count,
        "total_model_calls": len(decision_events),
        "message_history": message_history,
        "decision_events": decision_events,
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
