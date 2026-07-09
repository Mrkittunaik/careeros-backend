from fastapi import status

from app.core.exceptions import AppError


class PlanNotEligibleError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "INTEGRATION_PLAN_NOT_ELIGIBLE"

    def __init__(self):
        super().__init__(
            "Connecting your own MongoDB is available on paid plans only. "
            "Upgrade to Premium or Enterprise."
        )


class MongoConnectionValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "INTEGRATION_MONGO_INVALID"

    def __init__(self, reason: str):
        super().__init__("Could not connect to the provided MongoDB instance.", details={"reason": reason})


class MongoConnectionNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "INTEGRATION_MONGO_NOT_FOUND"

    def __init__(self):
        super().__init__("No MongoDB connection found for this account.")
