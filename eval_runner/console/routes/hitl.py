import json
import logging
from queue import Empty, Queue

from flask import Blueprint, Response, jsonify, request, session

from eval_runner.hitl.pending import global_registry, subscribe_sse, unsubscribe_sse

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

hitl_bp = Blueprint("hitl", __name__)


@hitl_bp.route("/v1/hitl/queue", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_hitl_queue():
    """Lists all unresolved pending human intervention requests."""
    pending_items = global_registry.pending()
    return jsonify({"pending": [item.to_dict() for item in pending_items]})


@hitl_bp.route("/v1/hitl/<approval_id>/resolve", methods=["POST"])
@require_permission(Permission.HITL_RESOLVE)
def resolve_hitl_request(approval_id):
    """Resolves a pending human intervention request (approve/reject)."""
    data = request.json or {}
    action = data.get("action")
    response_val = data.get("response", "")

    if not action or action not in ["approve", "reject"]:
        return jsonify({"error": "Invalid action. Must be 'approve' or 'reject'."}), 400

    # Retrieve actor identity from session or token context
    user = session.get("user") or {}
    resolved_by = user.get("id", "root-admin")

    with global_registry._lock:
        approval = global_registry._items.get(approval_id)

    if not approval:
        return jsonify(
            {"error": f"Pending approval item '{approval_id}' not found or already resolved."}
        ), 404

    is_resumed_from_db = bool(getattr(approval, "resumed_from_db", False) is True)
    raw_run_id = getattr(approval, "run_id", None)
    run_id = str(raw_run_id) if isinstance(raw_run_id, str) else None
    raw_token = getattr(approval, "resumption_token", None)
    resumption_token = str(raw_token) if isinstance(raw_token, str) else None

    success = global_registry.resolve(approval_id, action, response_val, resolved_by)
    if not success:
        return jsonify(
            {"error": f"Pending approval item '{approval_id}' not found or already resolved."}
        ), 404

    resumed = False
    if is_resumed_from_db and run_id:
        try:
            from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

            backend = InProcessExecutionBackend.get_instance()
            backend.resume(run_id, resumption_token=resumption_token, background=True)
            resumed = True
            logger.info(
                f"[HITL] Automatically resumed background execution for run '{run_id}' "
                f"after resolving restart-orphaned approval '{approval_id}'"
            )
        except Exception as e:
            logger.warning(f"[HITL] Failed to auto-resume execution for run '{run_id}': {e}")

    return jsonify(
        {
            "resolved": True,
            "approval_id": approval_id,
            "resumed": resumed,
            "run_id": run_id,
        }
    )


@hitl_bp.route("/v1/hitl/stream", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def stream_hitl_events():
    """SSE endpoint to stream real-time creation and resolution events."""
    event_queue = Queue()

    def listener(event_type, data):
        event_queue.put((event_type, data))

    subscribe_sse(listener)

    def event_generator():
        # Yield initial connection confirmation event
        yield "event: ping\ndata: {}\n\n"

        try:
            while True:
                try:
                    # Non-blocking pull with short timeout to allow checking for disconnect
                    event_type, data = event_queue.get(timeout=2.0)
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                except Empty:
                    # Keepalive ping
                    yield "event: ping\ndata: {}\n\n"
        except GeneratorExit:
            # Browser disconnected
            pass
        finally:
            unsubscribe_sse(listener)

    return Response(event_generator(), mimetype="text/event-stream")
