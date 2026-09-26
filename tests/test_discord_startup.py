import threading

from fh6 import discord_reports as reports


def test_enabled_reporter_launch_is_nonblocking(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(reports.secrets, 'enabled', lambda: True)
    def launch():
        entered.set()
        release.wait(2)
    monkeypatch.setattr(reports, 'start_watcher', launch)
    thread = reports.start_if_enabled()
    try:
        assert entered.wait(1)
        assert thread.is_alive()
        assert thread.daemon
    finally:
        release.set()
        thread.join(2)


def test_disabled_reports_do_not_launch(monkeypatch):
    monkeypatch.setattr(reports.secrets, 'enabled', lambda: False)
    monkeypatch.setattr(reports, 'start_watcher', lambda: (_ for _ in ()).throw(AssertionError('launched')))
    writes = []
    monkeypatch.setattr(reports, 'write_json', lambda *args: writes.append(args))
    reports.start_if_enabled().join(2)
    assert writes == []


def test_launch_failure_is_sanitized_and_retains_delivery(monkeypatch):
    monkeypatch.setattr(reports.secrets, 'enabled', lambda: True)
    monkeypatch.setattr(reports, 'start_watcher', lambda: (_ for _ in ()).throw(OSError('secret URL')))
    monkeypatch.setattr(reports, 'read_json', lambda path: {'receipt': {'message_id': 'old'}})
    writes = []
    monkeypatch.setattr(reports, 'write_json', lambda path, value: writes.append(value))
    reports.start_if_enabled().join(2)
    assert writes[0]['receipt']['message_id'] == 'old'
    assert 'secret' not in writes[0]['error']
    assert 'could not start' in writes[0]['error']
