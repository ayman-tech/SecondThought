"""Task presets and bounded serving budgets for the experimental website."""
from secondthought.steering_rewriter import BASE_REWRITE_PROMPT

MAX_CHARACTERS = 20_000
MAX_SYSTEM_CHARACTERS = 4_000
DEFAULT_INPUT_TOKENS = 2048
MAX_INPUT_TOKENS = 4096
DEFAULT_OUTPUT_TOKENS = 128
MAX_OUTPUT_TOKENS = 512
LIMITS = dict(input=dict(min=128,max=MAX_INPUT_TOKENS,default=DEFAULT_INPUT_TOKENS),
              output=dict(min=32,max=MAX_OUTPUT_TOKENS,default=DEFAULT_OUTPUT_TOKENS),
              characters=MAX_CHARACTERS, system_characters=MAX_SYSTEM_CHARACTERS)

TASKS = {
    'rewrite': dict(label='Rewrite', system_prompt=BASE_REWRITE_PROMPT, output_tokens=128),
    'answer': dict(label='Answer', system_prompt="Answer the user's question directly and accurately.", output_tokens=256),
    'summarize': dict(label='Summarize', system_prompt='Summarize the supplied text without introducing new facts. Return only the summary.', output_tokens=256),
    'continue': dict(label='Continue', system_prompt='Continue the supplied text coherently. Return only the continuation.', output_tokens=256),
    'custom': dict(label='Custom', system_prompt=BASE_REWRITE_PROMPT, output_tokens=256),
    'none': dict(label='No system instruction', system_prompt=None, output_tokens=256),
}
