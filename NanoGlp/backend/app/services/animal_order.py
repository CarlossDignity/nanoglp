"""Operational tracking only: never changes dates/resources on SampleRecord or Study."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from fastapi import HTTPException
from app.utils.facility_time import facility_today


def transition_animal_order(state, payload, user):
    state = deepcopy(state)
    action = payload.action.lower()
    today = facility_today()
    now = datetime.utcnow().isoformat(timespec="seconds")
    tracked = state.get("animal_tracking") is True
    legacy_done = not tracked and (state.get("done") or state.get("marker") == "+")
    if action == "complete":
        if legacy_done:
            return state
        raise HTTPException(
            409, "Hayvan kabulü için önce sipariş, ardından kabul kaydı gerekir."
        )
    if action == "undo":
        if not tracked:
            return {"done": False}
        if state.get("received_date"):
            keys = ("received_date", "received_by_id", "received_by", "received_at")
        elif state.get("order_date"):
            keys = (
                "order_date",
                "estimated_delivery_days",
                "expected_delivery_date",
                "ordered_by_id",
                "ordered_by",
                "ordered_at",
            )
        else:
            return state
        state.setdefault("history", []).append(
            {
                **{k: state.pop(k, None) for k in keys},
                "undone_by_id": user.id,
                "undone_by": user.full_name,
                "undone_at": now,
            }
        )
        for key in ("done_by", "done_at"):
            state.pop(key, None)
        state["done"] = False
        return state
    if action == "order":
        if legacy_done:
            raise HTTPException(
                409, "Tamamlanmış eski kaydı değiştirmek için önce geri alın."
            )
        order_date = payload.order_date or (
            date.fromisoformat(state["order_date"])
            if state.get("order_date")
            else today
        )
        days = (
            payload.estimated_delivery_days
            if payload.estimated_delivery_days is not None
            else state.get("estimated_delivery_days", 15)
        )
        if order_date > today:
            raise HTTPException(
                422, "Sipariş tarihi tesisin bugünkü tarihinden sonra olamaz."
            )
        try:
            expected = order_date + timedelta(days=days)
        except OverflowError:
            raise HTTPException(422, "Tahmini geliş tarihi hesaplanamıyor.")
        if state.get("order_date"):
            if (
                state["order_date"] == order_date.isoformat()
                and state["estimated_delivery_days"] == days
            ):
                return state
            raise HTTPException(
                409, "Sipariş zaten kayıtlı; değiştirmek için önce geri alın."
            )
        return {
            "animal_tracking": True,
            "source": "application",
            "done": False,
            "history": state.get("history", []),
            "order_date": order_date.isoformat(),
            "estimated_delivery_days": days,
            "expected_delivery_date": expected.isoformat(),
            "ordered_by_id": user.id,
            "ordered_by": user.full_name,
            "ordered_at": now,
        }
    if action == "receive":
        if not tracked or not state.get("order_date"):
            raise HTTPException(409, "Kabul için kayıtlı sipariş gerekir.")
        received = payload.received_date
        if (
            received is None
            or received < date.fromisoformat(state["order_date"])
            or received > today
        ):
            raise HTTPException(
                422,
                "Kabul tarihi sipariş tarihinden önce veya tesisin bugünkü tarihinden sonra olamaz.",
            )
        if state.get("received_date"):
            if state["received_date"] == received.isoformat():
                return state
            raise HTTPException(
                409, "Kabul zaten kayıtlı; değiştirmek için önce geri alın."
            )
        state.update(
            received_date=received.isoformat(),
            received_by_id=user.id,
            received_by=user.full_name,
            received_at=now,
            done=True,
            done_by=user.full_name,
            done_at=now,
        )
        return state
    raise HTTPException(422, "Hayvan adımı için order, receive veya undo kullanın.")
