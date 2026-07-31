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

    success = global_registry.resolve(approval_id, action, response_val, resolved_by)
    if not success:
        return jsonify(
            {"error": f"Pending approval item '{approval_id}' not found or already resolved."}
        ), 404

    return jsonify({"resolved": True, "approval_id": approval_id})


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
