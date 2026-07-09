"""Test-collection-time stub for app.ai_core.email_analysis.

app.ai_core is still SQLAlchemy/Postgres-backed at this point in the
migration (it's next in the conversion queue after email_comm) and its
import chain currently fails outright: app.core.database dropped its
SQLAlchemy `Base` when it was converted to Mongo-only, but
app.ai_core.models still does `from app.core.database import Base`. That
break is pre-existing and out of scope for the email_comm conversion —
it isn't something introduced here, and fixing it properly is ai_core's
own migration work.

EmailIngestionService imports EmailAnalysisEngine from
app.ai_core.email_analysis at module load time, so without a stub the
entire app.email_comm.service module — including EmailAccountService and
EmailQueryService, which have nothing to do with ai_core — would fail to
import in a test environment. This conftest installs a minimal fake
implementation into sys.modules before any test module imports
app.email_comm.service, so email_comm's own (fully Mongo) logic can be
exercised in isolation. Once ai_core is converted in its own pass, this
stub becomes unnecessary and should be deleted.
"""

import sys
import types


def _install_ai_core_email_analysis_stub() -> None:
    if "app.ai_core.email_analysis" in sys.modules:
        return

    module = types.ModuleType("app.ai_core.email_analysis")

    class EmailAnalysisEngine:  # noqa: D401 - test stub, not the real engine
        def __init__(self, db, user_id=None):
            self.db = db
            self.user_id = user_id

        async def analyze(self, email_text: str, source_email_id=None):
            raise NotImplementedError(
                "app.ai_core.email_analysis is stubbed out in tests; "
                "EmailIngestionService._classify_and_link is not exercised "
                "by this module's test suite (see conftest.py docstring)."
            )

    module.EmailAnalysisEngine = EmailAnalysisEngine
    sys.modules["app.ai_core.email_analysis"] = module


_install_ai_core_email_analysis_stub()
