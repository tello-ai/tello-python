"""Call control helpers.

In v0.1 call control is exposed directly on :class:`tello.client.TelloClient`
(``create_call`` / ``answer`` / ``cancel``) since it is all one WS connection.
This module is a placeholder for a future ``client.calls`` grouping if REST
call management (list/get/summary) is ever added; those are **not** part of the
gateway WS contract and are out of scope for v0.1.
"""
