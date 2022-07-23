from functools import cached_property
from typing import Tuple


class _FancyExceptionBase(Exception):

    """Exception base that renders a message and __cause__ in str(e).

    The message looks something like:

        [message: ][_str][: CauseType: cause as string]

    The resulting exception pickles successfully;
    __cause__ still gets lost per https://bugs.python.org/issue29466,
    but a string representation of it remains stored on the exception.

    """

    #: Message; overridable.
    message: str = ''

    @property
    def _str(self) -> str:
        """The exception's unique attributes, as string; overridable."""
        return ''

    def __init__(self, message: str = ''):
        if message:
            self.message = message

    @cached_property
    def _cause_name(self) -> str:
        if not self.__cause__:
            return ''
        t = type(self.__cause__)
        return f'{t.__module__}.{t.__qualname__}'

    @cached_property
    def _cause_str(self) -> str:
        return str(self.__cause__) if self.__cause__ else ''

    def __reduce__(self) -> object:  # type: ignore
        # "prime" the cached properties before pickling
        str(self)
        return super().__reduce__()

    def __str__(self) -> str:
        parts = [self.message, self._str, self._cause_name, self._cause_str]
        # map is here to only to please mypy on python <3.8
        return ': '.join(map(str, filter(None, parts)))


class ReaderError(_FancyExceptionBase):
    """Base for all public exceptions."""


class ReaderWarning(UserWarning):
    """Base for all warnings emitted by *reader*.
    that are not :exc:`DeprecationWarning`.

    .. versionadded:: 2.13

    """


class ResourceNotFoundError(ReaderError):
    """Resource (feed, entry) not found.

    .. versionadded:: 2.8

    """

    @property
    def resource_id(self) -> Tuple[str, ...]:  # pragma: no cover
        """The `resource_id` of the resource."""
        raise NotImplementedError


class FeedError(ReaderError):
    """A feed error occurred."""

    def __init__(self, url: str, message: str = '') -> None:
        super().__init__(message)

        #: The feed URL.
        self.url = url

    @property
    def _str(self) -> str:
        return repr(self.url)

    @property
    def resource_id(self) -> Tuple[str]:
        """Alias for (:attr:`~url`,).

        .. versionadded:: 2.17

        """
        return (self.url,)


class FeedExistsError(FeedError):
    """Feed already exists."""

    message = "feed exists"


class FeedNotFoundError(FeedError, ResourceNotFoundError):
    """Feed not found."""

    message = "no such feed"


class InvalidFeedURLError(FeedError, ValueError):
    """Invalid feed URL.

    .. versionadded:: 2.5

    """

    message = "invalid feed URL"


class ParseError(FeedError, ReaderWarning):
    """An error occurred while getting/parsing feed.

    The original exception should be chained to this one (e.__cause__).

    """


class EntryError(ReaderError):
    """An entry error occurred.

    .. versionchanged:: 1.18
        The ``url`` argument/attribute was renamed to ``feed_url``.
    """

    def __init__(self, feed_url: str, id: str, message: str = '') -> None:
        super().__init__(message)

        #: The feed URL.
        self.feed_url = feed_url

        #: The entry id.
        self.id = id

    @property
    def _str(self) -> str:
        return repr((self.feed_url, self.id))

    @property
    def resource_id(self) -> Tuple[str, str]:
        """Alias for (:attr:`~feed_url`, :attr:`~id`).

        .. versionadded:: 2.17

        """
        return self.feed_url, self.id


class EntryExistsError(EntryError):
    """Entry already exists.

    .. versionadded:: 2.5

    """

    message = "entry exists"


class EntryNotFoundError(EntryError, ResourceNotFoundError):
    """Entry not found."""

    message = "no such entry"


class StorageError(ReaderError):
    """An exception was raised by the underlying storage.

    The original exception should be chained to this one (e.__cause__).

    """


class SearchError(ReaderError):
    """A search-related exception.

    If caused by an exception raised by the underlying search provider,
    the original exception should be chained to this one (e.__cause__).

    """


class SearchNotEnabledError(SearchError):
    """A search-related method was called when search was not enabled."""

    message = "operation not supported with search disabled"


class InvalidSearchQueryError(SearchError, ValueError):
    """The search query provided was somehow invalid."""


class PluginError(ReaderError):
    """A plugin-related exception."""


class InvalidPluginError(PluginError, ValueError):
    """An invalid plugin was provided.

    .. versionadded:: 1.16

    """


class TagError(ReaderError):
    """A tag error occurred.

    .. versionadded:: 2.8

    .. versionchanged:: 2.17
        Signature changed from ``TagError(key, object_id, message='')``
        to ``TagError(key, resource_id, message='')``.

    """

    def __init__(
        self, key: str, resource_id: Tuple[str, ...], message: str = ''
    ) -> None:
        super().__init__(message)

        #: The tag key.
        self.key = key

        #: The `resource_id` of the resource.
        self.resource_id = resource_id

    @property
    def _str(self) -> str:
        parts = self.resource_id + (self.key,)
        return ': '.join(repr(part) for part in parts)


class TagNotFoundError(TagError):
    """Tag not found.

    .. versionadded:: 2.8

    """

    message = "no such tag"
