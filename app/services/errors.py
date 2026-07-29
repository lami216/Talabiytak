class AppError(Exception):
    """Base exception safe to display to an administrator."""


class ValidationError(AppError):
    """The submitted business input is invalid."""


class UnsafeWorkbookError(ValidationError):
    """The workbook archive violates an import safety constraint."""


class ImageProcessingError(ValidationError):
    """An image could not be safely validated and normalized."""


class ImageKitError(AppError):
    """An ImageKit operation failed without exposing credentials."""


class RemoteDeleteError(ImageKitError):
    """An ImageKit deletion failed and can be retried."""
