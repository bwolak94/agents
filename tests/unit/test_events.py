"""
Unit tests for core/events.py  (EventBus).

The tests for session_id filtering are written against the *new* API where
EventBus.subscribe() accepts an optional session_id= keyword argument and
the queue only receives events that match that session_id (or all events
when session_id is None).  This is the planned API — tests here describe the
expected behaviour BEFORE the implementation is merged so they act as a spec.
"""
import asyncio
import pytest
from unittest.mock import patch, MagicMock

# We import EventBus directly so each test can work with a fresh instance
# rather than the module-level singleton.
from core.events import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _drain(q: asyncio.Queue) -> list:
    """Return all items currently sitting in the queue (non-blocking)."""
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------

class TestSubscribeUnsubscribe:
    def test_subscribe_returns_queue(self):
        bus = EventBus()
        q = bus.subscribe()
        assert isinstance(q, asyncio.Queue)

    def test_subscribe_adds_to_internal_list(self):
        bus = EventBus()
        assert len(bus._subscribers) == 0
        bus.subscribe()
        assert len(bus._subscribers) == 1

    def test_multiple_subscribers_each_get_own_queue(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        assert q1 is not q2
        assert len(bus._subscribers) == 2

    def test_unsubscribe_removes_queue(self):
        bus = EventBus()
        q = bus.subscribe()
        assert len(bus._subscribers) == 1
        bus.unsubscribe(q)
        assert len(bus._subscribers) == 0

    def test_unsubscribe_unknown_queue_is_safe(self):
        """Unsubscribing a queue that was never registered must not raise."""
        bus = EventBus()
        orphan = asyncio.Queue()
        bus.unsubscribe(orphan)  # should not raise

    def test_unsubscribe_only_removes_matching_queue(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.unsubscribe(q1)
        assert q2 in bus._subscribers
        assert q1 not in bus._subscribers


# ---------------------------------------------------------------------------
# emit — basic broadcasting
# ---------------------------------------------------------------------------

class TestEmit:
    @pytest.mark.asyncio
    async def test_emit_delivers_to_single_subscriber(self):
        bus = EventBus()
        q = bus.subscribe()
        event = {"type": "test", "value": 42}
        await bus.emit(event)
        assert not q.empty()
        received = q.get_nowait()
        assert received == event

    @pytest.mark.asyncio
    async def test_emit_broadcasts_to_all_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        q3 = bus.subscribe()
        event = {"type": "broadcast", "msg": "hello"}
        await bus.emit(event)
        for q in (q1, q2, q3):
            assert not q.empty()
            assert q.get_nowait() == event

    @pytest.mark.asyncio
    async def test_emit_with_no_subscribers_does_not_raise(self):
        bus = EventBus()
        await bus.emit({"type": "orphan"})  # should not raise

    @pytest.mark.asyncio
    async def test_emit_multiple_events_preserves_order(self):
        bus = EventBus()
        q = bus.subscribe()
        events = [{"type": "e", "seq": i} for i in range(5)]
        for ev in events:
            await bus.emit(ev)
        received = await _drain(q)
        assert received == events

    @pytest.mark.asyncio
    async def test_emit_after_unsubscribe_not_delivered(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        await bus.emit({"type": "gone"})
        assert q.empty()


# ---------------------------------------------------------------------------
# QueueFull — slow subscriber is silently dropped
# ---------------------------------------------------------------------------

class TestQueueFull:
    @pytest.mark.asyncio
    async def test_full_queue_drops_event_silently(self):
        """When a subscriber's queue is full, emit() must not raise and must
        not block — the event is simply dropped for that subscriber."""
        bus = EventBus()
        q = bus.subscribe()
        # Fill the queue to capacity
        for i in range(q.maxsize):
            q.put_nowait({"type": "fill", "i": i})
        # This must not raise QueueFull or block
        await bus.emit({"type": "overflow"})
        # Queue size unchanged — overflow event was dropped
        assert q.qsize() == q.maxsize

    @pytest.mark.asyncio
    async def test_full_queue_does_not_affect_other_subscribers(self):
        """A full queue for one subscriber must not prevent delivery to others."""
        bus = EventBus()
        full_q = bus.subscribe()
        ok_q = bus.subscribe()
        # Fill only full_q
        for i in range(full_q.maxsize):
            full_q.put_nowait({"type": "fill", "i": i})
        event = {"type": "important"}
        await bus.emit(event)
        # ok_q should still receive it
        assert not ok_q.empty()
        assert ok_q.get_nowait() == event


# ---------------------------------------------------------------------------
# session_id filtering — NEW API (subscribe(session_id=...))
#
# These tests describe the planned behaviour.  The current EventBus has no
# session_id support, so these tests WILL FAIL against the current code and
# PASS once the new API is implemented.
# ---------------------------------------------------------------------------

class TestSessionIdFiltering:
    @pytest.mark.asyncio
    async def test_subscriber_with_no_session_id_receives_all_events(self):
        """subscribe(session_id=None) — receives every event regardless of session."""
        bus = EventBus()
        q = bus.subscribe(session_id=None)
        await bus.emit({"type": "e", "session_id": "alice"})
        await bus.emit({"type": "e", "session_id": "bob"})
        received = await _drain(q)
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_subscriber_with_session_id_only_gets_matching_events(self):
        """subscribe(session_id='alice') — only receives events where event['session_id'] == 'alice'."""
        bus = EventBus()
        alice_q = bus.subscribe(session_id="alice")
        await bus.emit({"type": "msg", "session_id": "alice"})
        await bus.emit({"type": "msg", "session_id": "bob"})
        await bus.emit({"type": "msg", "session_id": "alice"})
        received = await _drain(alice_q)
        assert len(received) == 2
        assert all(e["session_id"] == "alice" for e in received)

    @pytest.mark.asyncio
    async def test_two_session_subscribers_are_isolated(self):
        """Two subscribers with different session_ids must not see each other's events."""
        bus = EventBus()
        alice_q = bus.subscribe(session_id="alice")
        bob_q = bus.subscribe(session_id="bob")
        await bus.emit({"type": "msg", "session_id": "alice"})
        await bus.emit({"type": "msg", "session_id": "bob"})
        alice_items = await _drain(alice_q)
        bob_items = await _drain(bob_q)
        assert len(alice_items) == 1
        assert alice_items[0]["session_id"] == "alice"
        assert len(bob_items) == 1
        assert bob_items[0]["session_id"] == "bob"

    @pytest.mark.asyncio
    async def test_session_subscriber_and_global_subscriber_coexist(self):
        """A global subscriber (session_id=None) and a session subscriber can coexist.
        Global gets all; session subscriber only gets its own."""
        bus = EventBus()
        global_q = bus.subscribe(session_id=None)
        alice_q = bus.subscribe(session_id="alice")
        await bus.emit({"type": "x", "session_id": "alice"})
        await bus.emit({"type": "x", "session_id": "charlie"})
        global_items = await _drain(global_q)
        alice_items = await _drain(alice_q)
        assert len(global_items) == 2
        assert len(alice_items) == 1

    @pytest.mark.asyncio
    async def test_event_without_session_id_key_delivered_to_global_only(self):
        """Events that carry no session_id key should reach global subscribers
        but not session-specific ones (session_id mismatch is treated as no match)."""
        bus = EventBus()
        global_q = bus.subscribe(session_id=None)
        alice_q = bus.subscribe(session_id="alice")
        await bus.emit({"type": "heartbeat"})  # no session_id field
        global_items = await _drain(global_q)
        alice_items = await _drain(alice_q)
        assert len(global_items) == 1
        assert len(alice_items) == 0
