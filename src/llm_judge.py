# shortlist + 뉴스만 보고 블라인드로 포트폴리오 판단을 내리는 LLM 모듈 (나의 보유 종목은 절대 미포함)
import json

import anthropic

import config

_DECISION_TOOL = {
    "name": "submit_portfolio_decision",
    "description": "이번 주 블라인드 포트폴리오 판단을 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stock_code": {"type": "string"},
                        "stock_name": {"type": "string"},
                        "action": {"type": "string", "enum": ["매수", "매도", "홀딩"]},
                        "target_weight": {"type": "number", "description": "포트폴리오 내 목표 비중 (%, 0~100)"},
                        "rationale": {"type": "string", "description": "이 판단을 내린 이유 (자연어)"},
                        "conviction": {"type": "string", "enum": ["상", "중", "하"]},
                    },
                    "required": ["stock_code", "stock_name", "action", "target_weight", "rationale", "conviction"],
                },
            }
        },
        "required": ["decisions"],
    },
}

_SYSTEM_PROMPT = f"""당신은 국내주식(코스피+코스닥) 전문 포트폴리오 매니저입니다.
아래 제공되는 shortlist 종목들과 뉴스만을 근거로, 백지에서 포트폴리오를 구성하세요.

규칙:
- {config.TARGET_STOCK_MIN}~{config.TARGET_STOCK_MAX}개 종목을 선택하고 목표비중 합은 100%에 맞추세요.
- 특정 섹터에 집중하고 싶다면 그렇게 하되, 왜 그런 판단을 내렸는지 논리와 확신도를 반드시 남기세요.
- 스크리너가 이미 위생/중복/쏠림 정리를 마친 shortlist이므로, 이 안에서 자유롭게 선택하면 됩니다.
- 당신은 어떤 개인의 기존 보유 종목도 알지 못하며 알 필요가 없습니다. 순수하게 이 데이터만으로 판단하세요."""


def _build_user_prompt(shortlist: list[dict], news_by_stock: dict, market_news: list[dict]) -> str:
    lines = ["## Shortlist 종목\n"]
    for s in shortlist:
        lines.append(f"- {s['stock_name']}({s['stock_code']}): 90일 수익률 {s['momentum_score']:+.1%}")
        for n in news_by_stock.get(s["stock_name"], [])[:3]:
            lines.append(f"    · {n['title']}")
    lines.append("\n## 시장 전반 뉴스\n")
    for n in market_news[:5]:
        lines.append(f"- {n['title']}")
    return "\n".join(lines)


def judge(shortlist: list[dict], news_by_stock: dict, market_news: list[dict]) -> list[dict]:
    client = anthropic.Anthropic()
    user_prompt = _build_user_prompt(shortlist, news_by_stock, market_news)

    response = client.messages.create(
        model=config.LLM_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        tools=[_DECISION_TOOL],
        tool_choice={"type": "tool", "name": "submit_portfolio_decision"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_portfolio_decision":
            return block.input["decisions"]

    raise RuntimeError("LLM이 구조화된 판단을 반환하지 않음")


if __name__ == "__main__":
    sample_shortlist = [{"stock_code": "005930", "stock_name": "삼성전자", "momentum_score": 0.05}]
    print(json.dumps(judge(sample_shortlist, {}, []), ensure_ascii=False, indent=2))
