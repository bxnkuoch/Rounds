"""Thin LangChain tools over the Services seam. No logic lives here.

Every tool returns model_dump_json() of the service result, or the string
"ERROR: <ExceptionType>: <message>". A tool never raises. Argument-validation
failures (e.g. a malformed id) are also returned as error strings, via
handle_validation_error.
"""
import json
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, TypeAdapter

from app.models.domain import JobAdded, SafeId, StaffUnavailable
from app.services.contract import Services

_NUMBERS = " Quote every number from the result exactly; never estimate or compute distances, times or orderings yourself."


def _dump(result: Any) -> str:
    if isinstance(result, BaseModel):
        return result.model_dump_json()
    if isinstance(result, list):
        return json.dumps([TypeAdapter(type(r)).dump_python(r, mode="json") for r in result])
    return json.dumps(result)


def _err(e: Exception) -> str:
    return f"ERROR: {type(e).__name__}: {e}"


def _validation_err(e: Exception) -> str:
    return f"ERROR: {type(e).__name__}: invalid arguments: {e}"


def _wrap(name: str, fn: Callable[..., Any], description: str, args_schema: type[BaseModel] | None = None) -> BaseTool:
    def run(**kwargs: Any) -> str:
        try:
            return _dump(fn(**kwargs))
        except Exception as e:  # a tool never raises
            return _err(e)

    return StructuredTool.from_function(
        func=run, name=name, description=description + _NUMBERS, args_schema=args_schema,
        handle_validation_error=_validation_err,
    )


class _NoArgs(BaseModel):
    pass


class _ListJobs(BaseModel):
    status: str | None = None


class _ProposePlan(BaseModel):
    job_ids: list[str] | None = None


class _ProposeReplan(BaseModel):
    kind: Literal["job_added", "staff_unavailable"]
    id: SafeId


class _Route(BaseModel):
    a_place_id: str
    b_place_id: str


class _CompareSwap(BaseModel):
    staff_id: SafeId
    job_a: SafeId
    job_b: SafeId


class _Apply(BaseModel):
    plan_id: str


def build_tools(services: Services) -> dict[str, BaseTool]:
    def propose_replan(kind: str, id: str):
        event = JobAdded(kind="job_added", job_id=id) if kind == "job_added" else StaffUnavailable(
            kind="staff_unavailable", staff_id=id)
        return services.propose_replan(event)

    tools = [
        _wrap("list_places", services.list_places, "List places (rooms/labels) known to the map.", _NoArgs),
        _wrap("list_staff", services.list_staff, "List staff members and their shifts.", _NoArgs),
        _wrap("list_jobs", lambda status=None: services.list_jobs(status),
              "List jobs, optionally filtered by status.", _ListJobs),
        _wrap("get_current_plan", services.get_current_plan, "Get the currently applied plan, or null.", _NoArgs),
        _wrap("propose_plan", lambda job_ids=None: services.propose_plan(job_ids),
              "Propose a plan for all jobs (or the given job_ids). Returns a Proposal; read plan.id from it. "
              "Does not change the schedule.", _ProposePlan),
        _wrap("propose_replan", propose_replan,
              "Propose a replan after an event: kind 'job_added' with the job id, or 'staff_unavailable' with the "
              "staff id. Returns a Proposal; read plan.id from it. Does not change the schedule.", _ProposeReplan),
        _wrap("route_between", services.route_between,
              "Get the walking route (meters, node ids) between two place ids.", _Route),
        _wrap("compare_swap", services.compare_swap,
              "Read-only what-if: a staff member's jobs in the current plan's order vs the same jobs with job_a and "
              "job_b swapped, replayed with the optimizer's travel model. Returns both orders' stops, total_meters "
              "and late jobs, plus meters_delta and late_jobs_delta (swapped minus current). Changes nothing.",
              _CompareSwap),
        _wrap("shift_summary", services.shift_summary,
              "Read-only facts for the shift handoff: each staff member's remaining jobs, next stop and remaining "
              "meters after the current time, plus late, infeasible and unscheduled jobs and the plan's meters vs "
              "baseline.", _NoArgs),
        _wrap("apply_plan", lambda plan_id: services.apply_plan(plan_id),
              "Apply a previously proposed plan by plan_id. Requires human approval.", _Apply),
    ]
    return {t.name: t for t in tools}
