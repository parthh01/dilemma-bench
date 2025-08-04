from langgraph.graph import END, START, StateGraph, MessagesState
from typing import List, Dict, Any, Annotated
from langchain_core.messages import HumanMessage , SystemMessage, ToolMessage, AIMessageChunk, AIMessage
from langgraph.prebuilt import InjectedState, ToolNode
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from typing import Literal
import os 

class AgentState(MessagesState):
    action: str = "idle"

@tool(parse_docstring=True)
def throw_key(query: str, state: Annotated[dict, InjectedState],tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Throw the key to the opponent
    """
    return Command(update={"action": "throw_key"})  

@tool(parse_docstring=True)
def keep_key(query: str, state: Annotated[dict, InjectedState],tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Keep the key for yourself, do not throw it to the opponent
    """
    return Command(update={"action": "keep_key"})  

tools = [throw_key,keep_key]
tool_node = ToolNode(tools)


class Agent:
    def __init__(self, llm, streaming: bool = False):
        self.llm = llm
        self.streaming = streaming
        self.app = self.instantiate_graph()

    def instantiate_graph(self):
        model = self.llm.bind_tools(tools)
        def call_model(state: AgentState):
            messages = state['messages']
            response = model.invoke(messages)
            return {"messages": [response],"streaming": self.streaming}

        def should_continue(state: MessagesState) -> Literal["tools", END]:
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

        app = workflow.compile()
        return app


if __name__ == "__main__":
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"), temperature=0,streaming=True)
    agent = Agent(llm, streaming=True)
    agent.app.invoke({"messages": [HumanMessage(content="tell me a joke")]})