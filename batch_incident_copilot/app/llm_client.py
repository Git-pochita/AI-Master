from openai import AzureOpenAI

from config import settings


def create_client() -> AzureOpenAI:
    api_key = settings.require_api_key()
    return AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=api_key,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )


def chat_complete(system_prompt: str, user_prompt: str) -> str:
    """메시지 기반 단일 LLM 호출. OpenAI native tool calling API는 사용하지 않는다."""
    client = create_client()
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )
    content = resp.choices[0].message.content
    if not content:
        raise RuntimeError("LLM 응답이 비어 있습니다.")
    return content
