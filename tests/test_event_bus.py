from app.core.event_bus.event_bus import EventBus


def test_subscribe_publish():
    bus = EventBus()
    result = []

    bus.subscribe("event", lambda value: result.append(value))
    bus.publish("event", 5)

    assert result == [5]


def test_unsubscribe():
    bus = EventBus()
    result = []

    def cb(value):
        result.append(value)

    bus.subscribe("event", cb)
    bus.unsubscribe("event", cb)
    bus.publish("event", 1)

    assert result == []


def test_clear():
    bus = EventBus()
    bus.subscribe("a", lambda: None)

    assert bus.has_subscribers("a")

    bus.clear()

    assert not bus.has_subscribers("a")
