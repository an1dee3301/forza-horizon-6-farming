"""Purchase module: preserve the locally tested, single-attempt transaction."""
from forza_cycle import purchase_once, return_to_collection


def buy(nav, ledger):
    purchase_once(nav.recognizer, nav.capture, nav.monitor, nav.title, nav.running, ledger,
                  timeout=nav.timeout, fast=getattr(nav, 'fast_navigation', False) is True)


def acknowledge(nav):
    return_to_collection(nav.recognizer, nav.capture, nav.monitor, nav.title, nav.running,
                         timeout=nav.timeout, fast=getattr(nav, 'fast_navigation', False) is True)
