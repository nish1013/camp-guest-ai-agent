import sys

import anyio
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from camp_agent.config import Settings
from camp_agent.llm.pydantic_ai_llm import PydanticAiLlm
from camp_agent.llm.retrying_llm import RetryingLlm
from tests.evals.eval_suite import EvalSuite, failing_cases


def main() -> int:
    settings = Settings()
    if settings.openai_api_key is None:
        print("make evals needs OPENAI_API_KEY in the environment or in .env", file=sys.stderr)
        return 2
    provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value())
    model = OpenAIChatModel(settings.llm_model, provider=provider)
    llm = RetryingLlm(
        PydanticAiLlm(model, settings.llm_timeout_s),
        settings.llm_attempts,
        settings.llm_retry_delay_s,
    )
    reports = anyio.run(EvalSuite(llm).run)
    for report in reports:
        report.print(include_input=True, include_output=True, include_reasons=True)
    failed = [f"{report.name}/{case}" for report in reports for case in failing_cases(report)]
    if failed:
        print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"Evals passed with {settings.llm_model}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
