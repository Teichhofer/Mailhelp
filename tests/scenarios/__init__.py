"""Synthetic application states and process entry points (Planung 4.1, Schritt 9.3).

* ``web_scenario``: synthetic Mailhelp state shared by the Python and the browser tests.
* ``safety_process``: real application entry points in a spawned process with hard-kill
  checkpoints, started by ``tests.fakes.safety_harness.ProcessHarness``.

Modules are imported directly; this package re-exports nothing.
"""
