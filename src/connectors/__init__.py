"""Everything Sentry talks to that is not Sentry.

:mod:`connectors.memory_connector` is the storage the recordings live in;
:mod:`connectors.genai_connectors` is the generative backend behind the
summaries. Both are interfaces first and one implementation second, so
what is on the other side can be replaced without the core noticing.
"""
