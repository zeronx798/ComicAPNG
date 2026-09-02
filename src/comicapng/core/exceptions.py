"""Application-specific exceptions."""


class ComicApngError(Exception):
    """Base exception for expected application failures."""


class InvalidImageError(ComicApngError):
    """Raised when an image cannot be decoded safely."""


class InvalidApngError(ComicApngError):
    """Raised when an input is not a readable PNG/APNG image."""


class InvalidMetadataError(ComicApngError):
    """Raised when metadata cannot be represented safely."""


class DestinationExistsError(ComicApngError):
    """Raised when a destination would be overwritten."""


class OperationCancelledError(ComicApngError):
    """Raised when a cancellable operation is stopped."""


class ResourceLimitError(ComicApngError):
    """Raised when an image exceeds safe decoder or memory limits."""


class InvalidArchiveError(ComicApngError):
    """Raised when a ZIP archive cannot be read safely."""


class UnsafeArchiveError(InvalidArchiveError):
    """Raised when an archive contains an unsafe entry name."""


class ArchiveWriteError(ComicApngError):
    """Raised when a ZIP archive cannot be written."""
