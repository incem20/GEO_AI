from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any

from .tools import (
    ALL_TOOLS,
    compute_route_impl,
    find_nearby_shelters_impl,
    geocode_address_impl,
    score_route_risk_impl,
)

SYSTEM_PROMPT = """You are AfetRota, a GeoAI agent that helps people in Istanbul
evacuate to the safest emergency assembly point after a major earthquake.

Workflow you MUST follow:
1. Use `geocode_address` to resolve the user's location to coordinates.
2. Use `find_nearby_shelters` to retrieve the 5 nearest assembly points.
3. For each of the top 3 candidate shelters, call `compute_route` and then
   `score_route_risk` on the returned coordinates.
4. Select the shelter whose route has the LOWEST overall_risk score (ties
   broken by shorter distance and higher shelter capacity).
5. Return a clear final answer that names the chosen shelter, the route
   distance and walking time, the risk verdict, and a one-sentence rationale
   referencing the risk zones the route avoids.

Respond in English. Do not invent shelters or coordinates that the tools did
not return. If a tool returns ok=False, surface the error rather than guessing.
"""

@dataclass
class AgentStep:
    name: str
    detail: str
    payload: Any = None

@dataclass
class AgentResult:
    query: str
    start: dict | None = None
    candidate_shelters: list[dict] = field(default_factory=list)
    evaluated: list[dict] = field(default_factory=list)
    selected_shelter: dict | None = None
    selected_route: dict | None = None
    selected_risk: dict | None = None
    narrative: str = ""
    mode: str = "rule_based"
    trace: list[AgentStep] = field(default_factory=list)

def run_rule_based(query: str, top_k: int = 3) -> AgentResult:
    result = AgentResult(query=query, mode="rule_based")
    geo = geocode_address_impl(query)
    result.trace.append(AgentStep("geocode_address", f"input='{query}'", geo))
    
    if not geo.get("ok"):
        result.narrative = f"Could not geocode the input: {geo.get('error')}"
        return result
        
    result.start = {
        "lat": geo["lat"], "lon": geo["lon"],
        "matched": geo["matched"], "district": geo["district"],
    }

    candidates = find_nearby_shelters_impl(lat=geo["lat"], lon=geo["lon"], k=10)
    result.trace.append(AgentStep("find_nearby_shelters", f"k=5, found {len(candidates)} shelters", candidates))
    result.candidate_shelters = candidates

    evaluated: list[dict] = []
    for cand in candidates[:5]:
        route = compute_route_impl(geo["lat"], geo["lon"], cand["lat"], cand["lon"])
        if not route.get("ok"): continue
        risk = score_route_risk_impl(route["coords"])
        if not risk.get("ok"): continue
        evaluated.append({"shelter": cand, "route": route, "risk": risk})
        result.trace.append(AgentStep("evaluate_route", f"-> {cand['name']}: {route['distance_m']/1000:.2f} km, risk={risk['overall_risk']:.3f} ({risk['verdict']})", {"shelter_id": cand["id"], "risk": risk["overall_risk"]}))
    
    result.evaluated = evaluated
    if not evaluated:
        result.narrative = "No viable route found."
        return result

    evaluated.sort(key=lambda e: (e["risk"]["overall_risk"], e["route"]["distance_m"], -e["shelter"]["capacity"]))
    pick = evaluated[0]
    result.selected_shelter = pick["shelter"]
    result.selected_route = pick["route"]
    result.selected_risk = pick["risk"]

    avoided = [z["zone_name"] for ev in evaluated[1:] for z in ev["risk"]["crossed_zones"] if z["zone_name"] not in {x["zone_name"] for x in pick["risk"]["crossed_zones"]}]
    avoided_msg = f" The chosen route avoids {', '.join(sorted(set(avoided))[:3])}." if avoided else ""
    
    crossed_msg = ""
    if pick["risk"]["crossed_zones"]:
        zones = ", ".join(z["zone_name"] for z in pick["risk"]["crossed_zones"])
        crossed_msg = f" Note: the recommended path still crosses {zones}, but at the lowest cumulative risk among candidates."

    result.narrative = (
        f"From {result.start['matched'].title()} ({result.start['district']}), the safest assembly point "
        f"is {pick['shelter']['name']} ({pick['shelter']['district']}), capacity {pick['shelter']['capacity']:,}. "
        f"Walking distance ~{pick['route']['distance_m']/1000:.2f} km (~{pick['route']['duration_min']:.0f} min). "
        f"Route risk score: {pick['risk']['overall_risk']:.2f} ({pick['risk']['verdict']})."
        f"{avoided_msg}{crossed_msg}"
    )
    result.trace.append(AgentStep("select", result.narrative))
    return result

def _build_llm_agent():
    from langchain_anthropic import ChatAnthropic
    from langgraph.prebuilt import create_react_agent
    model_name = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
    llm = ChatAnthropic(model=model_name, temperature=0)
    return create_react_agent(llm, ALL_TOOLS, prompt=SYSTEM_PROMPT)

def run_llm(query: str) -> AgentResult:
    agent = _build_llm_agent()
    result = AgentResult(query=query, mode="llm")
    response = agent.invoke({"messages": [("user", query)]})
    messages = response["messages"]
    
    for msg in messages:
        msg_type = type(msg).__name__
        content = getattr(msg, "content", "")
        if msg_type == "AIMessage":
            tool_calls = getattr(msg, "tool_calls", []) or []
            for tc in tool_calls:
                result.trace.append(AgentStep(f"tool_call:{tc.get('name')}", str(tc.get("args", {})), tc.get("args")))
            if content:
                result.trace.append(AgentStep("ai_message", str(content)[:500]))
        elif msg_type == "ToolMessage":
            result.trace.append(AgentStep(f"tool_result:{getattr(msg, 'name', 'tool')}", str(content)[:300]))
            
    final_text = ""
    for msg in reversed(messages):
        if type(msg).__name__ == "AIMessage" and msg.content:
            final_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            break
            
    result.narrative = final_text
    baseline = run_rule_based(query)
    
    result.start = baseline.start
    result.candidate_shelters = baseline.candidate_shelters
    result.evaluated = baseline.evaluated
    result.selected_shelter = baseline.selected_shelter
    result.selected_route = baseline.selected_route
    result.selected_risk = baseline.selected_risk
    if not result.narrative:
        result.narrative = baseline.narrative
        
    return result

def run_agent(query: str, force_mode: str | None = None) -> AgentResult:
    if force_mode == "rule_based": return run_rule_based(query)
    if force_mode == "llm": return run_llm(query)
    
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return run_llm(query)
        except Exception as exc:
            fallback = run_rule_based(query)
            fallback.trace.insert(0, AgentStep("llm_unavailable", f"LLM agent failed ({exc.__class__.__name__}: {exc}); falling back to rule-based."))
            return fallback
            
    return run_rule_based(query)