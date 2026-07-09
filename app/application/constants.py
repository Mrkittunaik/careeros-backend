MAX_ATTACHMENTS_PER_APPLICATION = 20
MAX_NOTE_LENGTH = 10_000
MAX_TITLE_LENGTH = 255
MAX_COMPANY_NAME_LENGTH = 255
MAX_ROLE_TITLE_LENGTH = 255

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100

# Default cover-letter tone when the application module invokes the
# AI Core cover letter engine without an explicit tone override.
DEFAULT_COVER_LETTER_TONE = "professional"

# Prompt key registered/resolved through AI Core's PromptManager for
# generating structured answers to application-form questions. Falls back
# to the hardcoded default in this module's `utils.py` if no DB override
# exists, mirroring how app.ai_core.prompts.PromptManager already works
# for cover_letter_prompt / cold_email_prompt / etc.
APPLICATION_ANSWER_PROMPT_KEY = "application_answer_prompt"
APPLICATION_ANSWER_AI_STAGE = "application_answer"
