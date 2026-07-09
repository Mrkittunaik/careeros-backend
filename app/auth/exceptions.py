from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError


class UserAlreadyExistsError(ConflictError):
    code = "AUTH_010"

    def __init__(self, email: str):
        super().__init__(f"A user with email '{email}' already exists.", details={"email": email})


class UserNotFoundError(NotFoundError):
    code = "AUTH_011"

    def __init__(self, identifier: str):
        super().__init__("User not found.", details={"identifier": identifier})


class InvalidCredentialsError(UnauthorizedError):
    code = "AUTH_001"

    def __init__(self):
        super().__init__("Invalid credentials.")


class InactiveUserError(ForbiddenError):
    code = "AUTH_002"

    def __init__(self):
        super().__init__("This user account is inactive.")


class EmailNotVerifiedError(ForbiddenError):
    code = "AUTH_003"

    def __init__(self):
        super().__init__("Please verify your email before logging in.")


class AccountLockedError(ForbiddenError):
    code = "AUTH_004"

    def __init__(self, unlock_at: str | None = None):
        super().__init__(
            "Account temporarily locked due to repeated failed login attempts.",
            details={"unlock_at": unlock_at} if unlock_at else {},
        )


class InvalidTokenError(UnauthorizedError):
    code = "AUTH_005"

    def __init__(self, reason: str = "Token is invalid or expired."):
        super().__init__(reason)


class TokenRevokedError(UnauthorizedError):
    code = "AUTH_006"

    def __init__(self):
        super().__init__("This token has been revoked.")


class InsufficientPermissionsError(ForbiddenError):
    code = "AUTH_007"

    def __init__(self, required: str | None = None):
        super().__init__(
            "You do not have permission to perform this action.",
            details={"required": required} if required else {},
        )


class EmailAlreadyVerifiedError(ConflictError):
    code = "AUTH_008"

    def __init__(self):
        super().__init__("This email has already been verified.")


class SessionNotFoundError(NotFoundError):
    code = "AUTH_012"

    def __init__(self, session_id: str):
        super().__init__("Session not found.", details={"session_id": session_id})


class WeakPasswordError(ConflictError):
    code = "AUTH_009"
    status_code = 422

    def __init__(self, reason: str):
        super().__init__(reason)
