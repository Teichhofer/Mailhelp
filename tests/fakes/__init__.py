"""Test doubles and shared synthetic fixtures (Planung 4.1, Schritt 9.3).

Test modules import from here, never from one another, and every module states what it
replaces. No module talks to a real external service or uses personal data.

* Doubles of one component: ``activity_fakes``, ``clock_fakes``, ``dav_fakes``,
  ``lock_fakes``, ``log_fakes``, ``push_fakes``, ``store_fakes``.
* Harnesses running real application parts against synthetic services:
  ``initial_harness``, ``learning_harness``, ``provider_matrix``, ``safety_harness``,
  ``reconciliation_fakes``.
* Fixtures and doubles shared by the tests of one area: ``shared_<area>``.
  ``shared_web_auth``, ``shared_web_actions``, ``shared_web_server``, ``shared_setup`` and
  ``shared_profiles`` also provide pytest fixtures and are loaded as plugins by
  ``tests/conftest.py``.

Modules are imported directly (``from tests.fakes.shared_core import proposal``); this
package re-exports nothing, so importing one double never loads the others.
"""
