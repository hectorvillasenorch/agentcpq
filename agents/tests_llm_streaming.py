"""Regression tests for the streaming LLM helper (``agents.llm.chat_stream``)."""

from unittest import mock

from django.test import SimpleTestCase

from agents.llm import chat_stream
from agents.streaming import StreamSink, set_sink


def _chunk(content):
    class _Delta:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.delta = _Delta(c)

    class _Chunk:
        def __init__(self, c):
            self.choices = [_Choice(c)]

    return _Chunk(content)


class ChatStreamTests(SimpleTestCase):
    def test_stream_returns_joined_content(self):
        """Streaming must return ``.choices[0].message.content`` with the full text.

        Regression: ``class _Msg: content = content`` raised
        ``NameError: name 'content' is not defined`` inside the class body.
        """
        client = mock.Mock()
        client.chat.completions.create.return_value = [
            _chunk("Hello"),
            _chunk(", "),
            _chunk("world"),
        ]

        sink = StreamSink()
        set_sink(sink)
        try:
            resp = chat_stream(client, "test-model", [{"role": "user", "content": "hi"}])
        finally:
            set_sink(None)

        self.assertEqual(resp.choices[0].message.content, "Hello, world")

    def test_no_sink_delegates_to_normal_create(self):
        """Without a sink, ``chat_stream`` behaves like a normal (non-stream) call."""
        client = mock.Mock()
        client.chat.completions.create.return_value = "ok"

        set_sink(None)
        resp = chat_stream(client, "test-model", [{"role": "user", "content": "hi"}])

        self.assertEqual(resp, "ok")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertNotIn("stream", kwargs)
