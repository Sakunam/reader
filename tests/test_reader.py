from datetime import datetime
from itertools import chain
from collections import OrderedDict
import threading

import pytest

from reader.reader import Reader, Feed, Entry
from reader.parser import ParseError, NotModified

from test_parser import make_feed, make_entry


@pytest.fixture
def reader(monkeypatch, tmpdir):
    monkeypatch.chdir(tmpdir)
    return Reader(':memory:')


class FakeParser:

    def __init__(self, feeds=None, entries=None):
        self.feeds = feeds or {}
        self.entries = entries or {}

    @classmethod
    def from_parser(cls, other):
        return cls(other.feeds, other.entries)

    def feed(self, number, updated=None):
        feed = make_feed(number, updated)
        self.feeds[number] = feed
        self.entries.setdefault(number, OrderedDict())
        return feed

    def entry(self, feed_number, number, updated):
        entry = make_entry(number, updated)
        self.entries[feed_number][number] = entry
        return entry

    def __call__(self, url, http_etag, http_last_modified):
        for feed_number, feed in self.feeds.items():
            if feed.url == url:
                break
        else:
            raise RuntimeError("unkown feed: {}".format(url))
        return feed, self.entries[feed_number].values(), http_etag, http_last_modified

    def get_tuples(self):
        for feed_number, entries in self.entries.items():
            feed = self.feeds[feed_number]
            for entry in entries.values():
                yield feed, entry


class BlockingFakeParser(FakeParser):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_parser = threading.Event()
        self.can_return_from_parser = threading.Event()

    def __call__(self, *args, **kwargs):
        self.in_parser.set()
        self.can_return_from_parser.wait()
        raise ParseError()


def test_update_feed_updated(reader):
    """A feed should be processed only if it is newer than the stored one."""

    parser = FakeParser()
    reader._parse = parser

    old_feed = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(old_feed.url)
    reader.update_feeds()
    assert set(reader.get_entries()) == {(old_feed, entry_one)}

    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    reader.update_feeds()
    assert set(reader.get_entries()) == {(old_feed, entry_one)}

    new_feed = parser.feed(1, datetime(2010, 1, 2))
    reader.update_feeds()
    assert set(reader.get_entries()) == {(new_feed, entry_one), (new_feed, entry_two)}


def test_update_entry_updated(reader):
    """An entry should be updated only if it is newer than the stored one."""

    parser = FakeParser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    old_entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()
    assert set(reader.get_entries()) == {(feed, old_entry)}

    feed = parser.feed(1, datetime(2010, 1, 2))
    new_entry = old_entry._replace(title='New Entry')
    parser.entries[1][1] = new_entry
    reader.update_feeds()
    assert set(reader.get_entries()) == {(feed, old_entry)}

    feed = parser.feed(1, datetime(2010, 1, 3))
    new_entry = new_entry._replace(updated=datetime(2010, 1, 2))
    parser.entries[1][1] = new_entry
    reader.update_feeds()
    assert set(reader.get_entries()) == {(feed, new_entry)}


def test_mark_as_read_unread(reader):

    parser = FakeParser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()

    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_read(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_read(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_unread(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_unread(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert not entry.read


def test_add_remove_feed(reader):

    parser = FakeParser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()

    assert set(reader.get_entries()) == {(feed, entry)}

    reader.remove_feed(feed.url)
    assert set(reader.get_entries()) == set()


@pytest.mark.slow
def test_mark_as_read_during_update_feeds(monkeypatch, tmpdir):
    monkeypatch.chdir(tmpdir)
    db_path = str(tmpdir.join('db.sqlite'))

    parser = FakeParser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    feed2 = parser.feed(2, datetime(2010, 1, 1))

    reader = Reader(db_path)
    reader._parse = parser

    reader.add_feed(feed.url)
    reader.add_feed(feed2.url)
    reader.update_feeds()

    blocking_parser = BlockingFakeParser.from_parser(parser)

    def target():
        reader = Reader(db_path)
        reader._parse = blocking_parser
        reader.update_feeds()

    t = threading.Thread(target=target)
    t.start()

    blocking_parser.in_parser.wait()

    try:
        # shouldn't raise an exception
        reader.mark_as_read(feed.url, entry.id)
    finally:
        blocking_parser.can_return_from_parser.set()
        t.join()


@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test
    0,                                  # unchunked query
])
def test_get_entries_order(reader, chunk_size):
    reader._get_entries_chunk_size = chunk_size

    parser = FakeParser()
    reader._parse = parser

    one = parser.feed(1)
    two = parser.feed(2)
    reader.add_feed(two.url)

    parser.entry(2, 1, datetime(2010, 1, 1))
    parser.entry(2, 4, datetime(2010, 1, 4))
    two = parser.feed(2, datetime(2010, 1, 4))
    reader.update_feeds()

    reader.add_feed(one.url)

    parser.entry(1, 1, datetime(2010, 1, 2))
    one = parser.feed(1, datetime(2010, 1, 2))
    reader.update_feeds()

    parser.entry(2, 1, datetime(2010, 1, 5))
    parser.entry(2, 2, datetime(2010, 1, 2))
    two = parser.feed(2, datetime(2010, 1, 5))
    reader.update_feeds()

    parser.entry(1, 2, datetime(2010, 1, 2))
    parser.entry(1, 4, datetime(2010, 1, 3))
    parser.entry(1, 3, datetime(2010, 1, 4))
    one = parser.feed(1, datetime(2010, 1, 6))
    parser.entry(2, 3, datetime(2010, 1, 2))
    parser.entry(2, 5, datetime(2010, 1, 3))
    two = parser.feed(2, datetime(2010, 1, 6))
    reader.update_feeds()

    expected = sorted(
        parser.get_tuples(),
        key=lambda t: (t[1].updated, t[0].url, t[1].id),
        reverse=True)

    assert list(reader.get_entries()) == expected


@pytest.mark.slow
@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test

    # check unchunked queries still blocks writes
    pytest.param(0, marks=pytest.mark.xfail(raises=Exception, strict=True)),
])
def test_mark_as_read_during_get_entries(monkeypatch, tmpdir, chunk_size):
    monkeypatch.chdir(tmpdir)
    db_path = str(tmpdir.join('db.sqlite'))

    parser = FakeParser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    parser.entry(1, 2, datetime(2010, 1, 2))
    parser.entry(1, 3, datetime(2010, 1, 3))

    reader = Reader(db_path)
    reader._parse = parser
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader._get_entries_chunk_size = chunk_size

    entries = reader.get_entries(_unread_only=True)
    next(entries)

    # shouldn't raise an exception
    Reader(db_path).mark_as_read(feed.url, entry.id)
    Reader(db_path).mark_as_unread(feed.url, entry.id)

    # just a sanity check
    assert len(list(entries)) == 3 - 1


def test_get_feeds(reader):
    parser = FakeParser()
    reader._parse = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 1, 2))

    reader.add_feed(one.url)
    reader.add_feed(two.url)

    assert set(reader.get_feeds()) == {
        Feed(f.url, None, None, None) for f in (one, two)
    }, "only url should be set for feeds not yet updated"

    reader.update_feeds()

    assert set(reader.get_feeds()) == {one, two}


def test_get_feed(reader):
    parser = FakeParser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))

    assert reader.get_feed(feed.url) == None

    reader.add_feed(feed.url)

    assert reader.get_feed(feed.url) == Feed(feed.url, None, None, None)

    reader.update_feeds()

    assert reader.get_feed(feed.url) == feed

