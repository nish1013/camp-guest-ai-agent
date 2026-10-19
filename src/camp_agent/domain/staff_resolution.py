from camp_agent.domain.route_guard import Category, TaskKind, TaskState
from camp_agent.domain.specialist import specialist_for


def approved_state(kind: TaskKind, reported: bool) -> TaskState:
    # An approved task goes back into its lane; one with no lane is done by staff.
    if kind is TaskKind.FAULT:
        # A fault never reported is checked against its cabin first (I4).
        return TaskState.DRAFTING if reported else TaskState.SPLIT_CONFIRMED
    if kind is TaskKind.TABLE:
        return TaskState.QUEUED
    return TaskState.DONE


def edit_errors(kind: TaskKind, category: Category | None, edited: bool) -> list[str]:
    # Staff edit the proposed action only, never write to the guest (D31).
    if not edited:
        return []
    if kind is not TaskKind.FAULT:
        return ["only a fault's category and urgency can be edited"]
    if category is not None and specialist_for(category) is None:
        return [f"no specialist for {category}"]
    return []
